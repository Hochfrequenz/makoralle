import yaml

from makoralle.serialization.markdown import (
    _deadline_legend,
    _render_sd_table,
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
    assert "https://ahb-tabellen.hochfrequenz.de/ahb/FV2604/17115" in md
    assert "[19116](https://ahb-tabellen.hochfrequenz.de/ahb/FV2604/19116)" in md
    assert "[19117](https://ahb-tabellen.hochfrequenz.de/ahb/FV2604/19117)" in md
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
    assert "{u}" in text
    assert "WT" in text  # business days
    assert "ÜZ" in text or "ÜT" in text


def test_deadline_legend_emitted_for_terminiert() -> None:
    sd = {"steps": [{"nr": 1, "deadline_rule": {"type": "terminiert", "anchor": "Zahlungsziel"}}]}
    text = "\n".join(_deadline_legend(sd))
    assert text  # legend shown
    assert "vor" in text and "nach" in text  # explains the terminiert direction vocabulary


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
    row = next(l for l in _render_sd_table(sd) if l.strip().startswith("| 1 "))
    assert "\\|" in row  # literal pipe escaped
    assert "\n" not in row  # newline collapsed
    # the table structure stays a single 8-column row
    assert row.count(" | ") >= 1
