"""Render process YAML into MkDocs-flavoured Markdown (with Mermaid diagrams)."""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from makoralle.config import AHB_PID_URL
from makoralle.ebd_clusters import cluster_to_kind, extract_cluster
from makoralle.models.process import REF_PREFIX, is_known_actor, is_ref_step
from makoralle.serialization.wsd import span_of_lanes

logger = logging.getLogger(__name__)


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


#: The fill/stroke of each outcome class, from the company palette's *semantic* tokens
#: (``companystylesheet/css/hochfrequenz.css``) rather than from raw red and green. The colours
#: carry the decision, so they cannot be mapped to the brand lila the way the sequence diagrams
#: were (makorele#38); what they can be mapped to is the palette's own positive/negative/neutral
#: family, which exists for exactly this (makoralle#23).
#:
#: The stroke is the *dark* token of each family, not the base one. Measured contrast against the
#: light fill, base vs dark: accept 1.94 vs 4.87, reject 1.42 vs 5.79, info 1.31 vs 5.91 — the base
#: token would have left `accept` exactly as invisible as the raw `#ccffcc/#00cc00` pair it
#: replaces (1.94) and made `reject` worse than the `#ffcccc/#cc0000` it replaces (4.14 -> 1.42).
#: Every class is now more legible than what it replaces, and they are legible to the same degree.
#:
#: `unknown` is the exception on purpose: the palette's neutral grey with the soft-black ink, so
#: that an outcome the source did not classify reads as *outlined but uncoloured* rather than as a
#: fourth outcome. No hue is available for "no answer".
OUTCOME_STYLES = {
    # --color-negative-light / --color-negative-dark
    "reject": "fill:#ffaaac,stroke:#6d292b",
    # --color-positive-light / --color-positive-dark
    "accept": "fill:#b9cf85,stroke:#44541f",
    # --color-neutral-light / --color-neutral-dark: the source states an outcome that is neither
    # an approval nor a rejection, and the gelb family is what annotates elsewhere in this corpus
    "info": "fill:#ffd495,stroke:#68491a",
    # --neutral-grau / --weiches-schwarz: the source classifies nothing
    "unknown": "fill:#e7e6e5,stroke:#25141d",
}

#: mermaid class per outcome kind. The kinds come from `ebd_clusters`, i.e. from the
#: EBD PDF's own `Cluster:` prefix — the only authority on what an answer code means.
_OUTCOME_CLASS = {"rejection": "reject", "approval": "accept", "info": "info", "unknown": "unknown"}


def _outcome_cluster(cluster: str | None, hint: str | None) -> str | None:
    """The branch's cluster: the resolved field, else the `Cluster:` prefix of its hint.

    p09 does not always lift the prefix into `if_*_cluster` — in the committed EBD data
    only 91 branches have the field while **1110** carry the prefix in the hint alone.
    """
    if cluster and cluster.strip():
        return cluster.strip()
    extracted, _ = extract_cluster(hint)
    return extracted


def _outcome_kind(cluster: str | None, result: str | None) -> str:
    """Classify a branch's outcome: `rejection`, `approval`, `info` or `unknown`.

    Only the cluster classifies (see :func:`_outcome_cluster`); `result` is accepted as
    an argument so callers cannot mistake it for one. Without a cluster the answer is
    `unknown` — grey — never an approval and never a rejection.

    That split is not a judgement call, it is measured against
    Hochfrequenz/machine-readable_entscheidungsbaumdiagramme, where every EBD is verified
    from an independent source (ebdamame + rebdhuhn). Over the 1437 answer codes shared
    with that repo (FV2604 and FV2610 agree):

    ==========================================  ==============
    rule                                        agreement
    ==========================================  ==============
    the result text, by substring ("ablehnung")  822/1407 58.4 %
    cluster, falling back to the result text    1030/1407 73.2 %
    **cluster only, else unknown**             1304/1407 92.7 %
    ==========================================  ==============

    The fallback is what costs the 19 points: the result text carries the same constant
    for every code of an EBD, so it invents a rejection for 372 codes the verified data
    classifies as unknown. Per kind, the current rule classifies every verified approval
    (92/92) and every verified rejection (822/822) exactly; the residue is 98 codes where
    this pipeline has a cluster the verified corpus does not, plus 5 info/unknown
    crossings.
    """
    del result  # deliberately unused: it does not classify anything
    if cluster and cluster.strip():
        return cluster_to_kind(cluster.strip())
    return "unknown"


