"""Convert PlantUML activity diagrams to BPMN 2.0 XML.

Handles:
- Swimlanes → BPMN Lanes within a single Pool
- Actions (;) → BPMN Tasks
- Signals (/) → BPMN SendTasks
- Subprocess refs (#FFFACD ... |) → BPMN CallActivity
- Decisions (if/else/endif) → BPMN ExclusiveGateway
- Fork/join (fork/end fork) → BPMN ParallelGateway
- Start/stop → BPMN StartEvent/EndEvent
"""

import io
import json
import logging
import re
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ElementTree, SubElement, indent

logger = logging.getLogger(__name__)


def _parse_plantuml_to_flow(puml: str) -> list[dict[str, Any]]:  # pylint: disable=too-many-branches,too-many-statements
    """Parse PlantUML activity diagram into a flat flow list."""
    flow: list[dict[str, Any]] = []
    current_lane: str | None = None
    node_counter = [0]

    def next_id(prefix: str = "node") -> str:
        node_counter[0] += 1
        return f"{prefix}_{node_counter[0]}"

    lines = puml.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line or line.startswith("'") or line.startswith("skinparam") or line.startswith("!"):
            continue

        # Swimlane: |LF|
        if re.match(r"^\|[^|]+\|$", line):
            current_lane = line.strip("|")
            continue

        # Start
        if line == "start":
            flow.append({"type": "start", "id": next_id("start"), "lane": current_lane})
            continue

        # Stop/end
        if line in ("stop", "end"):
            flow.append({"type": "end", "id": next_id("end"), "lane": current_lane})
            continue

        # Subprocess ref: #FFFACD:Name|
        if "#FFFACD" in line and line.endswith("|"):
            name = re.sub(r"^#\w+:", "", line).rstrip("|").replace("\\n", " ")
            flow.append({"type": "subprocess", "id": next_id("sub"), "name": name, "lane": current_lane})
            continue

        # Signal (message send): :text/
        if line.startswith(":") and line.endswith("/"):
            name = line[1:-1].replace("\\n", " ")
            flow.append({"type": "send", "id": next_id("send"), "name": name, "lane": current_lane})
            continue

        # Action: :text;
        if line.startswith(":") and line.endswith(";"):
            name = line[1:-1].replace("\\n", " ")
            flow.append({"type": "task", "id": next_id("task"), "name": name, "lane": current_lane})
            continue

        # Decision: if (condition?) then (ja)
        if_match = re.match(r"if\s*\((.+?)\)\s*then\s*\((.+?)\)", line)
        if if_match:
            condition = if_match.group(1).replace("\\n", " ")
            flow.append(
                {
                    "type": "gateway_split",
                    "id": next_id("gw"),
                    "name": condition,
                    "lane": current_lane,
                    "gateway_type": "exclusive",
                }
            )
            flow.append({"type": "branch_start", "branch": if_match.group(2), "lane": current_lane})
            continue

        if line.startswith("else"):
            branch = ""
            else_match = re.match(r"else\s*\((.+?)\)", line)
            if else_match:
                branch = else_match.group(1)
            flow.append({"type": "branch_else", "branch": branch, "lane": current_lane})
            continue

        if line == "endif":
            flow.append(
                {"type": "gateway_merge", "id": next_id("gw_merge"), "lane": current_lane, "gateway_type": "exclusive"}
            )
            continue

        # Fork: fork / fork again / end fork
        if line == "fork":
            flow.append(
                {
                    "type": "gateway_split",
                    "id": next_id("par"),
                    "name": "",
                    "lane": current_lane,
                    "gateway_type": "parallel",
                }
            )
            flow.append({"type": "branch_start", "branch": "fork_1", "lane": current_lane})
            continue

        if line == "fork again":
            flow.append({"type": "branch_else", "branch": "fork_next", "lane": current_lane})
            continue

        if line == "end fork":
            flow.append(
                {"type": "gateway_merge", "id": next_id("par_merge"), "lane": current_lane, "gateway_type": "parallel"}
            )
            continue

        # Note (skip)
        if line.startswith("note ") or line == "end note":
            continue

    return flow


