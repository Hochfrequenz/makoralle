"""A step's Frist, in the shape the prose actually has.

``DeadlineRule`` (``models.process``) is flat: one type and one set of anchor/offset
fields. A MaKo Frist routinely states **two obligations at once** — *act without undue
delay*, **and** *no later than X* — each with its own anchor. With one field set, one of
them wins and the other survives only in ``raw``. Measured over dataset v0.0.20, of the 414
``unverzüglich`` rules, **168** state a backstop in prose that no structured field holds
(93 by the narrower "jedoch spätest…" wording the issue used). Conditional Frists lose
even more: there is no slot for a condition at all, so everything after the first clause
goes — 121 distinct raw texts among the dropped, many opening "Bei … gilt:".

This module adds the shape without changing the old one. ``DeadlineRule`` is untouched, so
makorele's ``p12_link`` and ``render_sequence_diagrams`` keep working unchanged; the lift in
:func:`deadline_from_rule` reads the flat rule and yields the richer view, which lets a
consumer use it against the shipped dataset **today**, before the parser learns to fill it.

makoralle#57 sets out the reverse direction — ``DeadlineRule`` derived from
``alternatives[0]`` — and that is right once makorele populates the new shape natively. It
cannot come first: nothing produces ``Deadline`` yet, and a regeneration is expensive
(makorele's p06 uses Claude Vision, is non-deterministic and costs budget). Lifting old to
new is the half that needs no re-parse.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from makoralle.models.process import DeadlineRule

#: The two transmission events a Frist can speak about. ``ÜT`` is the Übertragungstag (the
#: day), ``ÜZ`` the Übertragungszeitpunkt (the instant).
TransmissionEvent = Literal["ÜT", "ÜZ"]


class Offset(BaseModel):
    """A distance from an anchor, in the unit the source names.

    ``unit`` exists because the corpus is not only Werktage: two Frists are stated in
    Stunden — `einrichtung_der_konfigurationen…` ("1 Stunde nach dem ÜZ von Nr. 1") and
    `ermittlung_der_malo-id_der_marktlokation` ("2 Stunden nach dem ÜZ von Nr. 1") — and a
    bare ``business_days: int`` cannot hold them without lying about which calendar applies.
    """

    #: Positive: the model already has ``direction`` for "before", so a negative
    #: amount would be a second, unvalidated way to say the same thing — and
    #: ``-5`` with ``direction="nach"`` says both at once. Every offset in the
    #: dataset is 1..61 (all 1601 ``deadline_rule`` rows, both the
    #: ``sequence_diagram`` and ``diagrams[]`` sets), so nothing real is excluded.
    amount: int = Field(gt=0)
    #: Defaulted, where makoralle#57 has it required: every offset the flat rule can express
    #: is in Werktage (the field is literally ``business_days``), so requiring it would make
    #: the lift restate the only value it can produce — on all 160 offsets across the 906
    #: ``diagrams[]`` rules at v0.0.20. A non-Werktage unit must be stated explicitly, never
    #: inferred. ``kalendertage`` is in the Literal on makoralle#57's report of 2 Frists at
    #: v0.0.18; at v0.0.20 no Frist names Kalendertage in any spelling ("Kalendertag", "KT")
    #: in either the 906 ``diagrams[]`` rules or all 1601 including ``sequence_diagram`` —
    #: only "Kalenderjahr", which is not an offset unit. Kept for #57 step 3, like
    #: ``kind="event"``, not because this corpus produces one.
    unit: Literal["werktage", "kalendertage", "stunden"] = "werktage"
    #: Defaults to ``nach`` rather than being optional: of the 148 rules at v0.0.20 that
    #: carry an offset and no explicit direction, **0** have prose containing "vor". Making
    #: it non-optional removes a guess every consumer would otherwise have to make.
    direction: Literal["vor", "nach"] = "nach"


class Anchor(BaseModel):
    """What an offset is measured from.

    ``steps`` is a list because the source says "Nr. 3 bzw. 4" — a disjunctive reference a
    single ``int`` cannot hold. ``name`` carries an anchor the parser cannot reduce to a
    step or a known external date ("nach dem Abschluss des Entsperrauftrags").
    """

    kind: Literal["step", "external", "event", "unanchored"]
    steps: list[int] = Field(default_factory=list)
    event: TransmissionEvent | None = None
    name: str | None = None
    #: The step that FIXES an external anchor's value, where the source names both — e.g.
    #: `beginn_messstellenbetrieb` step 16, "der 11. WT nach dem in Nr. 2 vom NB bestätigten
    #: Zuordnungsbeginn". The step does not compete with the anchor; it says where the
    #: anchor's value comes from, which is why it is not in ``steps``.
    established_by: int | None = None

    @model_validator(mode="after")
    def _kind_matches_its_fields(self) -> "Anchor":
        """A public model should not validate a shape it cannot mean: ``kind="step"`` with
        no steps, or ``kind="event"`` with no event, says nothing while looking specific."""
        if self.kind == "step" and not self.steps:
            raise ValueError("an anchor of kind 'step' must name at least one step")
        if self.kind == "external" and not self.name:
            raise ValueError("an anchor of kind 'external' must be named")
        if self.kind == "unanchored" and (self.steps or self.name):
            raise ValueError("an 'unanchored' anchor must carry neither steps nor a name")
        if self.kind == "step" and self.name:
            # The shape the lift deliberately avoids: where a step and an external anchor
            # coexist, the anchor is external and the step is `established_by`.
            raise ValueError("a 'step' anchor must not also be named; use 'external' with established_by")
        if self.kind == "event" and self.event is None and not self.name:
            # Either the transmission event, or a description of the process event the
            # corpus anchors to and the parser cannot reduce ("nach dem Abschluss des
            # Entsperrauftrags"). One of the two, not necessarily the Literal.
            raise ValueError("an anchor of kind 'event' must carry an event or a description")
        return self


class Schedule(BaseModel):
    """A hard date: *this* step's event must happen by ``anchor`` plus ``offset``."""

    #: NOTE on makoralle#57's third invariant — "reference_step always points backwards"
    #: (0 of 203 at v0.0.18, and 0 of 203 re-measured at v0.0.20). It is NOT enforced here,
    #: deliberately: an ``Anchor`` does not know which step owns it, so the check belongs on
    #: ``SDStep`` or on the diagram, where both numbers are in scope. Asserting it in this
    #: model would need the owning step passed in, which every construction site would then
    #: have to supply. Left for #57 step 3, where the parser has that context.

    #: Which of THIS step's own events must meet the deadline ("spätester ÜT ist …").
    #: Distinct from ``anchor.event``, which names an EARLIER step's event that the offset
    #: is measured from. The flat model has one field for both, so whichever it does not
    #: hold is dropped: at v0.0.20, 32 Frists name two events that DIFFER. (makoralle#57
    #: also counts 183 naming two events at all; that total moves with the matching
    #: pattern, so only the 32 — which reproduces exactly — is quoted here.) For a consumer
    #: evaluating a run these are different checks: "was the ÜZ in time" is not "was the
    #: ÜT in time".
    subject: TransmissionEvent | None = None
    anchor: Anchor
    offset: Offset | None = None
    #: A 24-hour wall-clock time, ``HH:MM``. Validated because this is the one
    #: field of an otherwise machine-checkable model that was a bare string:
    #: ``"99:99"`` and ``"not a time"`` both used to be accepted, leaving every
    #: consumer to parse defensively and to decide for itself what a malformed
    #: value means. The nine distinct values in the dataset all match.
    latest_time: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    #: True when ``latest_time`` applies to the anchor's own day rather than to the day the
    #: offset lands on — "15:00 Uhr am ÜT". 15 Frists say this, and without the flag a
    #: consumer computes the clock time against the wrong day.
    time_on_anchor_day: bool = False
    recurrence: Literal["täglich", "werktäglich"] | None = None

    @model_validator(mode="after")
    def _must_say_something(self) -> "Schedule":
        """A backstop with nothing in it is the failure this module exists to
        remove, and it was reachable in one line: ``Schedule(anchor=Anchor(
        kind="unanchored"))`` validated, and ``Deadline.states_a_backstop`` — a
        pure presence test — then answered ``True`` with nothing behind it. So a
        consumer would read the step as "hard date present, go check it".

        ``deadline_from_rule`` already refused to build one, but that guard is a
        decision inside one function, and #57 step 3 replaces that function with
        the parser: the invariant would have left with it. ``Anchor`` and
        ``DeadlineAlternative`` both validate their own coherence; this is the
        third of the three.

        ``time_on_anchor_day`` deliberately does not count as content — it
        qualifies ``latest_time`` and means nothing without one.
        """
        if not _says_something(
            subject=self.subject,
            anchor=self.anchor,
            offset=self.offset,
            latest_time=self.latest_time,
            recurrence=self.recurrence,
        ):
            raise ValueError(
                "a Schedule must carry something: an offset, a cutoff time, a recurrence, "
                "a subject event, or an anchor that is not 'unanchored'"
            )
        return self


