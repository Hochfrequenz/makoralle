"""Formatversionen are bundles: which edition of each document an FV holds, and from when."""

import datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from makoralle.models.formatversion import (
    Bundle,
    Formatversionen,
    FormatversionEntry,
    load_bundle,
    load_formatversionen,
    write_json,
)

TABLE = """
default: FV2604
bundles:
  - fv: FV2510
    gueltig_ab: "2025-10-01"
    quelle: "BDEW Veröffentlichung"
  - fv: FV2604
    gueltig_ab: "2026-04-01"
  - fv: FV2610
    gueltig_ab: "2026-10-01"
"""

BUNDLE = """
fv: FV2604
documents:
  gpke_teil1: {file_name: Anlage1a_GPKE_Teil1_Lesefassung.pdf}
  ebd:
    file_name: EBD_4.2_20260401_20260930_20260623_xoxo_12240.pdf
    document_version: "4.2"
    date: "2026-06-23"
    valid_from: "2026-04-01"
    valid_to: "2026-09-30"
"""


def test_the_table_loads_and_knows_its_default(tmp_path: Path) -> None:
    (tmp_path / "formatversionen.yaml").write_text(TABLE, "utf-8")
    table = load_formatversionen(tmp_path / "formatversionen.yaml")
    assert table.default == "FV2604"
    assert [b.fv for b in table.bundles] == ["FV2510", "FV2604", "FV2610"]


