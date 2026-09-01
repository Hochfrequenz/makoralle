import yaml

from makoralle.serialization.markdown import (
    _deadline_legend,
    _render_sd_table,
    _render_sequence_diagram,
    yaml_to_markdown,
)


def test_yaml_to_markdown() -> None:
    yaml_content = """
process:
  id: lieferbeginn
  name: Lieferbeginn
  source: "GPKE Teil 2, Kapitel 2.1"
  category: Zuordnungsprozesse
use_case:
  goal: Zuordnung eines LF
  description: Anmeldung
  roles: [LF, NB]
"""
    md = yaml_to_markdown(yaml_content)
    assert "# Lieferbeginn" in md
    assert "Zuordnung eines LF" in md
    assert "LF" in md


_SD_YAML = """
process:
  id: lieferbeginn
  name: Lieferbeginn
  source: "GPKE Teil 2"
sequence_diagram:
  participants: [LF, NB]
  steps:
    - {nr: 1, sender: LF, receiver: NB, message: Anmeldung}
"""


def test_markdown_embeds_svg_when_has_sequence() -> None:
    md = yaml_to_markdown(_SD_YAML, has_sequence=True)
    # faithful SVG embedded + interactive viewer link, no Mermaid block
    assert "![Sequence Diagram" in md
    assert "../../sequence/lieferbeginn.svg" in md
    assert "../../sequence/lieferbeginn.html" in md
    # the embedded image itself links to the interactive viewer
    assert (
        "[![Sequence Diagram: Lieferbeginn](../../sequence/lieferbeginn.svg)](../../sequence/lieferbeginn.html)" in md
    )
    assert "```mermaid" not in md


def test_markdown_falls_back_to_mermaid_without_sequence() -> None:
    md = yaml_to_markdown(_SD_YAML, has_sequence=False)
    assert "```mermaid" in md
    assert "../../sequence/" not in md


def test_pid_table_links_each_pid_to_ahb() -> None:
    content = yaml.safe_dump(
        {
            "id": "demo",
            "name": "Demo",
            "category": "GPKE",
            "sequence_diagram": {
                "participants": ["LF", "NB"],
                "steps": [
                    {
                        "nr": 1,
                        "sender": "LF",
                        "receiver": "NB",
                        "message": "Sperrauftrag",
                        "format": "ORDERS",
                        "pid_refs": [17115],
                    },
                    {
                        "nr": 2,
                        "sender": "NB",
                        "receiver": "LF",
                        "message": "Antwort",
                        "format": "ORDRSP",
                        "pid_refs": [19116, 19117],
                    },
                    {"nr": 3, "sender": "NB", "receiver": "NB", "message": "ref Sub", "pid_refs": []},
                ],
            },
        },
        allow_unicode=True,
    )
    md = yaml_to_markdown(content, has_sequence=True)
    assert "https://ahb-tabellen.hochfrequenz.de/ahb/current/17115" in md
    assert "[19116](https://ahb-tabellen.hochfrequenz.de/ahb/current/19116)" in md
    assert "[19117](https://ahb-tabellen.hochfrequenz.de/ahb/current/19117)" in md
    assert "Prüfidentifikator" in md  # table present


def test_deadline_legend_emitted_only_when_tags_present() -> None:
    sd_with = {"steps": [{"nr": 1, "deadline_rule": {"type": "parallel", "reference_step": 2}}]}
    sd_without = {"steps": [{"nr": 1, "deadline_rule": {"type": "none"}}]}
    assert any("∥#" in line for line in _deadline_legend(sd_with))
    # pylint: disable-next=use-implicit-booleaness-not-comparison  # assert the exact empty-list shape
    assert _deadline_legend(sd_without) == []


def test_deadline_legend_emitted_for_complex_only() -> None:
    sd = {"steps": [{"nr": 1, "deadline_rule": {"type": "complex", "raw": "x"}}]}
    # complex deadlines render as a (!) [REVIEW] note on the image, so the legend applies
    assert any("REVIEW" in line for line in _deadline_legend(sd))


def test_deadline_legend_explains_vocabulary() -> None:
    sd = {"steps": [{"nr": 1, "deadline_rule": {"type": "unverzüglich", "business_days": 1}}]}
    text = "\n".join(_deadline_legend(sd))
    # This diagram renders `{u ≤1WT}` and nothing else, so since makoralle#59 it gets the bound
    # entry and NOT the bare `{u}` one — the legend is derived from the tags actually drawn.
    assert "`{u ≤nWT vor|nach ÜZ#N}`" in text
    assert "{u}" not in text
    assert "WT" in text  # business days
    assert "ÜZ" in text or "ÜT" in text


