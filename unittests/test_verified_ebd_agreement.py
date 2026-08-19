"""A ratchet: EBD outcome classification may never agree less with the verified source.

`Hochfrequenz/machine-readable_entscheidungsbaumdiagramme` carries every EBD verified from
an independent source (ebdamame + rebdhuhn). `fixtures/verified_ebd_outcome_kinds.json`
pairs, for each answer code this pipeline also has, the inputs available here (the
resolved cluster field, the Hinweis text, the result text) with the kind that repo
assigns — pinned at commit 834fd748cca1b51c37e883d8beb67001247bd552, FV2604:

    https://github.com/Hochfrequenz/machine-readable_entscheidungsbaumdiagramme/tree/834fd748cca1b51c37e883d8beb67001247bd552/FV2604

Reaching 100 % needs more than this module can do — part of the residue is genuinely
missing data upstream (Hochfrequenz/makorele#68) and part is Formatversion skew between
the two corpora. What this test guarantees is the thing that matters in the meantime:
**it cannot get worse.** Raise `MINIMUM_AGREEMENT` when a change earns it; never lower it.

For the record, the rules measured against this fixture:

    the result text, by substring ("ablehnung")    57 %   <- what shipped before makoralle#29
    cluster, falling back to the result text       72 %
    cluster only, else unknown                     92 %   <- current

Long run, this homebrew EBD path should give way to that toolchain entirely —
Hochfrequenz/mako_prozesse#1.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

from makoralle.serialization.markdown import _outcome_cluster, _outcome_kind

FIXTURE = Path(__file__).parent / "fixtures" / "verified_ebd_outcome_kinds.json"

#: Matches out of 1407 verified answer codes, as measured when this test was written.
MINIMUM_AGREEMENT = 1298


def _cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    return cases


def _classify(case: dict[str, Any]) -> str:
    cluster = _outcome_cluster(case["cluster"], case["hint"])
    return _outcome_kind(cluster, case["result"])


def test_agreement_with_the_verified_ebds_does_not_regress() -> None:
    cases = _cases()
    matches = sum(1 for c in cases if _classify(c) == c["verified_kind"])
    assert matches >= MINIMUM_AGREEMENT, (
        f"agreement with the verified EBDs dropped to {matches}/{len(cases)}, "
        f"below the {MINIMUM_AGREEMENT} recorded here"
    )


def test_no_verified_approval_is_rendered_as_a_rejection() -> None:
    """The direction that misleads worst: telling a reader a branch was refused when the
    source says it was agreed. 98 codes were in this state before makoralle#29."""
    wrong = [c for c in _cases() if c["verified_kind"] == "approval" and _classify(c) == "rejection"]
    assert not wrong, f"{len(wrong)} verified approvals classified as rejections, e.g. {wrong[:3]}"


def test_no_verified_rejection_is_rendered_as_an_approval() -> None:
    """The other direction: 91 codes were in this state before makoralle#29."""
    wrong = [c for c in _cases() if c["verified_kind"] == "rejection" and _classify(c) == "approval"]
    assert not wrong, f"{len(wrong)} verified rejections classified as approvals, e.g. {wrong[:3]}"


def test_the_result_text_alone_never_decides() -> None:
    """Every case where this pipeline has no cluster at all must come out `unknown` —
    that is what took agreement from 72 % to 92 %."""
    for case in _cases():
        if not _outcome_cluster(case["cluster"], case["hint"]):
            assert _classify(case) == "unknown", case


def test_the_fixture_still_describes_a_real_disagreement() -> None:
    """If the fixture ever became all-agreeing the ratchet would be vacuous."""
    kinds = Counter(c["verified_kind"] for c in _cases())
    assert kinds["approval"] and kinds["rejection"] and kinds["info"], kinds
    mismatches = sum(1 for c in _cases() if _classify(c) != c["verified_kind"])
    assert mismatches, "no mismatch left — raise MINIMUM_AGREEMENT and delete this test"