@pytest.mark.parametrize(
    ("on", "expected"),
    [
        ("2025-06-01", "FV2510"),
        ("2025-10-01", "FV2510"),
        ("2026-04-01", "FV2604"),
        ("2026-09-11", "FV2604"),
        ("2027-01-01", "FV2610"),
    ],
)
def test_in_force_is_the_newest_bundle_whose_gueltig_ab_has_passed(on: str, expected: str) -> None:
    """Before the first gueltig_ab the oldest bundle is 'in force': there is nothing older to show."""
    table = Formatversionen.model_validate(
        {
            "default": "FV2604",
            "bundles": [
                {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                {"fv": "FV2604", "gueltig_ab": "2026-04-01"},
                {"fv": "FV2610", "gueltig_ab": "2026-10-01"},
            ],
        }
    )
    assert table.in_force(datetime.date.fromisoformat(on)) == expected


def test_the_default_must_be_one_of_the_bundles() -> None:
    with pytest.raises(ValidationError, match="default"):
        Formatversionen.model_validate({"default": "FV2604", "bundles": [{"fv": "FV2510", "gueltig_ab": "2025-10-01"}]})


def test_an_empty_table_is_rejected() -> None:
    """No bundles means no default to point at and nothing for :meth:`in_force` to return."""
    with pytest.raises(ValidationError, match="default"):
        Formatversionen.model_validate({"default": "FV2604", "bundles": []})


def test_bundles_are_sorted_and_unique() -> None:
    with pytest.raises(ValidationError, match="sorted"):
        Formatversionen.model_validate(
            {
                "default": "FV2610",
                "bundles": [
                    {"fv": "FV2610", "gueltig_ab": "2026-10-01"},
                    {"fv": "FV2604", "gueltig_ab": "2026-04-01"},
                ],
            }
        )
    # The same-day/different-FV sub-case is gone: with efoli as source of truth two
    # distinct FVs can never share a gueltig_ab, so that table is unreachable without a
    # disagreeing date — which now dies in the entry's drift check before this check runs.
    with pytest.raises(ValidationError, match="twice"):
        Formatversionen.model_validate(
            {
                "default": "FV2510",
                "bundles": [
                    {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                    {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                ],
            }
        )


@pytest.mark.parametrize("bad", ["FV26", "fv2604", "FV26040", "2604", "FV２６０４"])
def test_a_formatversion_is_fv_plus_four_digits(bad: str) -> None:
    with pytest.raises(ValidationError):
        Bundle.model_validate({"fv": bad, "documents": {}})


def test_a_bundle_names_its_editions(tmp_path: Path) -> None:
    (tmp_path / "bundle.yaml").write_text(BUNDLE, "utf-8")
    bundle = load_bundle(tmp_path / "bundle.yaml")
    assert bundle.fv == "FV2604"
    assert bundle.documents["ebd"].document_version == "4.2"
    assert bundle.documents["gpke_teil1"].date is None


def test_write_json_is_the_yaml_as_the_app_reads_it(tmp_path: Path) -> None:
    """The app's build script is stdlib-only, so the JSON twin is what it consumes."""
    (tmp_path / "bundle.yaml").write_text(BUNDLE, "utf-8")
    dest = tmp_path / "bundle.json"
    bundle = load_bundle(tmp_path / "bundle.yaml")
    write_json(bundle, dest)
    text = dest.read_text("utf-8")
    assert '"fv": "FV2604"' in text and text.endswith("\n")
    assert '"sha256"' not in text  # None fields stay out, the app treats absence as unknown
    assert b"\r\n" not in dest.read_bytes()  # byte-stable wherever it is written
    assert Bundle.model_validate(json.loads(text)) == bundle


def test_write_json_keeps_umlauts_and_typographic_quotes(tmp_path: Path) -> None:
    """The ``quelle`` is German prose; it reaches the JSON twin as written and reads back unchanged."""
    quelle = "„BDEW-Mitteilung“ zur Übergangsregelung – gültig für Änderungen ‚ab sofort‘"
    (tmp_path / "formatversionen.yaml").write_text(
        f"default: FV2604\nbundles:\n  - fv: FV2604\n    gueltig_ab: \"2026-04-01\"\n    quelle: '{quelle}'\n", "utf-8"
    )
    table = load_formatversionen(tmp_path / "formatversionen.yaml")
    assert table.bundles[0].quelle == quelle
    dest = tmp_path / "formatversionen.json"
    write_json(table, dest)
    text = dest.read_text("utf-8")
    assert quelle in text  # not \u-escaped
    assert Formatversionen.model_validate(json.loads(text)) == table


def test_gueltig_ab_is_derived_from_efoli_when_absent() -> None:
    """The table no longer carries hand-maintained dates: efoli is the source of truth."""
    assert FormatversionEntry(fv="FV2510", quelle="x").gueltig_ab == "2025-10-01"
    assert FormatversionEntry(fv="FV2604").gueltig_ab == "2026-04-01"
    assert FormatversionEntry(fv="FV2610").gueltig_ab == "2026-10-01"


def test_a_hand_written_date_that_disagrees_with_efoli_is_rejected() -> None:
    with pytest.raises(ValidationError, match="efoli"):
        FormatversionEntry(fv="FV2510", gueltig_ab="2025-10-02")


def test_an_fv_efoli_does_not_know_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The enum-miss branch, mocked so the pin survives efoli gaining new versions
    (the dependency is a floor pin; a routine lock refresh must not break this test)."""

    def _raise(value: str) -> None:
        raise ValueError(f"{value} is not a valid EdifactFormatVersion")

    monkeypatch.setattr("makoralle.models.formatversion.EdifactFormatVersion", _raise)
    with pytest.raises(ValidationError, match="bump efoli"):
        FormatversionEntry(fv="FV2704")


def test_fv2104_whose_start_efoli_does_not_know_is_rejected() -> None:
    """efoli knows FV2104 but not its start date — a loud failure that does NOT send the
    reader chasing an efoli bump no release can bring (its earliest version has none)."""
    with pytest.raises(ValidationError, match="don't list it in the table"):
        FormatversionEntry(fv="FV2104")


def test_the_drift_check_runs_before_the_table_checks() -> None:
    """Entry validation precedes the table's sorted/unique check: the drift error wins."""
    with pytest.raises(ValidationError, match="efoli"):
        Formatversionen.model_validate(
            {
                "default": "FV2510",
                "bundles": [
                    {"fv": "FV2604", "gueltig_ab": "2026-04-02"},
                    {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                ],
            }
        )


def test_a_derived_table_dumps_and_round_trips() -> None:
    # Constructed via model_validate like every existing table construction in this file.
    table = Formatversionen.model_validate({"default": "FV2604", "bundles": [{"fv": "FV2604"}, {"fv": "FV2610"}]})
    dumped = table.model_dump(mode="json")
    assert dumped["bundles"][0]["gueltig_ab"] == "2026-04-01"
    assert Formatversionen.model_validate(dumped) == table