def _outcome_class(cluster: str | None, result: str | None) -> str:
    """The mermaid class for a branch's outcome — see :func:`_outcome_kind`."""
    return _OUTCOME_CLASS[_outcome_kind(cluster, result)]


def _outcome_label(code: str, cluster: str | None, result: str | None) -> str:
    """`A01: Zustimmung` — the code plus whatever names the outcome, or the bare code.

    The cluster names it first, so a branch the EBD did classify does not degrade to a
    bare answer code. The result text is still allowed to *name* an outcome even though
    it may not *classify* one (see :func:`_outcome_kind`): a possibly-stale name is
    better than none, whereas a wrong colour asserts something the source did not say.
    """
    for value in (cluster, result):
        if value and value.strip():
            return f"{code}: {value.strip()}"
    return code


def _render_ebd_flowchart(dt: dict[str, Any]) -> list[str]:
    """Render an EBD decision tree as a Mermaid flowchart with full text."""
    steps = dt.get("steps", [])
    if not steps:
        return []

    lines = ["```mermaid", "flowchart TD"]
    lines.extend(f"    classDef {name} {style}" for name, style in OUTCOME_STYLES.items())
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
            cluster = _outcome_cluster(step.get("if_yes_cluster"), step.get("if_yes_hint"))
            label = _outcome_label(code, cluster, result)
            lines.append(f'    s{nr} -->|ja| ry{nr}["{_escape_mermaid(label)}"]')
            lines.append(f"    ry{nr}:::{_outcome_class(cluster, result)}")

        # No branch
        if step.get("if_no") and isinstance(step["if_no"], int):
            lines.append(f"    s{nr} -->|nein| s{step['if_no']}")
        elif step.get("if_no_code"):
            code = step["if_no_code"]
            result = step.get("if_no_result", "")
            cluster = _outcome_cluster(step.get("if_no_cluster"), step.get("if_no_hint"))
            label = _outcome_label(code, cluster, result)
            lines.append(f'    s{nr} -->|nein| rn{nr}["{_escape_mermaid(label)}"]')
            lines.append(f"    rn{nr}:::{_outcome_class(cluster, result)}")

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


def _renders_as_unplaceable_note(step: dict[str, Any], participants: list[str]) -> bool:
    """Whether this step is drawn as a "(!) … ungelesen" note rather than as an arrow."""
    sender, receiver = step.get("sender", ""), step.get("receiver", "")
    if is_known_actor(sender) and is_known_actor(receiver):
        return False
    anchor = next((role for role in (sender, receiver) if is_known_actor(role)), None)
    if is_ref_step(step.get("message"), step.get("subprocess_ref")) and anchor:
        return False  # stays a self-message on the lifeline it names
    return bool(anchor) or any(is_known_actor(p) for p in participants)


def _deadline_legend(sd: dict[str, Any]) -> list[str]:
    """A short vocabulary legend for the deadline tags/notes rendered on the SD
    image. Only the marker kinds actually present on this diagram are listed:
    inline tags (unverzüglich/parallel/terminiert), an (i) reference note, and/or
    a [REVIEW] note for a still-unstructured complex Frist."""
    steps = sd.get("steps", [])
    participants = sd.get("participants", [])
    types = {(s.get("deadline_rule") or {}).get("type") for s in steps}
    has_tags = bool(types & {"unverzüglich", "parallel", "terminiert"})
    has_reference = "reference" in types
    has_complex = "complex" in types
    # The same "(!)" marker now also flags a step whose endpoint could not be read
    # (makorele#78), and that step need not carry a deadline at all — without this the
    # legend either omits the marker the diagram shows or defines it as a Frist it is not.
    # Only steps that actually render as a note: a "ref" with an unread endpoint stays a
    # self-message (its other end never named an actor), and a step with no lane at all is
    # dropped. Without that exclusion the legend announced a marker the diagram does not
    # show -- live on reklamation_von_werten_beim_msb's primary SD, whose three unread
    # endpoints are all refs (a later SD of the same process does draw such a note). The
    # block is rendered for the WSD-SVG page too, not just the Mermaid fallback, so a false
    # entry was not confined to one output.
    has_unread_endpoint = any(_renders_as_unplaceable_note(step, participants) for step in steps)
    if not (has_tags or has_reference or has_complex or has_unread_endpoint):
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
    if has_unread_endpoint:
        lines.append("- `(!) … ungelesen` (Notiz) — Schritt mit unlesbarem Endpunkt, als Notiz statt als Pfeil")
    lines.append("")
    return lines


