"""Serialize a :class:`SequenceDiagram` into websequencediagrams (WSD) DSL text."""

import json
import logging
from pathlib import Path

from makoralle.models.process import DeadlineRule, SDFragment, SDNote, SDStep, SequenceDiagram

logger = logging.getLogger(__name__)


def _arrow(step: SDStep) -> str:
    """WSD arrow token for a step's line/arrowhead style.

    The two axes compose: line picks the shaft ('-' solid / '--' dashed),
    arrowhead picks the tip ('>' filled / '>>' open). UML request -> '->',
    UML reply (dashed + open) -> '-->>'."""
    shaft = "--" if step.line == "dashed" else "-"
    tip = ">>" if step.arrowhead == "open" else ">"
    return f"{shaft}{tip}"


def _deadline_tag(rule: DeadlineRule | None) -> str:
    """Compact inline deadline tag appended to an arrow label.

    Simple rule types only — ``none`` and ``complex`` return ''. ``complex``
    is surfaced as a flagged note in ``emit_wsd`` instead (see _deadline_note).
    Examples: ``{u}`` (unverzüglich), ``{∥#2}`` (parallel to step 2),
    ``{≤07:00 1WT ÜZ#5}`` (within 1 WT after the ÜZ of step 5, latest 07:00)."""
    if rule is None or rule.type in ("none", "complex"):
        return ""
    if rule.type == "parallel":
        return f"{{∥#{rule.reference_step}}}" if rule.reference_step else "{∥}"
    if rule.type == "unverzüglich":
        parts: list[str] = []
        if rule.latest_time:
            parts.append(f"≤{rule.latest_time}")
        if rule.business_days is not None:
            parts.append(f"{rule.business_days}WT")
        if rule.reference_step:
            evt = rule.reference_event or ""
            parts.append(f"{evt}#{rule.reference_step}")
        return "{" + " ".join(parts) + "}" if parts else "{u}"
    return ""


def _clean_note_text(text: str) -> str:
    """Collapse whitespace/newlines so raw Frist text is a single safe note line
    (the WSD parser treats newlines as statement breaks). See p17 escaping TODO."""
    return " ".join((text or "").split())


def _deadline_note(step: SDStep, participants: list[str]) -> str | None:
    """A flagged review note for a complex (unstructured) deadline, or None.

    The note anchors to the same lifeline the step's arrow uses: for a ``ref``
    subprocess step that is the sender lifeline (via ``_ref_lifeline``), since
    Vision often mis-guesses the receiver of a ref."""
    dl = step.deadline_rule
    if not dl or dl.type != "complex" or not dl.raw:
        return None
    if (step.message or "").strip().lower().startswith("ref "):
        who = _ref_lifeline(step, participants)
    else:
        who = step.receiver if step.receiver and step.receiver != "?" else step.sender
    if not who or who == "?":
        return None
    return f"note right of {who}: (!) Frist: {_clean_note_text(dl.raw)}  [REVIEW]"


def _build_step_paths(fragments: list[SDFragment]) -> dict[int, list[tuple[SDFragment, int]]]:
    """Map each step nr to its branch path [(fragment, branch_idx), ...] root->leaf."""
    paths: dict[int, list[tuple[SDFragment, int]]] = {}

    def walk(frag_list: list[SDFragment], prefix: list[tuple[SDFragment, int]]) -> None:
        for frag in frag_list:
            for bi, branch in enumerate(frag.branches):
                bpath = prefix + [(frag, bi)]
                for nr in branch.step_nrs:
                    paths[nr] = bpath
                walk(branch.fragments, bpath)

    walk(fragments, [])
    return paths


def _open_token(frag: SDFragment, branch_idx: int) -> str:
    branch = frag.branches[branch_idx]
    cond = branch.condition or ""
    if frag.type == "alt":
        return f"alt {cond}".rstrip()
    if frag.type == "opt":
        return f"opt {cond}".rstrip()
    if frag.type == "loop":
        return f"loop {frag.label or cond}".rstrip()
    if frag.type == "par":
        return f"par {frag.label or cond}".rstrip()
    return f"opt {cond}".rstrip()  # safe fallback


def _else_token(frag: SDFragment, branch_idx: int) -> str:
    cond = frag.branches[branch_idx].condition or ""
    return f"else {cond}".rstrip()


def _open_lines(frag: SDFragment, branch_idx: int) -> list[str]:
    """Lines to open a fragment when entering branch `branch_idx`.

    For ``alt`` the full leading branch skeleton is rendered so that empty
    leading branches keep their condition labels: ``alt <cond_0>`` followed by
    ``else <cond_k>`` for every k in 1..branch_idx. Other fragment types open
    with a single token for the entered branch.
    """
    if frag.type == "alt":
        out = [f"alt {frag.branches[0].condition or ''}".rstrip()]
        for k in range(1, branch_idx + 1):
            out.append(_else_token(frag, k))
        return out
    return [_open_token(frag, branch_idx)]


# websequencediagrams note placements: "over", "left of", "right of".
_NOTE_PLACEMENT = {"over": "over", "left": "left of", "right": "right of", "left of": "left of", "right of": "right of"}


def _ref_lifeline(step: SDStep, participants: list[str]) -> str:
    """The lifeline a subprocess-reference box sits on: the sender (the invoking
    role), falling back to receiver, then the first participant."""
    for cand in (step.sender, step.receiver):
        if cand and cand != "?":
            return cand
    return participants[0] if participants else "?"


