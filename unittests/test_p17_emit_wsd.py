from makoralle.models.process import DeadlineRule, SDBranch, SDFragment, SDNote, SDStep, SequenceDiagram
from makoralle.serialization.wsd import _deadline_note, _deadline_tag, emit_wsd
from makoralle.webapp_export import extract_review_notes


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
    """Structured deadlines (tag-rendered) never produce a note."""
    for t in ("terminiert", "unverzüglich", "parallel", "none"):
        assert _deadline_note(_step_with_deadline(DeadlineRule(type=t, raw="x")), ["LF", "NB"]) is None


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


def test_deadline_tag_unverzueglich_with_clock_omits_null_pieces() -> None:
    rule = DeadlineRule(
        type="unverzüglich", latest_time="07:00", business_days=1, reference_event="ÜZ", reference_step=5, raw="..."
    )
    assert _deadline_tag(rule) == "{≤07:00 1WT ÜZ#5}"
    # only a reference step, no clock/event
    assert _deadline_tag(DeadlineRule(type="unverzüglich", reference_step=5, raw="...")) == "{#5}"
    # business days only
    assert _deadline_tag(DeadlineRule(type="unverzüglich", business_days=3, raw="...")) == "{3WT}"


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
    assert line == "NB->>LF: 5. Zuordnung (UTILMD 55001) {≤07:00 1WT ÜZ#5}"


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
    with, so the note spans them all. It is flagged like the one-sided case: this step is
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
    """``_ref_lifeline`` falls back to the first participant; when that is the placeholder
    too, the self-arrow would be "?->>?" — two phantom lanes for one step."""
    sd = SequenceDiagram(participants=["?"], steps=[SDStep(nr=1, sender="?", receiver="?", message="ref Etwas")])
    assert not [line for line in emit_wsd(sd).splitlines() if "?" in line]


def test_an_unresolved_note_anchor_is_dropped_not_named() -> None:
    """p12 leaves "?" in a note's anchor list when it cannot resolve it; ``note over ?``
    places the same phantom lane."""
    sd = SequenceDiagram(
        participants=["NB"],
        steps=[SDStep(nr=1, sender="NB", receiver="NB", message="A")],
        notes=[
            SDNote(text="Gilt für beide", participants=["NB", "?"], position="over", after_step=1),
            SDNote(text="Ohne Anker", participants=["?"], position="over", after_step=1),
        ],
    )
    lines = emit_wsd(sd).splitlines()
    assert "note over NB: Gilt für beide" in lines
    assert not [line for line in lines if "Ohne Anker" in line]
    assert not [line for line in lines if "?" in line]


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
