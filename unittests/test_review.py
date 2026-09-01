"""The "Prüfung nötig" worklist, derived from the model (replaces the `.wsd` `[REVIEW]` grep)."""

from typing import Any

from makoralle.review import REVIEW_MARKER, Severity, is_actionable, review_items


def _diagram(*steps: dict[str, Any], notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"participants": ["LF", "NB"], "steps": list(steps), "notes": notes or []}


def _step(nr: int = 1, **over: Any) -> dict[str, Any]:
    return {"nr": nr, "sender": "LF", "receiver": "NB", "message": "Anmeldung", **over}


def test_a_step_with_nothing_wrong_earns_no_entry() -> None:
    """The list is a worklist, not an inventory: a readable step with a fully structured
    Frist has nothing anyone needs to do about it."""
    step = _step(deadline_rule={"type": "unverzüglich", "raw": "Unverzüglich."})
    assert review_items(_diagram(step)) == []


def test_an_unstructured_frist_is_work_a_human_can_do() -> None:
    """`complex` is prose nobody has reduced yet — the entry the old `[REVIEW]` note carried,
    now with the step number a note could not hold."""
    step = _step(nr=4, deadline_rule={"type": "complex", "raw": "Gemäß  irgendwas\nmit Umbruch."})
    (item,) = review_items(_diagram(step))
    assert (item.kind, item.severity, item.step) == ("deadline_unstructured", Severity.STRUCTURE, 4)
    # Whitespace collapsed, so a multi-line `raw` reads as one line in the webapp's list.
    assert item.text == "Gemäß irgendwas mit Umbruch."


def test_a_reference_frist_is_uncheckable_but_not_a_task() -> None:
    """The case that separates the two severities.

    A `reference` Frist points at another table or a contract: no amount of parsing makes it
    checkable, so it must not sit on a human's list asking for work that cannot be done. Its
    coverage is `opaque`, exactly like `complex` — which is why this list reads the kind too,
    and why coverage alone cannot build it.
    """
    step = _step(deadline_rule={"type": "reference", "raw": "Gemäß Rahmenvertrag."})
    (item,) = review_items(_diagram(step))
    assert (item.kind, item.severity) == ("deadline_reference", Severity.UNCHECKABLE)


def test_a_partially_structured_frist_is_reported_rather_than_passed_silently() -> None:
    """The population the old worklist could not see at all.

    "Unverzüglich, jedoch spätestens bis zum Ablauf des 3. WT nach Eingang" states a hard
    date that no structured field holds. The old build emitted no note for it, so it reached
    nobody; a conformance suite evaluating the structure alone would check a weaker
    obligation than the regulation imposes and pass.
    """
    step = _step(
        deadline_rule={
            "type": "unverzüglich",
            "raw": "Unverzüglich, jedoch spätestens bis zum Ablauf des 3. WT nach Eingang der Abmeldung.",
        }
    )
    (item,) = review_items(_diagram(step))
    assert (item.kind, item.severity) == ("deadline_partial", Severity.UNCHECKABLE)


def test_an_unread_endpoint_is_a_defect_in_the_data() -> None:
    """Not a property of the process: fixing it means re-parsing or hand-correcting, which is
    why it outranks everything else on the list."""
    one = review_items(_diagram(_step(nr=2, receiver="?")))
    assert [(i.kind, i.severity, i.step) for i in one] == [("endpoint_unread", Severity.DEFECT, 2)]
    assert one[0].text == "Anmeldung — Gegenstelle ungelesen"

    both = review_items(_diagram(_step(nr=3, sender="?", receiver="?")))
    assert [(i.kind, i.severity) for i in both] == [("endpoints_unread", Severity.DEFECT)]
    assert both[0].text == "Anmeldung — beide Endpunkte ungelesen"


