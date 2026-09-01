"""The structured Frist, and the lift from the flat rule (makoralle#57)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from makoralle.models.deadline import (
    _KIND_BY_TYPE,
    Anchor,
    Deadline,
    DeadlineAlternative,
    Offset,
    Schedule,
    deadline_from_rule,
)
from makoralle.models.process import DeadlineRule


def test_no_frist_lifts_to_none_not_to_an_empty_deadline() -> None:
    """`type: "none"` says there is no Frist. An empty `Deadline` would say there is one
    with no content, which a consumer deciding "is there a deadline to check" reads as the
    opposite of the truth."""
    assert deadline_from_rule(DeadlineRule(type="none", raw="--")) is None


def test_an_offset_means_the_flat_fields_describe_the_backstop() -> None:
    """The disambiguation the flat model forces on every consumer, encoded once.

    "Unverzüglich, jedoch spätester ÜT ist der 2. WT nach dem ÜT von Nr. 1" — the anchor
    fields belong to the backstop, and the immediacy obligation has no anchor of its own.
    Verified over dataset v0.0.20: 148 of 148 rules carrying an offset state a backstop.
    """
    d = deadline_from_rule(
        DeadlineRule(
            type="unverzüglich",
            business_days=2,
            reference_step=1,
            reference_event="ÜT",
            raw="Unverzüglich, jedoch spätester ÜT ist der 2. WT nach dem ÜT von Nr. 1.",
        )
    )
    assert d is not None
    (alt,) = d.alternatives
    assert alt.kind == "immediate"
    assert alt.immediacy == Anchor(kind="unanchored")
    assert alt.backstop is not None
    assert alt.backstop.anchor == Anchor(kind="step", steps=[1], event="ÜT")
    assert alt.backstop.offset == Offset(amount=2, unit="werktage", direction="nach")
    assert d.states_a_backstop


def test_no_offset_means_the_flat_fields_describe_the_immediacy_anchor() -> None:
    """ "Unverzüglich nach dem ÜZ von Nr. 1" — same fields, the other obligation."""
    d = deadline_from_rule(
        DeadlineRule(
            type="unverzüglich", reference_step=1, reference_event="ÜZ", raw="Unverzüglich nach dem ÜZ von Nr. 1."
        )
    )
    assert d is not None
    (alt,) = d.alternatives
    assert alt.immediacy == Anchor(kind="step", steps=[1], event="ÜZ")
    assert alt.backstop is None
    assert not d.states_a_backstop


def test_direction_defaults_to_nach_rather_than_staying_unknown() -> None:
    """Of the 148 rules at v0.0.20 with an offset and no explicit direction, 0 have prose
    containing "vor" — so the default is a fact about the corpus, not a guess."""
    d = deadline_from_rule(DeadlineRule(type="terminiert", business_days=4, anchor="Zahlungsziel", raw="x"))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.offset == Offset(amount=4, unit="werktage", direction="nach")


def test_an_explicit_vor_survives_the_lift() -> None:
    d = deadline_from_rule(
        DeadlineRule(type="terminiert", business_days=4, direction="vor", anchor="Zahlungsziel", raw="x")
    )
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.offset is not None
    assert d.alternatives[0].backstop.offset.direction == "vor"


def test_a_clock_time_on_an_unanchored_immediacy_rule_is_not_dropped() -> None:
    """The bug in miniature: an `unverzüglich` rule with a time but no offset has nowhere to
    put the time under the "fields describe the immediacy anchor" reading. It becomes an
    unanchored backstop rather than being lost."""
    d = deadline_from_rule(DeadlineRule(type="unverzüglich", latest_time="07:00", raw="Unverzüglich, bis 07:00 Uhr."))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.latest_time == "07:00"


def test_recurring_without_a_word_for_it_reads_as_taeglich() -> None:
    """`recurring: True` predates the `recurrence` field. "täglich" is the only reading that
    does not invent a weekday restriction the source may not impose — the same defect
    makorele#101 records in the other direction."""
    d = deadline_from_rule(DeadlineRule(type="unverzüglich", recurring=True, raw="Täglich."))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.recurrence == "täglich"
    werktaeglich = deadline_from_rule(
        DeadlineRule(type="unverzüglich", recurring=True, recurrence="werktäglich", raw="Werktäglich.")
    )
    assert werktaeglich is not None and werktaeglich.alternatives[0].backstop is not None
    assert werktaeglich.alternatives[0].backstop.recurrence == "werktäglich"


