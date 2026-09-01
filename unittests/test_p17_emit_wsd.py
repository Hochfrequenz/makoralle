import logging
from typing import Literal

import pytest

from makoralle.models.deadline import Anchor, Deadline, DeadlineAlternative, Offset, Schedule
from makoralle.models.process import DeadlineRule, SDBranch, SDFragment, SDNote, SDStep, SequenceDiagram
from makoralle.serialization.wsd import (
    _alternative_core,
    _deadline_note,
    _deadline_tag,
    _tag_of,
    _unverzueglich_sentence_beyond_the_tag,
    emit_wsd,
)
from makoralle.webapp_export import extract_review_notes

AlternativeKind = Literal["immediate", "parallel", "scheduled", "reference", "complex"]


def _step_with_deadline(rule: DeadlineRule) -> SDStep:
    return SDStep(nr=1, sender="LF", receiver="NB", message="Foo", deadline_rule=rule)


def test_deadline_note_complex_keeps_review_flag() -> None:
    note = _deadline_note(_step_with_deadline(DeadlineRule(type="complex", raw="Gemäß irgendwas.")), ["LF", "NB"])
    assert note == "note right of NB: (!) Frist: Gemäß irgendwas.  [REVIEW]"


def test_deadline_note_reference_is_info_without_review_flag() -> None:
    """A 'reference' deadline (real but irreducible) stays a note, but with an (i)
    marker and NO [REVIEW] — so extract_review_notes never pulls it into review."""
    note = _deadline_note(_step_with_deadline(DeadlineRule(type="reference", raw="Gemäß Rahmenvertrag.")), ["LF", "NB"])
    assert note == "note right of NB: (i) Frist: Gemäß Rahmenvertrag."
    assert "[REVIEW]" not in note


def test_deadline_note_terminiert_and_structured_get_no_note() -> None:
    """A deadline its tag carries in full produces no note.

    `unverzüglich` used to be unconditional here and no longer is: the type is in the list only
    while its tag says everything the sentence does — a bare "Unverzüglich." or a row whose tag
    states the bound. Where the sentence says more, the note is the point (makorele#101);
    `test_deadline_note_lossy_unverzueglich_gets_its_sentence` is that case.
    """
    for t in ("terminiert", "parallel", "none"):
        assert _deadline_note(_step_with_deadline(DeadlineRule(type=t, raw="x")), ["LF", "NB"]) is None
    # the sentence is the marker word and nothing else, so `{u}` already says it
    assert (
        _deadline_note(_step_with_deadline(DeadlineRule(type="unverzüglich", raw="Unverzüglich.")), ["LF", "NB"])
        is None
    )
    # the tag carries the bound, so the note would repeat the arrow — one case per disjunct of the
    # guard, because a fixture setting two of them lets each hide the other. `reference_step` is
    # NOT among them since #59: with no offset those fields are the immediacy anchor, not a
    # bound, so the tag states no bound and the note is what carries it —
    # `test_deadline_note_fires_when_the_tag_states_no_bound` is that case.
    for kwargs in ({"business_days": 1}, {"latest_time": "15:00"}):
        structured = DeadlineRule(type="unverzüglich", raw="Unverzüglich nach Nr. 2.", **kwargs)
        assert _unverzueglich_sentence_beyond_the_tag(structured) == ""
        assert _deadline_note(_step_with_deadline(structured), ["LF", "NB"]) is None


def test_a_recurrence_alone_is_not_a_bound_and_still_earns_its_note() -> None:
    """`Deadline.states_a_backstop` answers True for a schedule holding nothing but a recurrence,
    which is the right answer to the model's question and the wrong one for the arrow: no `≤`
    reaches the label, so the sentence is still the only place a bound could be.

    A draft of #59 keyed the note on `states_a_backstop` and lost "nach Nr. 2" from the tag *and*
    the note on this shape — a strict regression against the old `{u}` plus note. No v0.0.20 row
    reaches it (all 6 recurring rows on the 906 basis are `terminiert`), which is exactly why it
    needs a test rather than a corpus run.
    """
    rule = DeadlineRule(type="unverzüglich", recurring=True, raw="Unverzüglich nach Nr. 2.")
    assert _deadline_tag(rule) == "{u täglich}"
    assert _unverzueglich_sentence_beyond_the_tag(rule) == "nach Nr. 2"
    assert _deadline_note(_step_with_deadline(rule), ["LF", "NB"]) == (
        "note right of NB: (i) Frist: Unverzüglich nach Nr. 2."
    )
    # a recurrence beside a real bound is different: the `≤` is on the arrow, so no note
    bounded = DeadlineRule(type="unverzüglich", recurring=True, latest_time="14:00", raw="Unverzüglich nach Nr. 2.")
    assert _deadline_tag(bounded) == "{u täglich ≤14:00}"
    assert _unverzueglich_sentence_beyond_the_tag(bounded) == ""


def test_deadline_note_fires_when_the_tag_states_no_bound() -> None:
    """#59: an `unverzüglich` whose fields describe the immediacy anchor states no bound, so the
    sentence — where the bound and any condition actually live — becomes a note.

    `abrechnung_einer_für_den_esa_erbrachten_leistung` nr 2 verbatim, one of the 27 rows at
    dataset v0.0.20 whose tag carried an anchor and nothing else; before #59 the guard bailed on
    `reference_step` and the bound was lost from both the arrow and the diagram.
    """
    rule = DeadlineRule(
        type="unverzüglich",
        reference_step=1,
        reference_event="ÜZ",
        raw="Unverzüglich nach dem ÜZ von Nr. 1, jedoch spätester ÜT ist der 4. WT vor dem "
        "Zahlungsziel in der Rechnung.",
    )
    assert _deadline_tag(rule) == "{u ÜZ#1}"
    assert _unverzueglich_sentence_beyond_the_tag(rule).startswith("nach dem ÜZ von Nr. 1, jedoch spätester ÜT")
    # unflagged (i), like `reference`: the sentence is readable and real, just not compact
    assert _deadline_note(_step_with_deadline(rule), ["LF", "NB"]) == (
        "note right of NB: (i) Frist: Unverzüglich nach dem ÜZ von Nr. 1, jedoch spätester ÜT "
        "ist der 4. WT vor dem Zahlungsziel in der Rechnung."
    )


def test_emit_flat() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung", format="UTILMD"),
            SDStep(nr=2, sender="NB", receiver="LF", message="Antwort", ebd_ref="E_0401"),
        ],
    )
    out = emit_wsd(sd, title="Lieferbeginn")
    lines = out.splitlines()
    assert "title Lieferbeginn" in lines
    # step number prefixed on every message
    assert "LF->>NB: 1. Anmeldung (UTILMD)" in lines
    assert "NB->>LF: 2. Antwort [E_0401]" in lines


def test_emit_opt() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="A"),
            SDStep(nr=2, sender="NB", receiver="LF", message="B"),
            SDStep(nr=3, sender="LF", receiver="NB", message="C"),
        ],
        fragments=[SDFragment(type="opt", branches=[SDBranch(condition="Fehler", step_nrs=[2])])],
    )
    lines = emit_wsd(sd).splitlines()
    assert lines.index("opt Fehler") < lines.index("NB->>LF: 2. B") < lines.index("end")
    # step 3 is outside the opt
    assert lines.index("end") < lines.index("LF->>NB: 3. C")


def test_emit_alt_with_else() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="Req"),
            SDStep(nr=2, sender="NB", receiver="LF", message="OK"),
            SDStep(nr=3, sender="NB", receiver="LF", message="Reject"),
        ],
        fragments=[
            SDFragment(
                type="alt",
                branches=[
                    SDBranch(condition="Zustimmung", step_nrs=[2]),
                    SDBranch(condition="Ablehnung", step_nrs=[3]),
                ],
            )
        ],
    )
    out = emit_wsd(sd)
    lines = out.splitlines()
    assert "alt Zustimmung" in lines
    assert "else Ablehnung" in lines
    assert out.count("end") == 1  # one fragment, closed once
    assert (
        lines.index("alt Zustimmung")
        < lines.index("NB->>LF: 2. OK")
        < lines.index("else Ablehnung")
        < lines.index("NB->>LF: 3. Reject")
        < lines.index("end")
    )


def test_sdstep_default_arrowhead_is_open() -> None:
    """Most arrows are open; filled is reserved for sync-call requests (derived later)."""
    s = SDStep(nr=1, sender="LF", receiver="NB", message="x")
    assert s.line == "solid"
    assert s.arrowhead == "open"


