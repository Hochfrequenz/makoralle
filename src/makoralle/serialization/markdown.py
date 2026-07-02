"""Render process YAML into MkDocs-flavoured Markdown (with Mermaid diagrams)."""

import re
from pathlib import Path
from typing import Any

import yaml

from makoralle.config import AHB_PID_URL


def _escape_mermaid(text: str) -> str:
    """Escape special characters for Mermaid node labels."""
    text = text.replace('"', "'")
    text = text.replace("\n", " ")
    # Remove PDF line-break hyphens like "verbrau- chende" -> "verbrauchende"
    text = re.sub(r"(\w)- (\w)", r"\1\2", text)
    return text.strip()


def _wrap_text(text: str, max_len: int = 80) -> str:
    """Wrap text for Mermaid node labels using <br/> for line breaks."""
    text = _escape_mermaid(text)
    if len(text) <= max_len:
        return text
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_len:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return "<br/>".join(lines)


def _render_ebd_flowchart(dt: dict[str, Any]) -> list[str]:
    """Render an EBD decision tree as a Mermaid flowchart with full text."""
    steps = dt.get("steps", [])
    if not steps:
        return []

    lines = ["```mermaid", "flowchart TD"]
    lines.append("    classDef reject fill:#ffcccc,stroke:#cc0000")
    lines.append("    classDef accept fill:#ccffcc,stroke:#00cc00")
    lines.append("")

    for step in steps:
        nr = step["nr"]
        check = _wrap_text(step.get("check", ""))
        lines.append(f'    s{nr}{{{{"{nr}. {check}"}}}}')

        # Yes branch
        if step.get("if_yes") and isinstance(step["if_yes"], int):
            lines.append(f"    s{nr} -->|ja| s{step['if_yes']}")
        elif step.get("if_yes_code"):
            code = step["if_yes_code"]
            result = step.get("if_yes_result", "")
            label = f"{code}: {result}" if result else code
            lines.append(f'    s{nr} -->|ja| ry{nr}["{_escape_mermaid(label)}"]')
            if result and "ablehnung" in result.lower():
                lines.append(f"    ry{nr}:::reject")
            else:
                lines.append(f"    ry{nr}:::accept")

        # No branch
        if step.get("if_no") and isinstance(step["if_no"], int):
            lines.append(f"    s{nr} -->|nein| s{step['if_no']}")
        elif step.get("if_no_code"):
            code = step["if_no_code"]
            result = step.get("if_no_result", "")
            label = f"{code}: {result}" if result else code
            lines.append(f'    s{nr} -->|nein| rn{nr}["{_escape_mermaid(label)}"]')
            if result and "ablehnung" in result.lower():
                lines.append(f"    rn{nr}:::reject")
            else:
                lines.append(f"    rn{nr}:::accept")

    lines.append("```")
    return lines


def _render_ebd_steps(dt: dict[str, Any]) -> list[str]:
    """Render EBD decision steps as a collapsible detail list with full text."""
    steps = dt.get("steps", [])
    if not steps:
        return []

    lines = ['??? abstract "Decision Steps"']
    for step in steps:
        nr = step["nr"]
        check = _escape_mermaid(step.get("check", ""))
        lines.append(f"    - **Step {nr}:** {check}")

        # Yes outcome
        if step.get("if_yes") and isinstance(step["if_yes"], int):
            hint = ""
            if step.get("if_yes_hint"):
                hint = f" {_escape_mermaid(step['if_yes_hint'])}"
            lines.append(f"        - \u2713 \u2192 Step {step['if_yes']}{hint}")
        elif step.get("if_yes_code"):
            code = step["if_yes_code"]
            hint = _escape_mermaid(step.get("if_yes_hint", ""))
            result = step.get("if_yes_result", "")
            lines.append(
                f"        - \u2713 \u2192 {code} {hint}" if hint else f"        - \u2713 \u2192 {code} {result}"
            )

        # No outcome
        if step.get("if_no") and isinstance(step["if_no"], int):
            hint = ""
            if step.get("if_no_hint"):
                hint = f" {_escape_mermaid(step['if_no_hint'])}"
            lines.append(f"        - \u2717 \u2192 Step {step['if_no']}{hint}")
        elif step.get("if_no_code"):
            code = step["if_no_code"]
            hint = _escape_mermaid(step.get("if_no_hint", ""))
            result = step.get("if_no_result", "")
            lines.append(
                f"        - \u2717 \u2192 {code} {hint}" if hint else f"        - \u2717 \u2192 {code} {result}"
            )

    return lines


