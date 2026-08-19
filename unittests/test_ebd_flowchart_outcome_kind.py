"""An EBD outcome node must never be styled as an acceptance on missing information.

`_render_ebd_flowchart` decides both a node's label and its mermaid class from the
branch's result text. When that text is absent the label degrades to the bare answer
code — and the class fell through to `accept`, i.e. green: an outcome nobody classified
was shown as approved. 77 nodes in the shipped dataset are in exactly that state, and a
regeneration that empties more result fields turns rejections green wholesale
(Hochfrequenz/makoralle#29, triggered by Hochfrequenz/makorele#68).

The cluster vocabulary in `ebd_clusters` is the source of truth for what an outcome
means — it comes from the EBD PDF's own `Cluster:` prefix — so the classes follow it
instead of a substring test.
"""

import re
from typing import Any

import pytest

from makoralle.serialization.markdown import _render_ebd_flowchart


def _flowchart(result_yes: str | None) -> str:
    dt: dict[str, Any] = {
        "steps": [
            {
                "nr": 10,
                "check": "Liegt eine Zuordnung vor?",
                "if_yes_code": "A01",
                "if_yes_result": result_yes,
                "if_no": 20,
            }
        ]
    }
    return "\n".join(_render_ebd_flowchart(dt))


@pytest.mark.parametrize("missing", ["", None])
def test_an_unclassified_outcome_is_not_green(missing: str | None) -> None:
    out = _flowchart(missing)
    assert "ry10:::accept" not in out, "a missing result must not be rendered as approval"
    assert "ry10:::unknown" in out
    assert 'ry10["A01"]' in out


def test_a_rejection_stays_red() -> None:
    """The only result text the shipped dataset carries — 1229 occurrences."""
    out = _flowchart("Ablehnung")
    assert "ry10:::reject" in out
    assert 'ry10["A01: Ablehnung"]' in out


def test_an_approval_is_green() -> None:
    out = _flowchart("Zustimmung")
    assert "ry10:::accept" in out


def test_an_informational_outcome_is_neither_accepted_nor_rejected() -> None:
    """ "Korrekturliste wegen Ablehnung" is `info` in the cluster vocabulary, but a
    substring test on "ablehnung" calls it a rejection."""
    out = _flowchart("Korrekturliste wegen Ablehnung")
    assert "ry10:::reject" not in out
    assert "ry10:::accept" not in out
    assert "ry10:::info" in out


def test_free_text_no_one_classified_is_not_green() -> None:
    out = _flowchart("weiter wie in Schritt 5")
    assert "ry10:::accept" not in out
    assert "ry10:::unknown" in out


def test_every_class_used_is_defined() -> None:
    """A mermaid `:::name` with no matching classDef renders unstyled and silently."""
    for result in ("", "Ablehnung", "Zustimmung", "Korrekturliste wegen Ablehnung", "sonstiges"):
        out = _flowchart(result)
        defined = set(re.findall(r"classDef (\w+)", out))
        used = set(re.findall(r":::(\w+)", out))
        assert used <= defined, f"{used - defined} used but not defined (result={result!r})"