def plantuml_to_bpmn(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    puml: str, process_name: str = "Process"
) -> str:
    """Convert PlantUML activity diagram to BPMN 2.0 XML."""
    flow = _parse_plantuml_to_flow(puml)

    # Collect lanes
    lanes: list[str] = []
    for item in flow:
        if item.get("lane") and item["lane"] not in lanes:
            lanes.append(item["lane"])
    if not lanes:
        lanes = ["Default"]

    # BPMN namespaces
    ns = {
        "": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
    }
    for prefix, uri in ns.items():
        if prefix:
            Element(f"_{prefix}").tag  # register  # pylint: disable=expression-not-assigned
            import xml.etree.ElementTree as ET  # pylint: disable=import-outside-toplevel

            ET.register_namespace(prefix, uri)
        else:
            import xml.etree.ElementTree as ET  # pylint: disable=import-outside-toplevel

            ET.register_namespace("", uri)

    definitions = Element(
        "definitions",
        {
            "xmlns": ns[""],
            "xmlns:bpmndi": ns["bpmndi"],
            "xmlns:dc": ns["dc"],
            "xmlns:di": ns["di"],
            "id": "definitions",
            "targetNamespace": "http://mako.energyerp.de",
        },
    )

    # Single process with lane set
    process = SubElement(
        definitions,
        "process",
        {
            "id": "process_1",
            "name": process_name,
            "isExecutable": "false",
        },
    )

    lane_set = SubElement(process, "laneSet", {"id": "laneSet_1"})
    lane_elements: dict[str, Element] = {}
    for lane_name in lanes:
        lane_id = f"lane_{lane_name}"
        lane_el = SubElement(lane_set, "lane", {"id": lane_id, "name": lane_name})
        lane_elements[lane_name] = lane_el

    # Build BPMN elements from flow
    gateway_stack: list[dict[str, Any]] = []  # stack for handling nested gateways

    prev_id: str | None = None

    for item in flow:
        item_type = item.get("type")
        item_id: str = item.get("id", "")
        item_name = item.get("name", "")
        item_lane = item.get("lane") or (lanes[0] if lanes else "Default")

        if item_type == "start":
            SubElement(process, "startEvent", {"id": item_id, "name": "Start"})
            if item_lane in lane_elements:
                SubElement(lane_elements[item_lane], "flowNodeRef").text = item_id
            if prev_id:
                sf_id = f"sf_{prev_id}_{item_id}"
                SubElement(process, "sequenceFlow", {"id": sf_id, "sourceRef": prev_id, "targetRef": item_id})
            prev_id = item_id

        elif item_type == "end":
            SubElement(process, "endEvent", {"id": item_id, "name": "End"})
            if item_lane in lane_elements:
                SubElement(lane_elements[item_lane], "flowNodeRef").text = item_id
            if prev_id:
                sf_id = f"sf_{prev_id}_{item_id}"
                SubElement(process, "sequenceFlow", {"id": sf_id, "sourceRef": prev_id, "targetRef": item_id})
            prev_id = item_id

        elif item_type == "task":
            SubElement(process, "task", {"id": item_id, "name": item_name})
            if item_lane in lane_elements:
                SubElement(lane_elements[item_lane], "flowNodeRef").text = item_id
            if prev_id:
                sf_id = f"sf_{prev_id}_{item_id}"
                SubElement(process, "sequenceFlow", {"id": sf_id, "sourceRef": prev_id, "targetRef": item_id})
            prev_id = item_id

        elif item_type == "send":
            SubElement(process, "sendTask", {"id": item_id, "name": item_name})
            if item_lane in lane_elements:
                SubElement(lane_elements[item_lane], "flowNodeRef").text = item_id
            if prev_id:
                sf_id = f"sf_{prev_id}_{item_id}"
                SubElement(process, "sequenceFlow", {"id": sf_id, "sourceRef": prev_id, "targetRef": item_id})
            prev_id = item_id

        elif item_type == "subprocess":
            SubElement(process, "callActivity", {"id": item_id, "name": item_name})
            if item_lane in lane_elements:
                SubElement(lane_elements[item_lane], "flowNodeRef").text = item_id
            if prev_id:
                sf_id = f"sf_{prev_id}_{item_id}"
                SubElement(process, "sequenceFlow", {"id": sf_id, "sourceRef": prev_id, "targetRef": item_id})
            prev_id = item_id

        elif item_type == "gateway_split":
            gw_type = item.get("gateway_type", "exclusive")
            tag = "exclusiveGateway" if gw_type == "exclusive" else "parallelGateway"
            SubElement(process, tag, {"id": item_id, "name": item_name, "gatewayDirection": "Diverging"})
            if item_lane in lane_elements:
                SubElement(lane_elements[item_lane], "flowNodeRef").text = item_id
            if prev_id:
                sf_id = f"sf_{prev_id}_{item_id}"
                SubElement(process, "sequenceFlow", {"id": sf_id, "sourceRef": prev_id, "targetRef": item_id})
            gateway_stack.append({"id": item_id, "type": gw_type, "branches": [], "prev_ends": []})
            prev_id = item_id

        elif item_type == "branch_start":
            # Mark the start of a branch from the current gateway
            if gateway_stack:
                gateway_stack[-1]["branch_start_prev"] = prev_id

        elif item_type == "branch_else":
            # End current branch, start new one
            if gateway_stack:
                gw = gateway_stack[-1]
                gw["prev_ends"].append(prev_id)
                prev_id = gw["id"]  # reset to gateway for next branch

        elif item_type == "gateway_merge":
            if gateway_stack:
                gw = gateway_stack.pop()
                gw["prev_ends"].append(prev_id)
                # Create merge gateway
                gw_type = gw.get("type", "exclusive")
                tag = "exclusiveGateway" if gw_type == "exclusive" else "parallelGateway"
                SubElement(process, tag, {"id": item_id, "name": "", "gatewayDirection": "Converging"})
                if item_lane in lane_elements:
                    SubElement(lane_elements[item_lane], "flowNodeRef").text = item_id
                # Connect all branch ends to merge
                for end_id in gw["prev_ends"]:
                    if end_id:
                        sf_id = f"sf_{end_id}_{item_id}"
                        SubElement(process, "sequenceFlow", {"id": sf_id, "sourceRef": end_id, "targetRef": item_id})
                prev_id = item_id

    # Generate diagram layout
    _generate_diagram(definitions, process, lane_elements)

    # Serialize
    indent(definitions, space="  ")
    buf = io.BytesIO()
    tree = ElementTree(definitions)
    tree.write(buf, xml_declaration=True, encoding="UTF-8")
    return buf.getvalue().decode("UTF-8")


