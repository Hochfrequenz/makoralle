"""Serialize a :class:`SequenceDiagram` into websequencediagrams (WSD) DSL text."""

import json
import logging
import re
from pathlib import Path

from makoralle.models.deadline import Anchor, Deadline, DeadlineAlternative, Schedule, deadline_from_rule
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


#: How an offset's unit is abbreviated on an arrow. Only ``werktage`` occurs at dataset
#: v0.0.20 — the flat ``DeadlineRule`` has no unit field at all, so :func:`deadline_from_rule`
#: can produce nothing else — but ``Offset`` carries the other two for makoralle#57 step 3.
#: Read through :func:`_unit` rather than indexed, so that widening ``Offset.unit`` cannot take
#: the serializer down: a unit spelled out in full is ugly, a KeyError mid-diagram is worse.
_UNIT_ABBREVIATION = {"werktage": "WT", "kalendertage": "KT", "stunden": "h"}


def _unit(unit: str) -> str:
    return _UNIT_ABBREVIATION.get(unit, unit)


def _step_anchor_tag(anchor: Anchor | None, *, or_establishing_step: bool = False, with_event: bool = True) -> str:
    """The compact ``[event]#nr`` form of an anchor, or "" for one the arrow cannot carry.

    Only a ``step`` anchor goes on the label. An ``external`` one is prose — 63 characters
    for "dem andernfalls erforderlichen Versand der BG-SZR (Kategorie B)", and longer
    elsewhere in the corpus — so it stays in the note, for the reason
    :func:`_unverzueglich_sentence_beyond_the_tag` sets out, and
    :func:`_holds_a_prose_anchor` makes the note fire for it even when the row also states a
    bound. 0 of the 414 ``unverzüglich`` rules at v0.0.20 set ``DeadlineRule.anchor`` at all,
    so no shipped row reaches either path.

    ``or_establishing_step`` and ``with_event`` are for a ``parallel`` alternative only. Where
    the flat rule names a step *and* an anchor, ``deadline_from_rule`` files the step as
    ``established_by``: for a bound that step says where the anchor's *value* came from and is
    not what the offset is measured from, so rendering it as the anchor would assert something
    the source does not. (`beginn_messstellenbetrieb` nr 16 is the wording that rule was drawn
    from — "der 11. WT nach dem **in Nr. 2** vom NB bestätigten Zuordnungsbeginn" — though that
    row is ``terminiert`` and so never reaches this function.) A coupling has no such
    distinction: "Parallel zu Nr. 3" names a step and nothing else, which is also why
    ``with_event=False`` there — a coupling is tied to the step, not to one of its transmission
    events, and `{∥ÜT#3}` would assert a precision the source does not state.

    ``steps`` joins on "/" because the source says "Nr. 3 bzw. 4". The flat rule cannot
    express that (all 442 ``unverzüglich`` and ``parallel`` rules at v0.0.20 hold at most one
    ``reference_step``), so like ``Offset.unit == "kalendertage"`` this branch is here for the
    parser of #57 step 3 rather than for anything this corpus produces.
    """
    if anchor is None:
        return ""
    event = anchor.event or "" if with_event else ""
    if anchor.kind == "external" and or_establishing_step and anchor.established_by is not None:
        return f"{event}#{anchor.established_by}"
    if anchor.kind != "step" or not anchor.steps:
        return ""
    return f"{event}#{'/'.join(str(s) for s in anchor.steps)}"


def _bound_core(sched: Schedule) -> str:
    """The ``≤``-led hard date a schedule states, or "" when it states none.

    Separate from :func:`_backstop_core` because a recurrence is not a hard date: "werktäglich"
    says how often the duty recurs, not by when it must be over. ``Schedule`` answers
    ``states_a_backstop`` True for a recurrence-only bound, which is the right answer to a
    different question — so the note predicate asks this one instead. Getting that wrong lost
    "nach Nr. 2" from both the arrow and the note on a recurrence-only ``unverzüglich``.
    """
    pieces: list[str] = []
    if sched.latest_time:
        pieces.append(sched.latest_time)
    anchor = _step_anchor_tag(sched.anchor)
    if sched.offset:
        # The direction is spelled out even though ``Offset`` defaults it to "nach" and 0 of
        # the 148 offsets at v0.0.20 say "vor": `{≤11WT nach #2}` is what a `terminiert` tag
        # already reads, and one vocabulary the legend can define beats three characters.
        # With no anchor it is dropped instead — "≤3WT nach" points at nothing, and a
        # preposition with no object reads as a truncation.
        offset = f"{sched.offset.amount}{_unit(sched.offset.unit)}"
        pieces.append(f"{offset} {sched.offset.direction}" if anchor else offset)
    if anchor:
        pieces.append(anchor)
    return "≤" + " ".join(pieces) if pieces else ""