def test_parallel_keeps_its_own_kind() -> None:
    """ "zeitgleich mit Nr. 3" is a coupling to another step, not a promptness duty; a
    consumer evaluating a run has to tell them apart."""
    d = deadline_from_rule(DeadlineRule(type="parallel", reference_step=3, raw="Zeitgleich mit Nr. 3."))
    assert d is not None and d.alternatives[0].kind == "parallel"


def test_an_unknown_type_becomes_complex_rather_than_raising() -> None:
    """A dataset written by a newer parser must still load: an unrecognised type is "real,
    but not reduced", which is exactly what `complex` means."""
    d = deadline_from_rule(DeadlineRule(type="etwas-neues", raw="x"))
    assert d is not None and d.alternatives[0].kind == "complex"


def test_a_scheduled_alternative_must_say_what_the_date_is() -> None:
    """Otherwise the new shape reintroduces the old bug: an assertion that a hard date
    exists, with no date."""
    with pytest.raises(ValidationError):
        DeadlineAlternative(kind="scheduled")


def test_a_deadline_needs_at_least_one_alternative() -> None:
    with pytest.raises(ValidationError):
        Deadline(alternatives=[], raw="x")


def test_the_shape_can_hold_what_the_flat_rule_cannot() -> None:
    """The point of the change, asserted directly: a conditional Frist with two branches,
    each with its own condition, its own immediacy anchor and its own backstop — and a
    subject event that differs from the anchor's."""
    d = Deadline(
        raw="Bei Aufbau der EDIFACT-Kommunikation: Unverzüglich, jedoch spätester ÜT ist der 1. WT "
        "nach dem Aufbau. Bei Änderung: Unverzüglich, jedoch spätester ÜZ ist 00:00 Uhr des 61. WT "
        "nach dem ÜT von Nr. 1.",
        alternatives=[
            DeadlineAlternative(
                kind="immediate",
                condition="Bei Aufbau der EDIFACT-Kommunikation",
                immediacy=Anchor(kind="unanchored"),
                backstop=Schedule(
                    subject="ÜT",
                    anchor=Anchor(kind="event", name="Aufbau der EDIFACT-Kommunikation"),
                    offset=Offset(amount=1),
                ),
            ),
            DeadlineAlternative(
                kind="immediate",
                condition="Bei Änderung",
                immediacy=Anchor(kind="unanchored"),
                # subject ÜZ, anchor event ÜT — the pair the flat model collapses into one
                # field, losing whichever it does not hold. 32 Frists at v0.0.20 differ here.
                backstop=Schedule(
                    subject="ÜZ",
                    anchor=Anchor(kind="step", steps=[1], event="ÜT"),
                    offset=Offset(amount=61),
                    latest_time="00:00",
                ),
            ),
        ],
    )
    assert d.is_conditional
    assert d.states_a_backstop
    assert d.alternatives[1].backstop is not None
    assert d.alternatives[1].backstop.subject == "ÜZ"
    assert d.alternatives[1].backstop.anchor.event == "ÜT"


def test_a_disjunctive_step_reference_fits() -> None:
    """ "Nr. 3 bzw. 4" — 3 Frists say this, and a single int cannot hold it."""
    assert Anchor(kind="step", steps=[3, 4]).steps == [3, 4]


def test_an_external_anchor_can_name_the_step_that_fixes_its_value() -> None:
    """`beginn_messstellenbetrieb` step 16: "der 11. WT nach dem in Nr. 2 vom NB bestätigten
    Zuordnungsbeginn". Nr. 2 does not compete with the anchor — it says where the anchor's
    value comes from, which is why it is not in `steps`."""
    a = Anchor(kind="external", name="Zuordnungsbeginn", established_by=2)
    assert a.steps == [] and a.established_by == 2


