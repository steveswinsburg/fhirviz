#!/usr/bin/env python3
"""
fhirviz — Interactive reference graph visualiser for FHIR resources.

Reads a directory of .ndjson or .json FHIR files and renders a force-directed
network of resource references as a self-contained HTML file.

Usage:
    python fhirviz.py --dir path/to/fhir/files
"""

import argparse
import json
import os
import re

LARGE_GRAPH_THRESHOLD = 5000
LOCAL_VIEW_NODE_LIMIT = 400
LOCAL_VIEW_EDGE_LIMIT = 1500
GROUP_VIEW_NODE_LIMIT = 300

# Colours per FHIR resource type
RESOURCE_COLOURS = {
    "Organization": "#4e79a7",
    "Practitioner": "#f28e2b",
    "PractitionerRole": "#e15759",
    "Location": "#76b7b2",
    "Endpoint": "#59a14f",
    "HealthcareService": "#edc948",
    "Provenance": "#b07aa1",
    "Patient": "#ff9da7",
    "Condition": "#9c755f",
    "Encounter": "#bab0ac",
    "Observation": "#d37295",
    "Procedure": "#a0cbe8",
    "MedicationRequest": "#ffbe7d",
    "MedicationStatement": "#8cd17d",
    "Medication": "#b6992d",
    "Immunization": "#86bcb6",
    "AllergyIntolerance": "#e15759",
    "RelatedPerson": "#79706e",
    "DiagnosticReport": "#d4a6c8",
}
DEFAULT_COLOUR = "#aaaaaa"


def resource_type_of(ref):
    if ref and "/" in ref:
        return ref.split("/")[0]
    return "Unknown"


def extract_references(obj, source_id, edges):
    if isinstance(obj, dict):
        if "reference" in obj and isinstance(obj["reference"], str):
            edges.append(obj["reference"])
        for v in obj.values():
            extract_references(v, source_id, edges)
    elif isinstance(obj, list):
        for item in obj:
            extract_references(item, source_id, edges)


def short_label(full_id):
    stripped = re.sub(r"^(healthconnect-|aucore-|example-healthconnect-|example-aucore-)", "", full_id)
    abbrevs = {
        "organization": "org",
        "practitioner": "pract",
        "practitionerrole": "pr-role",
        "location": "loc",
        "endpoint": "ep",
        "healthcareservice": "hcs",
        "provenance": "prov",
        "patient": "patient",
        "condition": "cond",
        "encounter": "enc",
        "observation": "obs",
        "procedure": "proc",
        "medicationrequest": "med-req",
        "medicationstatement": "med-stmt",
        "medication": "med",
        "immunization": "imm",
        "allergyintolerance": "allergy",
        "relatedperson": "rel",
    }
    for long, short in abbrevs.items():
        if stripped.startswith(long + "-"):
            rest = stripped[len(long) + 1:].lstrip("0") or "0"
            return f"{short}-{rest}"
    return stripped[:20]


def load_resources(path):
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()
    if path.endswith(".ndjson"):
        for line in content.splitlines():
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass
    else:
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            return
        if obj.get("resourceType") == "Bundle":
            for entry in obj.get("entry", []):
                if "resource" in entry:
                    yield entry["resource"]
        else:
            yield obj


def build_graph(directory):
    nodes = {}
    edges = set()

    for fname in sorted(os.listdir(directory)):
        if not (fname.endswith(".ndjson") or fname.endswith(".json")):
            continue
        path = os.path.join(directory, fname)
        for resource in load_resources(path):
            rtype = resource.get("resourceType", "Unknown")
            rid = resource.get("id", "")
            full_id = f"{rtype}/{rid}"
            colour = RESOURCE_COLOURS.get(rtype, DEFAULT_COLOUR)
            nodes[full_id] = {
                "label": short_label(rid),
                "title": full_id,
                "color": colour,
                "group": rtype,
            }
            resource_edges = []
            extract_references(resource, full_id, resource_edges)
            for target_ref in resource_edges:
                if target_ref != full_id:
                    edges.add((full_id, target_ref))

    for _, target_ref in edges:
        if target_ref not in nodes:
            rtype = resource_type_of(target_ref)
            colour = RESOURCE_COLOURS.get(rtype, DEFAULT_COLOUR)
            nodes[target_ref] = {
                "label": short_label(target_ref.split("/")[-1] if "/" in target_ref else target_ref),
                "title": target_ref + " (external)",
                "color": colour,
                "group": rtype,
            }

    return nodes, sorted(edges)


