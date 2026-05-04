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
            edges.append((source_id, obj["reference"]))
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
    edges = []

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
            extract_references(resource, full_id, edges)

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

    return nodes, edges


def render_html(nodes, edges, title):
    node_list = []
    for nid, props in nodes.items():
        escaped_title = props["title"].replace("'", "\\'")
        escaped_label = props["label"].replace("'", "\\'")
        node_list.append(
            f"  {{id: '{nid}', label: '{escaped_label}', title: '{escaped_title}', "
            f"color: '{props['color']}', group: '{props['group']}'}}"
        )

    edge_list = []
    seen = set()
    for i, (src, tgt) in enumerate(edges):
        key = (src, tgt)
        if key not in seen and src != tgt:
            seen.add(key)
            edge_list.append(f"  {{id: {i}, from: '{src}', to: '{tgt}', arrows: 'to'}}")

    nodes_js = ",\n".join(node_list)
    edges_js = ",\n".join(edge_list)

    seen_groups = sorted({props["group"] for props in nodes.values()})
    legend_items = "".join(
        f'<div class="legend-item"><span class="dot" style="background:{RESOURCE_COLOURS.get(g, DEFAULT_COLOUR)}"></span>{g}</div>'
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
  h1 {{ padding: 12px 16px; font-size: 14px; font-weight: 500; color: #89b4fa; border-bottom: 1px solid #313244; }}
  #network {{ width: 100%; height: calc(100vh - 84px); }}
  #legend {{
    display: flex; flex-wrap: wrap; gap: 8px 16px;
    padding: 8px 16px; border-top: 1px solid #313244; font-size: 12px;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="network"></div>
<div id="legend">{legend_items}</div>
<script>
const nodes = new vis.DataSet([
{nodes_js}
]);
const edges = new vis.DataSet([
{edges_js}
]);
const container = document.getElementById('network');
const data = {{ nodes, edges }};
const options = {{
  nodes: {{
    shape: 'dot',
    size: 14,
    font: {{ size: 11, color: '#cdd6f4' }},
    borderWidth: 1.5,
  }},
  edges: {{
    color: {{ color: '#585b70', highlight: '#89b4fa' }},
    width: 1,
    smooth: {{ type: 'continuous' }},
  }},
  physics: {{
    stabilization: {{ iterations: 200 }},
    forceAtlas2Based: {{
      gravitationalConstant: -40,
      centralGravity: 0.005,
      springLength: 120,
    }},
    solver: 'forceAtlas2Based',
  }},
  interaction: {{
    hover: true,
    tooltipDelay: 100,
    zoomView: true,
    dragView: true,
  }},
}};
new vis.Network(container, data, options);
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
    print(f"  {len(nodes)} nodes, {len(set((s, t) for s, t in edges if s != t))} edges")

    html = render_html(nodes, edges, title)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Graph written to: {out_path}")


if __name__ == "__main__":
    main()
