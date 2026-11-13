#!/usr/bin/env node

import { readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const LARGE_GRAPH_THRESHOLD = 5000;
export const LOCAL_VIEW_NODE_LIMIT = 400;
export const LOCAL_VIEW_EDGE_LIMIT = 1500;
export const GROUP_VIEW_NODE_LIMIT = 300;

const RESOURCE_COLOURS = {
  Organization: "#4e79a7",
  Practitioner: "#f28e2b",
  PractitionerRole: "#e15759",
  Location: "#76b7b2",
  Endpoint: "#59a14f",
  HealthcareService: "#edc948",
  Provenance: "#b07aa1",
  Patient: "#ff9da7",
  Condition: "#9c755f",
  Encounter: "#bab0ac",
  Observation: "#d37295",
  Procedure: "#a0cbe8",
  MedicationRequest: "#ffbe7d",
  MedicationStatement: "#8cd17d",
  Medication: "#b6992d",
  Immunization: "#86bcb6",
  AllergyIntolerance: "#e15759",
  RelatedPerson: "#79706e",
  DiagnosticReport: "#d4a6c8",
};
const DEFAULT_COLOUR = "#aaaaaa";
const TEMPLATE_PATH = new URL("./templates/graph.html", import.meta.url);

function compareText(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function resourceTypeOf(reference) {
  return reference && reference.includes("/")
    ? reference.split("/")[0]
    : "Unknown";
}

function shortLabel(fullId) {
  const stripped = fullId.replace(
    /^(healthconnect-|aucore-|example-healthconnect-|example-aucore-)/,
    "",
  );
  const abbreviations = {
    organization: "org",
    practitioner: "pract",
    practitionerrole: "pr-role",
    location: "loc",
    endpoint: "ep",
    healthcareservice: "hcs",
    provenance: "prov",
    patient: "patient",
    condition: "cond",
    encounter: "enc",
    observation: "obs",
    procedure: "proc",
    medicationrequest: "med-req",
    medicationstatement: "med-stmt",
    medication: "med",
    immunization: "imm",
    allergyintolerance: "allergy",
    relatedperson: "rel",
  };
  for (const [long, abbreviated] of Object.entries(abbreviations)) {
    if (stripped.startsWith(`${long}-`)) {
      const rest = stripped.slice(long.length + 1).replace(/^0+/, "") || "0";
      return `${abbreviated}-${rest}`;
    }
  }
  return stripped.slice(0, 20);
}

function extractReferences(value, references) {
  if (Array.isArray(value)) {
    for (const item of value) {
      extractReferences(item, references);
    }
    return;
  }
  if (!value || typeof value !== "object") {
    return;
  }
  if (typeof value.reference === "string") {
    references.push(value.reference);
  }
  for (const child of Object.values(value)) {
    extractReferences(child, references);
  }
}

export async function* loadResources(filePath, warn = () => {}) {
  const content = (await readFile(filePath, "utf8")).trim();
  if (filePath.endsWith(".ndjson")) {
    for (const [index, rawLine] of content.split(/\r?\n/).entries()) {
      const line = rawLine.trim();
      if (!line) {
        continue;
      }
      try {
        yield JSON.parse(line);
      } catch (error) {
        if (error instanceof SyntaxError) {
          warn(`${filePath}:${index + 1}: invalid JSON line; skipping`);
          continue;
        }
        throw error;
      }
    }
    return;
  }

  let resource;
  try {
    resource = JSON.parse(content);
  } catch (error) {
    if (error instanceof SyntaxError) {
      warn(`${filePath}: invalid JSON; skipping`);
      return;
    }
    throw error;
  }

  if (resource?.resourceType === "Bundle") {
    for (const entry of Array.isArray(resource.entry) ? resource.entry : []) {
      if (entry?.resource && typeof entry.resource === "object") {
        yield entry.resource;
      }
    }
  } else if (resource && typeof resource === "object" && !Array.isArray(resource)) {
    yield resource;
  }
}

export async function buildGraph(directory, warn = console.warn) {
  const nodes = new Map();
  const edges = new Set();
  const filenames = (await readdir(directory)).sort(compareText);

  for (const filename of filenames) {
    if (!filename.endsWith(".ndjson") && !filename.endsWith(".json")) {
      continue;
    }
    const filePath = path.join(directory, filename);
    for await (const resource of loadResources(filePath, warn)) {
      if (!resource || typeof resource !== "object" || Array.isArray(resource)) {
        continue;
      }
      const resourceType =
        typeof resource.resourceType === "string" ? resource.resourceType : "Unknown";
      const resourceId = typeof resource.id === "string" ? resource.id : "";
      const fullId = `${resourceType}/${resourceId}`;
      nodes.set(fullId, {
        label: shortLabel(resourceId),
        title: fullId,
        color: RESOURCE_COLOURS[resourceType] ?? DEFAULT_COLOUR,
        group: resourceType,
      });

      const references = [];
      extractReferences(resource, references);
      for (const target of references) {
        if (target !== fullId) {
          edges.add(JSON.stringify([fullId, target]));
        }
      }
    }
  }

  const sortedEdges = [...edges]
    .map((edge) => JSON.parse(edge))
    .sort(([leftSource, leftTarget], [rightSource, rightTarget]) =>
      compareText(leftSource, rightSource) || compareText(leftTarget, rightTarget),
    );

  for (const [, target] of sortedEdges) {
    if (nodes.has(target)) {
      continue;
    }
    const resourceType = resourceTypeOf(target);
    const targetId = target.includes("/") ? target.split("/").at(-1) : target;
    nodes.set(target, {
      label: shortLabel(targetId),
      title: `${target} (external)`,
      color: RESOURCE_COLOURS[resourceType] ?? DEFAULT_COLOUR,
      group: resourceType,
    });
  }

  return { nodes, edges: sortedEdges };
}

function buildGroupSummary(nodes, edges) {
  const groupCounts = new Map();
  const groupEdges = new Map();
  const groupMembers = new Map();
  const degrees = new Map([...nodes.keys()].map((nodeId) => [nodeId, 0]));

  for (const [nodeId, properties] of nodes) {
    groupCounts.set(properties.group, (groupCounts.get(properties.group) ?? 0) + 1);
    const members = groupMembers.get(properties.group) ?? [];
    members.push(nodeId);
    groupMembers.set(properties.group, members);
  }

  for (const [source, target] of edges) {
    const sourceGroup = nodes.get(source).group;
    const targetGroup = nodes.get(target).group;
    const key = JSON.stringify([sourceGroup, targetGroup]);
    groupEdges.set(key, (groupEdges.get(key) ?? 0) + 1);
    degrees.set(source, (degrees.get(source) ?? 0) + 1);
    degrees.set(target, (degrees.get(target) ?? 0) + 1);
  }

  const sortedGroupMembers = Object.create(null);
  for (const [group, members] of groupMembers) {
    sortedGroupMembers[group] = members.sort(
      (left, right) =>
        (degrees.get(right) ?? 0) - (degrees.get(left) ?? 0) ||
        compareText(nodes.get(left).label, nodes.get(right).label) ||
        compareText(left, right),
    );
  }

  const formatCount = (count) => count.toLocaleString("en-US");
  const summaryNodes = [...groupCounts.keys()]
    .sort(compareText)
    .map((group) => {
      const count = groupCounts.get(group);
      return {
        id: group,
        label: `${group}\n${formatCount(count)}`,
        title: `${group}: ${formatCount(count)} resources`,
        color: RESOURCE_COLOURS[group] ?? DEFAULT_COLOUR,
        size: Math.max(20, Math.min(34, 14 + String(count).length * 2)),
        font: { size: 12 },
      };
    });

  const summaryEdges = [...groupEdges]
    .map(([key, count]) => [JSON.parse(key), count])
    .sort(([left], [right]) =>
      compareText(left[0], right[0]) || compareText(left[1], right[1]),
    )
    .map(([[sourceGroup, targetGroup], count], index) => ({
      id: `g${index}`,
      from: sourceGroup,
      to: targetGroup,
      title: `${sourceGroup} -> ${targetGroup}: ${formatCount(count)} references`,
      width: Math.max(1, Math.min(6, String(count).length)),
      arrows: "to",
    }));

  return { summaryNodes, summaryEdges, groupMembers: sortedGroupMembers };
}

function safeJson(value) {
  return JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, (character) => {
    const escapes = {
      "<": "\\u003c",
      ">": "\\u003e",
      "&": "\\u0026",
      "\u2028": "\\u2028",
      "\u2029": "\\u2029",
    };
    return escapes[character];
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const escapes = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return escapes[character];
  });
}

export async function renderHtml(nodes, edges, title) {
  const { summaryNodes, summaryEdges, groupMembers } = buildGroupSummary(nodes, edges);
  const adjacency = Object.create(null);
  const nodeRecords = [...nodes]
    .sort(([left], [right]) => compareText(left, right))
    .map(([id, properties]) => {
      adjacency[id] = [];
      return {
        id,
        label: properties.label,
        title: properties.title,
        color: properties.color,
        group: properties.group,
      };
    });

  const edgeRecords = edges.map(([source, target], index) => {
    adjacency[source].push(target);
    adjacency[target].push(source);
    return { id: index, from: source, to: target, arrows: "to" };
  });
  const groups = [...new Set([...nodes.values()].map(({ group }) => group))].sort(compareText);
  const legendItems = groups
    .map(
      (group) =>
        `<button type="button" class="legend-item is-active" data-group="${escapeHtml(group)}" style="--legend-colour:${RESOURCE_COLOURS[group] ?? DEFAULT_COLOUR}"><span class="dot"></span>${escapeHtml(group)}</button>`,
    )
    .join("");

  const template = await readFile(TEMPLATE_PATH, "utf8");
  const replacements = {
    __TITLE__: escapeHtml(title),
    __NODE_COUNT__: nodeRecords.length.toLocaleString("en-US"),
    __EDGE_COUNT__: edgeRecords.length.toLocaleString("en-US"),
    __LEGEND_ITEMS__: legendItems,
    __NODES_JSON__: safeJson(nodeRecords),
    __EDGES_JSON__: safeJson(edgeRecords),
    __ADJACENCY_JSON__: safeJson(adjacency),
    __GROUP_NODES_JSON__: safeJson(summaryNodes),
    __GROUP_EDGES_JSON__: safeJson(summaryEdges),
    __GROUP_MEMBERS_JSON__: safeJson(groupMembers),
    __LARGE_GRAPH_THRESHOLD__: String(LARGE_GRAPH_THRESHOLD),
    __LOCAL_VIEW_NODE_LIMIT__: String(LOCAL_VIEW_NODE_LIMIT),
    __LOCAL_VIEW_EDGE_LIMIT__: String(LOCAL_VIEW_EDGE_LIMIT),
    __GROUP_VIEW_NODE_LIMIT__: String(GROUP_VIEW_NODE_LIMIT),
  };
  return template.replace(/__[A-Z_]+__/g, (placeholder) => {
    if (!Object.hasOwn(replacements, placeholder)) {
      throw new Error(`Unknown HTML template placeholder: ${placeholder}`);
    }
    return replacements[placeholder];
  });
}

function parseArguments(argumentsList) {
  let directory;
  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument === "--help" || argument === "-h") {
      return { help: true };
    }
    if (argument !== "--dir") {
      throw new Error(`Unknown argument: ${argument}`);
    }
    directory = argumentsList[index + 1];
    if (!directory || directory.startsWith("--")) {
      throw new Error("--dir requires a directory path");
    }
    index += 1;
  }
  if (!directory) {
    throw new Error("Missing required argument: --dir");
  }
  return { directory };
}

