"""Deriving a code entry's kind, where the document gives no `Cluster:` prefix.

A Codeliste row has no cluster classifier, so the kind comes from the German wording:
the row's own name where it says one, and otherwise the list's name — which is what
makes `ZB6 Erforderliche Versicherung fehlt` a rejection: it sits in
`S_0056_Ablehnung Anmeldung MSB`, and every code in an Ablehnung list rejects.
"""

import pytest

from makoralle.ebd_clusters import derive_code_kind


@pytest.mark.parametrize(
    ("entry_name", "expected"),
    [
        ("Ablehnung (Messproblem)", "rejection"),
        ("Ablehnung wg. Fristüberschreitung", "rejection"),
        ("Abweisung der Anfrage", "rejection"),
        ("Zustimmung ohne Korrekturen", "approval"),
        ("Zustimmung mit Terminänderung", "approval"),
        ("Bestätigung der Anforderung", "approval"),
    ],
)
def test_the_rows_own_wording_decides(entry_name: str, expected: str) -> None:
    assert derive_code_kind(entry_name, list_name="irrelevant") == expected


def test_a_silent_row_inherits_the_lists_wording() -> None:
    assert derive_code_kind("Erforderliche Versicherung fehlt", list_name="Ablehnung Anmeldung MSB") == "rejection"


def test_a_silent_row_in_a_bestaetigung_list_is_an_approval() -> None:
    assert derive_code_kind("MSB-Scheitermeldung liegt vor", list_name="Bestätigung Ende MSB") == "approval"


def test_a_statusmeldung_is_information() -> None:
    assert derive_code_kind("MSB-Scheitermeldung liegt vor", list_name="Statusmeldung") == "info"


def test_nothing_recognisable_stays_unknown() -> None:
    assert derive_code_kind("Sonstiges", list_name="Weitere Bearbeitung prüfen") == "unknown"


def test_the_row_outranks_the_list() -> None:
    """An Ablehnung row inside a Bestätigung list is still a rejection."""
    assert derive_code_kind("Ablehnung (keine Zuordnung möglich)", list_name="Bestätigung Anmeldung MSB") == "rejection"