def build_group_summary(nodes, edges):
    group_counts = {}
    group_edges = {}
    group_members = {}
    degrees = {node_id: 0 for node_id in nodes}

    for node_id, props in nodes.items():
        group = props["group"]
        group_counts[group] = group_counts.get(group, 0) + 1
        group_members.setdefault(group, []).append(node_id)

    for src, tgt in edges:
        src_group = nodes[src]["group"]
        tgt_group = nodes[tgt]["group"]
        key = (src_group, tgt_group)
        group_edges[key] = group_edges.get(key, 0) + 1
        degrees[src] = degrees.get(src, 0) + 1
        degrees[tgt] = degrees.get(tgt, 0) + 1

    sorted_group_members = {}
    for group, members in group_members.items():
        sorted_group_members[group] = sorted(
            members,
            key=lambda node_id: (-degrees.get(node_id, 0), nodes[node_id]["label"], node_id),
        )

    summary_nodes = []
    for group in sorted(group_counts):
        count = group_counts[group]
        summary_nodes.append(
            {
                "id": group,
                "label": f"{group}\n{count:,}",
                "title": f"{group}: {count:,} resources",
                "color": RESOURCE_COLOURS.get(group, DEFAULT_COLOUR),
                "size": max(20, min(34, 14 + len(str(count)) * 2)),
                "font": {"size": 12},
            }
        )

    summary_edges = []
    for index, ((src_group, tgt_group), count) in enumerate(sorted(group_edges.items())):
        summary_edges.append(
            {
                "id": f"g{index}",
                "from": src_group,
                "to": tgt_group,
                "title": f"{src_group} -> {tgt_group}: {count:,} references",
                "width": max(1, min(6, len(str(count)))),
                "arrows": "to",
            }
        )

    return summary_nodes, summary_edges, sorted_group_members