def _says_something(
    *,
    subject: TransmissionEvent | None,
    anchor: "Anchor",
    offset: "Offset | None",
    latest_time: str | None,
    recurrence: str | None,
) -> bool:
    """Whether a would-be [`Schedule`] carries any information at all.

    One predicate, two call sites: [`Schedule._must_say_something`] enforces it as
    an invariant, and [`deadline_from_rule`] consults it to decide whether to build
    a backstop in the first place. They are the same question asked at different
    moments — "may this exist?" and "should I make one?" — and having them drift
    is how a contentless backstop would come back.
    """
    return (
        offset is not None
        or bool(latest_time)
        or recurrence is not None
        or subject is not None
        or anchor.kind != "unanchored"
    )


class DeadlineAlternative(BaseModel):
    """One branch of a Frist: a condition, an immediacy obligation, a backstop, or several.

    ``immediacy`` and ``backstop`` are both optional and both may be present — that pairing
    is the whole point, and is what the flat rule cannot express.
    """

    kind: Literal["immediate", "parallel", "scheduled", "reference", "complex"]
    #: The guard the source states for this branch: "Bei Aufbau der EDIFACT-Kommunikation",
    #: "Bei EEG-Marktlokationen … gilt". ``None`` on an unconditional Frist.
    condition: str | None = None
    #: What this step is tied to when it is not tied to a date: "unverzüglich [nach
    #: <anchor>]" for ``immediate``, and the coupled step for ``parallel`` ("zeitgleich mit
    #: Nr. 3"). Both are obligations relative to another event rather than to a calendar,
    #: which is why they share the field; ``kind`` is what tells them apart, and a consumer
    #: evaluating a run must read it — a coupling is not a promptness duty.
    immediacy: Anchor | None = None
    #: "jedoch spätester ÜT ist …" — the hard date the immediacy obligation is bounded by.
    backstop: Schedule | None = None

    @model_validator(mode="after")
    def _scheduled_has_a_backstop(self) -> "DeadlineAlternative":
        """A ``scheduled`` alternative without a backstop would assert a hard date and then
        not say what it is — the failure mode this model exists to remove, reintroduced in
        the new shape."""
        if self.kind == "scheduled" and self.backstop is None:
            raise ValueError("a 'scheduled' alternative must carry a backstop")
        return self