def _pid_table(sd: dict[str, Any]) -> list[str]:
    """Per-step Prüfidentifikatoren, each linked to its AHB table page."""
    rows = []
    for s in sd.get("steps", []):
        pids = s.get("pid_refs") or []
        if not pids:
            continue
        links = ", ".join(f"[{p}]({AHB_PID_URL.format(pid=p)})" for p in pids)
        msg = (s.get("message") or "").replace("|", r"\|")
        rows.append(f"| {s.get('nr')} | {msg} | {s.get('format') or ''} | {links} |")
    if not rows:
        return []
    return [
        "**Prüfidentifikatoren:**",
        "",
        "| Schritt | Nachricht | Format | Prüfidentifikator |",
        "|---|---|---|---|",
        *rows,
        "",
    ]


def _deadline_legend(sd: dict[str, Any]) -> list[str]:
    """A short vocabulary legend for the deadline tags/notes rendered on the SD
    image. Only the marker kinds actually present on this diagram are listed:
    inline tags (unverzüglich/parallel/terminiert), an (i) reference note, and/or
    a [REVIEW] note for a still-unstructured complex Frist."""
    steps = sd.get("steps", [])
    types = {(s.get("deadline_rule") or {}).get("type") for s in steps}
    has_tags = bool(types & {"unverzüglich", "parallel", "terminiert"})
    has_reference = "reference" in types
    has_complex = "complex" in types
    if not (has_tags or has_reference or has_complex):
        return []
    lines = ["**Fristen (Legende der Diagramm-Markierungen):**", ""]
    if has_tags:
        lines += [
            "- `{u}` — unverzüglich",
            "- `{∥#N}` — parallel zu Schritt N",
            "- `{≤HH:MM nWT ÜZ#N}` — spätestens HH:MM, n Werktage nach dem ÜZ/ÜT von Schritt N",
            "- `{≤nWT vor|nach Anker}` — terminierte Frist, n Werktage vor/nach einem Termin "
            "(z. B. Zahlungsziel, Änderungstermin)",
        ]
    if has_reference:
        lines.append(
            "- `(i) …` (Notiz) — Frist als Verweis auf eine Tabelle / ein SD / den Rahmenvertrag oder mit Bedingung"
        )
    if has_complex:
        lines.append("- `(!) … [REVIEW]` (Notiz) — komplexe Frist, noch nicht strukturiert geparst")
    lines.append("")
    return lines


def _render_sequence_diagram(sd: dict[str, Any]) -> list[str]:  # pylint: disable=too-many-locals
    """Render a Mermaid sequence diagram with full message text."""
    steps = sd.get("steps", [])
    participants = sd.get("participants", [])
    if not steps:
        return []

    lines = ["```mermaid", "sequenceDiagram"]
    for p in participants:
        lines.append(f"    participant {p}")

    for step in steps:
        nr = step.get("nr", "")
        sender = step.get("sender", "")
        receiver = step.get("receiver", "")
        message = step.get("message", "")
        fmt = step.get("format", "")
        subprocess_ref = step.get("subprocess_ref", "")
        pids = step.get("pid_refs", [])

        # Build message label
        if subprocess_ref:
            label = f"{nr}. ref {message}"
        else:
            label = f"{nr}. {message}"
            if fmt:
                label += f" [{fmt}]"
            if pids:
                pid_str = ",".join(str(p) for p in pids)
                label += f" (PID:{pid_str})"

        # Mermaid expresses the dashed/solid shaft (-->> vs ->>); the open-vs-filled
        # head distinction has no clean Mermaid equivalent, so it is not carried here.
        arrow = "-->>" if step.get("line") == "dashed" else "->>"

        lines.append(f"    {sender}{arrow}+{receiver}: {label}")
        if subprocess_ref and sender != receiver:
            lines.append(f"    Note right of {receiver}: Subprocess call")

    lines.append("```")
    return lines