def _states_a_hard_date(deadline: Deadline) -> bool:
    """Whether any alternative's bound actually reaches the arrow as a ``≤`` date.

    ``Deadline.states_a_backstop`` is the model's question — "is there a Schedule here" — and
    it answers True for a schedule holding nothing but a recurrence. The note has to ask the
    renderer's question instead: if no ``≤`` reaches the label, the sentence is still the only
    place the bound is written.
    """
    return any(alt.backstop is not None and _bound_core(alt.backstop) for alt in deadline.alternatives)


def _backstop_core(sched: Schedule) -> str:
    """The ``≤``-led text of a hard date — "at the latest, *this*".

    Reads clock, then offset, then anchor, which is the order the shipped tags already use:
    ``≤07:00 1WT ÜT#1`` on 4 of the 906 ``diagrams[]`` rows at v0.0.20, and 14 of them carry
    that clock-offset-step shape at some clock value. The ``≤`` leads whichever piece comes
    first, so a bound with no clock reads ``≤2WT nach ÜT#1``.

    Kept separate from :func:`_terminiert_core` on purpose. The two agree on the anchor and
    on ``täglich``, but a ``terminiert`` tag renders an offset *or* a clock and never both,
    and drops the direction when the source did not state one. Routing ``terminiert`` through
    here would rewrite all 23 of its shipped tags to settle a disagreement no corpus row
    exhibits; #59 is about the ``unverzüglich`` rows, so the older function keeps its 23.
    """
    bound = _bound_core(sched)
    if not sched.recurrence:
        return bound
    # The recurrence says how OFTEN the obligation recurs and the rest says by when, so it
    # prefixes the bound instead of replacing it. An earlier draft returned here with the
    # recurrence alone, which discarded the offset and its anchor whenever a rule carried
    # both — no v0.0.20 rule does, and the upstream is a non-deterministic Vision stage, so
    # "no row does" is not a reason to drop the field. `_terminiert_core` still does replace,
    # and is left alone with the rest of `terminiert`.
    return f"{sched.recurrence} {bound}" if bound else sched.recurrence


def _alternative_core(alt: DeadlineAlternative) -> str:
    """Inner text of one branch of a Frist, or "" for a branch with nothing compact in it.

    The fix #59 is about: the obligation leads and the bound follows it, so an
    ``unverzüglich`` bounded by a hard date renders BOTH — ``{u ≤2WT nach ÜT#1}`` — where the
    old code let the first structured field it found evict the ``u`` entirely.

    ``reference`` and ``complex`` return "": they are prose, and ``_deadline_note`` is where
    they are surfaced. A ``scheduled`` branch returns "" too — :func:`_deadline_tag` routes
    those to :func:`_terminiert_core` off the flat rule, for the reason
    :func:`_backstop_core` gives.
    """
    if alt.kind == "parallel":
        # A coupling has one thing to say — which step it is tied to — and `≤` would assert a
        # hard date the source never stated ("Parallel zu Nr. 3" is not "by Nr. 3"). So no
        # backstop is rendered, and the coupled step is read from whichever slot holds it:
        # `deadline_from_rule` files the anchor under `backstop` once an offset is present,
        # and that disambiguation was corpus-verified for `unverzüglich`, not for `parallel`.
        # `or_establishing_step` recovers the step from an external anchor, where for a
        # coupling the step *is* what the source named. No space after the marker: "{∥#2}" is
        # the shipped form, and it reads as one token with the step it couples to.
        coupled = _step_anchor_tag(alt.immediacy, or_establishing_step=True, with_event=False) or _step_anchor_tag(
            alt.backstop.anchor if alt.backstop else None, or_establishing_step=True, with_event=False
        )
        return f"∥{coupled}"
    if alt.kind != "immediate":
        return ""
    pieces = ["u", _step_anchor_tag(alt.immediacy)]
    if alt.backstop is not None:
        pieces.append(_backstop_core(alt.backstop))
    return " ".join(p for p in pieces if p)