#: How much of a Frist's prose the structure accounts for.
#:
#: The reason this exists: a consumer must be able to tell *"this step has no deadline"*
#: from *"this step has a deadline nobody has structured"*. Without it, the Fristen whose
#: stated backstop no structured field holds read as unconstrained, and a conformance suite
#: passes them silently — a false pass each, which is worse than a reported gap.
#:
#: * ``complete`` — the structure holds the whole obligation.
#: * ``partial``  — structure is present, but the prose states more than it holds (a dropped
#:   backstop, a condition, a second anchor). Evaluating only the structured part would
#:   check a *weaker* obligation than the regulation imposes.
#: * ``opaque``   — nothing checkable: a ``reference`` or ``complex`` alternative.
Coverage = Literal["complete", "partial", "opaque"]


class Deadline(BaseModel):
    """A step's Frist. More than one alternative means the source states a conditional."""

    alternatives: list[DeadlineAlternative] = Field(min_length=1)
    #: How much of :attr:`raw` the structure above accounts for. Defaulted to the safe
    #: answer rather than the optimistic one: a ``Deadline`` assembled by hand, by a
    #: consumer or a test, claims nothing about prose it never saw.
    coverage: Coverage = "partial"
    #: The source's own wording, unchanged. Required, not defaulted: it is the only thing a
    #: human can check against the document, and the only full record until the parser fills
    #: the structure (#57 step 3). A Deadline without it asserts a Frist nobody can verify.
    raw: str

    @property
    def is_conditional(self) -> bool:
        return len(self.alternatives) > 1

    @property
    def states_a_backstop(self) -> bool:
        """True when any alternative carries a hard date.

        The question `emit_wsd` has to answer to stop rendering a bounded obligation as a
        bare "{u}", and the question a test suite has to answer before deciding a step has
        no deadline to check.
        """
        return any(a.backstop is not None for a in self.alternatives)