def render_html(nodes, edges, title):
    node_records = []
    adjacency = {}
    group_nodes, group_edges, group_members = build_group_summary(nodes, edges)

    for nid, props in sorted(nodes.items()):
        node_records.append(
            {
                "id": nid,
                "label": props["label"],
                "title": props["title"],
                "color": props["color"],
                "group": props["group"],
            }
        )
        adjacency[nid] = []

    edge_records = []
    for index, (src, tgt) in enumerate(edges):
        edge_records.append({"id": index, "from": src, "to": tgt, "arrows": "to"})
        adjacency[src].append(tgt)
        adjacency[tgt].append(src)

    nodes_js = json.dumps(node_records, separators=(",", ":"))
    edges_js = json.dumps(edge_records, separators=(",", ":"))
    adjacency_js = json.dumps(adjacency, separators=(",", ":"))
    group_nodes_js = json.dumps(group_nodes, separators=(",", ":"))
    group_edges_js = json.dumps(group_edges, separators=(",", ":"))
    group_members_js = json.dumps(group_members, separators=(",", ":"))

    seen_groups = sorted({props["group"] for props in nodes.values()})
    legend_items = "".join(
        f'<button type="button" class="legend-item is-active" data-group="{g}" style="--legend-colour:{RESOURCE_COLOURS.get(g, DEFAULT_COLOUR)}"><span class="dot"></span>{g}</button>'
        for g in seen_groups
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #1e1e2e; color: #cdd6f4; }}
    h1 {{ padding: 12px 16px 6px; font-size: 14px; font-weight: 600; color: #89b4fa; }}
    .toolbar {{
        display: flex; flex-wrap: wrap; gap: 8px;
        padding: 0 16px 12px; border-bottom: 1px solid #313244; align-items: center;
    }}
    .toolbar input, .toolbar select, .toolbar button {{
        background: #11111b; color: #cdd6f4; border: 1px solid #45475a;
        border-radius: 6px; padding: 7px 10px; font-size: 12px;
    }}
    .search-wrap {{ position: relative; min-width: 280px; flex: 1 1 280px; }}
    .toolbar input {{ width: 100%; }}
    .toolbar button {{ cursor: pointer; }}
    .toolbar button:hover {{ border-color: #89b4fa; }}
    .pill {{
        padding: 6px 10px; border-radius: 999px; font-size: 12px;
        background: #181825; border: 1px solid #313244; color: #bac2de;
    }}
    #status {{ padding: 8px 16px; font-size: 12px; color: #a6adc8; border-bottom: 1px solid #313244; }}
    #network {{ width: 100%; height: calc(100vh - 172px); }}
    #legend {{
        display: flex; flex-wrap: wrap; gap: 8px;
        padding: 10px 16px; border-top: 1px solid #313244; font-size: 12px;
    }}
    .legend-item {{
        display: inline-flex; align-items: center; gap: 6px;
        padding: 7px 10px; border-radius: 999px; cursor: pointer;
        background: #11111b; color: #cdd6f4; border: 1px solid #313244;
        transition: border-color 120ms ease, opacity 120ms ease, background 120ms ease;
    }}
    .legend-item:hover {{ border-color: #89b4fa; }}
    .legend-item.is-active {{ background: #181825; border-color: var(--legend-colour); }}
    .legend-item:not(.is-active) {{ opacity: 0.45; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; background: var(--legend-colour); }}
    #search-results {{
        position: absolute; left: 0; right: 0; top: calc(100% + 6px); z-index: 20;
        display: none; max-height: 280px; overflow-y: auto;
        background: #11111b; border: 1px solid #313244; border-radius: 10px;
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.35);
    }}
    #search-results.has-results {{ display: block; }}
    .search-result {{
        display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left;
        padding: 9px 10px; border: 0; border-bottom: 1px solid #1e1e2e;
        background: transparent; color: #cdd6f4; cursor: pointer;
    }}
    .search-result:last-child {{ border-bottom: 0; }}
    .search-result:hover, .search-result.is-active {{ background: #181825; }}
    .search-result-title {{ font-size: 12px; color: #f5e0dc; }}
    .search-result-meta {{ font-size: 11px; color: #a6adc8; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="toolbar">
    <span class="pill" id="mode-pill">Preparing graph</span>
    <span class="pill">{len(nodes):,} nodes</span>
    <span class="pill">{len(edges):,} edges</span>
    <div class="search-wrap">
        <input id="node-search" type="search" placeholder="Search by full reference, id fragment, or label" autocomplete="off" spellcheck="false" />
        <div id="search-results"></div>
    </div>
    <select id="depth-select">
        <option value="1">Depth 1</option>
        <option value="2" selected>Depth 2</option>
        <option value="3">Depth 3</option>
    </select>
    <select id="limit-select">
        <option value="150">150 nodes</option>
        <option value="300">300 nodes</option>
        <option value="400" selected>400 nodes</option>
        <option value="600">600 nodes</option>
    </select>
    <button id="search-button">Explore</button>
    <button id="selected-button">Explore selected</button>
    <button id="back-button" disabled>Back</button>
    <button id="overview-button">Overview</button>
</div>
<div id="status"></div>
<div id="network"></div>
<div id="legend">{legend_items}</div>
<script>
const allNodes = {nodes_js};
const allEdges = {edges_js};
const adjacency = {adjacency_js};
const groupNodes = {group_nodes_js};
const groupEdges = {group_edges_js};
const groupMembers = {group_members_js};
const largeGraphThreshold = {LARGE_GRAPH_THRESHOLD};
const defaultDetailNodeLimit = {LOCAL_VIEW_NODE_LIMIT};
const detailEdgeLimit = {LOCAL_VIEW_EDGE_LIMIT};
const groupViewNodeLimit = {GROUP_VIEW_NODE_LIMIT};
const nodeMap = new Map(allNodes.map((node) => [node.id, node]));
const isLargeGraph = allNodes.length >= largeGraphThreshold;

const container = document.getElementById('network');
const searchInput = document.getElementById('node-search');
const searchResults = document.getElementById('search-results');
const depthSelect = document.getElementById('depth-select');
const limitSelect = document.getElementById('limit-select');
const statusEl = document.getElementById('status');
const modePill = document.getElementById('mode-pill');
const backButton = document.getElementById('back-button');
const legendButtons = Array.from(document.querySelectorAll('#legend .legend-item'));

let network;
let currentNodeId = null;
let currentGroupId = null;
let currentView = null;
const historyStack = [];
const activeGroups = new Set(Object.keys(groupMembers));
let currentMatches = [];
let activeMatchIndex = -1;

function setStatus(message) {{
    statusEl.textContent = message;
}}

function setMode(mode) {{
    modePill.textContent = mode;
}}

function updateBackButton() {{
    backButton.disabled = historyStack.length === 0;
}}

function syncLegendButtons() {{
    for (const button of legendButtons) {{
        const group = button.dataset.group;
        button.classList.toggle('is-active', activeGroups.has(group));
    }}
}}

function cloneView(view) {{
    return view ? {{ ...view }} : null;
}}

function filterData(data, viewMode) {{
    if (viewMode === 'overview') {{
        const nodes = data.nodes.filter((node) => activeGroups.has(node.id));
        const allowed = new Set(nodes.map((node) => node.id));
        const edges = data.edges.filter((edge) => allowed.has(edge.from) && allowed.has(edge.to));
        return {{ nodes, edges }};
    }}

    const nodes = data.nodes.filter((node) => activeGroups.has(node.group));
    const allowed = new Set(nodes.map((node) => node.id));
    const edges = data.edges.filter((edge) => allowed.has(edge.from) && allowed.has(edge.to));
    return {{ nodes, edges }};
}}

function findNodeMatches(query, limit = 12) {{
    const trimmed = query.trim().toLowerCase();
    if (!trimmed) {{
        return [];
    }}

    const exact = [];
    const prefix = [];
    const contains = [];
    for (const node of allNodes) {{
        if (!activeGroups.has(node.group)) {{
            continue;
        }}
        const idLower = node.id.toLowerCase();
        const labelLower = node.label.toLowerCase();
        const suffix = node.id.includes('/') ? node.id.split('/').slice(1).join('/') : node.id;
        const suffixLower = suffix.toLowerCase();

        if (idLower === trimmed || suffixLower === trimmed || labelLower === trimmed) {{
            exact.push(node);
        }} else if (idLower.startsWith(trimmed) || suffixLower.startsWith(trimmed) || labelLower.startsWith(trimmed)) {{
            prefix.push(node);
        }} else if (idLower.includes(trimmed) || suffixLower.includes(trimmed) || labelLower.includes(trimmed)) {{
            contains.push(node);
        }}

        if (exact.length + prefix.length + contains.length >= limit * 4) {{
            break;
        }}
    }}

    return [...exact, ...prefix, ...contains].slice(0, limit);
}}

function clearSearchResults() {{
    currentMatches = [];
    activeMatchIndex = -1;
    searchResults.innerHTML = '';
    searchResults.classList.remove('has-results');
}}

function renderSearchResults(matches) {{
    currentMatches = matches;
    activeMatchIndex = matches.length ? 0 : -1;
    if (!matches.length) {{
        clearSearchResults();
        return;
    }}

    searchResults.innerHTML = matches.map((node, index) => `
        <button type="button" class="search-result${{index === activeMatchIndex ? ' is-active' : ''}}" data-node-id="${{node.id}}">
            <span class="search-result-title">${{node.id}}</span>
            <span class="search-result-meta">${{node.group}} | ${{node.label}}</span>
        </button>
    `).join('');
    searchResults.classList.add('has-results');
}}

function updateActiveSearchResult() {{
    const buttons = Array.from(searchResults.querySelectorAll('.search-result'));
    buttons.forEach((button, index) => {{
        button.classList.toggle('is-active', index === activeMatchIndex);
    }});
    if (buttons[activeMatchIndex]) {{
        buttons[activeMatchIndex].scrollIntoView({{ block: 'nearest' }});
    }}
}}

function commitSearchSelection(nodeId) {{
    if (!nodeId) {{
        return;
    }}
    searchInput.value = nodeId;
    clearSearchResults();
    exploreNode(nodeId);
}}

function refreshSearchResults() {{
    const trimmed = searchInput.value.trim();
    if (trimmed.length < 2) {{
        clearSearchResults();
        return;
    }}
    renderSearchResults(findNodeMatches(trimmed));
}}

function makeOptions(viewMode, enablePhysics) {{
    const isOverviewMode = viewMode === 'overview';
    return {{
        autoResize: true,
        nodes: {{
            shape: 'dot',
            size: isOverviewMode ? 24 : 10,
            borderWidth: 1,
            font: {{ size: isOverviewMode ? 11 : 10, color: '#cdd6f4', face: 'sans-serif' }},
            scaling: {{
                min: 8,
                max: isOverviewMode ? 30 : 22,
                label: {{ enabled: !isOverviewMode, min: 12, max: 18 }}
            }}
        }},
        edges: {{
            color: {{ color: '#585b70', highlight: '#89b4fa', hover: '#89b4fa' }},
            width: isOverviewMode ? 1.4 : 0.8,
            selectionWidth: 1.5,
            smooth: false,
            font: {{ size: 10, color: '#bac2de', strokeWidth: 0 }},
            arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }}
        }},
        interaction: {{
            hover: true,
            tooltipDelay: 80,
            hideEdgesOnDrag: true,
            hideNodesOnDrag: false,
            zoomView: true,
            dragView: true
        }},
        layout: {{ improvedLayout: false }},
        physics: enablePhysics ? {{
            stabilization: {{ iterations: isOverviewMode ? 180 : 120, updateInterval: 25 }},
            barnesHut: {{
                gravitationalConstant: isOverviewMode ? -5200 : -3500,
                springLength: isOverviewMode ? 220 : 95,
                springConstant: 0.02,
                damping: isOverviewMode ? 0.28 : 0.2,
                avoidOverlap: isOverviewMode ? 0.4 : 0.1
            }}
        }} : false
    }};
}}

function render(data, viewMode, enablePhysics) {{
    const filtered = filterData(data, viewMode);
    if (network) {{
        network.destroy();
    }}
    network = new vis.Network(
        container,
        {{ nodes: new vis.DataSet(filtered.nodes), edges: new vis.DataSet(filtered.edges) }},
        makeOptions(viewMode, enablePhysics)
    );
    network.on('selectNode', (params) => {{
        const selectedId = params.nodes[0] || null;
        currentNodeId = null;
        currentGroupId = null;
        if (selectedId && nodeMap.has(selectedId)) {{
            currentNodeId = selectedId;
            searchInput.value = selectedId;
            setStatus(`Selected ${{selectedId}}`);
            return;
        }}
        if (selectedId && groupMembers[selectedId]) {{
            currentGroupId = selectedId;
            setStatus(`Selected group ${{selectedId}}. Click again or use Explore selected to open its busiest resources.`);
            return;
        }}
    }});
    network.on('doubleClick', (params) => {{
        const selectedId = params.nodes[0] || null;
        if (!selectedId) {{
            return;
        }}
        if (groupMembers[selectedId]) {{
            exploreGroup(selectedId);
            return;
        }}
        if (nodeMap.has(selectedId)) {{
            exploreNode(selectedId);
        }}
    }});
}}

function renderOverview() {{
    setMode(isLargeGraph ? 'Overview mode' : 'Full graph mode');
    if (isLargeGraph) {{
        setStatus('Showing resource-type summary. Search for a node or select one to render a local neighborhood.');
        render({{ nodes: groupNodes, edges: groupEdges }}, 'overview', true);
        return;
    }}
    setStatus('Showing the full graph.');
    render({{ nodes: allNodes, edges: allEdges }}, 'full', true);
}}

function showOverview(pushHistory = true) {{
    if (pushHistory && currentView) {{
        historyStack.push(cloneView(currentView));
    }}
    currentView = {{ type: isLargeGraph ? 'overview' : 'full' }};
    currentNodeId = null;
    currentGroupId = null;
    renderOverview();
    updateBackButton();
}}

function resolveNodeId(query) {{
    const trimmed = query.trim();
    if (!trimmed) {{
        return null;
    }}
    if (nodeMap.has(trimmed)) {{
        return trimmed;
    }}

    const lower = trimmed.toLowerCase();
    let bestSuffixMatch = null;
    for (const node of allNodes) {{
        if (node.id.toLowerCase() === lower) {{
            return node.id;
        }}
        const suffix = node.id.includes('/') ? node.id.split('/').slice(1).join('/') : node.id;
        if (suffix.toLowerCase() === lower) {{
            return node.id;
        }}
        if (!bestSuffixMatch && (suffix.toLowerCase().includes(lower) || node.label.toLowerCase().includes(lower))) {{
            bestSuffixMatch = node.id;
        }}
    }}
    return bestSuffixMatch;
}}

function buildNeighborhood(rootId, depth, nodeLimit) {{
    const selected = new Set([rootId]);
    const queue = [[rootId, 0]];
    let index = 0;

    while (index < queue.length && selected.size < nodeLimit) {{
        const [nodeId, level] = queue[index++];
        if (level >= depth) {{
            continue;
        }}
        const neighbors = adjacency[nodeId] || [];
        for (const neighborId of neighbors) {{
            if (!selected.has(neighborId)) {{
                selected.add(neighborId);
                queue.push([neighborId, level + 1]);
                if (selected.size >= nodeLimit) {{
                    break;
                }}
            }}
        }}
    }}

    const detailNodes = [];
    for (const nodeId of selected) {{
        const node = nodeMap.get(nodeId);
        if (!node) {{
            continue;
        }}
        detailNodes.push({{
            ...node,
            size: nodeId === rootId ? 22 : 10,
            borderWidth: nodeId === rootId ? 3 : 1,
            font: {{ size: nodeId === rootId ? 14 : 10 }}
        }});
    }}

    const detailEdges = [];
    for (const edge of allEdges) {{
        if (selected.has(edge.from) && selected.has(edge.to)) {{
            detailEdges.push(edge);
            if (detailEdges.length >= detailEdgeLimit) {{
                break;
            }}
        }}
    }}

    return {{
        nodes: detailNodes,
        edges: detailEdges,
        truncated: selected.size >= nodeLimit || detailEdges.length >= detailEdgeLimit
    }};
}}

function buildGroupView(groupId) {{
    const members = (groupMembers[groupId] || []).slice(0, groupViewNodeLimit);
    const selected = new Set(members);

    for (const nodeId of members) {{
        const neighbors = adjacency[nodeId] || [];
        for (const neighborId of neighbors) {{
            if (selected.size >= defaultDetailNodeLimit) {{
                break;
            }}
            selected.add(neighborId);
        }}
        if (selected.size >= defaultDetailNodeLimit) {{
            break;
        }}
    }}

    const detailNodes = [];
    const focusMemberSet = new Set(members);
    const focusCount = Math.max(1, members.length);
    const focusRadius = Math.max(240, Math.ceil(Math.sqrt(focusCount)) * 42);
    let focusIndex = 0;
    for (const nodeId of selected) {{
        const node = nodeMap.get(nodeId);
        if (!node) {{
            continue;
        }}
        const isFocusMember = focusMemberSet.has(nodeId);
        const angle = focusIndex / focusCount * Math.PI * 2;
        if (isFocusMember) {{
            focusIndex += 1;
        }}
        detailNodes.push({{
            ...node,
            color: isFocusMember ? '#ff4d4f' : node.color,
            size: isFocusMember ? 16 : 9,
            borderWidth: isFocusMember ? 3 : 1,
            font: {{ size: isFocusMember ? 12 : 9, color: isFocusMember ? '#ffe2e2' : '#cdd6f4' }},
            mass: isFocusMember ? 2.4 : 1,
            x: isFocusMember ? Math.cos(angle) * focusRadius : undefined,
            y: isFocusMember ? Math.sin(angle) * focusRadius : undefined,
        }});
    }}

    const detailEdges = [];
    for (const edge of allEdges) {{
        if (selected.has(edge.from) && selected.has(edge.to)) {{
            detailEdges.push(edge);
            if (detailEdges.length >= detailEdgeLimit) {{
                break;
            }}
        }}
    }}

    return {{
        nodes: detailNodes,
        edges: detailEdges,
        truncated: members.length >= groupViewNodeLimit || selected.size >= defaultDetailNodeLimit || detailEdges.length >= detailEdgeLimit,
        memberCount: groupMembers[groupId] ? groupMembers[groupId].length : 0
    }};
}}

function exploreNode(nodeId) {{
    exploreNodeInternal(nodeId, true);
}}

function exploreNodeInternal(nodeId, pushHistory) {{
    if (!nodeId || !nodeMap.has(nodeId)) {{
        setStatus('No matching node found. Try the full FHIR reference or a more specific id fragment.');
        return;
    }}
    if (pushHistory && currentView) {{
        historyStack.push(cloneView(currentView));
    }}
    const depth = Number(depthSelect.value);
    const nodeLimit = Number(limitSelect.value) || defaultDetailNodeLimit;
    const detail = buildNeighborhood(nodeId, depth, nodeLimit);
    currentView = {{ type: 'node', nodeId, depth, nodeLimit }};
    currentNodeId = nodeId;
    currentGroupId = null;
    setMode('Neighborhood mode');
    setStatus(
        `Showing ${{detail.nodes.length}} nodes and ${{detail.edges.length}} edges around ${{nodeId}}` +
        (detail.truncated ? ' (truncated for performance).' : '.')
    );
    render(detail, 'node', true);
    searchInput.value = nodeId;
    updateBackButton();
}}

function exploreGroup(groupId) {{
    exploreGroupInternal(groupId, true);
}}

function exploreGroupInternal(groupId, pushHistory) {{
    if (!groupId || !groupMembers[groupId]) {{
        setStatus('No matching group found in overview mode.');
        return;
    }}
    if (pushHistory && currentView) {{
        historyStack.push(cloneView(currentView));
    }}
    const detail = buildGroupView(groupId);
    currentView = {{ type: 'group', groupId }};
    currentGroupId = groupId;
    currentNodeId = null;
    setMode('Group mode');
    setStatus(
        `Showing a drill-down for ${{groupId}} with ${{detail.nodes.length}} nodes and ${{detail.edges.length}} edges from ${{detail.memberCount.toLocaleString()}} resources.` +
        (detail.truncated ? ' Refine further by selecting a node.' : '')
    );
    render(detail, 'group', true);
    updateBackButton();
}}

function restoreView(view) {{
    if (!view) {{
        showOverview(false);
        return;
    }}
    if (view.type === 'node') {{
        if (view.depth) {{
            depthSelect.value = String(view.depth);
        }}
        if (view.nodeLimit) {{
            limitSelect.value = String(view.nodeLimit);
        }}
        exploreNodeInternal(view.nodeId, false);
        return;
    }}
    if (view.type === 'group') {{
        exploreGroupInternal(view.groupId, false);
        return;
    }}
    showOverview(false);
}}

document.getElementById('search-button').addEventListener('click', () => {{
    exploreNode(resolveNodeId(searchInput.value));
}});

document.getElementById('selected-button').addEventListener('click', () => {{
    if (currentGroupId && groupMembers[currentGroupId]) {{
        exploreGroup(currentGroupId);
        return;
    }}
    if (currentNodeId && nodeMap.has(currentNodeId)) {{
        exploreNode(currentNodeId);
        return;
    }}
    exploreNode(resolveNodeId(searchInput.value));
}});

document.getElementById('overview-button').addEventListener('click', () => {{
    showOverview(true);
}});

backButton.addEventListener('click', () => {{
    const previousView = historyStack.pop();
    restoreView(previousView || null);
    updateBackButton();
}});

function rerenderCurrentView() {{
    restoreView(currentView);
}}

for (const button of legendButtons) {{
    button.addEventListener('click', () => {{
        const group = button.dataset.group;
        if (activeGroups.has(group)) {{
            if (activeGroups.size === 1) {{
                return;
            }}
            activeGroups.delete(group);
        }} else {{
            activeGroups.add(group);
        }}
        syncLegendButtons();
        rerenderCurrentView();
    }});
}}

syncLegendButtons();

searchInput.addEventListener('keydown', (event) => {{
    if (event.key === 'ArrowDown' && currentMatches.length) {{
        event.preventDefault();
        activeMatchIndex = Math.min(activeMatchIndex + 1, currentMatches.length - 1);
        updateActiveSearchResult();
        return;
    }}
    if (event.key === 'ArrowUp' && currentMatches.length) {{
        event.preventDefault();
        activeMatchIndex = Math.max(activeMatchIndex - 1, 0);
        updateActiveSearchResult();
        return;
    }}
    if (event.key === 'Enter') {{
        event.preventDefault();
        if (currentMatches.length && activeMatchIndex >= 0) {{
            commitSearchSelection(currentMatches[activeMatchIndex].id);
            return;
        }}
        exploreNode(resolveNodeId(searchInput.value));
    }}
    if (event.key === 'Escape') {{
        clearSearchResults();
    }}
}});

searchInput.addEventListener('input', () => {{
    refreshSearchResults();
}});

searchInput.addEventListener('focus', () => {{
    refreshSearchResults();
}});

searchInput.addEventListener('search', () => {{
    if (searchInput.value.trim()) {{
        exploreNode(resolveNodeId(searchInput.value));
        return;
    }}
    clearSearchResults();
    restoreView(currentView);
}});

searchResults.addEventListener('mousedown', (event) => {{
    const button = event.target.closest('.search-result');
    if (!button) {{
        return;
    }}
    event.preventDefault();
    commitSearchSelection(button.dataset.nodeId);
}});

document.addEventListener('click', (event) => {{
    if (event.target === searchInput || searchResults.contains(event.target)) {{
        return;
    }}
    clearSearchResults();
}});

showOverview(false);
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="fhirviz — render a FHIR resource reference graph as interactive HTML."
    )
    parser.add_argument(
        "--dir",
        required=True,
        help="Directory containing FHIR .ndjson or .json files.",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f"Error: directory not found: {args.dir}")
        raise SystemExit(1)

    out_path = os.path.join(args.dir, "graph.html")
    title = f"FHIR Reference Graph — {args.dir}"

    print(f"Reading from: {args.dir}")
    nodes, edges = build_graph(args.dir)
    print(f"  {len(nodes)} nodes, {len(edges)} edges")
    if len(nodes) >= LARGE_GRAPH_THRESHOLD:
        print("  Large dataset detected: graph will open in overview mode with neighborhood exploration.")

    html = render_html(nodes, edges, title)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Graph written to: {out_path}")


if __name__ == "__main__":
    main()
