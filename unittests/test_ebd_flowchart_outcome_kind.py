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


def _flowchart(result_yes: str | None, cluster_yes: str | None = None) -> str:
    dt: dict[str, Any] = {
        "steps": [
            {
                "nr": 10,
                "check": "Liegt eine Zuordnung vor?",
                "if_yes_code": "A01",
                "if_yes_result": result_yes,
                "if_yes_cluster": cluster_yes,
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


def test_the_cluster_classifies_a_branch_whose_result_text_is_missing() -> None:
    """`if_*_cluster` is the `Cluster:` prefix lifted out of the EBD's own Hinweis cell,
    so it is the authority — and 91 branches in the committed EBD data carry it while
    their result text is empty. Those are exactly the nodes that used to go green."""
    out = _flowchart("", cluster_yes="Ablehnung auf Kopfebene")
    assert "ry10:::reject" in out
    assert "ry10:::unknown" not in out
    assert 'ry10["A01: Ablehnung auf Kopfebene"]' in out, "the cluster also names the outcome"


def test_the_cluster_wins_over_a_disagreeing_result_text() -> None:
    """The result text is a rendering of the outcome; the cluster is its classification."""
    out = _flowchart("Ablehnung", cluster_yes="Zustimmung")
    assert "ry10:::accept" in out
    assert "ry10:::reject" not in out


def test_an_informational_cluster_is_neither() -> None:
    out = _flowchart("", cluster_yes="Korrekturliste wegen Ablehnung")
    assert "ry10:::info" in out


def test_a_result_text_still_classifies_when_no_cluster_was_extracted() -> None:
    """1405 branches in the committed data have a result and no cluster."""
    out = _flowchart("Ablehnung", cluster_yes=None)
    assert "ry10:::reject" in out
    assert 'ry10["A01: Ablehnung"]' in out


def test_neither_cluster_nor_result_is_unknown() -> None:
    out = _flowchart("", cluster_yes=None)
    assert "ry10:::unknown" in out
    assert 'ry10["A01"]' in out