#: Rule types that describe an obligation to act immediately rather than by a fixed date.
_IMMEDIATE_TYPES = frozenset({"unverzüglich", "parallel"})

#: How a flat ``DeadlineRule.type`` maps onto an alternative's ``kind``. ``parallel`` keeps
#: its own kind rather than folding into ``immediate``: "zeitgleich mit Nr. 3" is a
#: coupling to another step, not a promptness duty, and a consumer evaluating a run has to
#: tell them apart.
_KIND_BY_TYPE: dict[str, Literal["immediate", "parallel", "scheduled", "reference", "complex"]] = {
    "unverzüglich": "immediate",
    "parallel": "parallel",
    "terminiert": "scheduled",
    "reference": "reference",
    "complex": "complex",
}


#: "jedoch spätester ÜT ist ...", "spätester ÜZ ist ..." — the prose states a hard date.
_BACKSTOP = re.compile(r"jedoch\s+sp[äa]test|sp[äa]tester\s+(?:ÜT|ÜZ)\s+ist", re.I)
#: Two or more alternatives selected by a condition, which the flat rule cannot hold.
_CONDITIONAL = re.compile(r"(?:•.{0,400}•)|\bAnsonsten\b|\bI\.\)|\bII\.\)|Sofern\b.{0,80}\bgilt\s*:", re.S)
#: "der 1. WT nach dem ÜT von Nr. 3 bzw. 4" — ``reference_step`` holds one step.
_DISJUNCT_STEP = re.compile(r"Nr\.\s*\d+\s*(?:bzw\.|oder)\s*\d+", re.I)
#: An offset the flat rule cannot express: ``business_days`` is its only unit.
_NON_WT_UNIT = re.compile(r"\b\d+\s*Stunden?\b|\b\d+\.?\s*T\b(?![ÜA-Za-zäöü])|Kalendertag", re.I)
#: "spätester ÜZ ist 15:00 Uhr am ÜT" — the cutoff belongs to the anchor's day.
_TIME_ON_ANCHOR_DAY = re.compile(r"\d{1,2}:\d{2}\s*Uhr\s+am\b", re.I)
#: The event THIS step must meet ("spätester ÜT ist ...") and the event the offset is
#: measured from ("... nach dem ÜZ von Nr. 1"). The flat rule has one field for both.
_SUBJECT_EVENT = re.compile(r"sp[äa]tester\s+(ÜT|ÜZ)", re.I)
_ANCHOR_EVENT = re.compile(r"nach\s+dem\s+(ÜT|ÜZ)\s+von\s+Nr", re.I)

#: The downgrade reasons that need nothing but the prose. The two that also need to look at
#: the lifted structure — a dropped backstop, and a subject event that differs from the
#: anchor's — stay in :func:`_loss_in` below.
_LOSS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_CONDITIONAL, "several obligations selected by a condition, and one slot to hold them"),
    (_DISJUNCT_STEP, '"Nr. 3 bzw. 4", where `reference_step` holds one step'),
    (_NON_WT_UNIT, "Stunden or Kalendertage, where `business_days` is the only unit"),
    (_TIME_ON_ANCHOR_DAY, '"15:00 Uhr am ÜT" — no slot for which day the cutoff falls on'),
)


def coverage_of(rule: DeadlineRule, alternative: DeadlineAlternative) -> Coverage:
    """How much of ``rule.raw`` the lifted ``alternative`` accounts for.

    The **only** prose-reading in the lift, and it can only ever downgrade
    ``complete`` -> ``partial``. That asymmetry is what makes it a conservative marker
    rather than a second parser: every pattern below names a construct the flat
    :class:`~makoralle.models.process.DeadlineRule` provably cannot hold, so a match is
    evidence of loss, and a non-match is never taken as evidence of fidelity.

    This lived in makuna's dataset converter, where its own comment asked to be deleted
    "when makoralle#57 lands". It moves here ahead of that because it has to: a consumer
    reading the structured shape needs the marker in the same object, and a second copy
    beside every consumer is how the four measurements in this module's docstring came to
    disagree in the first place. makuna now delegates instead of reimplementing.

    Retire it — not the field — when the parser fills the structure natively: at that point
    ``partial`` should come from the parser saying what it could not represent, rather than
    from this function recognizing seven shapes.
    """
    if alternative.kind in ("reference", "complex"):
        return "opaque"
    return "complete" if _loss_in(rule.raw or "", alternative) is None else "partial"


