"""The structured Frist, and the lift from the flat rule (makoralle#57)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from makoralle.models.deadline import (
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


def test_recurring_without_a_word_for_it_reads_as_täglich() -> None:
    """`recurring: True` predates the `recurrence` field. "täglich" is the only reading that
    does not invent a weekday restriction the source may not impose — the same defect
    makorele#101 records in the other direction."""
    d = deadline_from_rule(DeadlineRule(type="unverzüglich", recurring=True, raw="Täglich."))
    assert d is not None and d.alternatives[0].backstop is not None
    assert d.alternatives[0].backstop.recurrence == "täglich"
    werktäglich = deadline_from_rule(
        DeadlineRule(type="unverzüglich", recurring=True, recurrence="werktäglich", raw="Werktäglich.")
    )
    assert werktäglich is not None and werktäglich.alternatives[0].backstop is not None
    assert werktäglich.alternatives[0].backstop.recurrence == "werktäglich"


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