def test_the_lift_loses_nothing_on_every_shape_the_corpus_actually_has() -> None:
    """The claim the change rests on, checked against real rules rather than invented ones.

    `unittests/fixtures/deadline_rule_shapes.json` holds one real rule per distinct
    *shape* — the set of populated fields plus the type — found in dataset v0.0.20's 906
    `deadline_rule` entries: 15 shapes, each recorded with the process, variant and step it
    came from. A fixture rather than a live read of the corpus, because makoralle is public
    and the dataset is not, so a test that reached for it could not run in CI.

    Run against the whole corpus while developing this, the same assertion holds for all
    906 rows: 0 failures, 0 fields lost, 307 `type: "none"` lifting to `None`.
    """
    shapes = json.loads((Path(__file__).parent / "fixtures" / "deadline_rule_shapes.json").read_text("utf-8"))
    assert shapes, "fixture is empty — the assertion below would pass vacuously"

    for entry in shapes:
        where = entry["_where"]
        rule = DeadlineRule(**{k: v for k, v in entry.items() if k != "_where"})
        lifted = deadline_from_rule(rule)

        if rule.type == "none":
            assert lifted is None, where
            continue
        assert lifted is not None, where
        alt = lifted.alternatives[0]
        schedule, immediacy = alt.backstop, alt.immediacy

        assert lifted.raw == rule.raw, where
        if rule.business_days is not None:
            assert schedule and schedule.offset and schedule.offset.amount == rule.business_days, where
        if rule.latest_time:
            assert schedule and schedule.latest_time == rule.latest_time, where
        if rule.reference_step is not None:
            carried = [*(schedule.anchor.steps if schedule else []), *(immediacy.steps if immediacy else [])]
            carried += [
                s
                for s in (
                    schedule.anchor.established_by if schedule else None,
                    immediacy.established_by if immediacy else None,
                )
                if s is not None
            ]
            assert rule.reference_step in carried, where
        if rule.anchor:
            names = [a.name for a in (schedule.anchor if schedule else None, immediacy) if a]
            assert rule.anchor in names, where

        # The other five fields. Without these, eight separate mutations survive — deleting
        # the event narrowing, the recurrence narrowing, the direction default, the explicit
        # direction, the kind mapping — because the loop above never looks at them.
        assert alt.kind == _KIND_BY_TYPE.get(rule.type, "complex"), where
        if rule.reference_event:
            events = [a.event for a in (schedule.anchor if schedule else None, immediacy) if a]
            if schedule is not None:
                events.append(schedule.subject)
            assert rule.reference_event in events, where
        if rule.direction:
            assert schedule and schedule.offset and schedule.offset.direction == rule.direction, where
        if rule.recurrence:
            assert schedule and schedule.recurrence == rule.recurrence, where
        elif rule.recurring:
            assert schedule and schedule.recurrence is not None, where


def test_a_step_and_an_external_anchor_together_keep_both() -> None:
    """`beginn_messstellenbetrieb` step 16: "der 11. WT nach dem in Nr. 2 vom NB bestätigten
    Zuordnungsbeginn". The step does not compete with the anchor — it says where the
    anchor's value comes from. Letting the step win drops the anchor name, and this is the
    only rule in the corpus where the two coexist, so it is also the only one that would
    have lost a field."""
    d = deadline_from_rule(
        DeadlineRule(type="terminiert", business_days=11, reference_step=2, anchor="Zuordnungsbeginn", raw="x")
    )
    assert d is not None and d.alternatives[0].backstop is not None
    anchor = d.alternatives[0].backstop.anchor
    assert anchor.kind == "external"
    assert anchor.name == "Zuordnungsbeginn"
    assert anchor.established_by == 2
    assert anchor.steps == []


