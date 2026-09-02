"""The Frist notation: the compact tag a Fristangabe renders as, and nothing else.

**One vocabulary, one owner.** A Frist reaches a reader through three surfaces that must
agree word for word: the tag drawn beside an arrow, the legend that defines the markers
below the diagram (:func:`makoralle.serialization.markdown._deadline_legend`, which derives
its entries from :func:`deadline_tag` for exactly this reason), and — since the
websequencediagrams API was retired — `makrake <https://github.com/Hochfrequenz/makrake>`_,
which draws the arrows from the structured model in Rust
(``layout::deadline_tag``). Two implementations of one notation, in two languages, with
nothing keeping them in step: that is makoralle#65.

This module is the answer to the "one owner" half. The notation used to live in
:mod:`makoralle.serialization.wsd`, a module named after a renderer that no longer runs, so
a reader looking for the vocabulary found it filed under a dialect and a reader changing the
dialect found the vocabulary. Nothing here is WSD-specific — the same strings go into the
Mermaid fallback, the markdown legend, and (through :func:`tag_matrix`) the fixture makuna
and makrake check their port against.

**The port is checked, not trusted.** :func:`tag_matrix` enumerates every shape
:func:`~makoralle.models.deadline.deadline_from_rule` can lift out of a flat
``DeadlineRule`` and pairs it with the tag this module draws. makuna vendors the result and
asserts that every shape deserializes into its Rust model; makrake asserts that
``layout::deadline_tag`` reproduces every tag. Both divergences found when that check was
first run had **zero corpus rows** — a ``Kalendertage`` abbreviated ``T`` instead of ``KT``,
and a transmission event named without its step, which makuna's model rejected outright and
so took the whole diagram down rather than one tag. A corpus ratchet cannot see either.
"""

from makoralle.models.deadline import Anchor, Deadline, DeadlineAlternative, Schedule, deadline_from_rule
from makoralle.models.process import DeadlineRule

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


def states_a_hard_date(deadline: Deadline) -> bool:
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
    they are surfaced. A ``scheduled`` branch renders its bound and nothing else — no
    ``scheduled`` alternative reaches here from a flat rule, because :func:`deadline_tag`
    routes ``terminiert`` to :func:`_terminiert_core` first for the reason
    :func:`_backstop_core` gives, but :func:`tag_of` is a public-ish entry point for step 3
    and must not have a kind it answers with silence.
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
    if alt.kind == "scheduled":
        # Unreached today: `deadline_tag` special-cases `type == "terminiert"` before it ever
        # builds a `Deadline`, so all 23 shipped `terminiert` tags keep going through
        # `_terminiert_core` byte-identically. It exists because :func:`tag_of` is meant to
        # become the direct entry point for an ``SDStep.deadline`` the parser of makoralle#57
        # step 3 fills natively — and without this branch such a deadline rendered NO tag at
        # all, an arrow silently saying nothing where the source states a hard date. That is
        # this PR's own defect one level worse, waiting for step 3 to trigger it.
        # `_scheduled_has_a_backstop` on the model guarantees the backstop; the fallback is an
        # expression rather than an `assert` because `-O` strips asserts and a library should not
        # depend on them.
        return _backstop_core(alt.backstop) if alt.backstop is not None else ""
    if alt.kind != "immediate":
        return ""
    pieces = ["u", _step_anchor_tag(alt.immediacy)]
    if alt.backstop is not None:
        pieces.append(_backstop_core(alt.backstop))
    return " ".join(p for p in pieces if p)


def deadline_tag(rule: DeadlineRule | None) -> str:
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
    return tag_of(deadline) if deadline is not None else ""


def tag_of(deadline: Deadline) -> str:
    """The braced tag for a structured Frist — every alternative, joined.

    A conditional Frist states two obligations, and showing one of them is the same class of
    bug as showing a bound without its obligation. Nothing produces a second alternative yet
    (``deadline_from_rule`` yields exactly one, on all 1601 rules at v0.0.20), so this waits
    on makoralle#57 step 3 with the rest of the shape. The conditions themselves stay off the
    arrow — "Bei Aufbau der EDIFACT-Kommunikation" is a label, not a tag — and ``raw`` carries
    them into the note.

    Split out from :func:`deadline_tag` so step 3 can render an ``SDStep.deadline`` the
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
        if rule.direction and anchor:
            # `and anchor`: without an anchor the direction points at nothing, and "≤2WT nach"
            # reads as a truncation — the same call `_bound_core` makes. Unifying the two cores
            # outright is still out of scope (they disagree about `established_by` too, and no
            # corpus row fixes what the target shape should be), but this half is free: 0 of the
            # 23 `terminiert` rows at v0.0.20 set a direction without an anchor or a step, so
            # every shipped tag is unchanged.
            core += f" {rule.direction}"
        return f"{core} {anchor}" if anchor else core
    if rule.latest_time:
        return f"≤{rule.latest_time} {anchor}" if anchor else f"≤{rule.latest_time}"
    if anchor:
        return f"≤{anchor}"
    return "terminiert"
