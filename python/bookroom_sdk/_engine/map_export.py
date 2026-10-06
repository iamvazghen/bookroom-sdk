"""Turn the report's concept-map Markdown into a validated portable graph."""

import re
import unicodedata
import json
from pathlib import Path

from report_format import REPORT_SECTIONS


def _node_id(label: str, ordinal: int) -> str:
    value = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:48]
    return f"{value or 'concept'}-{ordinal}"


def _parse_diagram(lines: list[str], nodes: list[dict], edges: list[dict]) -> bool:
    """Recover explicit columns and indented list relationships from a fenced text map."""
    headers: list[tuple[int, str, int]] = []
    central_id = None
    bullet_stacks: dict[str, list[tuple[int, str, int]]] = {}
    found_structure = False
    for raw in lines:
        letters = "".join(character for character in raw if character.isalpha())
        is_header = len(letters) >= 4 and letters.isupper() and not re.search(r"[•*+-]\s", raw)
        if is_header:
            parts = [part.strip(" \t│") for part in re.split(r"\s{3,}", raw.strip())]
            parts = [part for part in parts if part and any(char.isalpha() for char in part)]
            if parts:
                found_structure = True
                headers = []
                for part in parts:
                    column = raw.find(part)
                    parent = central_id if len(parts) > 1 and central_id else None
                    depth = 1 if parent else 0
                    node = {"id": _node_id(part, len(nodes) + 1), "label": part, "depth": depth}
                    nodes.append(node)
                    if parent:
                        edges.append({"source": parent, "target": node["id"], "relation": "organizes"})
                    headers.append((column, node["id"], depth))
                    bullet_stacks[node["id"]] = []
                if len(parts) == 1 and central_id is None:
                    central_id = headers[0][1]
                continue
        matches = list(re.finditer(r"(?<!\S)[•*+-]\s+(.+?)(?=\s{3,}[•*+-]\s+|$)", raw))
        if not matches or not headers:
            continue
        for match in matches:
            column, label = match.start(), match.group(1)
            group = min(headers, key=lambda entry: abs(entry[0] - column))
            stack = bullet_stacks[group[1]]
            while stack and stack[-1][0] >= column:
                stack.pop()
            parent_id = stack[-1][1] if stack else group[1]
            parent_depth = stack[-1][2] if stack else group[2]
            node = {"id": _node_id(label.strip(), len(nodes) + 1), "label": re.sub(r"\s+", " ", label.strip()), "depth": parent_depth + 1}
            nodes.append(node)
            edges.append({"source": parent_id, "target": node["id"], "relation": "subconcept_of"})
            stack.append((column, node["id"], node["depth"]))
    return found_structure


def markdown_to_graph(markdown_text: str) -> dict:
    nodes, edges, stack, diagram_lines = [], [], [], []
    lines = markdown_text.splitlines()
    in_code_block = False
    plain_lines = []
    for raw in lines:
        if raw.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            diagram_lines.append(raw)
            continue
        plain_lines.append(raw)
    structured_diagram = _parse_diagram(diagram_lines, nodes, edges) if diagram_lines else False
    for raw in plain_lines + ([] if structured_diagram else diagram_lines):
        match = re.match(r"^(\s*)(?:[-*+] |\d+[.)] )(.*)$", raw)
        if not match:
            continue
        indent, label = match.groups()
        label = re.sub(r"\s+", " ", label).strip()
        if not label:
            continue
        depth = min(8, len(indent.expandtabs(2)) // 2)
        node = {"id": _node_id(label, len(nodes) + 1), "label": label, "depth": depth}
        nodes.append(node)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            edges.append({"source": stack[-1][1], "target": node["id"], "relation": "subconcept_of"})
        stack.append((depth, node["id"]))
    if not nodes:
        for label in re.findall(r"[^\n.;]+", markdown_text):
            label = label.strip(" #-\t")
            if label:
                nodes.append({"id": _node_id(label, len(nodes) + 1), "label": label, "depth": 0})
    graph = {"schema_version": "1.0", "nodes": nodes, "edges": edges}
    validate_graph(graph)
    return graph


def validate_graph(graph: dict) -> None:
    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise ValueError("Graph requires nodes and edges arrays")
    ids = [node.get("id") for node in graph["nodes"]]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("Graph node IDs must be unique and non-empty")
    known = set(ids)
    for edge in graph["edges"]:
        if edge.get("source") not in known or edge.get("target") not in known:
            raise ValueError("Graph edge references an unknown node")
        if edge["source"] == edge["target"]:
            raise ValueError("Graph cannot contain self edges")


def write_study_map(report_path: Path) -> Path:
    report_path = Path(report_path)
    lines = report_path.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## Concept Map") + 1
    except ValueError as exc:
        raise ValueError("Report has no Concept Map section") from exc
    headings = {f"## {heading}" for _, heading in REPORT_SECTIONS}
    end = next((index for index in range(start, len(lines)) if lines[index] in headings), len(lines))
    graph = markdown_to_graph("\n".join(lines[start:end]).strip())
    output = report_path.with_name("study-maps.json")
    output.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate a validated concept-map JSON export from a study guide.")
    parser.add_argument("report", type=Path, help="Canonical study-guide Markdown file")
    args = parser.parse_args()
    output = write_study_map(args.report)
    print(f"Wrote {output} with {len(json.loads(output.read_text(encoding='utf-8'))['nodes'])} concepts.")