def test_the_missing_side_is_not_named() -> None:
    """Deliberately "Gegenstelle" rather than "Empfänger": when two identically labelled
    lifelines collapse into one, which endpoint keeps the surviving role is arbitrary, so
    naming the missing side would state a direction the data cannot support."""
    for step in (_step(sender="?"), _step(receiver="?")):
        (item,) = review_items(_diagram(step))
        assert item.text.endswith("— Gegenstelle ungelesen")


def test_a_diagram_the_pipeline_could_not_split_is_a_diagram_level_defect() -> None:
    """makorele flags a contaminated SD with a note carrying the marker. It has no step, and
    the marker itself is not shown to a reader."""
    note = {"position": "over", "participants": ["LF"], "text": f"Mehrere Diagramme {REVIEW_MARKER}"}
    (item,) = review_items(_diagram(notes=[note]))
    assert (item.kind, item.severity, item.step) == ("diagram_unsplit", Severity.DEFECT, None)
    assert item.text == "Mehrere Diagramme"


def test_an_ordinary_note_is_not_a_worklist_entry() -> None:
    assert review_items(_diagram(notes=[{"text": "Nur ein Hinweis", "participants": ["LF"]}])) == []


def test_entries_are_ordered_most_actionable_first_and_stably() -> None:
    """Severity first, then step number. Stable because this list is serialized into the
    dataset repo's `webapp/`, and an unordered one would churn on every rebuild."""
    items = review_items(
        _diagram(
            _step(nr=1, deadline_rule={"type": "reference", "raw": "Gemäß Vertrag."}),
            _step(nr=2, deadline_rule={"type": "complex", "raw": "Irgendwas."}),
            _step(nr=3, receiver="?"),
            _step(nr=4, deadline_rule={"type": "reference", "raw": "Gemäß Anlage."}),
        )
    )
    assert [(i.severity, i.step) for i in items] == [
        (Severity.DEFECT, 3),
        (Severity.STRUCTURE, 2),
        (Severity.UNCHECKABLE, 1),
        (Severity.UNCHECKABLE, 4),
    ]


def test_one_step_can_earn_two_entries() -> None:
    """An unplaceable step with an unstructured Frist has two independent problems, and
    collapsing them would hide whichever was reported second."""
    step = _step(nr=1, sender="?", receiver="?", deadline_rule={"type": "complex", "raw": "Frist X."})
    assert [i.kind for i in review_items(_diagram(step))] == ["endpoints_unread", "deadline_unstructured"]


def test_a_frist_the_source_does_not_state_earns_nothing() -> None:
    """`type: "none"` means there is no Frist, which is not a gap in the parse."""
    assert review_items(_diagram(_step(deadline_rule={"type": "none", "raw": "--"}))) == []


def test_an_empty_diagram_is_not_an_error() -> None:
    assert review_items({}) == []


def test_only_a_defect_or_unstructured_prose_is_somebody_s_task() -> None:
    """What the webapp's "Prüfung nötig" flag has to mean.

    Every `uncheckable` item is "review needed" by the letter of the words, and a flag
    counting them is on for 120 of the corpus's 196 processes while 21 have work to do — a
    flag that is on for everything says nothing. Measured on dataset v0.0.20, the 21 match
    the processes the old `[REVIEW]`-grep flagged, which is the behaviour to preserve.
    """
    reference = _diagram(_step(deadline_rule={"type": "reference", "raw": "Gemäß Vertrag."}))
    assert review_items(reference) and not is_actionable(review_items(reference))

    partial = _diagram(
        _step(deadline_rule={"type": "unverzüglich", "raw": "Unverzüglich, jedoch spätestens bis zum 3. WT."})
    )
    assert review_items(partial) and not is_actionable(review_items(partial))

    for actionable in (
        _diagram(_step(deadline_rule={"type": "complex", "raw": "Irgendwas."})),
        _diagram(_step(receiver="?")),
    ):
        assert is_actionable(review_items(actionable))


def test_an_empty_worklist_is_not_actionable() -> None:
    assert not is_actionable([])