def _deadline_tag(rule: DeadlineRule | None) -> str:
    """Compact inline deadline tag appended to an arrow label.

    ``none``, ``reference`` and ``complex`` return '' — those are prose, surfaced as a note
    in ``emit_wsd`` instead (see _deadline_note). Examples: ``{u}`` (unverzüglich, with no
    anchor and no bound), ``{u ÜZ#1}`` (unverzüglich after the ÜZ of step 1),
    ``{u ≤2WT nach ÜT#1}`` (unverzüglich, and at the latest 2 WT after the ÜT of step 1),
    ``{∥#2}`` (parallel to step 2), ``{≤20WT vor Änderungstermin}`` (terminiert).

    One shape still shows less on the arrow than the old tag did: an ``unverzüglich`` naming both
    a step and a prose anchor renders ``{u}`` where the flat tag rendered ``{ÜT#3}``, because
    ``deadline_from_rule`` files the step as ``established_by`` and that is not what the offset is
    measured from (see :func:`_step_anchor_tag`). Nothing is lost from the diagram —
    :func:`_holds_a_prose_anchor` makes the note fire — and 0 of the 414 ``unverzüglich`` rules at
    v0.0.20 set ``anchor``, so no shipped row takes that path.

    Goes through :func:`deadline_from_rule` rather than reading the flat fields directly,
    because *which obligation owns them* is not local knowledge: for an ``unverzüglich`` rule
    an offset means they describe the backstop and the promptness duty is unanchored, and no
    offset means they describe the immediacy anchor. That rule is corpus-verified in one
    place (makoralle#58) and this renderer is now the first consumer of it.
    """
    if rule is None:
        return ""
    if rule.type == "terminiert":
        # Unchanged, deliberately — see _backstop_core.
        return "{" + _terminiert_core(rule) + "}"
    deadline = deadline_from_rule(rule)
    return _tag_of(deadline) if deadline is not None else ""


def _tag_of(deadline: Deadline) -> str:
    """The braced tag for a structured Frist — every alternative, joined.

    A conditional Frist states two obligations, and showing one of them is the same class of
    bug as showing a bound without its obligation. Nothing produces a second alternative yet
    (``deadline_from_rule`` yields exactly one, on all 1601 rules at v0.0.20), so this waits
    on makoralle#57 step 3 with the rest of the shape. The conditions themselves stay off the
    arrow — "Bei Aufbau der EDIFACT-Kommunikation" is a label, not a tag — and ``raw`` carries
    them into the note.

    Split out from :func:`_deadline_tag` so step 3 can render an ``SDStep.deadline`` the
    parser filled directly, without a round trip back through the flat rule.
    """
    cores = [core for core in (_alternative_core(alt) for alt in deadline.alternatives) if core]
    return "{" + " ; ".join(cores) + "}" if cores else ""


def _terminiert_core(rule: DeadlineRule) -> str:
    """Inner text of a ``terminiert`` tag — a 'spätester' deadline fixed relative to
    an external anchor. Always leads with ``≤`` (or ``täglich``). Examples:
    ``≤20WT vor Änderungstermin``, ``≤11WT nach #2``, ``≤Zahlungsziel``,
    ``täglich ≤14:00``."""
    if rule.recurring:
        # `recurrence` names the granularity the source used; "täglich" only as the fallback for
        # a rule written before the field existed. Saying "täglich" for a werktäglich obligation
        # is not a shortening but a different claim — it adds Saturdays and Sundays.
        word = rule.recurrence or "täglich"
        return f"{word} ≤{rule.latest_time}" if rule.latest_time else word
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


#: The word an "unverzüglich" Frist opens with, and the punctuation that follows it. What remains
#: after stripping it is the part the compact tag cannot carry.
#:
#: The `^` is load-bearing: without it `re.sub` would strip the marker wherever it appears, and 48
#: corpus rows (35 distinct sentences) carry it mid-prose ("Bei Fall a: Unverzüglich nach X"), which would leave a
#: mangled residual. `!` and `?` are in the class because "Unverzüglich!" would otherwise leave the
#: bare "!" as a residual and earn a note that says nothing (Copilot); no corpus raw carries either
#: character, so it is hardening. The leading `\s*`, the `\b` and the rest of the punctuation class
#: are belt-and-braces too — no corpus raw ends the marker at a colon or runs it into a longer word
#: — and are disclosed as such rather than covered by a test no input can fail.
_UNVERZUEGLICH_MARKER = re.compile(r"^\s*(?:unverzüglich|sofort)\b[\s,.;:!?]*", re.I)


