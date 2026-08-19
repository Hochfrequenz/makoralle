"""How an EBD outcome node is classified and coloured.

The `Cluster:` prefix of the EBD's Hinweis cell is the only thing that classifies an
outcome. The branch's *result* text does not: it carries the same constant for every code
of an EBD, so `E_0488`'s A01 reads "Ablehnung" while the source says
`Cluster: Zustimmung`.

Measured against **Hochfrequenz/machine-readable_entscheidungsbaumdiagramme**, where
every EBD is verified from an independent source (ebdamame + rebdhuhn), over the 1437
answer codes it shares with this pipeline's data (FV2604 and FV2610 agree):

    the result text, by substring ("ablehnung")   829/1437   57 %   <- what shipped
    cluster, falling back to the result text     1045/1437   72 %
    cluster only, else unknown                   1328/1437   92 %   <- this module

92 % is also what the pipeline's own `answer_codes.yaml` scores, so the rendering is now
as faithful as its dedicated index. The fallback is what cost the other 20 points: it
invents a rejection for 386 codes the verified data classifies as unknown.

Verified sources for the cases below, pinned at commit 834fd748cca1b51c37e883d8beb67001247bd552:

* E_0488 A01 = `Cluster: Zustimmung`, A02 = `Cluster: Ablehnung` —
  https://github.com/Hochfrequenz/machine-readable_entscheidungsbaumdiagramme/blob/834fd748cca1b51c37e883d8beb67001247bd552/FV2604/E_0488.json
* E_0587 A02 = `Cluster: Änderung der Daten` (an outcome that is neither) —
  https://github.com/Hochfrequenz/machine-readable_entscheidungsbaumdiagramme/blob/834fd748cca1b51c37e883d8beb67001247bd552/FV2604/E_0587.json

Both were rendered *red* before this module changed, and A01 is an approval.
See Hochfrequenz/makoralle#29, and Hochfrequenz/mako_prozesse#1 on replacing this
homebrew EBD path with that toolchain in the long run.
"""

import re
from typing import Any

import pytest

from makoralle.serialization.markdown import _render_ebd_flowchart


def _flowchart(*, result: str | None = None, cluster: str | None = None, hint: str | None = None) -> str:
    dt: dict[str, Any] = {
        "steps": [
            {
                "nr": 10,
                "check": "Hat der MSB die generelle Zustimmung erteilt?",
                "if_yes_code": "A01",
                "if_yes_result": result,
                "if_yes_cluster": cluster,
                "if_yes_hint": hint,
                "if_no": 20,
            }
        ]
    }
    return "\n".join(_render_ebd_flowchart(dt))


# --- the cluster classifies -------------------------------------------------------


def test_e_0488_a01_is_an_approval() -> None:
    """The verified data says `Cluster: Zustimmung`; the result text says "Ablehnung"."""
    out = _flowchart(hint="Cluster: Zustimmung\nGenerelle Zustimmung des MSB liegt vor.", result="Ablehnung")
    assert "ry10:::accept" in out
    assert "ry10:::reject" not in out
    assert 'ry10["A01: Zustimmung"]' in out


def test_e_0488_a02_is_a_rejection() -> None:
    out = _flowchart(hint="Cluster: Ablehnung\nVerhinderungsgrund liegt vor.", result="Ablehnung")
    assert "ry10:::reject" in out


def test_e_0587_a02_is_neither_accepted_nor_rejected() -> None:
    """ "Änderung der Daten" is `info` in the cluster vocabulary — it was rendered red."""
    out = _flowchart(hint="Cluster: Änderung der Daten", result="Ablehnung")
    assert "ry10:::info" in out
    assert "ry10:::reject" not in out and "ry10:::accept" not in out


def test_the_resolved_cluster_field_is_used_when_present() -> None:
    """p09 lifts the prefix into `if_*_cluster` for 91 branches of the committed data."""
    out = _flowchart(cluster="Ablehnung auf Kopfebene", result="")
    assert "ry10:::reject" in out
    assert 'ry10["A01: Ablehnung auf Kopfebene"]' in out


def test_the_resolved_field_outranks_the_hint() -> None:
    out = _flowchart(cluster="Zustimmung", hint="Cluster: Ablehnung …", result="Ablehnung")
    assert "ry10:::accept" in out


# --- nothing else classifies -----------------------------------------------------


@pytest.mark.parametrize("result", ["", None, "Ablehnung", "weiter wie in Schritt 5"])
def test_without_a_cluster_the_outcome_is_unknown(result: str | None) -> None:
    """Whatever the result text says. It is a constant per EBD, and taking it for a
    classification is what disagreed with the verified data on 386 codes — in both
    directions: 98 verified approvals shown as rejections, and 77 nodes shown as
    approvals purely because the text was missing."""
    out = _flowchart(result=result)
    assert "ry10:::unknown" in out
    assert "ry10:::accept" not in out and "ry10:::reject" not in out


def test_a_hint_without_a_cluster_prefix_classifies_nothing() -> None:
    out = _flowchart(hint="Das identifizierte Problem ist zu beschreiben.", result="Ablehnung")
    assert "ry10:::unknown" in out


# --- labels and mermaid hygiene ---------------------------------------------------


def test_the_result_text_may_still_name_an_outcome_it_cannot_classify() -> None:
    """A possibly-stale name beats none; a wrong colour asserts what the source did not."""
    out = _flowchart(result="Ablehnung")
    assert 'ry10["A01: Ablehnung"]' in out
    assert "ry10:::unknown" in out


def test_an_outcome_with_neither_keeps_the_bare_code() -> None:
    out = _flowchart()
    assert 'ry10["A01"]' in out


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"result": "Ablehnung"},
        {"cluster": "Zustimmung"},
        {"hint": "Cluster: Änderung der Daten"},
        {"cluster": "etwas Unbekanntes"},
    ],
)
def test_every_class_used_is_defined(kwargs: dict[str, str]) -> None:
    """A mermaid `:::name` with no matching classDef renders unstyled and silently —
    which is how a defect in here goes unnoticed."""
    out = _flowchart(**kwargs)
    assert set(re.findall(r":::(\w+)", out)) <= set(re.findall(r"classDef (\w+)", out))
