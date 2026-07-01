import pytest

from makoralle.ebd_clusters import (
    CLUSTER_KIND,
    EBD_CLUSTER_BACKFILL,
    backfill_cluster,
    cluster_to_kind,
    extract_cluster,
)


def test_extract_cluster_ablehnung() -> None:
    cluster, hint = extract_cluster("Cluster: Ablehnung Es besteht eine Vertragsbindung")
    assert cluster == "Ablehnung"
    assert hint == "Es besteht eine Vertragsbindung"


def test_extract_cluster_zustimmung() -> None:
    cluster, hint = extract_cluster("Cluster: Zustimmung Vertragsverhältnis wurde beendet.")
    assert cluster == "Zustimmung"
    assert hint == "Vertragsverhältnis wurde beendet."


def test_extract_cluster_with_newline_separator() -> None:
    cluster, hint = extract_cluster("Cluster: Ablehnung\nVorlauffrist nicht eingehalten")
    assert cluster == "Ablehnung"
    assert hint == "Vorlauffrist nicht eingehalten"


def test_extract_cluster_no_prefix() -> None:
    cluster, hint = extract_cluster("Just some hint without a cluster prefix")
    assert cluster is None
    assert hint == "Just some hint without a cluster prefix"


def test_extract_cluster_empty() -> None:
    cluster, hint = extract_cluster("")
    assert cluster is None
    assert hint == ""


def test_extract_cluster_none_input() -> None:
    cluster, hint = extract_cluster(None)
    assert cluster is None
    assert hint is None


def test_extract_cluster_ablehnung_auf_kopfebene() -> None:
    cluster, hint = extract_cluster("Cluster: Ablehnung auf Kopfebene Rechnungsdatum liegt in der Zukunft")
    assert cluster == "Ablehnung auf Kopfebene"
    assert hint == "Rechnungsdatum liegt in der Zukunft"


def test_extract_cluster_keine_aenderung_der_daten() -> None:
    # "keine" is NOT a standalone cluster — the full phrase must match.
    cluster, hint = extract_cluster("Cluster: keine Änderung der Daten Der Verantwortliche teilt mit…")
    assert cluster == "keine Änderung der Daten"
    assert hint is not None
    assert hint.startswith("Der Verantwortliche")


def test_extract_cluster_longest_prefix_wins() -> None:
    # Without longest-first matching, this would wrongly match the shorter "Ablehnung".
    cluster, _ = extract_cluster("Cluster: Ablehnung auf Positionsebene Der Preis weicht ab")
    assert cluster == "Ablehnung auf Positionsebene"


def test_extract_cluster_bare_ablehnung_followed_by_explanation() -> None:
    # "Sonstiges Hinweis:" is free text, not a sub-cluster. Bare Ablehnung should match.
    cluster, hint = extract_cluster("Cluster: Ablehnung Sonstiges Hinweis: Das identifizierte Problem…")
    assert cluster == "Ablehnung"
    assert hint is not None
    assert hint.startswith("Sonstiges Hinweis:")


def test_extract_cluster_unknown_vocabulary_returns_none() -> None:
    # A Cluster: prefix followed by a word not in the vocabulary → treat as unknown.
    cluster, hint = extract_cluster("Cluster: NichtInDerListe something here")
    assert cluster is None
    assert hint == "Cluster: NichtInDerListe something here"


@pytest.mark.parametrize(
    "cluster,kind",
    [
        ("Ablehnung", "rejection"),
        ("Ablehnung auf Kopfebene", "rejection"),
        ("Ablehnung auf Positionsebene", "rejection"),
        ("Ablehnung auf Summenebene", "rejection"),
        ("Ablehnung der gesamten Liste", "rejection"),
        ("Abweisung", "rejection"),
        ("gescheitert", "rejection"),
        ("Zustimmung", "approval"),
        ("erfolgreich", "approval"),
        ("Änderung der Daten", "info"),
        ("keine Änderung der Daten", "info"),
        ("Keine Änderung der Daten", "info"),
        ("Korrekturliste wegen Ablehnung", "info"),
        ("SomethingElse", "unknown"),
        (None, "unknown"),
    ],
)
def test_cluster_to_kind(cluster: str | None, kind: str) -> None:
    assert cluster_to_kind(cluster) == kind


def test_backfill_noop_for_unmapped_ebd() -> None:
    step = {"if_no_code": "A01", "if_no_cluster": None, "if_no_hint": "x"}
    backfill_cluster("E_0001", step)
    assert step["if_no_cluster"] is None


def test_backfill_fills_missing_cluster_on_code_branch() -> None:
    step = {
        "if_yes_code": None,
        "if_yes_cluster": None,
        "if_yes_hint": None,
        "if_no_code": "A01",
        "if_no_cluster": None,
        "if_no_hint": "Rechnung nicht bekannt.",
    }
    backfill_cluster("E_0243", step)
    assert step["if_no_cluster"] == "Ablehnung auf Kopfebene"
    # Branch without a code must stay untouched.
    assert step["if_yes_cluster"] is None
    # Hint stays as-is; cluster lives in the structured field.
    assert step["if_no_hint"] == "Rechnung nicht bekannt."


def test_backfill_does_not_overwrite_existing_cluster() -> None:
    step = {"if_no_code": "A01", "if_no_cluster": "Zustimmung", "if_no_hint": "x"}
    backfill_cluster("E_0243", step)
    assert step["if_no_cluster"] == "Zustimmung"


def test_backfill_covers_all_12_remadv_ebds_from_issue_5() -> None:
    expected = {
        "E_0243",
        "E_0261",
        "E_0272",
        "E_0275",
        "E_0459",
        "E_0505",
        "E_0506",
        "E_0518",
        "E_0522",
        "E_0569",
        "E_0804",
        "E_0806",
    }
    assert expected <= set(EBD_CLUSTER_BACKFILL.keys())
    for ebd_id in expected:
        assert EBD_CLUSTER_BACKFILL[ebd_id] == "Ablehnung auf Kopfebene"


def test_cluster_kind_table_includes_known_minimum() -> None:
    required = {
        "Ablehnung",
        "Abweisung",
        "gescheitert",
        "Zustimmung",
        "erfolgreich",
        "Änderung der Daten",
        "Korrekturliste wegen Ablehnung",
        "keine Änderung der Daten",
        "Keine Änderung der Daten",
        "Ablehnung auf Kopfebene",
        "Ablehnung auf Positionsebene",
        "Ablehnung auf Summenebene",
        "Ablehnung der gesamten Liste",
    }
    assert required <= set(CLUSTER_KIND.keys())