def _emit_note(lines: list[str], note: SDNote) -> None:
    """Append a note line, skipping notes with no participants (Fix 3)."""
    if not note.participants:
        logger.debug("skipping note with empty participants: %r", note.text)
        return
    placement = _NOTE_PLACEMENT.get(note.position, "over")
    parts = ",".join(note.participants)
    lines.append(f"note {placement} {parts}: {note.text}")


def emit_wsd(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    sd: SequenceDiagram, title: str | None = None, style: str = "roundgreen"
) -> str:
    """Render a SequenceDiagram as websequencediagrams DSL text.

    Assumptions about the model:

    * Step numbers are regulatory-numbered top-to-bottom, so steps are emitted
      in ascending ``nr`` order and fragment branches are assumed to be entered
      in increasing branch-index order. The emitter does not support a branch
      being re-entered after a later branch has started (out-of-order step
      numbering within a fragment is unsupported and would mislabel branches).
    * Because branches are entered monotonically, empty leading/intermediate/
      trailing branches of an ``alt`` are reconstructed from the branch list so
      that every branch keeps its ``alt``/``else <condition>`` label even when
      it contains no steps.
    """
    lines: list[str] = []
    if title:
        lines.append(f"title {title}")
    lines.append(f"# style: {style}")  # consumed by the render script, ignored by parser
    for p in sd.participants:
        lines.append(f"participant {p}")

    paths = _build_step_paths(sd.fragments)
    notes_by_step: dict[int | None, list[SDNote]] = {}
    for note in sd.notes:
        notes_by_step.setdefault(note.after_step, []).append(note)

    # Unanchored notes (after_step is None) render as general diagram notes,
    # right after the participant block and before any step/fragment (Fix 1).
    for note in notes_by_step.get(None, []):
        _emit_note(lines, note)

    current: list[tuple[SDFragment, int]] = []
    for step in sorted(sd.steps, key=lambda s: s.nr):
        target = paths.get(step.nr, [])

        common = 0
        while (
            common < len(current)
            and common < len(target)
            and current[common][0] is target[common][0]
            and current[common][1] == target[common][1]
        ):
            common += 1

        # Close levels deeper than the common prefix (innermost first).
        i = len(current) - 1
        while i >= common:
            frag, bi = current[i]
            if i == common and i < len(target) and target[i][0] is frag and target[i][1] != bi:
                # Same alt fragment, advancing to a later branch -> emit `else`
                # for every branch from bi+1 up to and including the target
                # branch, so intermediate empty branches keep their labels.
                for k in range(bi + 1, target[i][1] + 1):
                    lines.append(_else_token(frag, k))
                current = current[:i] + [target[i]]
                break
            # Closing an alt: render any trailing empty branches' labels before
            # the `end` so they are not silently dropped.
            if frag.type == "alt":
                for k in range(bi + 1, len(frag.branches)):
                    lines.append(_else_token(frag, k))
            lines.append("end")
            current = current[:i]
            i -= 1

        # Open target levels beyond what is currently open.
        for j in range(len(current), len(target)):
            frag, bi = target[j]
            lines.extend(_open_lines(frag, bi))
            current = current[:j] + [(frag, bi)]

        # Annotate the arrow with the EDIFACT format and/or its Prüfidentifikator(en).
        # pid_refs are linked in link_process from the Prüfidentifikatoren list.
        suffix = ""
        pids = "/".join(str(p) for p in step.pid_refs)
        if step.format and pids:
            suffix += f" ({step.format} {pids})"
        elif step.format:
            suffix += f" ({step.format})"
        elif pids:
            suffix += f" (PID {pids})"
        if step.ebd_ref:
            suffix += f" [{step.ebd_ref}]"
        tag = _deadline_tag(step.deadline_rule)
        if tag:
            suffix += f" {tag}"
        # TODO(escaping): message text is not escaped for ':' or newlines, which
        # can confuse the websequencediagrams parser on real data
        # (e.g. message="Frist: 5 WT"). Tracked as a follow-up.
        msg = step.message or ""
        if msg.strip().lower().startswith("ref "):
            # A "ref" is a self-referenced subprocess on one lifeline, not a
            # message to another participant. Render as a self-message arrow
            # (lifeline->lifeline), which matches the source better than a box.
            # Vision often mis-guesses a different receiver for these (e.g. NB->LFA
            # for an NB self-reference), so loop on the sender's lifeline.
            lifeline = _ref_lifeline(step, sd.participants)
            lines.append(f"{lifeline}{_arrow(step)}{lifeline}: {step.nr}. {msg}{suffix}")
        else:
            lines.append(f"{step.sender}{_arrow(step)}{step.receiver}: {step.nr}. {msg}{suffix}")

        dl_note = _deadline_note(step, sd.participants)
        if dl_note:
            lines.append(dl_note)

        for note in notes_by_step.get(step.nr, []):
            _emit_note(lines, note)

    # Close any still-open fragments, rendering trailing empty alt branches.
    for frag, bi in reversed(current):
        if frag.type == "alt":
            for k in range(bi + 1, len(frag.branches)):
                lines.append(_else_token(frag, k))
        lines.append("end")

    return "\n".join(lines)


def emit_all_wsd(sd_dir: Path, output_dir: Path) -> None:
    """Emit a .wsd file for every parsed SD JSON in sd_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for sd_path in sorted(sd_dir.glob("*.json")):
        data = json.loads(sd_path.read_text())
        sd = SequenceDiagram(**data["sequence_diagram"])
        title = data.get("process_id", sd_path.stem)
        wsd = emit_wsd(sd, title=title)
        (output_dir / f"{sd_path.stem}.wsd").write_text(wsd, encoding="utf-8")
        logger.info("Emitted WSD: %s", sd_path.stem)
