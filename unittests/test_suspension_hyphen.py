r"""A suspension hyphen survives the markdown serializer (makoralle#50).

``_escape_mermaid`` used to carry ``re.sub(r"(\w)- (\w)", r"\1\2", text)`` for a PDF line break
("verbrau- chende"). A regex cannot tell that from a German *Ergänzungsstrich*, so it turned
"Arbeits- und Leistungswerte" into "Arbeitsund" in the shipped dataset.

Note where the decision actually belongs: EBD check and hint text is de-hyphenated upstream, by
``makorele``'s ``p09_parse_ebd`` (makorele#203), against an adjudicated table of 916 breaks. The
serializer sees less context than that stage did, so it preserves what the source says -- and the
source was measured to contain no line-break hyphens left to repair.

These tests pin both directions: the suspension hyphen that must survive, and the genuine line
break that is now *deliberately* left alone rather than silently glued shut.
"""

import yaml

from makoralle.serialization.markdown import (
    _escape_mermaid,
    _render_ebd_flowchart,
    _render_ebd_steps,
    _wrap_text,
    yaml_to_markdown,
)

SUSPENSION = "Arbeits- und Leistungswerte"


def test_escape_mermaid_keeps_a_suspension_hyphen() -> None:
    assert _escape_mermaid(f"Ermittlung aus den {SUSPENSION} des NB") == f"Ermittlung aus den {SUSPENSION} des NB"


def test_escape_mermaid_keeps_every_connective_the_corpus_uses() -> None:
    """The seven distinct hyphen pairs the old rule rewrote across dataset v0.0.36 / FV2604."""
    for text in ("Zu- oder", "Zu- und", "Beginn- und", "Leistungs- und", "Arbeits- und", "Grund- oder", "Keine- oder"):
        assert _escape_mermaid(f"x {text} y") == f"x {text} y"


def test_escape_mermaid_keeps_a_hyphen_before_a_capital() -> None:
    """The second documented failure mode: a compound whose line broke on its own hyphen.

    ``makorele.pipeline.wrapped_text`` records "MaBiS- ZP" -> "MaBiSZP" alongside "Arbeitsund" as
    what the bare regex shipped. The hyphen belongs to the compound and has to stay.
    """
    assert _escape_mermaid("Zuordnung der MaBiS- ZP zum Bilanzkreis") == "Zuordnung der MaBiS- ZP zum Bilanzkreis"


def test_escape_mermaid_leaves_a_genuine_line_break_alone() -> None:
    """The case the old rule was written for. Rejoining it is upstream's decision, not ours."""
    assert _escape_mermaid("eine verbrau- chende Marktlokation") == "eine verbrau- chende Marktlokation"


def test_escape_mermaid_still_swaps_quotes_and_collapses_newlines() -> None:
    """Guard the two jobs the function does keep."""
    assert _escape_mermaid('  Strom-\nund Gas "neu"  ') == "Strom- und Gas 'neu'"


def test_wrap_text_keeps_a_suspension_hyphen() -> None:
    """``_wrap_text`` routes through ``_escape_mermaid``, so it inherited the bug."""
    assert _wrap_text(SUSPENSION) == SUSPENSION


def test_wrap_text_keeps_it_across_a_line_break() -> None:
    """Long enough to be wrapped: the hyphen must survive the <br/> insertion too."""
    text = f"{'A' * 70} {SUSPENSION}"
    assert SUSPENSION in _wrap_text(text).replace("<br/>", " ")


def test_the_flowchart_label_keeps_a_suspension_hyphen() -> None:
    lines = _render_ebd_flowchart(
        {
            "id": "E_0406",
            "name": "x",
            "steps": [{"nr": 10, "check": f"Liegen die {SUSPENSION} vor?", "if_yes_result": f"Ende, {SUSPENSION}"}],
        }
    )
    assert f'    s10{{{{"10. Liegen die {SUSPENSION} vor?"}}}}' in lines
    assert f'    s10 -->|ja| ry10["Ende, {SUSPENSION}"]' in lines


def test_the_decision_step_list_keeps_a_suspension_hyphen() -> None:
    lines = _render_ebd_steps(
        {
            "id": "E_0406",
            "name": "x",
            "steps": [
                {"nr": 10, "check": f"Liegen die {SUSPENSION} vor?", "next": 20, "next_hint": f"prüfe {SUSPENSION}"}
            ],
        }
    )
    assert f"    - **Step 10:** Liegen die {SUSPENSION} vor?" in lines
    assert f"        - → Step 20 prüfe {SUSPENSION}" in lines


def test_a_suspension_hyphen_reaches_the_rendered_page() -> None:
    """End to end, the way the dataset produces it: YAML in, markdown out."""
    doc = {
        "process": {"id": "p", "name": "P", "source": "", "category": ""},
        "decision_trees": [
            {
                "id": "E_0406",
                "name": "x",
                "steps": [{"nr": 10, "check": f"Liegen die {SUSPENSION} vor?", "if_yes_result": "Ende"}],
            }
        ],
    }
    md = yaml_to_markdown(yaml.safe_dump(doc, allow_unicode=True))
    assert SUSPENSION in md
    assert "Arbeitsund" not in md