# Layout constants
TASK_W = 160
TASK_H = 60
GW_SIZE = 50
EVENT_SIZE = 36
H_GAP = 60  # horizontal gap between elements
V_GAP = 40  # vertical gap between lanes
LANE_PAD = 30  # padding inside lane
LANE_HEADER = 30  # width of lane label on left


def _generate_diagram(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks
    definitions: Element, process_el: Element, lane_elements: dict[str, Element]
) -> None:
    """Generate BPMNDiagram with proper layout coordinates and edges."""
    ns_bpmndi = "http://www.omg.org/spec/BPMN/20100524/DI"
    ns_dc = "http://www.omg.org/spec/DD/20100524/DC"
    ns_di = "http://www.omg.org/spec/DD/20100524/DI"

    # Collect all flow nodes and sequence flows from the process
    nodes: dict[str, str] = {}  # id -> element tag
    seq_flows: list[tuple[str, str, str]] = []  # (id, sourceRef, targetRef)
    node_order: list[str] = []  # preserve order
    lane_membership: dict[str, str] = {}  # node_id -> lane_name

    for child in process_el:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        eid = child.get("id", "")

        if tag == "laneSet":
            for lane_el in child:
                lane_tag = lane_el.tag.split("}")[-1] if "}" in lane_el.tag else lane_el.tag
                if lane_tag == "lane":
                    lane_name = lane_el.get("name", "")
                    for ref in lane_el:
                        ref_tag = ref.tag.split("}")[-1] if "}" in ref.tag else ref.tag
                        if ref_tag == "flowNodeRef" and ref.text:
                            lane_membership[ref.text] = lane_name
        elif tag == "sequenceFlow":
            seq_flows.append((eid, child.get("sourceRef", ""), child.get("targetRef", "")))
        elif eid:
            nodes[eid] = tag
            node_order.append(eid)

    if not nodes:
        return

    # Build adjacency for topological sort
    outgoing: dict[str, list[str]] = {}  # node_id -> [target_ids]
    incoming: dict[str, list[str]] = {}  # node_id -> [source_ids]
    for sf_id, src, tgt in seq_flows:
        outgoing.setdefault(src, []).append(tgt)
        incoming.setdefault(tgt, []).append(src)

    # Assign columns via BFS from start nodes
    start_nodes = [nid for nid in node_order if nid not in incoming or not incoming.get(nid)]
    if not start_nodes:
        start_nodes = [node_order[0]]

    col: dict[str, int] = {}  # node_id -> column index
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(nid, 0) for nid in start_nodes]
    for nid in start_nodes:
        col[nid] = 0
        visited.add(nid)

    while queue:
        nid, c = queue.pop(0)
        for tgt in outgoing.get(nid, []):
            new_col = c + 1
            if tgt in col:
                col[tgt] = max(col[tgt], new_col)
            else:
                col[tgt] = new_col
            if tgt not in visited:
                visited.add(tgt)
                queue.append((tgt, new_col))

    # Assign remaining nodes
    for nid in node_order:
        if nid not in col:
            col[nid] = len(col)

    # Determine lanes and their rows
    lanes = list(lane_elements.keys()) if lane_elements else ["Default"]
    lane_row = {lane: i for i, lane in enumerate(lanes)}

    # For each node, determine its row (lane) and column
    node_positions: dict[str, tuple[int, int, int, int]] = {}  # node_id -> (x, y, w, h)

    # Track columns per lane to handle multiple nodes in same column
    lane_col_rows: dict[tuple[str, int], int] = {}  # (lane, col) -> count of nodes

    for nid in node_order:
        if nid not in col:
            continue
        c = col[nid]
        lane = lane_membership.get(nid, lanes[0])
        row = lane_row.get(lane, 0)

        # Sub-row within lane for nodes sharing a column
        key = (lane, c)
        sub = lane_col_rows.get(key, 0)
        lane_col_rows[key] = sub + 1

        tag = nodes.get(nid, "")
        if tag in ("startEvent", "endEvent"):
            w, h = EVENT_SIZE, EVENT_SIZE
        elif "Gateway" in tag:
            w, h = GW_SIZE, GW_SIZE
        else:
            w, h = TASK_W, TASK_H

        x = LANE_HEADER + LANE_PAD + c * (TASK_W + H_GAP) + (TASK_W - w) // 2
        lane_height = TASK_H + V_GAP
        lane_y_start = row * (lane_height * 3 + V_GAP * 2)
        y = lane_y_start + LANE_PAD + sub * (TASK_H + V_GAP) + (TASK_H - h) // 2

        node_positions[nid] = (x, y, w, h)

    # Create BPMNDiagram
    diagram = SubElement(
        definitions,
        f"{{{ns_bpmndi}}}BPMNDiagram",
        {
            "id": "BPMNDiagram_1",
        },
    )
    plane = SubElement(
        diagram,
        f"{{{ns_bpmndi}}}BPMNPlane",
        {
            "id": "BPMNPlane_1",
            "bpmnElement": process_el.get("id", "process_1"),
        },
    )

    # Add lane shapes
    if lane_elements:
        # Calculate total width
        max_col = max(col.values()) if col else 0
        total_w = LANE_HEADER + LANE_PAD * 2 + (max_col + 1) * (TASK_W + H_GAP)

        SubElement(
            plane,
            f"{{{ns_bpmndi}}}BPMNShape",
            {
                "id": "laneSet_1_di",
                "bpmnElement": "laneSet_1",
                "isHorizontal": "true",
            },
        )
        lane_height_each = TASK_H + V_GAP * 2 + LANE_PAD * 2

        for lane_name in lanes:
            row = lane_row[lane_name]
            lane_id = f"lane_{lane_name}"
            ly = row * (lane_height_each + V_GAP)
            shape = SubElement(
                plane,
                f"{{{ns_bpmndi}}}BPMNShape",
                {
                    "id": f"{lane_id}_di",
                    "bpmnElement": lane_id,
                    "isHorizontal": "true",
                },
            )
            SubElement(
                shape,
                f"{{{ns_dc}}}Bounds",
                {
                    "x": "0",
                    "y": str(ly),
                    "width": str(total_w),
                    "height": str(lane_height_each),
                },
            )

    # Add node shapes
    for nid in node_order:
        if nid not in node_positions:
            continue
        x, y, w, h = node_positions[nid]
        tag = nodes.get(nid, "")

        attrs = {
            "id": f"{nid}_di",
            "bpmnElement": nid,
        }
        if "Gateway" in tag:
            attrs["isMarkerVisible"] = "true"

        shape = SubElement(plane, f"{{{ns_bpmndi}}}BPMNShape", attrs)
        SubElement(
            shape,
            f"{{{ns_dc}}}Bounds",
            {
                "x": str(x),
                "y": str(y),
                "width": str(w),
                "height": str(h),
            },
        )

    # Add edge waypoints
    for sf_id, src, tgt in seq_flows:
        if src not in node_positions or tgt not in node_positions:
            continue
        sx, sy, sw, sh = node_positions[src]
        tx, ty, _tw, th = node_positions[tgt]

        # Connect from right center of source to left center of target
        src_x = sx + sw
        src_y = sy + sh // 2
        tgt_x = tx
        tgt_y = ty + th // 2

        edge = SubElement(
            plane,
            f"{{{ns_bpmndi}}}BPMNEdge",
            {
                "id": f"{sf_id}_di",
                "bpmnElement": sf_id,
            },
        )

        if abs(src_y - tgt_y) < 5:
            # Same row — straight horizontal line
            SubElement(edge, f"{{{ns_di}}}waypoint", {"x": str(src_x), "y": str(src_y)})
            SubElement(edge, f"{{{ns_di}}}waypoint", {"x": str(tgt_x), "y": str(tgt_y)})
        else:
            # Different rows — route with right-angle bends
            mid_x = (src_x + tgt_x) // 2
            SubElement(edge, f"{{{ns_di}}}waypoint", {"x": str(src_x), "y": str(src_y)})
            SubElement(edge, f"{{{ns_di}}}waypoint", {"x": str(mid_x), "y": str(src_y)})
            SubElement(edge, f"{{{ns_di}}}waypoint", {"x": str(mid_x), "y": str(tgt_y)})
            SubElement(edge, f"{{{ns_di}}}waypoint", {"x": str(tgt_x), "y": str(tgt_y)})