def _render_sequence_diagram(sd: dict[str, Any]) -> list[str]:  # pylint: disable=too-many-locals
    """Render a Mermaid sequence diagram with full message text."""
    steps = sd.get("steps", [])
    participants = sd.get("participants", [])
    if not steps:
        return []

    lines = ["```mermaid", "sequenceDiagram"]
    # Same rule as emit_wsd: the "?" placeholder is not an actor, and naming it makes
    # Mermaid draw a nameless lifeline beside the real ones (makorele#78).
    known_lanes = [p for p in participants if is_known_actor(p)]
    for p in known_lanes:
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
        is_ref = is_ref_step(message, subprocess_ref)
        stripped_message = (message or "").strip()
        # The source tables already write "ref …" in most of the corpus (244 steps of the
        # shipped dataset carry both markers), and prefixing those again produced
        # "7. ref ref Stammdatenänderung …" on every one of them.
        needs_prefix = bool(subprocess_ref) and not REF_PREFIX.match(stripped_message)
        label = f"{nr}. ref {stripped_message}" if needs_prefix else f"{nr}. {stripped_message}"
        # Keyed on subprocess_ref, not on is_ref_step: a parsed subprocess call has never
        # carried its format and PIDs in the label, while a step that merely *writes*
        # "ref …" always has. Keying the omission on the message would drop them the first
        # time the pipeline attaches a PID to such a step — invisible in today's corpus,
        # where none of the 91 prefix-only refs carries one.
        if not subprocess_ref:
            if fmt:
                label += f" [{fmt}]"
            if pids:
                pid_str = ",".join(str(p) for p in pids)
                label += f" (PID:{pid_str})"

        # Mermaid expresses the dashed/solid shaft (-->> vs ->>); the open-vs-filled
        # head distinction has no clean Mermaid equivalent, so it is not carried here.
        arrow = "-->>" if step.get("line") == "dashed" else "->>"

        anchor = next((role for role in (sender, receiver) if is_known_actor(role)), None)
        if is_known_actor(sender) and is_known_actor(receiver):
            lines.append(f"    {sender}{arrow}+{receiver}: {label}")
            if subprocess_ref and sender != receiver:
                lines.append(f"    Note right of {receiver}: Subprocess call")
        elif is_ref and anchor:
            # A "ref" is a subprocess box on one lifeline, so its other endpoint never
            # named an actor: it stays the self-message the .wsd emitter draws, rather
            # than becoming a note that reports a missing counterpart it never had.
            lines.append(f"    {anchor}{arrow}+{anchor}: {label}")
        elif anchor:
            # An endpoint the pipeline could not read: say the step and leave the other
            # side open, rather than drawing an arrow to a lane that stands for
            # "unknown". The .wsd rendering does the same, with a [REVIEW] flag the
            # webapp's worklist picks up; this document has no such worklist, so the
            # marker is plain text. Which side is missing is left unsaid on purpose —
            # see _unknown_endpoint_note in the .wsd emitter.
            lines.append(f"    Note over {anchor}: (!) {label} — Gegenstelle ungelesen")
        elif known_lanes:
            # Neither endpoint known: span the outermost lanes. Note over takes at most
            # two actors in Mermaid's grammar (actor_pair), so naming every lane would
            # break the whole diagram, not just this line.
            lines.append(f"    Note over {span_of_lanes(known_lanes)}: (!) {label} — beide Endpunkte ungelesen")
        else:
            logger.warning("dropping step %s from the Mermaid diagram: no lane is known", nr)

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
            lines.append(f"[Open interactive sequence diagram](../../sequence/{process_id}.html){{ .md-button }}")
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
            f"[Open BPMN Viewer (interactive)](../../bpmn/{process_id}.html){{ .md-button .md-button--primary }}"
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
