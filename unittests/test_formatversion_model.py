"""Formatversionen are bundles: which edition of each document an FV holds, and from when."""

import datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from makoralle.models.formatversion import (
    Bundle,
    Formatversionen,
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
                "default": "FV2510",
                "bundles": [
                    {"fv": "FV2604", "gueltig_ab": "2026-04-01"},
                    {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                ],
            }
        )
    with pytest.raises(ValidationError, match="sorted"):
        Formatversionen.model_validate(
            {
                "default": "FV2510",
                "bundles": [
                    {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                    {"fv": "FV2604", "gueltig_ab": "2025-10-01"},
                ],
            }
        )
    with pytest.raises(ValidationError, match="twice"):
        Formatversionen.model_validate(
            {
                "default": "FV2510",
                "bundles": [
                    {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                    {"fv": "FV2510", "gueltig_ab": "2025-10-02"},
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
