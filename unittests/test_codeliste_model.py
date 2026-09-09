"""The Codeliste model: a flat answer-code table, as chapter 8/11 of the EBD document ships it."""

import pytest

from makoralle.models.codeliste import CodeEntry, Codeliste


def test_code_entry_carries_the_document_columns() -> None:
    entry = CodeEntry(
        code="E17",
        nutzung="O",
        name="Ablehnung wg. Fristüberschreitung",
        description="Der Absender lehnt die Transaktion ab.",
        kind="rejection",
    )
    assert entry.code == "E17"
    assert entry.nutzung == "O"
    assert entry.bedingung is None
    assert entry.kind == "rejection"


def test_code_entry_keeps_a_bedingung_when_the_table_has_that_column() -> None:
    entry = CodeEntry(
        code="Z01",
        nutzung="O [40]",
        bedingung="[40] Wenn SG4 STS+7++E02 (Transaktionsgrund: Einzug in eine Neuanlage) vorhanden",
        name="Zustimmung mit Terminänderung",
    )
    assert entry.bedingung is not None
    assert entry.bedingung.startswith("[40]")
    assert entry.kind == "unknown"


def test_codeliste_carries_its_parent_ebd() -> None:
    liste = Codeliste(
        id="S_0056",
        name="Ablehnung Anmeldung MSB",
        source="EBD und Codelisten 4.1, Seite 540-540",
        ebd_id="E_0201",
        codes=[CodeEntry(code="E11", nutzung="O", name="Ablehnung (Messproblem)")],
    )
    assert liste.id == "S_0056"
    assert liste.ebd_id == "E_0201"
    assert len(liste.codes) == 1


def test_codeliste_without_a_parent_section_is_allowed() -> None:
    """S_0086/S_0087 sit directly under `AD: Stornierung`, with no EBD between."""
    liste = Codeliste(id="S_0086", name="Bestätigung Anfrage Stornierung", codes=[])
    assert liste.ebd_id is None
    assert liste.source == ""


def test_codeliste_requires_an_id() -> None:
    with pytest.raises(ValueError):
        Codeliste(name="nameless", codes=[])  # type: ignore[call-arg]