def _loss_in(raw: str, alternative: DeadlineAlternative) -> str | None:
    """Why ``raw`` says more than ``alternative`` holds, or ``None`` when it does not.

    Returns the reason rather than a bool so that a caller debugging one Frist — or a test
    asserting *which* construct it caught — does not have to re-run the patterns by hand.
    """
    for pattern, why in _LOSS_PATTERNS:
        if pattern.search(raw):
            return why
    if _BACKSTOP.search(raw):
        backstop = alternative.backstop
        if backstop is None or (backstop.offset is None and backstop.latest_time is None):
            return "a hard date stated in prose and nowhere else"

    # The constrained event and the anchor's event share one field on the flat rule, so when
    # the prose names both and they DIFFER, whichever the field does not hold is lost.
    # Marking those `partial` is what lets a consumer read an absent `subject` on a
    # `complete` Frist as "the same event as the anchor's" — makuna's
    # `Schedule::constrained_event` relies on exactly that.
    subject, anchor_event = _SUBJECT_EVENT.search(raw), _ANCHOR_EVENT.search(raw)
    if subject and anchor_event and subject.group(1).upper() != anchor_event.group(1).upper():
        return "the constrained event differs from the anchor's, and one field holds both"
    return None


def _lifted(rule: DeadlineRule, alternative: DeadlineAlternative) -> "Deadline":
    """One place where a lifted alternative becomes a ``Deadline``, so that no return path
    can forget :func:`coverage_of` — the field's default is deliberately pessimistic, which
    would make an omission quiet rather than wrong."""
    return Deadline(alternatives=[alternative], coverage=coverage_of(rule, alternative), raw=rule.raw)


def _as_event(value: str | None) -> TransmissionEvent | None:
    """``ÜT``/``ÜZ`` if that is what the flat field holds, else ``None``.

    The corpus holds only ``ÜT``, ``ÜZ`` and ``None`` today, but the field is typed open,
    so narrow once here rather than trusting the looser upstream type at each call site.
    """
    if value == "ÜT":
        return "ÜT"
    if value == "ÜZ":
        return "ÜZ"
    return None


def _as_recurrence(value: str | None) -> Literal["täglich", "werktäglich"] | None:
    if value == "täglich":
        return "täglich"
    if value == "werktäglich":
        return "werktäglich"
    return None


def _as_kind(rule_type: str) -> Literal["immediate", "parallel", "scheduled", "reference", "complex"]:
    """An unknown type becomes ``complex`` — the kind that means "real, but not reduced"."""
    return _KIND_BY_TYPE.get(rule_type, "complex")


def _anchor_from_flat(*, step: int | None, event: str | None, name: str | None) -> Anchor:
    """The anchor a flat rule's fields describe.

    When the rule carries BOTH a step and an external anchor name, the external one is the
    anchor and the step says where its value comes from — that is what ``established_by``
    is for. `beginn_messstellenbetrieb` step 16 is the case: "Spätester ÜT ist der 11. WT
    nach dem **in Nr. 2 vom NB bestätigten Zuordnungsbeginn**" — the offset is measured from
    the Zuordnungsbeginn, and Nr. 2 is merely where that date was fixed. Letting the step
    win instead drops the anchor name, which is the one field the lift would otherwise lose
    across the whole corpus.
    """
    if step is not None and name:
        return Anchor(kind="external", name=name, event=_as_event(event), established_by=step)
    if step is not None:
        return Anchor(kind="step", steps=[step], event=_as_event(event))
    if name:
        return Anchor(kind="external", name=name, event=_as_event(event))
    if _as_event(event) is not None:
        # Unreachable from a flat rule today — over all 1601 `deadline_rule` entries at
        # v0.0.20 the lift builds no `event` anchor, because a bare `reference_event` with
        # no step and no anchor name is either drained into `subject` (terminiert) or left
        # on an otherwise empty anchor. Kept for the parser output of #57 step 3, which can
        # anchor to an event the corpus names in prose ("nach dem Abschluss des
        # Entsperrauftrags").
        return Anchor(kind="event", event=_as_event(event))
    return Anchor(kind="unanchored")