def _render_sd_table(sd: dict[str, Any]) -> list[str]:
    """Render sequence diagram step details as a collapsible table."""
    steps = sd.get("steps", [])
    if not steps:
        return []

    lines = ['??? abstract "Step Details"', ""]
    lines.append("    | Nr | From | To | Message | Format | Type | PIDs | Deadline |")
    lines.append("    |---|---|---|---|---|---|---|---|")
    for step in steps:
        nr = step.get("nr", "")
        sender = step.get("sender", "")
        receiver = step.get("receiver", "")
        message = step.get("message", "")
        fmt = step.get("format", "")
        subprocess_ref = step.get("subprocess_ref", "")
        pids = step.get("pid_refs", [])
        deadline = step.get("deadline", "")

        if subprocess_ref:
            message = f"\u21aa {message}"
            deadline = "\u2014"

        if isinstance(deadline, str):
            deadline = deadline.replace("\n", " ").replace("|", "\\|")

        pid_str = ",".join(str(p) for p in pids) if pids else ""

        lines.append(
            f"    | {nr} | {sender} | {receiver} | {message} | "
            f"{fmt} | {'subprocess_ref' if subprocess_ref else ''} | {pid_str} | {deadline} |"
        )

    return lines


def yaml_to_markdown(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    yaml_content: str, has_bpmn: bool = False, has_sequence: bool = False
) -> str:
    """Convert YAML process data to full enhanced markdown."""
    data = yaml.safe_load(yaml_content)
    lines = []

    proc = data.get("process", {})
    lines.append(f"# {proc.get('name', 'Unknown Process')}")
    lines.append("")
    lines.append(f"**Source:** {proc.get('source', '')}")
    lines.append("")

    # Use Case section with admonitions
    uc = data.get("use_case")
    if uc:
        lines.append("## Use Case")
        lines.append("")
        lines.append(f"**Goal:** {uc.get('goal', '')}")
        lines.append("")
        if uc.get("description"):
            lines.append(uc["description"])
            lines.append("")
        if uc.get("roles"):
            lines.append(f"**Roles:** {', '.join(uc['roles'])}")
            lines.append("")
        if uc.get("preconditions"):
            lines.append('??? info "Preconditions"')
            for p in uc["preconditions"]:
                lines.append(f"    - {p}")
            lines.append("")
        if uc.get("triggers"):
            lines.append('??? tip "Triggers"')
            for t in uc["triggers"]:
                lines.append(f"    - {t}")
            lines.append("")
        if uc.get("postconditions_success"):
            lines.append('??? success "Success"')
            for p in uc["postconditions_success"]:
                lines.append(f"    - {p}")
            lines.append("")
        if uc.get("postconditions_failure"):
            lines.append('??? failure "Failure"')
            for p in uc["postconditions_failure"]:
                lines.append(f"    - {p}")
            lines.append("")
        if uc.get("additional_requirements"):
            lines.append('??? note "Additional Requirements"')
            for r in uc["additional_requirements"]:
                lines.append(f"    - {r}")
            lines.append("")

    # Sequence Diagram section
    sd = data.get("sequence_diagram")
    if sd and sd.get("steps"):
        lines.append("## Sequence Diagram")
        lines.append("")
        if has_sequence:
            # Faithful websequencediagrams render (fragments, refs, source actor
            # order, step numbers). Embedded inline + interactive pan/zoom viewer.
            process_id = proc.get("id", "")
            # The embedded image links to the interactive viewer (pan/zoom + clickable PIDs).
            lines.append(
                f"[![Sequence Diagram: {proc.get('name', '')}](../../sequence/{process_id}.svg)]"
                f"(../../sequence/{process_id}.html)"
            )
            lines.append("")
            lines.append(f"[Open interactive sequence diagram](../../sequence/{process_id}.html)" "{ .md-button }")
            lines.append("")
        else:
            lines.extend(_render_sequence_diagram(sd))  # Mermaid fallback
            lines.append("")
        lines.extend(_deadline_legend(sd))
        lines.extend(_pid_table(sd))  # per-step Prüfidentifikatoren → AHB links
        lines.extend(_render_sd_table(sd))
        lines.append("")

    # Decision Trees (EBD) section
    dts = data.get("decision_trees", [])
    if dts:
        lines.append("## Decision Trees (EBD)")
        lines.append("")
        for dt in dts:
            ebd_id = dt.get("id", "")
            ebd_name = _escape_mermaid(dt.get("name", ""))
            role = dt.get("role", "")
            step_count = len(dt.get("steps", []))

            lines.append(f"### {ebd_id} \u2014 {ebd_name}")
            lines.append("")
            lines.append(f"**Role:** {role} | **Steps:** {step_count}")
            lines.append("")

            flowchart = _render_ebd_flowchart(dt)
            if flowchart:
                lines.extend(flowchart)
                lines.append("")

            step_details = _render_ebd_steps(dt)
            if step_details:
                lines.extend(step_details)
                lines.append("")

    # PID Mappings section
    pids = data.get("pid_mappings", [])
    if pids:
        lines.append("## Prüfidentifikatoren (PID)")
        lines.append("")
        lines.append("| PID | Anwendungsfall | Von | An | AHB | Weg |")
        lines.append("|---|---|---|---|---|---|")
        for pid in pids:
            lines.append(
                f"| {pid.get('prüfidentifikator', '')} | "
                f"{pid.get('anwendungsfall', '')} | "
                f"{pid.get('kommunikation_von', '')} | "
                f"{pid.get('kommunikation_an', '')} | "
                f"{pid.get('ahb', '')} | "
                f"{pid.get('übertragungsweg', '')} |"
            )
        lines.append("")

    # Activity Diagram / BPMN link
    if has_bpmn:
        process_id = proc.get("id", "")
        lines.append("## Activity Diagram")
        lines.append("")
        lines.append(
            f"[Open BPMN Viewer (interactive)](../../bpmn/{process_id}.html)" "{ .md-button .md-button--primary }"
        )
        lines.append("")

    return "\n".join(lines)


def emit_markdown(
    yaml_path: Path, output_dir: Path, bpmn_dir: Path | None = None, sequence_dir: Path | None = None
) -> Path:
    """Emit a markdown file from a YAML process definition.

    Args:
        yaml_path: Path to the YAML file
        output_dir: Directory to write the markdown file
        bpmn_dir: Optional path to BPMN directory to check for viewer files
        sequence_dir: Optional path to the rendered sequence-diagram SVG directory
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    yaml_content = yaml_path.read_text(encoding="utf-8")

    # Check if BPMN / sequence-diagram viewers exist for this process
    process_id = yaml_path.stem
    has_bpmn = False
    if bpmn_dir:
        has_bpmn = (bpmn_dir / f"{process_id}.html").exists()
    has_sequence = False
    if sequence_dir:
        has_sequence = (sequence_dir / f"{process_id}.svg").exists()

    md = yaml_to_markdown(yaml_content, has_bpmn=has_bpmn, has_sequence=has_sequence)
    output_path = output_dir / yaml_path.with_suffix(".md").name
    output_path.write_text(md, encoding="utf-8")
    return output_path
