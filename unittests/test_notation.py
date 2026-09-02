"""The Frist notation as a contract, not as a rendering detail.

:mod:`makoralle.notation` draws the tag; makrake's `layout::deadline_tag` draws the same tag
in Rust from the structure alone, and the markdown legend defines the markers beside it.
These tests pin what all three depend on.
"""

import json

from makoralle.models.process import DeadlineRule
from makoralle.notation import deadline_tag, tag_matrix, tag_matrix_json


def test_the_matrix_tag_is_a_function_of_the_deadline() -> None:
    """The precondition that makes the matrix a parity contract at all.

    makuna and makrake never see the flat rule — they get the lifted ``deadline`` and nothing
    else. So if two rules lift to the same structure and this module draws them differently,
    no port can reproduce both, and the difference is a defect on *this* side however the
    other one behaves.

    It has caught two: `terminiert` dropped a direction the lift had already defaulted to
    "nach" (`≤1WT #1` vs `≤1WT nach #1`, 37 shapes), and a `terminiert` rule holding nothing
    structured drew the bare word `{terminiert}` from a flat type its own lift had erased to
    `complex`, which draws no tag.
    """
    tags_by_deadline: dict[str, set[str]] = {}
    rules_by_deadline: dict[str, list[dict[str, object]]] = {}
    for row in tag_matrix():
        key = json.dumps(row["deadline"], sort_keys=True, ensure_ascii=False)
        tags_by_deadline.setdefault(key, set()).add(row["tag"])
        rules_by_deadline.setdefault(key, []).append(row["rule"])
    ambiguous = {key: tags for key, tags in tags_by_deadline.items() if len(tags) > 1}
    assert not ambiguous, "\n".join(
        f"{sorted(tags)} both drawn for {key} — from {rules_by_deadline[key]}" for key, tags in ambiguous.items()
    )


def test_the_matrix_reaches_every_obligation_kind_and_every_tag_form() -> None:
    """A matrix that missed a kind would report parity it never tested."""
    rows = tag_matrix()
    kinds = {alt["kind"] for row in rows for alt in row["deadline"]["alternatives"]}
    assert kinds == {"immediate", "parallel", "scheduled", "reference", "complex"}
    tags = {row["tag"] for row in rows}
    # One representative of each form the legend defines, plus the empty tag prose gets.
    for tag in ("", "u", "u ÜZ#1", "u ≤07:00 1WT nach ÜT#1", "u werktäglich", "∥", "∥#1", "terminiert"):
        assert tag in tags, tag
    assert len(rows) > 1500, len(rows)


def test_a_terminiert_offset_spells_the_direction_the_lift_defaults_to() -> None:
    """Two rules that lift identically must not draw differently.

    ``Offset.direction`` is defaulted, not optional, so a rule that states no direction lifts
    to "nach" — and makrake, which sees only the lift, writes the word. This function used to
    write it only when the flat rule said so.
    """
    stated = DeadlineRule(type="terminiert", business_days=1, reference_step=1, direction="nach", raw="")
    unstated = DeadlineRule(type="terminiert", business_days=1, reference_step=1, raw="")
    assert deadline_tag(stated) == "{≤1WT nach #1}"
    assert deadline_tag(unstated) == deadline_tag(stated)
    # "vor" is still the source's word when the source says it.
    assert deadline_tag(
        DeadlineRule(type="terminiert", business_days=20, anchor="Änderungstermin", direction="vor", raw="")
    ) == ("{≤20WT vor Änderungstermin}")
    # With no anchor the word is dropped: "≤2WT nach" points at nothing.
    assert deadline_tag(DeadlineRule(type="terminiert", business_days=2, raw="")) == "{≤2WT}"


def test_a_terminiert_rule_with_nothing_structured_draws_no_tag() -> None:
    """It lifts to ``complex`` — prose — and the note is where prose belongs.

    The bare word survives for the one `terminiert` shape that *does* structure something and
    still has no date to show: a subject event on its own ("spätester ÜT ist …").
    """
    empty = DeadlineRule(type="terminiert", raw="Zu einem im Vertrag geregelten Termin.")
    assert deadline_tag(empty) == ""
    subject_only = DeadlineRule(type="terminiert", reference_event="ÜT", raw="Spätester ÜT ist …")
    assert deadline_tag(subject_only) == "{terminiert}"


def test_the_matrix_json_is_one_row_per_line_and_stable() -> None:
    """What makes a refresh of the vendored fixture reviewable.

    Sorted keys and no incidental whitespace, so the same notation always produces the same
    bytes; one row per line, so a diff names the shapes that changed rather than the file.
    """
    first, second = tag_matrix_json(), tag_matrix_json()
    assert first == second
    lines = first.splitlines()
    assert lines[0] == "[" and lines[-1] == "]"
    assert len(lines) == len(tag_matrix()) + 2
    rows = json.loads(first)
    assert rows == tag_matrix()
    assert all(set(row) == {"rule", "deadline", "tag"} for row in rows)