def test_deadline_legend_lists_only_the_marker_families_the_diagram_shows() -> None:
    """makoralle#59: one `has_tags` flag for all three families made a `terminiert`-only diagram
    define every `{u …}` form as well — one stale line before #59 split the `unverzüglich` entry
    into four, four after. A legend that defines markers the diagram does not show teaches the
    reader to distrust it.
    """
    terminiert = "\n".join(
        _deadline_legend({"steps": [{"nr": 1, "deadline_rule": {"type": "terminiert", "anchor": "Zahlungsziel"}}]})
    )
    assert "{u" not in terminiert
    assert "∥" not in terminiert
    assert "{≤Zahlungsziel}" in terminiert  # the bare-anchor form this very diagram renders

    unverzueglich = "\n".join(
        _deadline_legend({"steps": [{"nr": 1, "deadline_rule": {"type": "unverzüglich", "reference_step": 3}}]})
    )
    assert "∥" not in unverzueglich
    assert "terminierte Frist" not in unverzueglich
    # `{u #N}` is live — `verpflichtung_gmsb` nr 4 ("Unmittelbar nach Nr. 3.") has a step and no
    # event, so an entry naming only the ÜZ/ÜT form would leave that arrow undefined
    assert "`{u #N}`" in unverzueglich
    # ... and this diagram draws no bound and no clock, so neither of those entries appears
    assert "spätester Uhrzeit" not in unverzueglich
    assert "spätestens n Werktage" not in unverzueglich

    parallel = "\n".join(_deadline_legend({"steps": [{"nr": 1, "deadline_rule": {"type": "parallel"}}]}))
    assert "{u" not in parallel
    # `{∥}` ships where the source names no single step (`beendigung_einer_konfiguration_vom_msb`
    # nr 3, "Parallel zu Nr. 1 oder 2.")
    assert "`{∥}`" in parallel
    assert "`{∥#N}`" not in parallel  # this diagram names no step, so that entry would be stale


def test_deadline_legend_defines_every_form_the_clocked_and_recurring_tags_show() -> None:
    """The three entries makoralle#59 added or reworked, each pinned against deletion: a diagram
    that draws a clocked bound, a recurring `unverzüglich`, or a conditional Frist must define it.
    """
    clocked = "\n".join(
        _deadline_legend(
            {
                "steps": [
                    {
                        "nr": 1,
                        "deadline_rule": {
                            "type": "unverzüglich",
                            "latest_time": "07:00",
                            "business_days": 1,
                            "reference_step": 1,
                            "reference_event": "ÜT",
                        },
                    }
                ]
            }
        )
    )
    assert "`{u ≤HH:MM …}`" in clocked
    assert "`{u ≤nWT vor|nach ÜZ#N}`" in clocked

    # `{u täglich …}` is renderable and was undefined: the recurring entries used to be gated on
    # the `terminiert` family, so a recurring `unverzüglich` showed a marker nothing explained.
    recurring = "\n".join(
        _deadline_legend(
            {"steps": [{"nr": 1, "deadline_rule": {"type": "unverzüglich", "recurring": True, "reference_step": 2}}]}
        )
    )
    assert "`{u täglich …}`" in recurring

    # `{täglich ≤HH:MM}` is the `terminiert` form — `übermittlung_der_täglichen_…` nr 1 ships it
    terminiert_recurring = "\n".join(
        _deadline_legend(
            {"steps": [{"nr": 1, "deadline_rule": {"type": "terminiert", "recurring": True, "latest_time": "14:00"}}]}
        )
    )
    assert "`{täglich ≤HH:MM}`" in terminiert_recurring


def test_deadline_legend_emitted_for_terminiert() -> None:
    sd = {"steps": [{"nr": 1, "deadline_rule": {"type": "terminiert", "anchor": "Zahlungsziel"}}]}
    text = "\n".join(_deadline_legend(sd))
    assert text  # legend shown
    # `{≤Zahlungsziel}` is all this diagram draws, so the vor/nach entry would define a form it
    # never shows; a diagram that does draw an offset gets that entry instead.
    assert "`{≤Anker}`" in text
    offset = {
        "steps": [
            {
                "nr": 1,
                "deadline_rule": {
                    "type": "terminiert",
                    "business_days": 20,
                    "direction": "vor",
                    "anchor": "Änderungstermin",
                },
            }
        ]
    }
    offset_text = "\n".join(_deadline_legend(offset))
    assert "vor" in offset_text and "nach" in offset_text  # explains the terminiert direction vocabulary