def test_parallel_keeps_its_step_as_a_coupling_not_a_backstop() -> None:
    """`_IMMEDIATE_TYPES` holds `parallel` as well as `unverzüglich`. Drop it and all 28
    `parallel` rules — 27 of which carry a `reference_step` and none an offset — silently
    move their step from the immediacy side to a backstop, asserting a hard date the source
    never states. `test_parallel_keeps_its_own_kind` checks only `kind`, so it does not see
    that."""
    d = deadline_from_rule(DeadlineRule(type="parallel", reference_step=3, raw="Zeitgleich mit Nr. 3."))
    assert d is not None
    alt = d.alternatives[0]
    assert alt.immediacy == Anchor(kind="step", steps=[3])
    assert alt.backstop is None
    assert not d.states_a_backstop


def test_a_reference_or_complex_rule_carries_no_empty_backstop() -> None:
    """104 `reference` and 30 `complex` rules hold no offset, time, step or anchor name. An
    empty `Schedule` would make `states_a_backstop` answer True with nothing behind it —
    which is the failure this model exists to remove, reintroduced in the new shape. A
    consumer would read 134 steps as "backstop present, go check it"."""
    for rule_type in ("reference", "complex"):
        d = deadline_from_rule(DeadlineRule(type=rule_type, raw="1 WT nach Abbestellung der Aggregationsebene RZ."))
        assert d is not None, rule_type
        assert d.alternatives[0].backstop is None, rule_type
        assert not d.states_a_backstop, rule_type


def test_terminiert_files_its_event_as_the_subject_not_the_anchors() -> None:
    """All 10 `terminiert` rules read "Spätester <event> ist …", so `reference_event` names
    THIS step's event, not the one an offset is measured from. Filing it on the anchor gives
    "measured from the ÜT of the Zahlungsziel", which is not a thing — and leaves `subject`
    empty in every lifted deadline, i.e. the headline field dead on arrival."""
    d = deadline_from_rule(
        DeadlineRule(
            type="terminiert",
            business_days=20,
            direction="vor",
            reference_event="ÜT",
            anchor="Änderungstermin",
            raw="Spätester ÜT ist der 20. WT vor dem gewünschten Änderungstermin.",
        )
    )
    assert d is not None and d.alternatives[0].backstop is not None
    backstop = d.alternatives[0].backstop
    assert backstop.subject == "ÜT"
    assert backstop.anchor.event is None
    assert backstop.anchor.name == "Änderungstermin"


def test_states_a_backstop_asks_whether_any_alternative_has_one() -> None:
    """`any`, not `all`: a conditional Frist where only one branch is bounded still states a
    backstop, and a consumer must go and check it. Only ever exercised on single-alternative
    deadlines otherwise, where the two are indistinguishable."""
    bounded = DeadlineAlternative(
        kind="immediate", backstop=Schedule(anchor=Anchor(kind="step", steps=[1]), offset=Offset(amount=1))
    )
    unbounded = DeadlineAlternative(kind="immediate", immediacy=Anchor(kind="unanchored"))
    assert Deadline(alternatives=[bounded, unbounded], raw="x").states_a_backstop
    assert not Deadline(alternatives=[unbounded, unbounded], raw="x").states_a_backstop


def test_is_conditional_means_more_than_one_alternative() -> None:
    single = DeadlineAlternative(kind="immediate", immediacy=Anchor(kind="unanchored"))
    assert not Deadline(alternatives=[single], raw="x").is_conditional
    assert Deadline(alternatives=[single, single], raw="x").is_conditional


def test_an_offset_is_werktage_unless_the_source_says_otherwise() -> None:
    """The default carries the corpus: Werktage is what a bare "N. WT" means. Stunden exist
    (2 Frists at v0.0.20) and must be stated, never inferred; no Frist at v0.0.20 names
    Kalendertage, so that member is there for #57 step 3 rather than for this corpus."""
    assert Offset(amount=3).unit == "werktage"
    assert Offset(amount=3, unit="stunden").unit == "stunden"


def test_a_clock_time_applies_to_the_offset_day_unless_flagged() -> None:
    """`time_on_anchor_day` defaults False: "15:00 Uhr am ÜT" (15 Frists) puts the time on
    the anchor's own day, and defaulting True would move every other Frist's clock time to
    the wrong day."""
    assert not Schedule(anchor=Anchor(kind="unanchored"), latest_time="15:00").time_on_anchor_day


