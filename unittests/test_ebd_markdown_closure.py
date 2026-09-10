"""Markdown draws every way an EBD branch can end, and says why an id has no tree.

Before: only a step target or an answer code was drawn, so ``ja → Ende`` (a leaf with no code),
E_0594's unconditional ``→ 110`` rows and the tree-less ``E_`` stubs all rendered as nothing.
"""

from typing import Any

import pytest
import yaml

from makoralle.serialization.markdown import (
    _render_ebd_flowchart,
    _render_ebd_steps,
    _render_ebd_stub,
    yaml_to_markdown,
)


def _tree(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"id": "E_0406", "name": "x", "steps": list(steps)}


def test_a_result_only_leaf_is_drawn_grey() -> None:
    """``ja → Ende`` without a cluster: an outcome, but the source classifies nothing."""
    lines = _render_ebd_flowchart(_tree({"nr": 805, "check": "Ist die Rechnung bezahlt?", "if_yes_result": "Ende"}))
    assert '    s805 -->|ja| ry805["Ende"]' in lines
    assert "    ry805:::unknown" in lines


def test_a_result_only_leaf_with_a_cluster_takes_the_clusters_colour() -> None:
    step = {
        "nr": 560,
        "check": "x",
        "if_no_result": "Ablehnung auf Summenebene",
        "if_no_cluster": "Ablehnung auf Summenebene",
    }
    lines = _render_ebd_flowchart(_tree(step))
    assert '    s560 -->|nein| rn560["Ablehnung auf Summenebene"]' in lines
    assert "    rn560:::reject" in lines


@pytest.mark.parametrize("result", [None, "", "   "])
def test_a_branch_with_no_outcome_draws_nothing(result: str | None) -> None:
    step: dict[str, Any] = {"nr": 10, "check": "x"}
    if result is not None:
        step["if_yes_result"] = result
    assert _render_ebd_flowchart(_tree(step))[-2:] == ['    s10{{"10. x"}}', "```"]
    assert _render_ebd_steps(_tree(step)) == ['??? abstract "Decision Steps"', "    - **Step 10:** x"]


def test_a_coded_branch_renders_as_before() -> None:
    step = {"nr": 15, "check": "x", "if_no_code": "A07", "if_no_cluster": "Ablehnung", "if_yes": 16}
    lines = _render_ebd_flowchart(_tree(step))
    assert "    s15 -->|ja| s16" in lines
    assert '    s15 -->|nein| rn15["A07: Ablehnung"]' in lines
    assert "    rn15:::reject" in lines


def test_the_code_wins_over_the_result_for_the_leaf_label() -> None:
    """E_0406 805 prints ``ja → Ende`` *and* A78: the leaf is the code's."""
    step = {"nr": 805, "check": "x", "if_yes_result": "Ende", "if_yes_code": "A78"}
    assert '    s805 -->|ja| ry805["A78: Ende"]' in _render_ebd_flowchart(_tree(step))


def test_an_unconditional_row_draws_one_unlabelled_edge() -> None:
    """E_0594 105: '[Adressprüfung] → 110' -- no ja, no nein."""
    lines = _render_ebd_flowchart(_tree({"nr": 105, "check": "[Adressprüfung]", "next": 110}))
    assert "    s105 --> s110" in lines
    assert not any("s105 -->|" in line for line in lines)


def test_the_step_list_names_the_result_only_leaf_and_its_hint() -> None:
    step = {"nr": 805, "check": "x", "if_yes_result": "Ende", "if_no_result": "Ende", "if_no_hint": "Rechnung offen"}
    lines = _render_ebd_steps(_tree(step))
    assert "        - ✓ → Ende" in lines
    assert "        - ✗ → Ende Rechnung offen" in lines


def test_the_step_list_names_the_next_step() -> None:
    lines = _render_ebd_steps(_tree({"nr": 105, "check": "x", "next": 110}))
    assert lines[-1] == "        - → Step 110"


