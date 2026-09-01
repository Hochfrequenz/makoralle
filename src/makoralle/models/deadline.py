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

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from makoralle.models.process import DeadlineRule

#: The two transmission events a Frist can speak about. ``ÜT`` is the Übertragungstag (the
#: day), ``ÜZ`` the Übertragungszeitpunkt (the instant).
TransmissionEvent = Literal["ÜT", "ÜZ"]


class Offset(BaseModel):
    """A distance from an anchor, in the unit the source names.

    ``unit`` exists because the corpus is not only Werktage: two Frists are stated in
    Stunden and two in Kalendertage, and a bare ``business_days: int`` cannot hold either
    without lying about which calendar applies.
    """

    amount: int
    #: Defaulted, where makoralle#57 has it required: every offset the flat rule can express
    #: is in Werktage (the field is literally ``business_days``), so requiring it would make
    #: the lift restate the only value it can produce — on all 160 offsets across the 906
    #: ``diagrams[]`` rules at v0.0.20. Kalendertage and Stunden exist (2 Frists each) and
    #: must be stated explicitly, never inferred.
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
    latest_time: str | None = None
    #: True when ``latest_time`` applies to the anchor's own day rather than to the day the
    #: offset lands on — "15:00 Uhr am ÜT". 15 Frists say this, and without the flag a
    #: consumer computes the clock time against the wrong day.
    time_on_anchor_day: bool = False
    recurrence: Literal["täglich", "werktäglich"] | None = None


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


class Deadline(BaseModel):
    """A step's Frist. More than one alternative means the source states a conditional."""

    alternatives: list[DeadlineAlternative] = Field(min_length=1)
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
        return Deadline(
            alternatives=[DeadlineAlternative(kind=kind, immediacy=anchor, backstop=backstop)], raw=rule.raw
        )

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
    has_content = (
        offset is not None or rule.latest_time or recurrence or subject is not None or anchor.kind != "unanchored"
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
    return Deadline(alternatives=[DeadlineAlternative(kind=kind, immediacy=immediacy, backstop=backstop)], raw=rule.raw)