def _unverzueglich_sentence_beyond_the_tag(rule: DeadlineRule) -> str:
    """What an ``unverzüglich`` rule's own sentence says that its tag does not, or "".

    For the rows whose tag states **no bound** — ``deadline_from_rule`` found no backstop in
    the flat fields, so the arrow can say when the duty starts but not by when it must be
    over. Those are the rows where the sentence carries something the reader acts on and the
    tag carries none of it: "Unverzüglich nach Kenntnisnahme", and, since #59, the 27 rows
    whose fields describe the immediacy anchor rather than a bound —
    `abrechnung_einer_für_den_esa_erbrachten_leistung` nr 2, "Unverzüglich nach dem ÜZ von
    Nr. 1, **jedoch spätester ÜT ist der 4. WT vor dem Zahlungsziel in der Rechnung**", whose
    tag is ``{u ÜZ#1}`` and whose bound exists only in prose. 18 of those 27 state such a
    bound; the other 9 state a condition ("sofern es sich um eine Zahlungsablehnung
    handelt"), which the tag has no slot for either.

    Keyed on the *absence of a backstop* rather than on "the tag came out bare", because a
    tag that shows the bound has said the part the sentence would repeat: a note beside
    ``{u ≤2WT nach ÜT#1}`` would restate the arrow on 143 of the 148 offset rows, and a
    diagram has little room. The 5 rows where prose names an immediacy anchor *and* a bound
    and the flat rule holds only the bound (`lieferbeginn` nr 10/13,
    `lieferende_von_nb_an_lf` nr 8/11/13) therefore still get no note — recovering the
    dropped half needs the parser (makoralle#57 step 3), not this predicate.

    Why a note rather than a longer tag: the anchors are multi-word — 63 characters for "dem
    andernfalls erforderlichen Versand der BG-SZR (Kategorie B)", and longer elsewhere in the
    corpus — which makes a 73-character tag out of that one, on an arrow label already 57
    characters long. So the compact tag cannot carry them and stops being a
    tag. Keeping ``{u}`` on the arrow and putting the sentence beside it is the form
    ``reference`` already uses, and it generalises to every remaining lossy row.
    """
    if rule.type != "unverzüglich":
        return ""
    deadline = deadline_from_rule(rule)
    if deadline is None:
        return ""
    if _states_a_hard_date(deadline) and not _holds_a_prose_anchor(deadline):
        return ""
    return _UNVERZUEGLICH_MARKER.sub("", rule.raw or "").strip(" .;,!?")


def _holds_a_prose_anchor(deadline: Deadline) -> bool:
    """Whether any alternative is anchored to something only prose can say.

    The second half of the note's job. A bound on the arrow answers "by when", so a row that
    has one needs no note — unless what it is measured *from* is an ``external`` anchor, which
    :func:`_step_anchor_tag` cannot put on a label. Without this a rule naming both a prose
    anchor and a clock ("unverzüglich, spätestens 07:00 Uhr nach dem Abschluss des
    Entsperrauftrags") would render ``{u ≤07:00}`` and drop the anchor from the tag *and* from
    the note, which is the failure this whole change is about, one level down.

    0 of the 414 ``unverzüglich`` rules at v0.0.20 set ``DeadlineRule.anchor``, so this fires
    on no shipped row; ``deadline_from_rule`` can already build the shape, and #57 step 3's
    parser is meant to.
    """
    for alt in deadline.alternatives:
        for anchor in (alt.immediacy, alt.backstop.anchor if alt.backstop else None):
            # No "and not _step_anchor_tag(anchor)" guard: that read like a check and was a
            # tautology, since every kind but ``step`` renders "" without
            # ``or_establishing_step``, which only the coupling branch passes.
            if anchor is not None and anchor.kind in ("external", "event"):
                return True
    return False