def test_a_terminiert_rule_carrying_only_its_event_still_lifts() -> None:
    """The regression round 1's own two fixes combined to create.

    `subject` drains `reference_event` out of the anchor, so the anchor is unanchored; if
    `has_content` does not count `subject` the backstop is None, and the `scheduled`
    validator then REJECTS it — the lift raising on input it used to handle. v0.0.20
    contains no such rule, so the corpus run stays clean and says nothing about it.
    """
    d = deadline_from_rule(DeadlineRule(type="terminiert", reference_event="ÜT", raw="Spätester ÜT ist …"))
    assert d is not None
    assert d.alternatives[0].kind == "scheduled"
    assert d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.subject == "ÜT"


def test_a_terminiert_rule_with_nothing_in_it_degrades_rather_than_raising() -> None:
    """`complex` means "real, but not reduced", which is exactly what this is. The function's
    contract is "None only for type: none"; a library that throws on a shape its own
    non-deterministic upstream can emit is worse than one that says it could not structure
    the Frist."""
    d = deadline_from_rule(DeadlineRule(type="terminiert", raw="Zum Bilanzierungsmonat."))
    assert d is not None
    assert d.alternatives[0].kind == "complex"
    assert d.alternatives[0].backstop is None
    assert d.raw == "Zum Bilanzierungsmonat."


def test_every_lift_of_every_shape_returns_rather_than_raises() -> None:
    """The contract, over the whole fixture plus the degenerate shapes the corpus lacks."""
    shapes = json.loads((Path(__file__).parent / "fixtures" / "deadline_rule_shapes.json").read_text("utf-8"))
    extra = [
        {"type": t, "raw": "x", **f}
        for t in ("terminiert", "reference", "complex", "unverzüglich", "parallel")
        for f in ({}, {"reference_event": "ÜT"}, {"reference_event": "ÜZ"}, {"recurring": True})
    ]
    for entry in [*({k: v for k, v in e.items() if k != "_where"} for e in shapes), *extra]:
        deadline_from_rule(DeadlineRule(**entry))  # must not raise


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "step", "steps": []},
        {"kind": "external", "name": None},
        {"kind": "event", "event": None, "name": None},
        {"kind": "unanchored", "steps": [3]},
        {"kind": "unanchored", "name": "Zahlungsziel"},
        {"kind": "step", "steps": [3], "name": "Zahlungsziel"},
    ],
)
def test_an_anchor_whose_kind_and_fields_disagree_is_refused(kwargs: dict[str, object]) -> None:
    """A public model should not validate a shape it cannot mean. Deleting any single branch
    of the validator, or the whole thing, otherwise survives the entire suite. The last case
    is the shape the lift deliberately avoids: a step and a name together mean the anchor is
    external and the step merely establishes its value."""
    with pytest.raises(ValidationError):
        Anchor(**kwargs)  # type: ignore[arg-type]


def test_raw_is_required_not_defaulted() -> None:
    """It is the only full record until the parser fills the structure, and the only thing a
    human can check against the document. Defaulting it to "" lets a Deadline assert a Frist
    nobody can verify — and nothing else in the suite notices."""
    with pytest.raises(ValidationError):
        Deadline(alternatives=[DeadlineAlternative(kind="complex")])  # type: ignore[call-arg]


def test_a_clock_time_alone_is_content_enough_for_a_backstop() -> None:
    """`has_content`'s `latest_time` term: without it, "Spätester ÜT ist 15:00 Uhr" loses its
    only structured fact."""
    d = deadline_from_rule(DeadlineRule(type="reference", latest_time="15:00", raw="… 15:00 Uhr"))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.latest_time == "15:00"


def test_a_recurrence_alone_is_content_enough_for_a_backstop() -> None:
    """`has_content`'s `recurrence` term, for the same reason."""
    d = deadline_from_rule(DeadlineRule(type="reference", recurrence="werktäglich", raw="Werktäglich."))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.recurrence == "werktäglich"