def test_deadline_legend_emitted_for_reference_note() -> None:
    sd = {"steps": [{"nr": 1, "deadline_rule": {"type": "reference", "raw": "Gemäß Rahmenvertrag."}}]}
    text = "\n".join(_deadline_legend(sd))
    assert "(i)" in text  # explains the info note
    assert "REVIEW" not in text  # a pure-reference SD needs no [REVIEW] legend line


def test_sd_table_keeps_full_complex_deadline() -> None:
    long_raw = "spätestens 5 Werktage vor dem geplanten Zuordnungsbeginn der Marktlokation X"
    sd = {"steps": [{"nr": 1, "sender": "NB", "receiver": "LF", "message": "Prüfung", "deadline": long_raw}]}
    out = "\n".join(_render_sd_table(sd))
    assert long_raw in out  # not truncated with "..."


def test_sd_table_escapes_pipe_and_newline_in_deadline() -> None:
    sd = {
        "steps": [{"nr": 1, "sender": "NB", "receiver": "LF", "message": "X", "deadline": "5 WT | spätestens\n07:00"}]
    }
    row = next(line for line in _render_sd_table(sd) if line.strip().startswith("| 1 "))
    assert "\\|" in row  # literal pipe escaped
    assert "\n" not in row  # newline collapsed
    # the table structure stays a single 8-column row
    assert row.count(" | ") >= 1


# --- an endpoint the pipeline could not read (makorele#78) -------------------------
#
# The Mermaid path draws a lifeline per participant just like the WSD one, so "?" makes
# a nameless lane here too. Same rule, and the same two real steps behind it.


def test_mermaid_renders_an_unread_endpoint_as_a_note() -> None:
    lines = _render_sequence_diagram(
        {
            "participants": ["NB", "MSB", "MSB (weiterer)"],
            "steps": [
                {"nr": 9, "sender": "MSB", "receiver": "NB", "message": "Antwort auf Bestellung"},
                {"nr": 10, "sender": "MSB", "receiver": "?", "message": "Mitteilung über Gesamtvorgang"},
            ],
        }
    )
    assert "    MSB->>+NB: 9. Antwort auf Bestellung" in lines
    assert "    Note over MSB: (!) 10. Mitteilung über Gesamtvorgang — Gegenstelle ungelesen" in lines
    assert not [line for line in lines if "?" in line]


def test_mermaid_names_the_receiver_when_the_sender_is_the_unread_one() -> None:
    lines = _render_sequence_diagram(
        {
            "participants": ["NB", "LF", "MSB"],
            "steps": [{"nr": 4, "sender": "?", "receiver": "MSB", "message": "Anforderung Wert einer Messlokation"}],
        }
    )
    assert "    Note over MSB: (!) 4. Anforderung Wert einer Messlokation — Gegenstelle ungelesen" in lines


def test_mermaid_never_declares_the_placeholder_as_a_participant() -> None:
    lines = _render_sequence_diagram(
        {"participants": ["?", "NB"], "steps": [{"nr": 1, "sender": "NB", "receiver": "NB", "message": "A"}]}
    )
    assert "    participant NB" in lines
    assert not [line for line in lines if "?" in line]


def test_mermaid_spans_the_lanes_when_neither_endpoint_is_known() -> None:
    lines = _render_sequence_diagram(
        {"participants": ["NB", "MSB"], "steps": [{"nr": 2, "sender": "?", "receiver": "?", "message": "Unklar"}]}
    )
    assert "    Note over NB,MSB: (!) 2. Unklar — beide Endpunkte ungelesen" in lines
    assert not [line for line in lines if "?" in line]


def test_mermaid_keeps_a_readable_step_unchanged() -> None:
    """The boundary: nothing about a step with two known endpoints moves."""
    lines = _render_sequence_diagram(
        {
            "participants": ["LF", "NB"],
            "steps": [{"nr": 1, "sender": "LF", "receiver": "NB", "message": "Anmeldung", "format": "UTILMD"}],
        }
    )
    assert "    LF->>+NB: 1. Anmeldung [UTILMD]" in lines