def _deadline_note(step: SDStep, known_lanes: list[str]) -> str | None:
    """The note for a Frist that only exists as prose, or None.

    Two kinds, and they are not the same claim: a ``complex`` rule gets ``(!) … [REVIEW]``, because
    nobody has structured it yet and the worklist should say so, while a ``reference`` rule gets an
    unflagged ``(i)`` — it is real but irreducible, pointing at another table or a contract, and
    putting it on the "Prüfung nötig" list would ask for work that cannot be done.

    The note anchors to the same lifeline the step's arrow uses: for a ``ref``
    subprocess step that is the sender lifeline (via ``_ref_lifeline``), since
    Vision often mis-guesses the receiver of a ref.

    A step with neither endpoint read has no lifeline at all, and the note used to be
    dropped with it — silently, which is the outcome ``_append_unplaceable`` exists to
    avoid. The unstructured text is the part a human needs in order to structure it, and
    exactly what ``extract_review_notes`` puts on the "Prüfung nötig" worklist, so it
    spans the diagram alongside the step instead (makoralle#37)."""
    dl = step.deadline_rule
    if not dl or not dl.raw:
        return None
    # A bare-tagged `unverzüglich` whose sentence says more joins the two note types: it is real
    # and readable, just not compact, which is exactly `reference`'s situation (makorele#101).
    lossy_unverzueglich = bool(_unverzueglich_sentence_beyond_the_tag(dl))
    if dl.type not in ("complex", "reference") and not lossy_unverzueglich:
        return None
    spanning = False
    if _has_ref_prefix(step.message):
        # The historical rule, on purpose: the broader is_ref_step would move this note
        # from the receiver to the sender for a step that carries only the other marker,
        # and where the note sits is not what #78 is about.
        who = _ref_lifeline(step) or ""
    else:
        who = step.receiver if is_known_actor(step.receiver) else step.sender
    if not is_known_actor(who):
        if not known_lanes:
            # No lane either, so nothing to hang the Frist on. Silent on purpose: whoever got here
            # has already had the step itself dropped — by the loop's own skip, or by
            # `_append_unplaceable` when one of the step's notes named an actor and kept the
            # fragment open — and `_log_dropped` names the lost Frist in that one line. A second
            # warning for one loss would be a second thing to count.
            return None
        who = span_of_lanes(known_lanes)
        spanning = True
    text = _clean_note_text(dl.raw)
    # A "reference" deadline is real but irreducible (points to another table/SD/
    # contract, or is conditional): keep it visible as an (i) note, but WITHOUT the
    # [REVIEW] flag so extract_review_notes never surfaces it as "Prüfung nötig".
    # "right of" takes one participant, so a span has to be "over" — and the flag says which case
    # this is rather than the string being asked whether it holds a comma. An actor named with a
    # comma would answer that wrongly, and although no such actor exists (nor could be declared as
    # a participant), a placement decided by punctuation inside a name is a coincidence, not a rule.
    # A one-lane span goes "over" as well, so the Frist sits the way the step it belongs to sits.
    placement = "over" if spanning else "right of"
    if dl.type == "reference" or lossy_unverzueglich:
        # Unflagged for the same reason `reference` is: the sentence is readable and real, so
        # putting it on the "Prüfung nötig" worklist would ask for work that is already done.
        return f"note {placement} {who}: (i) Frist: {text}"
    return f"note {placement} {who}: (!) Frist: {text}  [REVIEW]"


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


def _append_unplaceable(lines: list[str], text: str, known_lanes: list[str], step: SDStep) -> None:
    """Note a step whose endpoints are both unread, spanning the outermost lanes.

    Anchoring on one lane would file the step under an actor it may have nothing to do
    with, so the note spans the diagram instead: it says "this step is here and we could
    not place it" without naming a party. Flagged, because such a step is worse off than
    the one-sided case, not better — and the webapp lists it in its step table either way,
    so a silent drop would leave a step that appears in no diagram and on no worklist.

    With no lane at all there is nothing to hang it on, and the step is dropped: a diagram in
    which nothing was read. That is reachable even though :func:`_draws_nothing` filters the
    loop, because a dropped step can still carry a note that names an actor — the note is drawn
    and the step is not.
    """
    if not known_lanes:
        _log_dropped(step)
        return
    body = _clean_note_text(text)
    lines.append(f"note over {span_of_lanes(known_lanes)}: (!) {body} — beide Endpunkte ungelesen  [REVIEW]")