def test_an_anchor_alone_is_content_enough_for_a_backstop() -> None:
    """`has_content`'s `anchor.kind != "unanchored"` term, on the one path that reaches it.

    The 54 corpus rules with an anchor and no offset are all `unverzüglich`/`parallel`, so
    they take the immediacy branch and never get here; the two `terminiert` ones ("Spätester
    ÜT ist zum Zahlungsziel in der Rechnung") also carry a subject, which masks the term.
    Drop it and this `reference` rule silently loses its anchor — 0 tests notice.
    """
    d = deadline_from_rule(DeadlineRule(type="reference", anchor="Zahlungsziel", raw="Zum Zahlungsziel."))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.anchor == Anchor(kind="external", name="Zahlungsziel")
    assert d.states_a_backstop


def test_an_offset_alone_is_content_enough_for_a_backstop() -> None:
    """`has_content`'s `offset is not None` term. No rule at v0.0.20 carries an offset and
    nothing else — every one names a step or an anchor too — so the term is unexercised by
    the corpus and by every other test here, and dropping it survives the suite."""
    d = deadline_from_rule(DeadlineRule(type="reference", business_days=3, raw="3 WT."))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.offset == Offset(amount=3, unit="werktage", direction="nach")


# --- the invariants a public model should not be able to violate -------------
#
# Each of these was reachable before makoralle#58's follow-up. `deadline_from_rule`
# already avoided all three, but a guard inside one function is not an invariant:
# #57 step 3 replaces that function with the parser, and the guard would leave
# with it.


def test_a_schedule_must_carry_something() -> None:
    """The failure this module exists to remove, reachable in one line.

    `Schedule(anchor=Anchor(kind="unanchored"))` used to validate, and
    `Deadline.states_a_backstop` — a pure presence test — then answered True with
    nothing behind it, so a consumer would read the step as "hard date present,
    go check it".
    """
    with pytest.raises(ValidationError, match="must carry something"):
        Schedule(anchor=Anchor(kind="unanchored"))


@pytest.mark.parametrize(
    "build",
    [
        lambda: Schedule(anchor=Anchor(kind="unanchored"), offset=Offset(amount=1)),
        lambda: Schedule(anchor=Anchor(kind="unanchored"), latest_time="07:00"),
        lambda: Schedule(anchor=Anchor(kind="unanchored"), recurrence="täglich"),
        lambda: Schedule(anchor=Anchor(kind="unanchored"), subject="ÜT"),
    ],
    ids=["offset", "cutoff", "recurrence", "subject"],
)
def test_any_single_piece_of_content_is_enough(build: Callable[[], Schedule]) -> None:
    """Each term of the predicate on its own, so none can be dropped unnoticed —
    a term masked by the others is a term no test is really covering."""
    assert build() is not None


def test_a_named_anchor_is_content_by_itself() -> None:
    """The fifth term: an anchor that is not `unanchored` says something even with
    no offset — "spätester ÜT ist zum angegebenen Zahlungsziel"."""
    assert Schedule(anchor=Anchor(kind="external", name="Zahlungsziel")) is not None


def test_time_on_anchor_day_alone_is_not_content() -> None:
    """It qualifies `latest_time` and means nothing without one, so it must not
    keep an otherwise empty Schedule alive."""
    with pytest.raises(ValidationError, match="must carry something"):
        Schedule(anchor=Anchor(kind="unanchored"), time_on_anchor_day=True)


@pytest.mark.parametrize("amount", [0, -1, -61])
def test_an_offset_amount_must_be_positive(amount: int) -> None:
    """`direction` already expresses "before", so a negative amount is a second,
    unvalidated way to say it — and `-5` with `direction="nach"` says both."""
    with pytest.raises(ValidationError):
        Offset(amount=amount)


@pytest.mark.parametrize("value", ["not a time", "99:99", "25:00", "07:60", "", "7:00", "07:00:00"])
def test_a_cutoff_must_be_a_clock_time(value: str) -> None:
    with pytest.raises(ValidationError):
        Schedule(anchor=Anchor(kind="unanchored"), latest_time=value)


@pytest.mark.parametrize("value", ["00:00", "07:00", "23:59", "12:30"])
def test_a_well_formed_cutoff_is_kept_verbatim(value: str) -> None:
    assert Schedule(anchor=Anchor(kind="unanchored"), latest_time=value).latest_time == value