def deadline_from_rule(rule: DeadlineRule) -> Deadline | None:
    """Lift a flat ``DeadlineRule`` into the structured shape, losing nothing it holds.

    Returns ``None`` for ``type == "none"``, which is the model's way of saying there is no
    Frist — not a Frist with no content.

    THE ONE PIECE OF KNOWLEDGE THIS ENCODES, so that no consumer has to rediscover it:
    which obligation owns the flat rule's anchor fields. For ``unverzüglich`` it depends on
    whether an offset is present — verified over dataset v0.0.20, **148 of 148** rules with
    ``business_days`` state a backstop in prose ("… jedoch spätest…"), and of the 266
    without one, none that lack "spätest" state a backstop at all. So:

    * offset present  -> the fields describe the BACKSTOP, and the immediacy obligation is
      unanchored ("unverzüglich, jedoch spätester ÜT ist der 2. WT nach dem ÜT von Nr. 1");
    * offset absent   -> the fields describe the IMMEDIACY anchor ("unverzüglich nach …").

    What this CANNOT recover is what the flat rule never held: a condition, a second
    alternative, a subject event that differs from the anchor's, a unit other than Werktage.
    Those need the parser (makoralle#57 step 3). A lifted rule is therefore faithful, not
    complete — ``raw`` remains the only full record until then.
    """
    if not rule.type or rule.type == "none":
        return None

    kind = _as_kind(rule.type)
    offset = (
        Offset(amount=rule.business_days, unit="werktage", direction=rule.direction or "nach")
        if rule.business_days is not None
        else None
    )
    recurrence = _as_recurrence(rule.recurrence)
    if recurrence is None and rule.recurring:
        # `recurring: True` with no word for it predates the `recurrence` field. Defensive:
        # every recurring rule at v0.0.20 already carries one, so this only fires on a
        # dataset written before it. "täglich" is the reading that does not invent a
        # weekday restriction the source may not impose (makorele#101, in reverse).
        recurrence = "täglich"

    # For `terminiert`, `reference_event` is the SUBJECT — the corpus reads "Spätester <event>
    # ist …" in all 10 such rules — not the event an offset is measured from. Filing it on the
    # anchor produces "measured from the ÜT of the Zahlungsziel", which is not a thing, and
    # leaves `subject` empty in every lifted deadline. For `unverzüglich` it genuinely is the
    # anchor's event ("… nach dem ÜZ von Nr. 1").
    subject = _as_event(rule.reference_event) if rule.type == "terminiert" else None
    anchor = _anchor_from_flat(
        step=rule.reference_step,
        event=None if subject is not None else rule.reference_event,
        name=rule.anchor,
    )

    if rule.type in _IMMEDIATE_TYPES and offset is None:
        # The fields describe the immediacy anchor; there is no backstop to build. A clock
        # time or a recurrence still has to survive, so it becomes an unanchored backstop
        # rather than being dropped — which is the bug, in miniature.
        backstop = (
            Schedule(anchor=Anchor(kind="unanchored"), latest_time=rule.latest_time, recurrence=recurrence)
            if (rule.latest_time or recurrence)
            else None
        )
        return _lifted(rule, DeadlineAlternative(kind=kind, immediacy=anchor, backstop=backstop))

    # Only build a backstop when there is something in it. `reference` and `complex` rules
    # carry no offset, time, step or anchor name — 134 of them at v0.0.20 — and an empty
    # Schedule would make `states_a_backstop` answer True with nothing behind it. That is the
    # failure this model exists to remove, reintroduced in the new shape: a consumer would
    # read 134 steps as "backstop present, go check it".
    # `subject` counts as content. Without it a `terminiert` rule carrying only
    # `reference_event` builds no backstop — because the subject has just drained that field
    # out of the anchor — and the `scheduled` validator then REJECTS it, so the lift raises
    # on input it used to handle. v0.0.20 happens to contain no such rule, so the corpus run
    # stays clean and says nothing about it; the upstream is a non-deterministic Vision
    # stage, so "not in today's corpus" is not a guarantee.
    has_content = _says_something(
        subject=subject,
        anchor=anchor,
        offset=offset,
        latest_time=rule.latest_time,
        recurrence=recurrence,
    )
    backstop = (
        Schedule(subject=subject, anchor=anchor, offset=offset, latest_time=rule.latest_time, recurrence=recurrence)
        if has_content
        else None
    )
    if backstop is None and kind == "scheduled":
        # A `terminiert` rule with nothing structured in it is real but not reduced — which
        # is what `complex` means. Degrading beats raising: this function's contract is
        # "None only for type: none", and a library that throws on a shape its own upstream
        # can emit is worse than one that says "I could not structure this".
        kind = "complex"
    immediacy = Anchor(kind="unanchored") if rule.type in _IMMEDIATE_TYPES else None
    return _lifted(rule, DeadlineAlternative(kind=kind, immediacy=immediacy, backstop=backstop))