def test_mermaid_spans_only_two_lanes_however_many_are_declared() -> None:
    """Mermaid's grammar is ``actor_pair : actor ',' actor | actor`` — a third name makes
    the whole ```mermaid block fail to parse, so the page loses its diagram entirely."""
    lines = _render_sequence_diagram(
        {
            "participants": ["NB", "LF", "MSB"],
            "steps": [{"nr": 2, "sender": "?", "receiver": "?", "message": "Unklar"}],
        }
    )
    assert "    Note over NB,MSB: (!) 2. Unklar — beide Endpunkte ungelesen" in lines


def test_mermaid_keeps_a_ref_step_a_self_message() -> None:
    """As in the .wsd emitter: a ``ref`` sits on one lifeline, so its unread other end
    never named an actor and reporting a missing counterpart would be wrong. 11 of the
    16 "?" endpoints in the corpus are of this kind."""
    lines = _render_sequence_diagram(
        {
            "participants": ["MSB"],
            "steps": [
                {
                    "nr": 9,
                    "sender": "MSB",
                    "receiver": "?",
                    "message": "Aufbereitung und Übermittlung von Werten",
                    "subprocess_ref": "aufbereitung_und_übermittlung_von_werten",
                }
            ],
        }
    )
    assert "    MSB->>+MSB: 9. ref Aufbereitung und Übermittlung von Werten" in lines
    assert not [line for line in lines if "ungelesen" in line]


def test_mermaid_legend_defines_the_unread_endpoint_marker() -> None:
    """The legend renders for an unread endpoint even when the diagram has no deadline —
    otherwise the page shows a "(!)" the legend does not define, or defines as a Frist."""
    legend = _deadline_legend({"steps": [{"nr": 1, "sender": "?", "receiver": "NB", "message": "A"}]})
    assert [line for line in legend if "unlesbarem Endpunkt" in line]


def test_mermaid_legend_stays_empty_for_a_clean_diagram() -> None:
    assert _deadline_legend({"steps": [{"nr": 1, "sender": "LF", "receiver": "NB", "message": "A"}]}) == []


def test_mermaid_does_not_double_a_colon_form_ref_prefix() -> None:
    """The tables write the marker both ways; a check for "ref " alone left
    "3. ref ref: Aktivierung eines MaBiS-Zählpunkts …". 16 steps of the corpus write the
    marker that way (15 "ref:", one "ref."), of the 5 that also carry a subprocess_ref."""
    lines = _render_sequence_diagram(
        {
            "participants": ["ÜNB"],
            "steps": [
                {
                    "nr": 3,
                    "sender": "ÜNB",
                    "receiver": "ÜNB",
                    "message": "ref: Aktivierung eines MaBiS-Zählpunkts",
                    "subprocess_ref": "aktivierung",
                }
            ],
        }
    )
    assert "    ÜNB->>+ÜNB: 3. ref: Aktivierung eines MaBiS-Zählpunkts" in lines


def test_mermaid_does_not_double_the_ref_prefix() -> None:
    """244 steps of the shipped dataset carry both markers — a parsed ``subprocess_ref``
    and a message that already opens with "ref " — and every one of them rendered as
    "7. ref ref Stammdatenänderung …"."""
    lines = _render_sequence_diagram(
        {
            "participants": ["NB"],
            "steps": [
                {
                    "nr": 7,
                    "sender": "NB",
                    "receiver": "NB",
                    "message": "ref Stammdatenänderung vom NB",
                    "subprocess_ref": "stammdatenänderung",
                }
            ],
        }
    )
    assert "    NB->>+NB: 7. ref Stammdatenänderung vom NB" in lines


def test_mermaid_keeps_a_ref_step_whose_message_carries_the_marker_a_self_message() -> None:
    """The corpus shape: both markers set, one endpoint unread. 11 of the 16 "?" endpoints
    look like this."""
    lines = _render_sequence_diagram(
        {
            "participants": ["MSB"],
            "steps": [
                {
                    "nr": 9,
                    "sender": "MSB",
                    "receiver": "?",
                    "message": "ref Aufbereitung und Übermittlung von Werten",
                    "subprocess_ref": "aufbereitung_und_übermittlung_von_werten",
                }
            ],
        }
    )
    assert "    MSB->>+MSB: 9. ref Aufbereitung und Übermittlung von Werten" in lines
    assert not [line for line in lines if "ungelesen" in line]