def test_emit_arrow_styles() -> None:
    """line/arrowhead compose orthogonally onto WSD arrow tokens."""
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            # default: solid line, open head -> "->>"
            SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung"),
            # UML reply: dashed line, open head -> "-->>"
            SDStep(nr=2, sender="NB", receiver="LF", message="Antwort", line="dashed", arrowhead="open"),
            # dashed line, filled head -> "-->"
            SDStep(nr=3, sender="LF", receiver="NB", message="C", line="dashed", arrowhead="filled"),
            # sync call: solid line, filled head -> "->"
            SDStep(nr=4, sender="NB", receiver="LF", message="D", line="solid", arrowhead="filled"),
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "LF->>NB: 1. Anmeldung" in lines
    assert "NB-->>LF: 2. Antwort" in lines
    assert "LF-->NB: 3. C" in lines
    assert "NB->LF: 4. D" in lines


def test_emit_arrow_style_on_self_ref() -> None:
    """A dashed/open 'ref' self-message still honours the arrow style."""
    sd = SequenceDiagram(
        participants=["NB"],
        steps=[SDStep(nr=1, sender="NB", receiver="NB", message="ref Subprozess", line="dashed", arrowhead="open")],
    )
    lines = emit_wsd(sd).splitlines()
    assert "NB-->>NB: 1. ref Subprozess" in lines


def test_emit_nested_fragment() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=i, sender="LF", receiver="NB", message=f"M{i}") for i in (1, 2, 3)],
        fragments=[
            SDFragment(
                type="opt",
                label=None,
                branches=[
                    SDBranch(
                        condition="outer",
                        step_nrs=[1],
                        fragments=[
                            SDFragment(type="loop", label="3x", branches=[SDBranch(step_nrs=[2])]),
                        ],
                    ),
                ],
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert lines.index("opt outer") < lines.index("loop 3x") < lines.index("LF->>NB: 2. M2")
    assert lines.count("end") == 2
    # step 3 is fully outside both
    assert lines.index("LF->>NB: 3. M3") == len(lines) - 1


def test_emit_note() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="LF", receiver="NB", message="A")],
        notes=[SDNote(position="over", participants=["LF", "NB"], text="Wichtig", after_step=1)],
    )
    assert "note over LF,NB: Wichtig" in emit_wsd(sd).splitlines()


def test_emit_unanchored_note_rendered() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="LF", receiver="NB", message="A")],
        notes=[SDNote(position="over", participants=["LF", "NB"], text="Allgemein", after_step=None)],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over LF,NB: Allgemein" in lines
    # rendered before the first message
    assert lines.index("note over LF,NB: Allgemein") < lines.index("LF->>NB: 1. A")


def test_emit_alt_empty_first_branch_keeps_condition() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="NB", receiver="LF", message="Reject")],
        fragments=[
            SDFragment(
                type="alt",
                branches=[
                    SDBranch(condition="Zustimmung", step_nrs=[]),  # empty first branch
                    SDBranch(condition="Ablehnung", step_nrs=[1]),
                ],
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "alt Zustimmung" in lines
    assert "else Ablehnung" in lines
    assert lines.index("alt Zustimmung") < lines.index("else Ablehnung") < lines.index("NB->>LF: 1. Reject")


def test_emit_alt_trailing_empty_branch_keeps_condition() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="NB", receiver="LF", message="OK")],
        fragments=[
            SDFragment(
                type="alt",
                branches=[
                    SDBranch(condition="Zustimmung", step_nrs=[1]),
                    SDBranch(condition="Ablehnung", step_nrs=[]),  # empty trailing branch
                ],
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert (
        lines.index("alt Zustimmung")
        < lines.index("NB->>LF: 1. OK")
        < lines.index("else Ablehnung")
        < lines.index("end")
    )


def test_emit_note_empty_participants_skipped() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="LF", receiver="NB", message="A")],
        notes=[SDNote(position="over", participants=[], text="Leer", after_step=1)],
    )
    lines = emit_wsd(sd).splitlines()
    # no dangling "note over : text" line (nothing before the colon)
    for line in lines:
        if line.startswith("note "):
            head = line.split(":", 1)[0]  # e.g. "note over LF,NB"
            assert head.strip() != "note over", f"dangling note line: {line!r}"


def test_emit_par_fragment() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="A"),
            SDStep(nr=2, sender="NB", receiver="LF", message="B"),
        ],
        fragments=[
            SDFragment(
                type="par",
                label="parallel",
                branches=[
                    SDBranch(step_nrs=[1, 2]),
                ],
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert (
        lines.index("par parallel") < lines.index("LF->>NB: 1. A") < lines.index("NB->>LF: 2. B") < lines.index("end")
    )


def test_emit_par_uses_branch_condition_when_no_label() -> None:
    # par regions store their text in branch.condition (label is None); the opening
    # `par` line must show it (it was being dropped, unlike loop's cond fallback).
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="A"),
            SDStep(nr=2, sender="NB", receiver="LF", message="B"),
        ],
        fragments=[
            SDFragment(
                type="par",
                label=None,
                branches=[
                    SDBranch(condition="Immer, gegenüber LFN durchführen", step_nrs=[1]),
                    SDBranch(condition="gegenüber LFA durchführen", step_nrs=[2]),
                ],
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "par Immer, gegenüber LFN durchführen" in lines  # first branch on the par line
    assert "else gegenüber LFA durchführen" in lines  # second branch keeps its text


def test_emit_golden_string() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung", format="UTILMD"),
            SDStep(nr=2, sender="NB", receiver="LF", message="Antwort", ebd_ref="E_0401"),
        ],
    )
    expected = (
        "title Lieferbeginn\n"
        "# style: roundgreen\n"
        "participant LF\n"
        "participant NB\n"
        "LF->>NB: 1. Anmeldung (UTILMD)\n"
        "NB->>LF: 2. Antwort [E_0401]"
    )
    assert emit_wsd(sd, title="Lieferbeginn") == expected


def test_emit_alt_intermediate_empty_branch_keeps_condition() -> None:
    # 3-branch alt where the MIDDLE branch is empty; steps in branches 0 and 2.
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="First"),
            SDStep(nr=2, sender="NB", receiver="LF", message="Third"),
        ],
        fragments=[
            SDFragment(
                type="alt",
                branches=[
                    SDBranch(condition="A", step_nrs=[1]),
                    SDBranch(condition="B", step_nrs=[]),  # intermediate empty branch
                    SDBranch(condition="C", step_nrs=[2]),
                ],
            )
        ],
    )
    out = emit_wsd(sd)
    lines = out.splitlines()
    assert out.count("end") == 1
    assert out.count("else") == 2  # one else per non-first branch, no duplicates
    assert (
        lines.index("alt A")
        < lines.index("LF->>NB: 1. First")
        < lines.index("else B")
        < lines.index("else C")
        < lines.index("NB->>LF: 2. Third")
        < lines.index("end")
    )