def _log_dropped(step: SDStep) -> None:
    """One wording for one event, wherever it is decided.

    A Frist that only exists as prose is named in the same line rather than in a second warning:
    with no endpoint and no lane it has nowhere to go either, and it is the text a human needs in
    order to structure it (makoralle#37). Two warnings for one loss would be two things to count.

    "Only as prose" covers `complex` (nobody has structured it yet), `reference` (real but
    irreducible — it points at another table or a contract), and, since makorele#101, a
    bare-tagged `unverzüglich` whose sentence says more than `{u}`: for those the note *is* what
    carries the event, so dropping it is a loss like the other two. A `terminiert` rule, and an
    `unverzüglich` whose tag carries the bound, are still not named — they survive the drop as
    structure, so reporting them would announce a loss that did not happen.
    """
    dl = step.deadline_rule
    raw = dl.raw if dl and (dl.type in ("complex", "reference") or _unverzueglich_sentence_beyond_the_tag(dl)) else None
    if raw:
        logger.warning(
            "dropping step %s from the diagram: no endpoint and no lane is known; its unstructured "
            "Frist %r goes with it",
            step.nr,
            raw,
        )
        return
    logger.warning("dropping step %s from the diagram: no endpoint and no lane is known", step.nr)


def _draws_nothing(step: SDStep, known_lanes: list[str], notes: list[SDNote]) -> bool:
    """True if the emitter would produce no line at all for this step.

    The mirror of :func:`_append_unplaceable`'s drop, and the reason it exists: fragments are
    opened by the step loop *before* the step is drawn, so a diagram in which nothing was read
    used to yield a bare ``alt``/``else``/``end`` skeleton around no messages (makoralle#38).

    Exactly one shape draws nothing. With either endpoint readable there is always a line — an
    arrow, a self-arrow on the ``ref`` lifeline, or the one-sided note; with neither, a lane still
    lets the step span the diagram. Only both unread *and* no lane leaves nothing — and even then
    not if one of the step's own notes names an actor, since that note is drawn inside the branch.
    """
    if is_known_actor(step.sender) or is_known_actor(step.receiver):
        return False
    if known_lanes:
        return False
    return not any(is_known_actor(who) for note in notes for who in note.participants)


def span_of_lanes(lanes: list[str]) -> str:
    """The lane list for a note that belongs to no single actor: the outermost two.

    Not every lane: ``note over`` takes one or two participants — Mermaid's grammar says
    so outright (``actor_pair : actor ',' actor | actor``) and the websequencediagrams
    reference shows no more either, so a third name is at best undefined and at worst
    breaks the whole diagram. Naming the first and the last declared lane spans the same
    width without asserting anything about the ones between.
    """
    return lanes[0] if len(lanes) == 1 else f"{lanes[0]},{lanes[-1]}"


def _ref_lifeline(step: SDStep) -> str | None:
    """The lifeline a subprocess-reference box sits on: the sender, else the receiver.

    ``None`` when the step names neither — the caller then treats it like any other step
    with no readable endpoint instead of picking a lane. It used to fall back to the first
    participant, which files the step under an actor it may have nothing to do with; that
    is exactly what the non-ref path refuses to do (makorele#78), and a ``ref`` box is no
    more attributable than an arrow. Hence no ``participants`` argument any more: there was
    nothing left for it to contribute.
    """
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
        anchors = [span_of_lanes(known_lanes)]
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
        if _draws_nothing(step, known_lanes, notes_by_step.get(step.nr, [])):
            # Before the fragment bookkeeping, or the branch is opened for a step that never
            # arrives. Nothing else attached to the step draws either: its deadline note has no
            # lifeline and no lane, and its notes name no actor.
            _log_dropped(step)
            continue
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
            lifeline = _ref_lifeline(step)
            if lifeline:
                lines.append(f"{lifeline}{_arrow(step)}{lifeline}: {step.nr}. {msg}{suffix}")
            else:
                # The box names no lifeline of its own, and no lane may stand in for one,
                # so it is spanned like any other unplaceable step.
                _append_unplaceable(lines, f"{step.nr}. {msg}{suffix}", known_lanes, step)
        else:
            text = f"{step.nr}. {msg}{suffix}"
            unknown = _unknown_endpoint_note(step, text)
            if unknown:
                logger.debug("step %s has an unreadable endpoint, rendering it as a note", step.nr)
                lines.append(unknown)
            elif is_known_actor(step.sender) and is_known_actor(step.receiver):
                lines.append(f"{step.sender}{_arrow(step)}{step.receiver}: {text}")
            else:
                _append_unplaceable(lines, text, known_lanes, step)

        dl_note = _deadline_note(step, known_lanes)
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