def test_every_shape_the_corpus_has_still_lifts() -> None:
    """The tightening must not reject anything real.

    The fixture is the 15 distinct `deadline_rule` shapes the dataset holds, so
    this is the regression guard for all three validators at once: a constraint
    that excluded a live shape would fail here rather than in a regeneration.
    """
    shapes = json.loads((Path(__file__).parent / "fixtures" / "deadline_rule_shapes.json").read_text("utf-8"))
    assert shapes, "fixture is empty — this would pass vacuously"
    for entry in shapes:
        rule = DeadlineRule(**{k: v for k, v in entry.items() if k != "_where"})
        deadline_from_rule(rule)  # must not raise


def _coverage_shapes() -> list[dict[str, object]]:
    shapes = json.loads((Path(__file__).parent / "fixtures" / "deadline_coverage_shapes.json").read_text("utf-8"))
    assert shapes, "fixture is empty — the assertions below would pass vacuously"
    return shapes


def test_coverage_matches_the_corpus_on_every_verdict_it_produces() -> None:
    """One real rule per distinct coverage verdict, with the reason it was reached.

    `coverage_of` decides between "the structure holds this whole obligation" and "the
    prose says more than the structure holds", and getting it wrong in the optimistic
    direction is the expensive failure: a consumer reads an unconstrained Frist and a
    conformance suite passes it silently.

    A fixture rather than a live read, for the same reason as
    `deadline_rule_shapes.json` — makoralle is public, the dataset is not. Run against the
    whole corpus while porting this from makuna's converter, the verdicts reproduce it
    exactly: 599 lifted deadlines, 355 `complete` / 110 `partial` / 134 `opaque`, and the
    kinds 414 immediate / 104 reference / 30 complex / 28 parallel / 23 scheduled.
    """
    for entry in _coverage_shapes():
        where, expected = entry["_where"], entry["_coverage"]
        rule = DeadlineRule.model_validate({k: v for k, v in entry.items() if not str(k).startswith("_")})
        lifted = deadline_from_rule(rule)
        assert lifted is not None, where
        assert lifted.coverage == expected, f"{where} ({entry['_reason']})"


def test_a_reference_or_complex_alternative_is_always_opaque() -> None:
    """The two kinds that hold nothing checkable, whatever their prose says.

    `reference` is the case that separates "uncheckable" from "needs work": it points at
    another table or a contract, so it can never be evaluated — but nobody can structure
    it either, which is why a worklist must not treat it like `complex`.
    """
    for kind in ("reference", "complex"):
        rule = DeadlineRule(type=kind, business_days=2, reference_step=1, raw="1 WT nach dem ÜT von Nr. 1.")
        lifted = deadline_from_rule(rule)
        assert lifted is not None and lifted.coverage == "opaque", kind


def test_a_cutoff_on_the_anchors_own_day_is_partial() -> None:
    """ "spätester ÜZ ist 15:00 Uhr am ÜT von Nr. 1" — the time belongs to the anchor's day,
    and the flat rule has no slot saying so, so `latest_time` alone reads as "15:00 on the
    offset's day".

    Synthetic, unlike its neighbours: this is the one downgrade reason dataset v0.0.20 does
    not exercise (0 rows). Kept because the construct is legal MaKo prose and the pattern
    is cheap; a corpus that grows one must not silently read as `complete`.
    """
    rule = DeadlineRule(
        type="unverzüglich",
        latest_time="15:00",
        reference_step=1,
        reference_event="ÜT",
        raw="Unverzüglich, jedoch spätester ÜZ ist 15:00 Uhr am ÜT von Nr. 1.",
    )
    lifted = deadline_from_rule(rule)
    assert lifted is not None and lifted.coverage == "partial"


def test_coverage_defaults_to_partial_rather_than_complete() -> None:
    """A hand-built `Deadline` claims nothing about prose it never saw.

    The default is the safe direction on purpose: `complete` is the only verdict that lets
    a consumer act on the structure, so a caller has to say it deliberately.
    """
    assert Deadline(alternatives=[DeadlineAlternative(kind="immediate")], raw="x").coverage == "partial"