def test_emit_note_left_right_placement() -> None:
    # websequencediagrams requires "left of"/"right of", not bare "left"/"right".
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="LF", receiver="NB", message="A")],
        notes=[
            SDNote(position="left", participants=["LF"], text="L", after_step=1),
            SDNote(position="right", participants=["NB"], text="R", after_step=1),
            SDNote(position="over", participants=["LF", "NB"], text="O", after_step=1),
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note left of LF: L" in lines
    assert "note right of NB: R" in lines
    assert "note over LF,NB: O" in lines


def test_emit_ref_step_as_self_arrow_on_sender() -> None:
    # A "ref ..." step is a self-referenced subprocess on the sender's lifeline,
    # rendered as a self-message arrow (sender->sender) — NOT the Vision-guessed
    # receiver. So an NB->>LFA "ref" becomes NB->>NB.
    sd = SequenceDiagram(
        participants=["LF", "NB", "LFA"],
        steps=[
            SDStep(nr=10, sender="LF", receiver="NB", message="Anmeldung"),
            SDStep(nr=11, sender="NB", receiver="LFA", message="ref Abrechnungsdaten Netznutzungsabrechnung"),
        ],
    )
    lines = emit_wsd(sd).splitlines()
    # self-loop on the sender (NB), keeping the source "ref ..." label
    assert "NB->>NB: 11. ref Abrechnungsdaten Netznutzungsabrechnung" in lines
    assert not any(line.startswith("NB->>LFA:") for line in lines)
    # normal message still numbered
    assert "LF->>NB: 10. Anmeldung" in lines


def test_emit_ref_step_self_reference() -> None:
    sd = SequenceDiagram(
        participants=["NB", "LF"],
        steps=[SDStep(nr=5, sender="NB", receiver="NB", message="ref Stammdatenänderung")],
    )
    lines = emit_wsd(sd).splitlines()
    assert "NB->>NB: 5. ref Stammdatenänderung" in lines


def test_emit_step_renders_pid_refs() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung", format="UTILMD", pid_refs=[17115]),
            SDStep(nr=2, sender="NB", receiver="LF", message="Übersicht", format="UTILTS", pid_refs=[25004, 25006]),
            SDStep(nr=3, sender="LF", receiver="NB", message="Liste", pid_refs=[31001]),  # PID, no format
            SDStep(nr=4, sender="NB", receiver="LF", message="Antwort", format="APERAK"),  # format only (unchanged)
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "LF->>NB: 1. Anmeldung (UTILMD 17115)" in lines
    assert "NB->>LF: 2. Übersicht (UTILTS 25004/25006)" in lines  # multiple PIDs slash-joined
    assert "LF->>NB: 3. Liste (PID 31001)" in lines  # no format -> labeled PID
    assert "NB->>LF: 4. Antwort (APERAK)" in lines  # format-only unchanged


def test_deadline_tag_none_and_complex_are_empty() -> None:
    assert _deadline_tag(None) == ""
    assert _deadline_tag(DeadlineRule(type="none", raw="")) == ""
    # complex gets a note elsewhere, never an inline tag
    assert _deadline_tag(DeadlineRule(type="complex", raw="spätestens 5 WT vor X")) == ""


def test_deadline_tag_bare_unverzueglich() -> None:
    assert _deadline_tag(DeadlineRule(type="unverzüglich", raw="Unverzüglich")) == "{u}"


def test_deadline_tag_parallel() -> None:
    assert _deadline_tag(DeadlineRule(type="parallel", reference_step=2, raw="Parallel zu Nr. 2")) == "{∥#2}"
    assert _deadline_tag(DeadlineRule(type="parallel", raw="Parallel")) == "{∥}"


def test_deadline_tag_unverzueglich_keeps_the_u_and_marks_the_bound() -> None:
    """#59: the obligation leads, the bound follows it.

    Every one of these used to drop the `u` — the old code built the tag from whichever
    structured fields were set and fell back to `{u}` only when none were, so 175 of the 414
    `unverzüglich` rows at dataset v0.0.20 rendered an arrow that no longer said "unverzüglich".
    """
    rule = DeadlineRule(
        type="unverzüglich", latest_time="07:00", business_days=1, reference_event="ÜZ", reference_step=5, raw="..."
    )
    assert _deadline_tag(rule) == "{u ≤07:00 1WT nach ÜZ#5}"
    # an offset means the fields are the BOUND and the promptness duty is unanchored
    # (`abrechnungsdaten_bilanzkreisabrechnung` nr 2, "Unverzüglich, jedoch spätester ÜT ist der
    # 2. WT nach dem ÜT von Nr. 1.")
    with_offset = DeadlineRule(type="unverzüglich", business_days=2, reference_event="ÜT", reference_step=1, raw="...")
    assert _deadline_tag(with_offset) == "{u ≤2WT nach ÜT#1}"
    # no offset means they are the immediacy ANCHOR, so no `≤` — the same two fields, read the
    # other way round, which is the disambiguation `deadline_from_rule` owns
    assert _deadline_tag(DeadlineRule(type="unverzüglich", reference_event="ÜT", reference_step=1, raw="...")) == (
        "{u ÜT#1}"
    )
    # only a reference step, no clock/event
    assert _deadline_tag(DeadlineRule(type="unverzüglich", reference_step=5, raw="...")) == "{u #5}"
    # business days only: the direction is dropped with no anchor to point at, since "≤3WT nach"
    # reads as a truncation
    assert _deadline_tag(DeadlineRule(type="unverzüglich", business_days=3, raw="...")) == "{u ≤3WT}"
    # a clock with no offset is a bound too
    assert _deadline_tag(DeadlineRule(type="unverzüglich", latest_time="15:00", raw="...")) == "{u ≤15:00}"
    # "vor" survives where the source states it
    vor = DeadlineRule(type="unverzüglich", business_days=4, direction="vor", reference_step=1, raw="...")
    assert _deadline_tag(vor) == "{u ≤4WT vor #1}"
    # a recurrence prefixes the bound rather than replacing it — `_terminiert_core` does replace,
    # and is left alone with the rest of `terminiert`
    recurring = DeadlineRule(type="unverzüglich", recurring=True, recurrence="werktäglich", latest_time="14:00", raw="")
    assert _deadline_tag(recurring) == "{u werktäglich ≤14:00}"


def test_deadline_tag_unverzueglich_leaves_a_prose_anchor_to_the_note() -> None:
    """An external anchor is prose — 63 characters for one of them in the corpus — so it stays
    off the arrow and the note carries the whole sentence instead."""
    rule = DeadlineRule(type="unverzüglich", anchor="Kenntnisnahme des Sachverhalts", raw="Unverzüglich nach Kenntnis.")
    assert _deadline_tag(rule) == "{u}"
    assert _unverzueglich_sentence_beyond_the_tag(rule) == "nach Kenntnis"


def test_alternative_core_renders_the_shape_the_parser_will_fill() -> None:
    """The parts of `Deadline` no flat rule can produce, which line coverage does not reach.

    `deadline_from_rule` yields exactly one alternative, one step per anchor and only Werktage
    on all 1601 rules at dataset v0.0.20, so every branch below runs in its trivial shape when
    driven off a `DeadlineRule` — the join with one element, the "/" with one step, the unit
    lookup with "werktage". They are here for makoralle#57 step 3, and pinned now so the shape
    is a decision rather than whatever falls out later.
    """
    # BOTH an immediacy anchor and a bound, which is the pairing the flat rule cannot express
    # at all and the whole reason `Deadline` exists: "unverzüglich nach dem ÜZ von Nr. 1, jedoch
    # spätester ÜT ist der 2. WT nach dem ÜT von Nr. 3". The obligation and what it is measured
    # from come first, then the bound — the order matters, since "u ≤2WT nach ÜT#3 ÜZ#1" would
    # read as one bound with two anchors.
    assert (
        _alternative_core(
            DeadlineAlternative(
                kind="immediate",
                immediacy=Anchor(kind="step", steps=[1], event="ÜZ"),
                backstop=Schedule(
                    anchor=Anchor(kind="step", steps=[3], event="ÜT"), offset=Offset(amount=2), subject="ÜT"
                ),
            )
        )
        == "u ÜZ#1 ≤2WT nach ÜT#3"
    )
    # a disjunctive anchor: "Nr. 3 bzw. 4", which a single `reference_step` cannot hold
    assert (
        _alternative_core(
            DeadlineAlternative(kind="immediate", immediacy=Anchor(kind="step", steps=[3, 4], event="ÜZ"))
        )
        == "u ÜZ#3/4"
    )
    # a unit that is not Werktage: `einrichtung_der_konfigurationen…` nr 2 says "jedoch spätester
    # ÜZ ist 1 Stunde nach dem ÜZ von Nr. 1", which the flat rule does not misreport but simply
    # drops — it leaves `business_days` None, so the tag is `{u}` and only the note carries it
    stunden = DeadlineAlternative(
        kind="scheduled",
        backstop=Schedule(anchor=Anchor(kind="step", steps=[1], event="ÜZ"), offset=Offset(amount=1, unit="stunden")),
    )
    # A `scheduled` alternative renders its bound. This used to assert `""` — pinning the gap a
    # later review found: `_deadline_tag` never builds one (it routes `terminiert` to
    # `_terminiert_core` first), but `_tag_of` is the entry point makoralle#57 step 3 will call
    # directly, and a `scheduled` deadline arriving there rendered no tag at all.
    assert _alternative_core(stunden) == "≤1h nach ÜZ#1"
    assert _alternative_core(DeadlineAlternative(kind="immediate", backstop=stunden.backstop)) == "u ≤1h nach ÜZ#1"
    # a coupling renders the step and nothing else: "Parallel zu Nr. 3" is not "by Nr. 3", so a
    # `≤` here would assert a hard date the source never stated
    assert (
        _alternative_core(
            DeadlineAlternative(
                kind="parallel",
                immediacy=Anchor(kind="step", steps=[2]),
                backstop=Schedule(anchor=Anchor(kind="unanchored"), latest_time="14:00"),
            )
        )
        == "∥#2"
    )
    # and it finds its step wherever `deadline_from_rule` filed it — under `backstop` once an
    # offset is present, since that disambiguation was verified for `unverzüglich`, not for
    # `parallel`
    assert (
        _alternative_core(
            DeadlineAlternative(
                kind="parallel",
                immediacy=Anchor(kind="unanchored"),
                backstop=Schedule(anchor=Anchor(kind="step", steps=[3]), offset=Offset(amount=2)),
            )
        )
        == "∥#3"
    )
    # a recurrence prefixes the bound rather than replacing it — an earlier draft returned the
    # recurrence alone here and discarded the offset with its anchor
    assert (
        _alternative_core(
            DeadlineAlternative(
                kind="immediate",
                backstop=Schedule(
                    anchor=Anchor(kind="step", steps=[3], event="ÜZ"),
                    offset=Offset(amount=2),
                    recurrence="täglich",
                ),
            )
        )
        == "u täglich ≤2WT nach ÜZ#3"
    )
    # a unit outside the Literal renders spelled out rather than taking the serializer down
    assert (
        _alternative_core(
            DeadlineAlternative(
                kind="immediate",
                backstop=Schedule(
                    anchor=Anchor(kind="unanchored"),
                    offset=Offset.model_construct(amount=3, unit="monate", direction="nach"),
                ),
            )
        )
        == "u ≤3monate"
    )
    # prose branches carry nothing compact; `_deadline_note` is where they surface
    for kind in ("reference", "complex"):
        assert _alternative_core(DeadlineAlternative(kind=kind)) == ""


def test_no_field_combination_renders_less_than_the_flat_tag_did() -> None:
    """The shapes a review found silently dropping what the old tag showed.

    None occurs at dataset v0.0.20 — all 28 `parallel` rules on the 906 basis carry only
    `reference_step`, and 0 of the 414 `unverzüglich` rules set `anchor` — but the upstream is a
    non-deterministic Vision stage, so "no row does" is not a reason to lose a field.
    """
    # a coupling whose step arrives with an anchor name: `deadline_from_rule` files the step as
    # `established_by`, and for a coupling that step IS what the source named
    coupled = DeadlineRule(type="parallel", reference_step=3, anchor="Zahlungsziel", raw="Parallel zu Nr. 3.")
    assert _deadline_tag(coupled) == "{∥#3}"
    # ... and one carrying an offset keeps its step too, with no invented `≤`
    assert _deadline_tag(DeadlineRule(type="parallel", reference_step=3, business_days=2, raw="x")) == "{∥#3}"
    # a recurrence alongside an offset keeps both
    both = DeadlineRule(
        type="unverzüglich", business_days=2, reference_step=3, reference_event="ÜZ", recurring=True, raw="x"
    )
    assert _deadline_tag(both) == "{u täglich ≤2WT nach ÜZ#3}"
    # the `or_establishing_step=False` default: for an `unverzüglich` the step filed as
    # `established_by` says where the anchor's VALUE came from, not what the offset is measured
    # from, so it stays off the arrow — where a coupling renders exactly the same step
    withheld = DeadlineRule(
        type="unverzüglich", reference_step=3, reference_event="ÜT", anchor="Zahlungsziel", raw="Unverzüglich nach X."
    )
    assert _deadline_tag(withheld) == "{u}"
    assert _deadline_note(_step_with_deadline(withheld), ["LF", "NB"]) is not None
    # ... and the same fields typed as a coupling DO render it (the asymmetry, pinned both ways)
    assert _deadline_tag(DeadlineRule(type="parallel", reference_step=3, anchor="Zahlungsziel", raw="x")) == "{∥#3}"
    # a coupling is tied to a step, not to one of its transmission events
    assert _deadline_tag(DeadlineRule(type="parallel", reference_step=3, reference_event="ÜT", raw="x")) == "{∥#3}"
    # an anchor of kind "event" is prose too, so a clock beside it does not silence the note
    evented = DeadlineRule(
        type="unverzüglich", reference_event="ÜT", latest_time="07:00", raw="Unverzüglich nach dem ÜT, bis 07:00."
    )
    assert _deadline_note(_step_with_deadline(evented), ["LF", "NB"]) is not None
    # a prose anchor reached through the BACKSTOP rather than the immediacy slot: an offset moves
    # it there, and the note has to look in both places
    via_backstop = DeadlineRule(
        type="unverzüglich", anchor="dem Abschluss des Entsperrauftrags", business_days=2, raw="Unverzüglich, 2 WT."
    )
    assert _deadline_tag(via_backstop) == "{u ≤2WT}"
    assert _deadline_note(_step_with_deadline(via_backstop), ["LF", "NB"]) is not None
    # an `unverzüglich` anchored to prose keeps the anchor out of the tag — but the note fires
    # even though the clock is a bound, so the anchor survives somewhere
    prose = DeadlineRule(
        type="unverzüglich",
        anchor="dem Abschluss des Entsperrauftrags",
        latest_time="07:00",
        raw="Unverzüglich, spätestens 07:00 Uhr nach dem Abschluss des Entsperrauftrags.",
    )
    assert _deadline_tag(prose) == "{u ≤07:00}"
    assert _unverzueglich_sentence_beyond_the_tag(prose) == (
        "spätestens 07:00 Uhr nach dem Abschluss des Entsperrauftrags"
    )
    assert _deadline_note(_step_with_deadline(prose), ["LF", "NB"]) is not None


def test_tag_of_never_answers_a_real_deadline_with_silence() -> None:
    """Every alternative kind that carries structure must render something through `_tag_of`.

    `_tag_of` exists so makoralle#57 step 3 can render an `SDStep.deadline` the parser filled,
    without a round trip through the flat rule — so a kind it answers with `""` is an arrow that
    says nothing where the source states a Frist. `scheduled` was exactly that: unreachable from
    a `DeadlineRule` today, because `_deadline_tag` short-circuits `terminiert` before building a
    `Deadline` at all, and therefore invisible to every corpus run and to the exhaustive
    field-combination tests.
    """
    bound = Schedule(anchor=Anchor(kind="step", steps=[2], event="ÜT"), offset=Offset(amount=11), latest_time="14:00")
    carries_structure: list[tuple[AlternativeKind, str]] = [
        ("scheduled", "{≤14:00 11WT nach ÜT#2}"),
        ("immediate", "{u ≤14:00 11WT nach ÜT#2}"),
    ]
    for kind, expected in carries_structure:
        assert _tag_of(Deadline(alternatives=[DeadlineAlternative(kind=kind, backstop=bound)], raw="x")) == expected
    # `reference` and `complex` are the only kinds that may render nothing: they are prose, and
    # `_deadline_note` is what carries them
    prose: list[AlternativeKind] = ["reference", "complex"]
    for prose_kind in prose:
        assert _tag_of(Deadline(alternatives=[DeadlineAlternative(kind=prose_kind)], raw="x")) == ""


def test_terminiert_drops_a_direction_that_points_at_nothing() -> None:
    """`≤2WT nach` is a preposition with no object, which reads as a truncated tag.

    `_bound_core` already refused it; `_terminiert_core` did not, and the two cores disagreeing
    about the same question was the one piece of that divergence fixable without deciding how
    `established_by` should render. 0 of the 23 `terminiert` rows at dataset v0.0.20 set a
    direction with neither a step nor an anchor, so every shipped tag is unchanged.
    """
    assert _deadline_tag(DeadlineRule(type="terminiert", business_days=2, direction="nach", raw="x")) == "{≤2WT}"
    # ... and it is kept wherever it has something to point at
    with_step = DeadlineRule(type="terminiert", business_days=11, direction="nach", reference_step=2, raw="x")
    assert _deadline_tag(with_step) == "{≤11WT nach #2}"


def test_tag_of_joins_every_alternative_of_a_conditional_frist() -> None:
    """A conditional Frist states two obligations, and showing one of them is the same class of
    bug as showing a bound without its obligation.

    The conditions themselves stay off the arrow — "Bei Aufbau der EDIFACT-Kommunikation" is a
    label, not a tag — and `raw` carries them into the note. Unreachable from a `DeadlineRule`
    today: `deadline_from_rule` always yields exactly one alternative.
    """
    deadline = Deadline(
        raw="Bei X gilt: unverzüglich. Bei Y gilt: unverzüglich, jedoch spätester ÜT ist der 2. WT nach Nr. 1.",
        alternatives=[
            DeadlineAlternative(kind="immediate", condition="Bei X", immediacy=Anchor(kind="unanchored")),
            DeadlineAlternative(
                kind="immediate",
                condition="Bei Y",
                backstop=Schedule(anchor=Anchor(kind="step", steps=[1], event="ÜT"), offset=Offset(amount=2)),
            ),
        ],
    )
    assert _tag_of(deadline) == "{u ; u ≤2WT nach ÜT#1}"
    # every alternative prose-only: no tag at all rather than an empty "{}"
    assert _tag_of(Deadline(raw="x", alternatives=[DeadlineAlternative(kind="complex")])) == ""


def test_deadline_tag_terminiert_wt_before_external_anchor() -> None:
    rule = DeadlineRule(
        type="terminiert", direction="vor", business_days=20, reference_event="ÜT", anchor="Änderungstermin", raw="..."
    )
    assert _deadline_tag(rule) == "{≤20WT vor Änderungstermin}"


def test_deadline_tag_terminiert_wt_after_reference_step() -> None:
    rule = DeadlineRule(type="terminiert", direction="nach", business_days=11, reference_step=2, raw="...")
    assert _deadline_tag(rule) == "{≤11WT nach #2}"


def test_deadline_tag_terminiert_anchor_only() -> None:
    rule = DeadlineRule(type="terminiert", anchor="Zahlungsziel", raw="Spätester ÜT ist zum angegebenen Zahlungsziel.")
    assert _deadline_tag(rule) == "{≤Zahlungsziel}"


def test_deadline_tag_terminiert_recurring_with_time() -> None:
    rule = DeadlineRule(type="terminiert", recurring=True, latest_time="14:00", raw="Täglich … bis spätestens 14 Uhr.")
    assert _deadline_tag(rule) == "{täglich ≤14:00}"


def test_emit_appends_deadline_tag_after_pid_suffix() -> None:
    sd = SequenceDiagram(
        participants=["NB", "LF"],
        steps=[
            SDStep(
                nr=5,
                sender="NB",
                receiver="LF",
                message="Zuordnung",
                format="UTILMD",
                pid_refs=[55001],
                deadline_rule=DeadlineRule(
                    type="unverzüglich",
                    latest_time="07:00",
                    business_days=1,
                    reference_event="ÜZ",
                    reference_step=5,
                    raw="...",
                ),
            )
        ],
    )
    line = next(ln for ln in emit_wsd(sd).splitlines() if ln.startswith("NB->>LF: 5."))
    assert line == "NB->>LF: 5. Zuordnung (UTILMD 55001) {u ≤07:00 1WT nach ÜZ#5}"


def test_emit_bare_unverzueglich_tag() -> None:
    sd = SequenceDiagram(
        participants=["NB", "LF"],
        steps=[
            SDStep(
                nr=1,
                sender="NB",
                receiver="LF",
                message="Anmeldung",
                deadline_rule=DeadlineRule(type="unverzüglich", raw="Unverzüglich"),
            )
        ],
    )
    assert "NB->>LF: 1. Anmeldung {u}" in emit_wsd(sd).splitlines()


def test_emit_complex_deadline_becomes_review_note() -> None:
    sd = SequenceDiagram(
        participants=["NB", "LF"],
        steps=[
            SDStep(
                nr=440,
                sender="NB",
                receiver="LF",
                message="Prüfung Vorlauffrist",
                deadline_rule=DeadlineRule(type="complex", raw="spätestens 5 WT\nvor Zuordnungsbeginn"),
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "NB->>LF: 440. Prüfung Vorlauffrist" in lines  # no inline tag
    assert "note right of LF: (!) Frist: spätestens 5 WT vor Zuordnungsbeginn  [REVIEW]" in lines


def test_emit_no_deadline_rule_unchanged() -> None:
    sd = SequenceDiagram(participants=["NB", "LF"], steps=[SDStep(nr=1, sender="NB", receiver="LF", message="X")])
    assert "NB->>LF: 1. X" in emit_wsd(sd).splitlines()


def test_emit_complex_deadline_note_on_ref_step_uses_sender_lifeline() -> None:
    # A subprocess ref renders on the sender's lifeline; the note must anchor there,
    # not on a (possibly mis-guessed) receiver.
    sd = SequenceDiagram(
        participants=["NB", "LF"],
        steps=[
            SDStep(
                nr=7,
                sender="NB",
                receiver="LF",
                message="ref Übermittlung von Werten",
                deadline_rule=DeadlineRule(type="complex", raw="komplexe Frist"),
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note right of NB: (!) Frist: komplexe Frist  [REVIEW]" in lines


# --- an endpoint the pipeline could not read (makorele#78) -------------------------
#
# Both cases are real, from the dataset built off bnetza_bk6_mirror run 32251397627:
#
# The shipped corpus has 16 "?" endpoints: 11 on ``ref`` steps, where the other end never
# named an actor, and 5 on real arrows, across three processes. Two of the five are read
# below; the third process, reklamation_von_werten_beim_msb, carries the other three
# (``?->>MSB: 3. Reklamation Wert einer Messlokation`` and ``?->>ÜNB: 3. Stornierung an
# ÜNB`` in msb_der_messlokation_stellt_selbst_reklamationsbedarf_fest), which nobody has
# read against the source diagram yet — see makorele#96.
#
#   bestellung_einer_konfiguration_vom_nb_oder_lf_an_msb, step 10  MSB->>?
#       GPKE Teil 3, UC 1.3.3.1, diagram in 1.3.3.2 (pp. 47-48). It draws a "weiterer MSB" lane and Vision even read
#       it into the participant list as "MSB (weiterer)" — only the arrow's endpoint was
#       left unread.
#   anforderung_von_zwischenablesungswerten, step 4               ?->>MSB
#       WiM Teil 2 2.6.3, p. 40. The diagram draws two lifelines both labelled ":MSB",
#       told apart by their notes ("entspricht MSB am Objekt Marktlokation" / "… am
#       Objekt Messlokation"); the step runs from the one to the other. The two lanes
#       collapsed into one, so the sender had nothing left to point at.
#
# Neither "?" is a property of the source: both are defects to repair in the data, which
# is why the note carries [REVIEW] rather than quietly documenting an unknown actor.


def test_unread_receiver_becomes_a_flagged_note_on_the_sender() -> None:
    """The note names the endpoint that survived and says nothing about which side is
    missing: when two identically labelled lanes collapse, which endpoint keeps the role
    is arbitrary — for the WiM 2.6.3 step below the source has the *receiver* unplaced
    while the YAML says ``sender="?"``."""
    sd = SequenceDiagram(
        participants=["NB", "MSB", "MSB (weiterer)", "ÜNB"],
        steps=[SDStep(nr=10, sender="MSB", receiver="?", message="Mitteilung über Gesamtvorgang")],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over MSB: (!) 10. Mitteilung über Gesamtvorgang — Gegenstelle ungelesen  [REVIEW]" in lines
    assert not [line for line in lines if "?" in line]


def test_unread_sender_becomes_a_flagged_note_on_the_receiver() -> None:
    sd = SequenceDiagram(
        participants=["NB", "LF", "MSB"],
        steps=[SDStep(nr=4, sender="?", receiver="MSB", message="Anforderung Wert einer Messlokation")],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over MSB: (!) 4. Anforderung Wert einer Messlokation — Gegenstelle ungelesen  [REVIEW]" in lines
    assert not [line for line in lines if "?" in line]


def test_the_note_keeps_the_step_annotations() -> None:
    """Format, PIDs, EBD and deadline tag say what the step is; losing them with the
    arrow would make the note less informative than the defect it reports."""
    sd = SequenceDiagram(
        participants=["MSB"],
        steps=[
            SDStep(
                nr=10,
                sender="MSB",
                receiver="?",
                message="Mitteilung über Gesamtvorgang",
                format="UTILMD",
                pid_refs=[55001],
                ebd_ref="E_0401",
                deadline_rule=DeadlineRule(type="unverzüglich"),
            )
        ],
    )
    note = next(line for line in emit_wsd(sd).splitlines() if line.startswith("note "))
    assert note == (
        "note over MSB: (!) 10. Mitteilung über Gesamtvorgang (UTILMD 55001) [E_0401] {u} "
        "— Gegenstelle ungelesen  [REVIEW]"
    )


def test_a_step_with_two_known_endpoints_is_still_an_arrow() -> None:
    """The boundary: nothing about a readable step changes."""
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung")],
    )
    assert "LF->>NB: 1. Anmeldung" in emit_wsd(sd).splitlines()


def test_a_step_with_neither_endpoint_known_spans_the_declared_lanes() -> None:
    """Picking one lane would file the step under an actor it may have nothing to do
    with, so the note spans the diagram (its outermost two lanes). It is flagged like the one-sided case: this step is
    worse off, not better, and the webapp lists it in the step table either way — a silent
    drop would leave a step that appears in no diagram and on no worklist."""
    sd = SequenceDiagram(
        participants=["NB", "MSB"],
        steps=[
            SDStep(nr=1, sender="NB", receiver="NB", message="Bekannt"),
            SDStep(nr=2, sender="?", receiver="?", message="Beide Enden ungelesen"),
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "NB->>NB: 1. Bekannt" in lines
    assert "note over NB,MSB: (!) 2. Beide Enden ungelesen — beide Endpunkte ungelesen  [REVIEW]" in lines
    assert not [line for line in lines if "?" in line]


def test_a_step_with_neither_endpoint_nor_any_lane_is_dropped() -> None:
    """Nothing left to hang a note on — a diagram in which no actor was read at all."""
    sd = SequenceDiagram(
        participants=["?"],
        steps=[SDStep(nr=2, sender="?", receiver="?", message="Beide Enden ungelesen")],
    )
    lines = emit_wsd(sd).splitlines()
    assert not [line for line in lines if "Beide Enden ungelesen" in line]
    assert not [line for line in lines if "?" in line]


def test_the_placeholder_is_never_declared_as_a_participant() -> None:
    """makorele's p08 writes ``participants=["?"]`` for a diagram in which it could read
    no actor at all; declaring it is the same phantom lane by another route."""
    sd = SequenceDiagram(
        participants=["?"],
        steps=[SDStep(nr=1, sender="?", receiver="?", message="A")],
    )
    assert not [line for line in emit_wsd(sd).splitlines() if "?" in line]


def test_a_ref_step_with_one_unread_endpoint_stays_a_self_arrow() -> None:
    """A ``ref`` is a subprocess box on one lifeline, so an unread *other* endpoint costs
    nothing — it never named a second actor. This is the majority of the "?" endpoints in
    the corpus: 11 of the 16, spread over the same three processes that carry the 5
    non-ref ones."""
    sd = SequenceDiagram(
        participants=["MSB"],
        steps=[SDStep(nr=9, sender="MSB", receiver="?", message="ref Aufbereitung und Übermittlung von Werten")],
    )
    lines = emit_wsd(sd).splitlines()
    assert "MSB->>MSB: 9. ref Aufbereitung und Übermittlung von Werten" in lines
    assert not [line for line in lines if "?" in line]


def test_a_ref_step_with_no_lifeline_at_all_is_dropped() -> None:
    """With no lane to fall back on either, the self-arrow would be "?->>?" — two phantom
    lanes for one step."""
    sd = SequenceDiagram(participants=["?"], steps=[SDStep(nr=1, sender="?", receiver="?", message="ref Etwas")])
    assert not [line for line in emit_wsd(sd).splitlines() if "?" in line]


def test_a_ref_step_that_names_no_endpoint_is_not_filed_under_a_random_lane() -> None:
    """_ref_lifeline used to fall back to the first participant, which files the box under
    an actor it may have nothing to do with — the very thing the non-ref path refuses. It
    is spanned like any other unplaceable step instead."""
    sd = SequenceDiagram(
        participants=["NB", "MSB"],
        steps=[SDStep(nr=1, sender="?", receiver="?", message="ref Etwas")],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over NB,MSB: (!) 1. ref Etwas — beide Endpunkte ungelesen  [REVIEW]" in lines
    assert not [line for line in lines if line.startswith("NB->>NB")]


def test_a_subprocess_ref_without_the_ref_prefix_is_still_a_ref() -> None:
    """The two markers do not always agree — ``subprocess_ref`` is set and the message does
    not open with "ref " — and both serializers must read them alike, or the same step is a
    self-message in one output and a note about a missing counterpart in the other."""
    sd = SequenceDiagram(
        participants=["MSB"],
        steps=[
            SDStep(
                nr=2,
                sender="MSB",
                receiver="?",
                message="Aufbereitung und Übermittlung von Werten",
                subprocess_ref="aufbereitung_und_übermittlung_von_werten",
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "MSB->>MSB: 2. Aufbereitung und Übermittlung von Werten" in lines
    assert not [line for line in lines if "ungelesen" in line]


def test_an_unresolved_note_anchor_is_dropped_not_named() -> None:
    """p12 leaves "?" in a note's anchor list when it cannot resolve it; ``note over ?``
    places the same phantom lane. With one anchor left the note keeps that anchor."""
    sd = SequenceDiagram(
        participants=["NB"],
        steps=[SDStep(nr=1, sender="NB", receiver="NB", message="A")],
        notes=[
            SDNote(text="Gilt für beide", participants=["NB", "?"], position="over", after_step=1),
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over NB: Gilt für beide" in lines
    assert not [line for line in lines if "?" in line]


def test_a_note_whose_every_anchor_is_unresolved_spans_the_diagram() -> None:
    """It must not disappear: makorele's p12 anchors its diagram-level "[REVIEW]" note on
    the first participant precisely so emit_wsd keeps it, and a note that reaches no diagram
    and no worklist is what the spanning rule exists to prevent."""
    sd = SequenceDiagram(
        participants=["NB", "MSB"],
        steps=[SDStep(nr=1, sender="NB", receiver="NB", message="A")],
        notes=[SDNote(text="Trennung nicht möglich  [REVIEW]", participants=["?"], position="over", after_step=1)],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over NB,MSB: Trennung nicht möglich  [REVIEW]" in lines


def test_a_note_with_no_anchor_and_no_lane_is_skipped() -> None:
    sd = SequenceDiagram(
        participants=["?"],
        steps=[SDStep(nr=1, sender="?", receiver="?", message="A")],
        notes=[SDNote(text="Ohne Anker", participants=["?"], position="over", after_step=1)],
    )
    assert not [line for line in emit_wsd(sd).splitlines() if "Ohne Anker" in line]


def test_the_note_lands_inside_the_fragment_the_step_belongs_to() -> None:
    """The note replaces the arrow in place, so a step inside an ``alt`` stays inside it —
    both real cases sit in a branch (step 4 of 2.6.3 is in the "[Werte auf der
    Messlokation werden benötigt]" alt)."""
    sd = SequenceDiagram(
        participants=["MSB"],
        steps=[
            SDStep(nr=1, sender="MSB", receiver="MSB", message="A"),
            SDStep(nr=4, sender="?", receiver="MSB", message="Anforderung Wert einer Messlokation"),
        ],
        fragments=[SDFragment(type="alt", branches=[SDBranch(condition="Werte benötigt", step_nrs=[4])])],
    )
    lines = emit_wsd(sd).splitlines()
    note_idx = next(i for i, line in enumerate(lines) if line.startswith("note over MSB: (!) 4."))
    assert lines.index("alt Werte benötigt") < note_idx < lines.index("end")


def test_a_review_note_from_an_unread_endpoint_reaches_the_worklist() -> None:
    """End to end with the consumer: ``extract_review_notes`` builds the "Prüfung nötig"
    list the webapp shows, and an unread endpoint belongs on it."""
    sd = SequenceDiagram(
        participants=["MSB"],
        steps=[SDStep(nr=10, sender="MSB", receiver="?", message="Mitteilung über Gesamtvorgang")],
    )
    assert extract_review_notes(emit_wsd(sd)) == ["(!) 10. Mitteilung über Gesamtvorgang — Gegenstelle ungelesen"]


def test_a_span_names_two_lanes_however_many_are_declared() -> None:
    """``note over`` takes one or two participants — Mermaid's grammar says so outright
    and the websequencediagrams reference shows no more — so spanning every lane of a
    four-lane diagram would break the diagram rather than the line."""
    sd = SequenceDiagram(
        participants=["NB", "MSB", "MSB (weiterer)", "ÜNB"],
        steps=[SDStep(nr=2, sender="?", receiver="?", message="Unklar")],
    )
    note = next(line for line in emit_wsd(sd).splitlines() if line.startswith("note "))
    assert note == "note over NB,ÜNB: (!) 2. Unklar — beide Endpunkte ungelesen  [REVIEW]"


def test_a_span_of_one_lane_names_it_alone() -> None:
    sd = SequenceDiagram(participants=["NB"], steps=[SDStep(nr=2, sender="?", receiver="?", message="Unklar")])
    note = next(line for line in emit_wsd(sd).splitlines() if line.startswith("note "))
    assert note == "note over NB: (!) 2. Unklar — beide Endpunkte ungelesen  [REVIEW]"


def test_a_readable_colon_form_ref_keeps_the_arrow_the_document_draws() -> None:
    """The historical ref shape is not changed by #78: seven shipped arrows read
    "BIKO->>NB: 2. ref: Deaktivierung … vom BIKO an NB", and the ref's own title names the
    receiver. Only a ref whose other endpoint was *not* read becomes a self-message."""
    sd = SequenceDiagram(
        participants=["BIKO", "NB"],
        steps=[
            SDStep(nr=2, sender="BIKO", receiver="NB", message="ref: Deaktivierung eines MaBiS-Zählpunkts"),
            SDStep(nr=3, sender="BIKO", receiver="?", message="ref: Deaktivierung eines MaBiS-Zählpunkts"),
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "BIKO->>NB: 2. ref: Deaktivierung eines MaBiS-Zählpunkts" in lines
    assert "BIKO->>BIKO: 3. ref: Deaktivierung eines MaBiS-Zählpunkts" in lines


def test_a_deadline_note_keeps_its_historical_anchor() -> None:
    """_deadline_note anchors a ref's Frist on the sender and everything else's on the
    receiver, keyed on the "ref " prefix. The broader ref rule would move the note for a
    step that carries only the other marker, which is not what #78 is about."""
    step = SDStep(
        nr=1,
        sender="LF",
        receiver="NB",
        message="Aufbereitung",
        subprocess_ref="aufbereitung",
        deadline_rule=DeadlineRule(type="complex", raw="Gemäß irgendwas."),
    )
    assert _deadline_note(step, ["LF", "NB"]) == "note right of NB: (!) Frist: Gemäß irgendwas.  [REVIEW]"


def test_deadline_tag_says_werktaeglich_when_the_source_does() -> None:
    """ "täglich" for a werktäglich obligation is not a shortening — it adds the weekend.

    MaBiS's Netzgangzeitreihe reads "Werktäglich für den Vortag bzw. Vortage bis 12:00 Uhr", and
    two shipped steps rendered it as "{täglich ≤12:00}", claiming a duty on Saturdays and
    Sundays that the source does not impose (makorele#101).
    """
    werktaeglich = DeadlineRule(
        type="terminiert",
        recurring=True,
        recurrence="werktäglich",
        latest_time="12:00",
        raw="Werktäglich für den Vortag bzw. Vortage bis 12:00 Uhr.",
    )
    assert _deadline_tag(werktaeglich) == "{werktäglich ≤12:00}"
    taeglich = DeadlineRule(
        type="terminiert", recurring=True, recurrence="täglich", latest_time="13:00", raw="Täglich … 13:00 Uhr."
    )
    assert _deadline_tag(taeglich) == "{täglich ≤13:00}"
    # a rule written before the field existed still renders as it did
    legacy = DeadlineRule(type="terminiert", recurring=True, latest_time="14:00", raw="Täglich … 14 Uhr.")
    assert _deadline_tag(legacy) == "{täglich ≤14:00}"
    # and without a time, the granularity alone
    assert _deadline_tag(DeadlineRule(type="terminiert", recurring=True, recurrence="werktäglich", raw="…")) == (
        "{werktäglich}"
    )


def test_a_diagram_whose_every_step_is_dropped_emits_no_fragment_skeleton() -> None:
    """makoralle#38: fragments were opened before the emitter decided the step was undrawable.

    A diagram in which nothing was read yielded ``alt Bedingung 1 / else Bedingung 2 / end`` and
    nothing else — a fragment around no messages, which the renderer may or may not accept and
    which says nothing either way. Empty *branches* stay deliberate (``_open_lines`` reconstructs
    the labels of empty leading and trailing branches, and that is tested); it is opening a
    fragment for steps that never get emitted that is wrong.
    """
    sd = SequenceDiagram(
        participants=["?"],
        steps=[
            SDStep(nr=1, sender="?", receiver="?", message="Eins"),
            SDStep(nr=2, sender="?", receiver="?", message="Zwei"),
        ],
        fragments=[
            SDFragment(
                type="alt",
                branches=[
                    SDBranch(condition="Bedingung 1", step_nrs=[1]),
                    SDBranch(condition="Bedingung 2", step_nrs=[2]),
                ],
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert not [line for line in lines if line.startswith(("alt ", "else ", "end"))], lines


def test_a_fragment_is_still_opened_for_a_step_that_becomes_a_note() -> None:
    """The boundary: undrawable as an *arrow* is not undrawable. A step that spans the diagram or
    becomes a one-sided note is inside its branch, so the branch must be there."""
    sd = SequenceDiagram(
        participants=["NB", "MSB"],
        steps=[SDStep(nr=1, sender="?", receiver="?", message="Eins")],
        fragments=[SDFragment(type="alt", branches=[SDBranch(condition="Bedingung 1", step_nrs=[1])])],
    )
    lines = emit_wsd(sd).splitlines()
    assert "alt Bedingung 1" in lines
    assert "end" in lines
    note = next(line for line in lines if line.startswith("note over"))
    assert lines.index("alt Bedingung 1") < lines.index(note) < lines.index("end")


def test_a_fragment_survives_for_a_dropped_step_that_still_carries_a_readable_note() -> None:
    """No lane, no endpoint — but the note names an actor, so something *is* drawn in the branch."""
    sd = SequenceDiagram(
        participants=["?"],
        steps=[SDStep(nr=1, sender="?", receiver="?", message="Eins")],
        # The readable anchor sits *behind* an unreadable one, so a predicate that looks only at
        # the first participant misses it and deletes the note with the step.
        notes=[SDNote(position="over", participants=["?", "NB"], text="Hinweis", after_step=1)],
        fragments=[SDFragment(type="alt", branches=[SDBranch(condition="Bedingung 1", step_nrs=[1])])],
    )
    lines = emit_wsd(sd).splitlines()
    assert "alt Bedingung 1" in lines
    assert "note over NB: Hinweis" in lines


def test_an_empty_leading_branch_still_keeps_its_label() -> None:
    """The behaviour this must not break: a fragment with drawable steps keeps every branch label,
    including the empty ones — which is why the fix is not "never emit an empty branch"."""
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[SDStep(nr=1, sender="LF", receiver="NB", message="Eins")],
        fragments=[
            SDFragment(
                type="alt",
                branches=[
                    SDBranch(condition="Leer", step_nrs=[]),
                    SDBranch(condition="Voll", step_nrs=[1]),
                ],
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "alt Leer" in lines
    assert "else Voll" in lines


@pytest.mark.parametrize(
    ("sender", "receiver"),
    [pytest.param("MSB", "?", id="sender-known"), pytest.param("?", "MSB", id="receiver-known")],
)
def test_a_step_naming_an_actor_no_participant_declares_is_still_drawn(sender: str, receiver: str) -> None:
    """The lane list and the endpoints can disagree, and then the endpoints win.

    p08 writes ``participants=["?"]`` for a diagram in which it read no actor, so `known_lanes` can
    be empty while a step still names one. Skipping such a step because there is no lane would
    delete the only readable thing in the diagram — so the endpoint, not the lane list, decides.

    Both endpoints get a case: review found that checking only the sender left the suite green while
    silently deleting the step of every receiver-only diagram, which is the severe direction.
    """
    sd = SequenceDiagram(
        participants=["?"],
        steps=[SDStep(nr=1, sender=sender, receiver=receiver, message="Mitteilung")],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over MSB: (!) 1. Mitteilung — Gegenstelle ungelesen  [REVIEW]" in lines


def test_a_note_that_names_nothing_readable_does_not_keep_the_fragment(caplog: pytest.LogCaptureFixture) -> None:
    """The third boundary: a note has to be *drawable*, not merely present.

    `_emit_note` skips a note whose participants are all unreadable when there is no lane to span,
    so treating "the step has a note" as "something will be drawn" reopens the exact skeleton this
    change removes — verified: `alt B1 / else B2 / end` around no messages.
    """
    sd = SequenceDiagram(
        participants=["?"],
        steps=[SDStep(nr=1, sender="?", receiver="?", message="Eins")],
        notes=[SDNote(position="over", participants=["?"], text="Hinweis", after_step=1)],
        fragments=[SDFragment(type="alt", branches=[SDBranch(condition="Bedingung 1", step_nrs=[1])])],
    )
    with caplog.at_level(logging.WARNING, logger="makoralle.serialization.wsd"):
        lines = emit_wsd(sd).splitlines()
    assert not [line for line in lines if line.startswith(("alt ", "else ", "end"))], lines
    assert "Hinweis" not in "\n".join(lines)
    # and the drop is audible: a step that leaves no trace in the diagram must leave one in the log
    assert [record for record in caplog.records if "dropping step 1" in record.message]


def test_the_other_drop_path_is_audible_too(caplog: pytest.LogCaptureFixture) -> None:
    """`_append_unplaceable`'s own drop — reached when a note keeps the fragment but the step itself
    still has nowhere to go. Both paths go through `_log_dropped`, and neither may go quiet."""
    sd = SequenceDiagram(
        participants=["?"],
        steps=[SDStep(nr=1, sender="?", receiver="?", message="Eins")],
        notes=[SDNote(position="over", participants=["?", "NB"], text="Hinweis", after_step=1)],
    )
    with caplog.at_level(logging.WARNING, logger="makoralle.serialization.wsd"):
        lines = emit_wsd(sd).splitlines()
    assert "note over NB: Hinweis" in lines
    assert not [line for line in lines if "Eins" in line]
    assert [record for record in caplog.records if "dropping step 1" in record.message]


def test_an_unplaceable_step_keeps_its_unstructured_frist(caplog: pytest.LogCaptureFixture) -> None:
    """makoralle#37: the step spans the diagram, and its complex Frist used to vanish with it.

    ``_deadline_note`` anchors on a lifeline, and a step with neither endpoint read has none — so
    it returned ``None`` and the raw Frist text was dropped without a word. That text is the whole
    point: it is unstructured *because* a human still has to structure it, and it is exactly what
    ``extract_review_notes`` puts on the "Prüfung nötig" worklist. So it spans the diagram with the
    step it belongs to.
    """
    sd = SequenceDiagram(
        participants=["NB", "MSB"],
        steps=[
            SDStep(
                nr=1,
                sender="?",
                receiver="?",
                message="ref Etwas",
                deadline_rule=DeadlineRule(type="complex", raw="Frist X"),
            )
        ],
    )
    with caplog.at_level(logging.WARNING, logger="makoralle.serialization.wsd"):
        lines = emit_wsd(sd).splitlines()
    assert "note over NB,MSB: (!) 1. ref Etwas — beide Endpunkte ungelesen  [REVIEW]" in lines
    assert "note over NB,MSB: (!) Frist: Frist X  [REVIEW]" in lines
    assert not caplog.records  # nothing was lost, so nothing to warn about


def test_an_unplaceable_frist_reaches_the_worklist() -> None:
    """End to end with the consumer, because "visible in the diagram" is not the requirement."""
    sd = SequenceDiagram(
        participants=["NB", "MSB"],
        steps=[
            SDStep(
                nr=1,
                sender="?",
                receiver="?",
                message="Etwas",
                deadline_rule=DeadlineRule(type="complex", raw="unverzüglich, jedoch spätester ÜT ist der 5. WT"),
            )
        ],
    )
    assert "(!) Frist: unverzüglich, jedoch spätester ÜT ist der 5. WT" in extract_review_notes(emit_wsd(sd))


def test_an_unplaceable_reference_frist_stays_unflagged_when_it_spans() -> None:
    """A ``reference`` deadline is real but irreducible, so it must not reach the worklist —
    the spanning fallback must not quietly promote it to a review item."""
    sd = SequenceDiagram(
        participants=["NB", "MSB"],
        steps=[
            SDStep(
                nr=1,
                sender="?",
                receiver="?",
                message="Etwas",
                deadline_rule=DeadlineRule(type="reference", raw="siehe Vertrag"),
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over NB,MSB: (i) Frist: siehe Vertrag" in lines
    assert not [note for note in extract_review_notes(emit_wsd(sd)) if "Vertrag" in note]


def test_a_frist_with_no_lane_at_all_is_dropped_loudly(caplog: pytest.LogCaptureFixture) -> None:
    """With no lane the step itself is already dropped; the Frist goes the same way, and the one
    warning that reports the drop names it — a silent drop is what #37 is about.

    One line, not two: the loss is one event. `_log_dropped` carries the Frist text so that the
    thing a human needs in order to structure it is in the log rather than nowhere.
    """
    sd = SequenceDiagram(
        participants=["?"],
        steps=[
            SDStep(
                nr=1,
                sender="?",
                receiver="?",
                message="Etwas",
                deadline_rule=DeadlineRule(type="complex", raw="Frist X"),
            )
        ],
    )
    with caplog.at_level(logging.WARNING, logger="makoralle.serialization.wsd"):
        lines = emit_wsd(sd).splitlines()
    assert not [line for line in lines if "Frist X" in line]
    assert [record for record in caplog.records if "Frist" in record.message]


def test_a_note_keeps_the_fragment_and_the_frist_is_still_reported_once(caplog: pytest.LogCaptureFixture) -> None:
    """The one path that reaches `_deadline_note`'s no-lane branch: the step draws nothing, but one
    of its notes names an actor, so the loop does not skip it and `_append_unplaceable` drops it.

    The Frist has nowhere to go there either, and it must be reported exactly once — the drop line
    carries it, and the Frist branch stays silent so the loss is not counted twice.
    """
    sd = SequenceDiagram(
        participants=["?"],
        steps=[
            SDStep(
                nr=1,
                sender="?",
                receiver="?",
                message="Etwas",
                deadline_rule=DeadlineRule(type="complex", raw="Frist X"),
            )
        ],
        notes=[SDNote(position="over", participants=["?", "NB"], text="Hinweis", after_step=1)],
    )
    with caplog.at_level(logging.WARNING, logger="makoralle.serialization.wsd"):
        lines = emit_wsd(sd).splitlines()
    assert "note over NB: Hinweis" in lines
    assert not [line for line in lines if "Frist X" in line]
    assert len([record for record in caplog.records if "Frist X" in record.message]) == 1


def test_a_structured_rule_is_not_reported_as_a_lost_frist(caplog: pytest.LogCaptureFixture) -> None:
    """`raw` exists on structured rules too, and losing one of those is not the same event.

    A `terminiert`/`unverzüglich` rule survives the drop as data — the step is gone from the diagram
    but its tag was derivable from structure — so naming it in the warning would report a loss that
    did not happen and bury the one that did.
    """
    sd = SequenceDiagram(
        participants=["?"],
        steps=[
            SDStep(
                nr=1,
                sender="?",
                receiver="?",
                message="Etwas",
                deadline_rule=DeadlineRule(type="unverzüglich", raw="unverzüglich", business_days=5),
            )
        ],
    )
    with caplog.at_level(logging.WARNING, logger="makoralle.serialization.wsd"):
        emit_wsd(sd)
    assert [record for record in caplog.records if "dropping step 1" in record.message]
    assert not [record for record in caplog.records if "Frist" in record.message]


def test_a_one_lane_span_puts_the_frist_where_the_step_is() -> None:
    """A single declared lane spans to itself, so `span_of_lanes` returns a bare name with no comma.

    The step goes ``note over NB``; deciding the Frist's placement by looking for a comma sent it to
    ``note right of NB`` — two different placements for two halves of the same step. The flag knows
    it is a span whether or not the name happens to contain punctuation.
    """
    sd = SequenceDiagram(
        participants=["NB"],
        steps=[
            SDStep(
                nr=1,
                sender="?",
                receiver="?",
                message="Etwas",
                deadline_rule=DeadlineRule(type="complex", raw="Frist X"),
            )
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over NB: (!) 1. Etwas — beide Endpunkte ungelesen  [REVIEW]" in lines
    assert "note over NB: (!) Frist: Frist X  [REVIEW]" in lines


# --- A bare-tagged "unverzüglich" whose sentence says more (makorele#101) -----------------


def test_deadline_note_lossy_unverzueglich_gets_its_sentence() -> None:
    """`{u}` says "immediately" and drops the event the reader acts on.

    "Unverzüglich, spätestens jedoch 1 WT nach Erhalt der Aktivierung." has an outer bound whose
    anchor is prose, not a step. The compact tag cannot carry it — the corpus's anchors run to 63
    characters — so the sentence goes beside the arrow instead, the way `reference` already does.
    """
    rule = DeadlineRule(type="unverzüglich", raw="Unverzüglich, spätestens jedoch 1 WT nach Erhalt der Aktivierung.")
    note = _deadline_note(_step_with_deadline(rule), ["LF", "NB"])
    assert note == ("note right of NB: (i) Frist: Unverzüglich, spätestens jedoch 1 WT nach Erhalt der Aktivierung.")
    assert "[REVIEW]" not in note


def test_deadline_note_lossy_unverzueglich_keeps_its_compact_tag() -> None:
    """The tag is unchanged — this is "tag *and* note", not a replacement for the tag."""
    rule = DeadlineRule(type="unverzüglich", raw="Unverzüglich nach Kenntnisnahme.")
    assert _deadline_tag(rule) == "{u}"
    assert _deadline_note(_step_with_deadline(rule), ["LF", "NB"]) is not None


def test_the_sentence_beyond_the_tag_is_empty_where_the_tag_says_everything() -> None:
    """The predicate itself, on the shapes that decide it."""
    beyond = _unverzueglich_sentence_beyond_the_tag

    assert beyond(DeadlineRule(type="unverzüglich", raw="Unverzüglich.")) == ""
    assert beyond(DeadlineRule(type="unverzüglich", raw="Sofort.")) == ""
    # CONSTRUCTED: no corpus raw carries "!" or "?", but without them in the class the bare
    # punctuation survives as a residual and earns a note that says nothing (Copilot).
    assert beyond(DeadlineRule(type="unverzüglich", raw="Unverzüglich!")) == ""
    assert beyond(DeadlineRule(type="unverzüglich", raw="Sofort?")) == ""
    assert beyond(DeadlineRule(type="unverzüglich", raw="Unverzüglich nach Kenntnisnahme.")) == "nach Kenntnisnahme"
    # a structured tag already carries the bound
    assert beyond(DeadlineRule(type="unverzüglich", business_days=1, raw="Unverzüglich, spätestens 1 WT.")) == ""
    # and a type that is not unverzüglich is not this predicate's business
    assert beyond(DeadlineRule(type="reference", raw="Gemäß Rahmenvertrag.")) == ""
    # the marker is stripped only where the sentence opens with it: 48 corpus sentences carry it
    # mid-prose, and stripping it there would leave a mangled residual
    assert (
        beyond(DeadlineRule(type="unverzüglich", raw="Bei Fall a: Unverzüglich nach X."))
        == "Bei Fall a: Unverzüglich nach X"
    )


def test_a_dropped_lossy_unverzueglich_is_named_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """`_log_dropped` names the sentence it just lost, not only a `complex`/`reference` one.

    Its rationale used to be that an `unverzüglich` rule "survives the drop as structure" — true
    while `{u}` said everything, false for a row whose sentence carries the event (makorele#101).
    Nothing in the v0.0.16 corpus reaches this path today (all 220 land `right of` a known lane),
    so only a test can hold the claim.
    """
    lossy = SDStep(
        nr=1,
        sender="?",
        receiver="?",
        message="Eins",
        deadline_rule=DeadlineRule(type="unverzüglich", raw="Unverzüglich nach Kenntnisnahme."),
    )
    structured = SDStep(
        nr=2,
        sender="?",
        receiver="?",
        message="Zwei",
        deadline_rule=DeadlineRule(type="unverzüglich", business_days=1, raw="Unverzüglich, spätestens 1 WT."),
    )
    with caplog.at_level(logging.WARNING, logger="makoralle.serialization.wsd"):
        emit_wsd(SequenceDiagram(participants=["?"], steps=[lossy, structured]))
    messages = [record.getMessage() for record in caplog.records]
    assert any("dropping step 1" in m and "Unverzüglich nach Kenntnisnahme." in m for m in messages), messages
    # the tag still carries this one, so announcing a loss would announce one that did not happen
    assert any(m == "dropping step 2 from the diagram: no endpoint and no lane is known" for m in messages), messages
