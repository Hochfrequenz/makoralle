"""Which marker spelling makes a section a use case (makoralle#28).

`grouping` keyed on the literal ``"UC:"``. The documents are not consistent about it: measured over
the 379 headings of `BK6-24-174_MaBiS_Lesefassung.pdf`, ``UC:`` appears 101 times (the leaf
section), ``Use-Case:`` 104 times (its parent, and the *only* marker on four use cases), and
``Use Case:`` once. A use case whose only marker is the long spelling got no grouping entry at all,
so its SDs fell back to fuzzy matching.

The leaf spelling stays the primary key on purpose: a normal use case has both, and the leaf is the
canonical section p07 keeps. The long spelling is a fallback for a parent with no leaf below it —
otherwise every use case would produce two keys, one per spelling, which is a far bigger change than
the four sections this is about.
"""

import logging
from typing import Any

import pytest

from makoralle.grouping import UC_HEADING_MARKER, uc_process_id, uc_sd_section_groups


def _sections(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {"sections": [{"section_id": sid, "heading": heading} for sid, heading in pairs]}


def test_the_leaf_spelling_still_keys_the_group() -> None:
    """The shape of nearly every use case in the corpus, and it must not move."""
    groups = uc_sd_section_groups(
        _sections(
            ("6.5", "6.5 Use-Case: Übermittlung von normierten Profilen"),
            ("6.5.1", "6.5.1 UC: Übermittlung von normierten Profilen"),
            ("6.5.2", "6.5.2 SD: Übermittlung von normierten Profilen"),
        )
    )
    assert list(groups) == ["übermittlung_von_normierten_profilen"]
    assert [s["section_id"] for s in groups["übermittlung_von_normierten_profilen"]] == ["6.5.2"]


def test_a_use_case_whose_only_marker_is_the_long_spelling_gets_its_group() -> None:
    """MaBiS 6.8, 8.5 and 12.4: the parent carries ``Use-Case:`` and no child carries ``UC:``.

    Its SD is a *child* of the marked section rather than a sibling, so this one keys on the
    section's own id — which is what the SD's parent id points at.
    """
    groups = uc_sd_section_groups(
        _sections(
            ("6.8", "6.8 Use-Case: Übermittlung von normierten Profilen vom NB an MSB"),
            ("6.8.1", "6.8.1 von normierten Profilen vom NB an MSB"),
            ("6.8.2", "6.8.2 SD: Übermittlung von normierten Profilen vom NB an MSB"),
        )
    )
    assert list(groups) == ["übermittlung_von_normierten_profilen_vom_nb_an_msb"]
    assert [s["section_id"] for s in groups["übermittlung_von_normierten_profilen_vom_nb_an_msb"]] == ["6.8.2"]


def test_a_child_marker_without_a_colon_does_not_claim_the_group() -> None:
    """MaBiS 12.4.1 reads "UC Austausch …" with no colon, so the parent's ``Use-Case:`` is still the
    only marker — a colon-less child must not be mistaken for the leaf and steal the key."""
    groups = uc_sd_section_groups(
        _sections(
            ("12.4", "12.4 Use-Case: Austausch der Deltazeitreihenübertrag-Liste von ÜNB an NB"),
            ("12.4.1", "12.4.1 UC Austausch der Deltazeitreihenübertrag-Liste von ÜNB an NB"),
            ("12.4.2", "12.4.2 SD: Austausch der Deltazeitreihenübertrag-Liste von ÜNB an NB"),
        )
    )
    assert list(groups) == ["austausch_der_deltazeitreihenübertrag-liste_von_ünb_an_nb"]


def test_a_use_case_with_both_spellings_produces_one_group_not_two() -> None:
    """The reason the long spelling is a fallback and not simply an alternative."""
    groups = uc_sd_section_groups(
        _sections(
            ("6.5", "6.5 Use-Case: Etwas"),
            ("6.5.1", "6.5.1 UC: Etwas"),
            ("6.5.2", "6.5.2 SD: Etwas"),
            ("6.6", "6.6 Use-Case: Anderes"),
            ("6.6.1", "6.6.1 UC: Anderes"),
        )
    )
    assert sorted(groups) == ["anderes", "etwas"]


def test_the_id_is_the_name_after_the_last_marker_whichever_spelling_it_is() -> None:
    """``split("UC:")[-1]`` returned the *whole* heading for a ``Use-Case:`` one — number, marker
    and all — so the slug it derived was not the id anything else uses."""
    assert uc_process_id("6.5.1 UC: Etwas Wichtiges") == "etwas_wichtiges"
    assert uc_process_id("6.8 Use-Case: Etwas Wichtiges") == "etwas_wichtiges"
    assert uc_process_id("10.2 Use Case: Etwas Wichtiges") == "etwas_wichtiges"
    assert uc_process_id("6.5 USE-CASE: Etwas Wichtiges") == "etwas_wichtiges"


def test_a_heading_with_no_marker_keeps_its_whole_text() -> None:
    """The historical fallback: no marker, no cut. Callers that need to know check the marker."""
    assert uc_process_id("8.5.1 Austausch der Liste") == "8_5_1_austausch_der_liste"
    assert not UC_HEADING_MARKER.search("8.5.1 Austausch der Liste")


def test_a_leaf_does_not_claim_its_own_subtree() -> None:
    """The leaf form groups its SDs as *siblings*, and that is deliberate.

    Letting a leaf also claim its own children would attach an SD nested one level deeper — which
    the documents do use for the long-spelling parents (6.8.2 under 6.8) but not for the leaf form.
    Whether the leaf should accept both shapes is a separate question with corpus consequences, so
    the current relationship is pinned rather than widened by accident.
    """
    groups = uc_sd_section_groups(
        _sections(
            ("6.5", "6.5 Use-Case: Etwas"),
            ("6.5.1", "6.5.1 UC: Etwas"),
            ("6.5.1.1", "6.5.1.1 SD: Etwas"),
        )
    )
    assert groups == {"etwas": []}


def test_the_long_spelling_yields_to_a_leaf_further_down_the_subtree() -> None:
    """The claim check is not "same parent": a leaf can sit two levels below the long-spelling
    section, and then the long spelling must still not open a second group over the same use case."""
    # The two headings word the use case differently — which 10 of the 14 MaBiS misses do — so a
    # second group is visible as a second *key*, not just as a duplicate of the first.
    groups = uc_sd_section_groups(
        _sections(
            ("6.5", "6.5 Use-Case: Etwas"),
            ("6.5.1", "6.5.1 Vorbemerkung"),
            ("6.5.1.1", "6.5.1.1 UC: Etwas Genauer"),
            ("6.5.1.2", "6.5.1.2 SD: Etwas Genauer"),
        )
    )
    assert list(groups) == ["etwas_genauer"]
    assert [s["section_id"] for s in groups["etwas_genauer"]] == ["6.5.1.2"]


def test_the_leaf_marker_tolerates_the_spacing_and_case_the_toc_uses() -> None:
    """The table of contents prints headings upper-cased, and the extraction leaves a space before
    the colon often enough that a literal ``"UC:"`` misses the leaf and the parent claims it."""
    # Again with two different names, so that missing the leaf shows up as the *wrong key* rather
    # than as an indistinguishable duplicate: the id comes from the leaf, not from its parent.
    groups = uc_sd_section_groups(
        _sections(
            ("6.5", "6.5 Use-Case: Etwas"),
            ("6.5.1", "6.5.1 uc : Etwas Genauer"),
            ("6.5.2", "6.5.2 SD: Etwas Genauer"),
        )
    )
    assert list(groups) == ["etwas_genauer"]
    assert [s["section_id"] for s in groups["etwas_genauer"]] == ["6.5.2"]


def test_a_numeric_neighbour_is_not_a_descendant() -> None:
    """`6.10` is not below `6.1`, and the trailing dot in the subtree check is what says so.

    Review found this revertible with a green suite: with `startswith(section_id)` instead of
    `startswith(f"{section_id}.")`, the use case at 6.1 sees 6.10's claimed leaf as its own and
    yields — so its group, its process id and its diagram disappear, and its SD falls back to fuzzy
    matching. Losing a process to its numeric neighbour is the regression this whole change exists
    to avoid.
    """
    groups = uc_sd_section_groups(
        _sections(
            ("6.1", "6.1 Use-Case: Alpha"),
            ("6.1.2", "6.1.2 SD: Alpha"),
            ("6.10", "6.10 Use-Case: Beta"),
            ("6.10.1", "6.10.1 UC: Beta"),
            ("6.10.2", "6.10.2 SD: Beta"),
        )
    )
    assert sorted(groups) == ["alpha", "beta"]
    assert [s["section_id"] for s in groups["alpha"]] == ["6.1.2"]
    assert [s["section_id"] for s in groups["beta"]] == ["6.10.2"]


def test_two_nested_fallback_sections_do_not_depend_on_the_order_they_arrive_in() -> None:
    """The fallback loop appends to the same dict its guard reads, so a live read makes the answer
    depend on section order — and the real segmented documents are not ordered (MaBiS has 6
    backwards section-id transitions, WiM Teil 2 has 9). Snapshotting the leaf pass's keys makes
    both orders answer the same.
    """
    pairs = [
        ("6.8", "6.8 Use-Case: Outer"),
        ("6.8.2", "6.8.2 Use-Case: Inner"),
        ("6.8.2.1", "6.8.2.1 SD: Inner"),
        ("6.8.3", "6.8.3 SD: Outer"),
    ]
    forward = uc_sd_section_groups(_sections(*pairs))
    backward = uc_sd_section_groups(_sections(*reversed(pairs)))
    assert forward == backward
    assert sorted(forward) == ["inner", "outer"]


def test_two_use_cases_that_slug_the_same_are_reported(caplog: pytest.LogCaptureFixture) -> None:
    """One group where the documents describe two processes — silent before, because `out` is keyed
    by slug and the second simply appended to the first."""
    with caplog.at_level(logging.WARNING, logger="makoralle.grouping"):
        groups = uc_sd_section_groups(
            _sections(
                ("3.1", "3.1 Use-Case: Anmeldung"),
                ("3.1.1", "3.1.1 UC: Anmeldung"),
                ("3.1.2", "3.1.2 SD: Anmeldung"),
                ("9.4", "9.4 Use-Case: Anmeldung"),
                ("9.4.1", "9.4.1 SD: Anmeldung Variante"),
            )
        )
    assert list(groups) == ["anmeldung"]
    assert [record for record in caplog.records if "slug the same" in record.message or "slug to" in record.message]