def test_mermaid_drops_a_step_with_no_lane_at_all() -> None:
    lines = _render_sequence_diagram(
        {"participants": ["?"], "steps": [{"nr": 1, "sender": "?", "receiver": "?", "message": "Unklar"}]}
    )
    assert not [line for line in lines if "Unklar" in line or "?" in line]


def test_the_legend_stays_silent_when_every_unread_endpoint_is_a_ref() -> None:
    """A ref keeps its self-message, so the diagram carries no "(!) … ungelesen" note and
    the legend must not announce one. Live case: reklamation_von_werten_beim_msb, whose
    three unread endpoints are all refs — its primary SD, that is; a later SD of the same
    process has two non-ref "?" arrows and does get the line."""
    legend = _deadline_legend(
        {
            "participants": ["MSB", "NB"],
            "steps": [
                {"nr": 8, "sender": "MSB", "receiver": "?", "message": "ref Stornierung", "subprocess_ref": "s"},
                {"nr": 9, "sender": "MSB", "receiver": "?", "message": "ref Aufbereitung", "subprocess_ref": "a"},
            ],
        }
    )
    assert not [line for line in legend if "ungelesen" in line]


def test_the_legend_announces_the_marker_when_a_note_is_really_drawn() -> None:
    legend = _deadline_legend(
        {"participants": ["MSB"], "steps": [{"nr": 4, "sender": "?", "receiver": "MSB", "message": "Anforderung"}]}
    )
    assert [line for line in legend if "unlesbarem Endpunkt" in line]


def test_the_legend_announces_the_marker_for_a_both_ends_unread_step() -> None:
    """The spanning case draws a note too, so the legend must cover it — reducing the
    predicate to "has one known endpoint" would leave this diagram's marker undefined."""
    legend = _deadline_legend(
        {"participants": ["NB", "MSB"], "steps": [{"nr": 2, "sender": "?", "receiver": "?", "message": "Unklar"}]}
    )
    assert [line for line in legend if "unlesbarem Endpunkt" in line]


def test_mermaid_keeps_the_annotations_of_a_step_that_only_writes_the_ref_marker() -> None:
    """A parsed subprocess call has never carried its format and PIDs in the label; a step
    that merely *writes* "ref …" always has. Keying the omission on the message instead of
    on subprocess_ref would drop them the first time the pipeline attaches a PID to such a
    step — invisible today, because none of the corpus's 91 prefix-only refs has one."""
    step = {"nr": 1, "sender": "NB", "receiver": "MSB", "message": "ref X", "format": "UTILMD", "pid_refs": [55001]}
    lines = _render_sequence_diagram({"participants": ["NB", "MSB"], "steps": [step]})
    assert "    NB->>+MSB: 1. ref X [UTILMD] (PID:55001)" in lines


def test_mermaid_omits_the_annotations_of_a_parsed_subprocess_call() -> None:
    step = {
        "nr": 1,
        "sender": "NB",
        "receiver": "MSB",
        "message": "ref X",
        "subprocess_ref": "x",
        "format": "UTILMD",
        "pid_refs": [55001],
    }
    lines = _render_sequence_diagram({"participants": ["NB", "MSB"], "steps": [step]})
    assert "    NB->>+MSB: 1. ref X" in lines


def test_deadline_legend_defines_the_info_marker_a_lossy_unverzueglich_shows() -> None:
    """A diagram can show `(i)` without carrying a single `reference` row (makorele#101).

    Keying the entry on the type alone left 107 of the 228 shipped diagrams showing a marker the
    legend does not define — the same failure the `(!)` entry's own comment records for
    makorele#78.
    """
    sd = {
        "participants": ["LF", "NB"],
        "steps": [
            {
                "nr": 1,
                "sender": "LF",
                "receiver": "NB",
                "message": "Foo",
                "deadline_rule": {"type": "unverzüglich", "raw": "Unverzüglich nach Kenntnisnahme."},
            }
        ],
    }
    legend = _deadline_legend(sd)
    assert any(line.startswith("- `(i) …`") for line in legend), legend
    # and a row whose tag says everything still shows no `(i)` marker, so none is announced
    sd_bare = {
        "participants": ["LF", "NB"],
        "steps": [
            {
                "nr": 1,
                "sender": "LF",
                "receiver": "NB",
                "message": "Foo",
                "deadline_rule": {"type": "unverzüglich", "raw": "Unverzüglich."},
            }
        ],
    }
    assert not any(line.startswith("- `(i) …`") for line in _deadline_legend(sd_bare))
