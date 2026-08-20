"""Serialize a :class:`SequenceDiagram` into websequencediagrams (WSD) DSL text."""

import json
import logging
from pathlib import Path

from makoralle.models.process import (
    DeadlineRule,
    SDFragment,
    SDNote,
    SDStep,
    SequenceDiagram,
    is_known_actor,
    is_ref_step,
)

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
    if rule.type == "terminiert":
        return "{" + _terminiert_core(rule) + "}"
    return ""


def _terminiert_core(rule: DeadlineRule) -> str:
    """Inner text of a ``terminiert`` tag — a 'spätester' deadline fixed relative to
    an external anchor. Always leads with ``≤`` (or ``täglich``). Examples:
    ``≤20WT vor Änderungstermin``, ``≤11WT nach #2``, ``≤Zahlungsziel``,
    ``täglich ≤14:00``."""
    if rule.recurring:
        return f"täglich ≤{rule.latest_time}" if rule.latest_time else "täglich"
    anchor = f"#{rule.reference_step}" if rule.reference_step else rule.anchor
    if rule.business_days is not None:
        core = f"≤{rule.business_days}WT"
        if rule.direction:
            core += f" {rule.direction}"
        return f"{core} {anchor}" if anchor else core
    if rule.latest_time:
        return f"≤{rule.latest_time} {anchor}" if anchor else f"≤{rule.latest_time}"
    if anchor:
        return f"≤{anchor}"
    return "terminiert"


def _has_ref_prefix(message: str | None) -> bool:
    """Whether the message itself opens with the "ref " marker the step tables write."""
    return (message or "").strip().lower().startswith("ref ")


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
    if not dl or dl.type not in ("complex", "reference") or not dl.raw:
        return None
    if _has_ref_prefix(step.message):
        # The historical rule, on purpose: the broader is_ref_step would move this note
        # from the receiver to the sender for a step that carries only the other marker,
        # and where the note sits is not what #78 is about.
        who = _ref_lifeline(step, participants) or ""
    else:
        who = step.receiver if is_known_actor(step.receiver) else step.sender
    if not is_known_actor(who):
        return None
    text = _clean_note_text(dl.raw)
    # A "reference" deadline is real but irreducible (points to another table/SD/
    # contract, or is conditional): keep it visible as an (i) note, but WITHOUT the
    # [REVIEW] flag so extract_review_notes never surfaces it as "Prüfung nötig".
    if dl.type == "reference":
        return f"note right of {who}: (i) Frist: {text}"
    return f"note right of {who}: (!) Frist: {text}  [REVIEW]"


def _build_step_paths(fragments: list[SDFragment]) -> dict[int, list[tuple[SDFragment, int]]]:
    """Map each step nr to its branch path [(fragment, branch_idx), ...] root->leaf."""
    paths: dict[int, list[tuple[SDFragment, int]]] = {}

    def walk(frag_list: list[SDFragment], prefix: list[tuple[SDFragment, int]]) -> None:
        for frag in frag_list:
            for bi, branch in enumerate(frag.branches):
                bpath = [*prefix, (frag, bi)]
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


def _unknown_endpoint_note(step: SDStep, text: str) -> str | None:
    """The step rendered as a flagged note on the endpoint that *is* known, or None.

    Only for a step with exactly one unreadable endpoint. The caller routes a ``ref`` away
    before asking: it sits on one lifeline anyway, so its other endpoint never named an
    actor and there is no missing counterpart to report.

    A note rather than an arrow because an arrow needs two actors and only one is known:
    drawing it to a "?" lane asserts an actor the source does not have, and drawing it as
    a self-message asserts the known actor talked to itself. The note says what the step
    says and leaves the other side open. It carries the ``[REVIEW]`` flag, so the step
    lands on the "Prüfung nötig" worklist ``extract_review_notes`` builds: an unread
    endpoint is a defect to fix in the data, not a property of the process.
    """
    sender_known, receiver_known = is_known_actor(step.sender), is_known_actor(step.receiver)
    if sender_known == receiver_known:  # both readable, or neither
        return None
    who = step.sender if sender_known else step.receiver
    # Deliberately not "Absender"/"Empfänger unbekannt": when two identically labelled
    # lifelines collapse into one (WiM Teil 2 2.6.3 — two ":MSB" lanes told apart only by
    # their notes), which of the two endpoints keeps the surviving role is arbitrary, so
    # naming the missing side would state a direction the data cannot support. For that
    # very step the source has the *receiver* unplaced while the YAML says sender="?".
    return f"note over {who}: (!) {_clean_note_text(text)} — Gegenstelle ungelesen  [REVIEW]"


def _append_unplaceable(lines: list[str], text: str, known_lanes: list[str], nr: int) -> None:
    """Note a step whose endpoints are both unread, spanning the outermost lanes.

    Anchoring on one lane would file the step under an actor it may have nothing to do
    with, so the note spans the diagram instead: it says "this step is here and we could
    not place it" without naming a party. Flagged, because such a step is worse off than
    the one-sided case, not better — and the webapp lists it in its step table either way,
    so a silent drop would leave a step that appears in no diagram and on no worklist.

    With no lane at all there is nothing to hang it on, and the step is dropped with a
    warning: a diagram in which nothing was read.
    """
    if not known_lanes:
        logger.warning("dropping step %s from the diagram: no endpoint and no lane is known", nr)
        return
    lines.append(f"note over {_span(known_lanes)}: (!) {_clean_note_text(text)} — beide Endpunkte ungelesen  [REVIEW]")


