import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { Script } from "node:vm";
import { buildGraph, renderHtml } from "../src/fhirviz.js";

async function withTemporaryDirectory(callback) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "fhirviz-"));
  try {
    await callback(directory);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test("buildGraph reads JSON Bundles and NDJSON and deduplicates references", async () => {
  await withTemporaryDirectory(async (directory) => {
    await writeFile(
      path.join(directory, "bundle.json"),
      JSON.stringify({
        resourceType: "Bundle",
        entry: [
          {
            resource: {
              resourceType: "Patient",
              id: "aucore-patient-0007",
              managingOrganization: { reference: "Organization/org-1" },
              link: [{ other: { reference: "Patient/aucore-patient-0007" } }],
            },
          },
        ],
      }),
    );
    await writeFile(
      path.join(directory, "observations.ndjson"),
      [
        JSON.stringify({
          resourceType: "Observation",
          id: "obs-1",
          subject: { reference: "Patient/aucore-patient-0007" },
        }),
        "{invalid json",
      ].join("\n"),
    );

    const warnings = [];
    const { nodes, edges } = await buildGraph(directory, (message) => warnings.push(message));
    assert.equal(nodes.get("Patient/aucore-patient-0007").label, "patient-7");
    assert.equal(nodes.get("Organization/org-1").title, "Organization/org-1 (external)");
    assert.deepEqual(edges, [
      ["Observation/obs-1", "Patient/aucore-patient-0007"],
      ["Patient/aucore-patient-0007", "Organization/org-1"],
    ]);
    assert.equal(warnings.length, 1);
    assert.match(warnings[0], /invalid JSON line/);
  });
});

test("renderHtml embeds graph data safely and replaces all template tokens", async () => {
  const nodes = new Map([
    [
      "Observation/obs-1",
      {
        label: "</script><script>alert(1)</script>",
        title: "Observation/obs-1",
        color: "#d37295",
        group: "Observation",
      },
    ],
  ]);
  const html = await renderHtml(nodes, [], "<Graph & test>");

  assert.match(html, /&lt;Graph &amp; test&gt;/);
  assert.match(html, /\\u003c\/script\\u003e/);
  assert.doesNotMatch(html, /__[A-Z_]+__/);
  const browserScript = html.match(/<script>\n([\s\S]*?)\n<\/script>/)?.[1];
  assert.ok(browserScript);
  assert.doesNotThrow(() => new Script(browserScript));
});

test("CLI accepts positional and legacy paths and shows help without arguments", async () => {
  await withTemporaryDirectory(async (directory) => {
    await writeFile(
      path.join(directory, "patient.json"),
      JSON.stringify({ resourceType: "Patient", id: "patient-1" }),
    );

    const scriptPath = new URL("../src/fhirviz.js", import.meta.url);
    const result = spawnSync(
      process.execPath,
      [scriptPath.pathname, directory],
      { encoding: "utf8" },
    );
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Graph written to:/);
    assert.match(await readFile(path.join(directory, "graph.html"), "utf8"), /Patient\/patient-1/);

    const currentDirectory = spawnSync(
      process.execPath,
      [scriptPath.pathname, "."],
      { cwd: directory, encoding: "utf8" },
    );
    assert.equal(currentDirectory.status, 0, currentDirectory.stderr);
    assert.match(currentDirectory.stdout, /Graph written to:/);

    const help = spawnSync(process.execPath, [scriptPath.pathname], {
      encoding: "utf8",
    });
    assert.equal(help.status, 0, help.stderr);
    assert.match(help.stdout, /Usage: fhirviz <path>/);

    const legacy = spawnSync(
      process.execPath,
      [scriptPath.pathname, "--dir", directory],
      { encoding: "utf8" },
    );
    assert.equal(legacy.status, 0, legacy.stderr);
    assert.match(legacy.stdout, /Graph written to:/);
  });
});