const HELP = `Usage: fhirviz --dir <path>

Render a FHIR resource reference graph as interactive HTML.

Options:
  --dir <path>  Directory containing FHIR .ndjson or .json files
  -h, --help    Show this help
`;

export async function main(argumentsList = process.argv.slice(2)) {
  const options = parseArguments(argumentsList);
  if (options.help) {
    console.log(HELP);
    return;
  }

  const directory = path.resolve(options.directory);
  if (!(await stat(directory)).isDirectory()) {
    throw new Error(`Not a directory: ${directory}`);
  }

  const outputPath = path.join(directory, "graph.html");
  const title = `FHIR Reference Graph — ${directory}`;
  console.log(`Reading from: ${directory}`);
  const { nodes, edges } = await buildGraph(directory, (message) => {
    console.warn(`Warning: ${message}`);
  });
  console.log(`  ${nodes.size.toLocaleString("en-US")} nodes, ${edges.length.toLocaleString("en-US")} edges`);
  if (nodes.size >= LARGE_GRAPH_THRESHOLD) {
    console.log("  Large dataset detected: graph will open in overview mode with neighborhood exploration.");
  }

  const html = await renderHtml(nodes, edges, title);
  await writeFile(outputPath, html, "utf8");
  console.log(`Graph written to: ${outputPath}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch((error) => {
    console.error(`Error: ${error.message}`);
    process.exitCode = 1;
  });
}