def _span(lanes: list[str]) -> str:
    """The lane list for a note that belongs to no single actor: the outermost two.

    Not every lane: ``note over`` takes one or two participants — Mermaid's grammar says
    so outright (``actor_pair : actor ',' actor | actor``) and the websequencediagrams
    reference shows no more either, so a third name is at best undefined and at worst
    breaks the whole diagram. Naming the first and the last declared lane spans the same
    width without asserting anything about the ones between.
    """
    return lanes[0] if len(lanes) == 1 else f"{lanes[0]},{lanes[-1]}"


def _ref_lifeline(step: SDStep, participants: list[str]) -> str | None:
    """The lifeline a subprocess-reference box sits on: the sender, else the receiver.

    ``None`` when the step names neither — the caller then treats it like any other step
    with no readable endpoint instead of picking a lane. It used to fall back to the first
    participant, which files the step under an actor it may have nothing to do with; that
    is exactly what the non-ref path refuses to do (makorele#78), and a ``ref`` box is no
    more attributable than an arrow.

    ``participants`` is kept in the signature because :func:`_deadline_note` passes it and
    reads the result the same way; nothing in it can name the lifeline of a step that does
    not name it itself.
    """
    del participants  # see above: no lane may stand in for an unnamed one
    return next((cand for cand in (step.sender, step.receiver) if is_known_actor(cand)), None)


def _emit_note(lines: list[str], note: SDNote, known_lanes: list[str] | None = None) -> None:
    """Append a note line, skipping notes with no participants (Fix 3).

    An anchor the pipeline could not resolve is dropped from the anchor list rather than
    named: ``note over ?`` places the same phantom lane an arrow to "?" would (makorele#78).

    When *every* anchor is unresolved the note spans the diagram instead of disappearing.
    makorele's ``p12_link._review_note`` anchors its diagram-level ``[REVIEW]`` note on the
    first participant precisely so that emit_wsd keeps it, and a note that reaches no
    diagram and no worklist is the outcome :func:`_append_unplaceable` exists to avoid.
    """
    anchors = [p for p in note.participants if is_known_actor(p)]
    if not anchors and known_lanes:
        logger.warning("note %r has no readable anchor; spanning the diagram instead", note.text)
        anchors = [_span(known_lanes)]
    if not anchors:
        logger.warning("skipping note with no known participants: %r", note.text)
        return
    placement = _NOTE_PLACEMENT.get(note.position, "over")
    parts = ",".join(anchors)
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
    # Defensive: makorele's p12 already strips "?" from the participant list, and none of
    # the 194 shipped processes declares it — but p08 does write participants=["?"] for a
    # diagram in which it read no actor at all, and declaring that would place the very
    # lane the notes below exist to avoid (makorele#78).
    known_lanes = [p for p in sd.participants if is_known_actor(p)]
    for p in known_lanes:
        lines.append(f"participant {p}")
    paths = _build_step_paths(sd.fragments)
    notes_by_step: dict[int | None, list[SDNote]] = {}
    for note in sd.notes:
        notes_by_step.setdefault(note.after_step, []).append(note)

    # Unanchored notes (after_step is None) render as general diagram notes,
    # right after the participant block and before any step/fragment (Fix 1).
    for note in notes_by_step.get(None, []):
        _emit_note(lines, note, known_lanes)

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
                current = [*current[:i], target[i]]
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
            current = [*current[:j], (frag, bi)]

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
        both_ends_known = is_known_actor(step.sender) and is_known_actor(step.receiver)
        # Two ref rules, deliberately. The historical one keys on the "ref " prefix and
        # decides the *shape* of a fully readable step; #78 must not change that, and
        # widening it to is_ref_step turned 7 shipped arrows into self-messages —
        # "BIKO->>NB: 2. ref: Deaktivierung … vom BIKO an NB" is drawn as the document
        # draws it, receiver and all. The broader rule applies only where #78 is at issue:
        # a ref whose *other* endpoint was not read never named a second actor, so it is a
        # self-message on the lifeline it does name rather than a note about a missing
        # counterpart. Unifying the shape for readable steps is a separate question, filed
        # as makoralle#36.
        if (is_ref_step(msg, step.subprocess_ref) and not both_ends_known) or _has_ref_prefix(msg):
            # A "ref" is a self-referenced subprocess on one lifeline, not a
            # message to another participant. Render as a self-message arrow
            # (lifeline->lifeline), which matches the source better than a box.
            # Vision often mis-guesses a different receiver for these (e.g. NB->LFA
            # for an NB self-reference), so loop on the sender's lifeline.
            lifeline = _ref_lifeline(step, sd.participants)
            if lifeline:
                lines.append(f"{lifeline}{_arrow(step)}{lifeline}: {step.nr}. {msg}{suffix}")
            else:
                # The box names no lifeline of its own, and no lane may stand in for one,
                # so it is spanned like any other unplaceable step.
                _append_unplaceable(lines, f"{step.nr}. {msg}{suffix}", known_lanes, step.nr)
        else:
            text = f"{step.nr}. {msg}{suffix}"
            unknown = _unknown_endpoint_note(step, text)
            if unknown:
                logger.debug("step %s has an unreadable endpoint, rendering it as a note", step.nr)
                lines.append(unknown)
            elif is_known_actor(step.sender) and is_known_actor(step.receiver):
                lines.append(f"{step.sender}{_arrow(step)}{step.receiver}: {text}")
            else:
                _append_unplaceable(lines, text, known_lanes, step.nr)

        dl_note = _deadline_note(step, sd.participants)
        if dl_note:
            lines.append(dl_note)

        for note in notes_by_step.get(step.nr, []):
            _emit_note(lines, note, known_lanes)

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