def test_a_real_tree_gets_no_stub_line() -> None:
    assert not _render_ebd_stub({"id": "E_0622", "kind": "tree", "steps": [{"nr": 10, "check": "x"}]})
    assert not _render_ebd_stub({"id": "E_0622", "steps": []})  # a v0.0.29 tree has no kind


def test_a_codelist_only_stub_names_its_lists() -> None:
    stub = {"id": "E_0201", "kind": "codelist_only", "codelisten": ["S_0055", "S_0056"], "steps": []}
    assert _render_ebd_stub(stub) == ["**No decision tree** (`codelist_only`) Codelisten: S_0055, S_0056"]


def test_a_use_other_ebd_stub_quotes_the_document_and_names_the_target() -> None:
    stub = {"id": "E_0541", "kind": "use_other_ebd", "note": "Es ist das EBD E_0539 zu nutzen.", "use_ebd": "E_0539"}
    assert _render_ebd_stub(stub) == [
        "**No decision tree** (`use_other_ebd`): Es ist das EBD E_0539 zu nutzen. → E_0539"
    ]


@pytest.mark.parametrize("kind", ["no_tree_aperak", "no_tree_no_answer", "codelist_in_format", "unclassified"])
def test_every_other_stub_kind_is_named(kind: str) -> None:
    (line,) = _render_ebd_stub({"id": "E_0033", "kind": kind, "steps": []})
    assert line == f"**No decision tree** (`{kind}`)"


def test_a_stub_note_is_quoted_verbatim_on_one_line() -> None:
    """Markdown text, not a mermaid label: no quote swapping, no suspension hyphen glued shut."""
    (line,) = _render_ebd_stub({"id": "E_0452", "kind": "unclassified", "note": 'Strom- und\nGas "neu"'})
    assert line == '**No decision tree** (`unclassified`): Strom- und Gas "neu"'


def test_a_stub_reaches_the_rendered_page() -> None:
    doc = {
        "process": {"id": "p", "name": "P", "source": "", "category": ""},
        "decision_trees": [
            {"id": "E_0541", "name": "x", "kind": "use_other_ebd", "use_ebd": "E_0539", "steps": []},
            {"id": "E_0539", "name": "y", "steps": []},
        ],
    }
    md = yaml_to_markdown(yaml.safe_dump(doc, allow_unicode=True))
    assert "**Steps:** 0\n\n**No decision tree** (`use_other_ebd`) → E_0539\n\n### E_0539" in md


@pytest.mark.parametrize(
    ("branch", "line"),
    [
        ({"if_yes_result": "Ende", "if_yes_code": "A78"}, "        - ✓ → A78 Ende"),
        ({"if_yes_result": "Ende "}, "        - ✓ → Ende"),
        ({"if_no_code": "A07", "if_no_result": "Ablehnung"}, "        - ✗ → A07 Ablehnung"),
        ({"if_yes": 20, "if_yes_hint": "weiter"}, "        - ✓ → Step 20 weiter"),
    ],
)
def test_the_step_list_line_for_each_branch_shape(branch: dict[str, Any], line: str) -> None:
    assert line in _render_ebd_steps(_tree({"nr": 805, "check": "x", **branch}))


def test_the_step_list_quotes_what_the_hinweis_says_beside_an_unconditional_row() -> None:
    step = {"nr": 105, "check": "x", "next": 110, "next_hint": "Aufnahme von 0..n Treffern"}
    assert _render_ebd_steps(_tree(step))[-1] == "        - → Step 110 Aufnahme von 0..n Treffern"


def test_the_next_hint_is_escaped_like_every_other_step_list_hint() -> None:
    step = {"nr": 105, "check": "x", "next": 110, "next_hint": 'Treffer "neu"'}
    assert _render_ebd_steps(_tree(step))[-1] == "        - → Step 110 Treffer 'neu'"