def emit_bpmn(puml_path: Path, output_dir: Path, process_name: str = "") -> Path | None:
    """Convert a PlantUML AD file to BPMN and render it."""
    output_dir.mkdir(parents=True, exist_ok=True)

    puml = puml_path.read_text()
    if not process_name:
        process_name = puml_path.stem.replace("_", " ").title()

    bpmn_xml = plantuml_to_bpmn(puml, process_name)

    # Save raw BPMN
    bpmn_path = output_dir / f"{puml_path.stem}.bpmn"
    bpmn_path.write_text(bpmn_xml)

    # Create HTML viewer
    html_path = output_dir / f"{puml_path.stem}.html"
    bpmn_content = bpmn_path.read_text()
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{process_name} — BPMN</title>
    <script src="https://unpkg.com/bpmn-js@18/dist/bpmn-navigated-viewer.production.min.js"></script>
    <style>
        html, body {{ height: 100%; margin: 0; font-family: sans-serif; }}
        #header {{ padding: 10px 20px; background: #f0f0f0; border-bottom: 1px solid #ddd; }}
        #canvas {{ height: calc(100% - 50px); }}
    </style>
</head>
<body>
    <div id="header"><strong>{process_name}</strong> — Activity Diagram as BPMN</div>
    <div id="canvas"></div>
    <script>
        var bpmnXML = {json.dumps(bpmn_content)};
        var viewer = new BpmnJS({{ container: '#canvas' }});
        viewer.importXML(bpmnXML).then(function() {{
            viewer.get('canvas').zoom('fit-viewport');
        }}).catch(function(err) {{
            document.getElementById('canvas').innerHTML = '<pre style="padding:20px">' + err.message + '</pre>';
        }});
    </script>
</body>
</html>"""
    html_path.write_text(html)

    logger.info("BPMN: %s, HTML: %s", bpmn_path, html_path)
    return bpmn_path
