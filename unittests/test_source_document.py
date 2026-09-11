"""An edition is one published file: version, validity window, the bytes themselves."""

import datetime

import pytest
from pydantic import ValidationError

from makoralle.models.source import SourceDocument


def test_an_edition_carries_version_validity_and_hash() -> None:
    doc = SourceDocument(
        file_name="EBD_4.2_20260401_20260930_20260623_xoxo_12240.pdf",
        date="2026-06-23",
        document_version="4.2",
        valid_from="2026-04-01",
        valid_to="2026-09-30",
        sha256="a" * 64,
    )
    assert (doc.date, doc.document_version, doc.valid_from, doc.valid_to, doc.sha256) == (
        "2026-06-23",
        "4.2",
        "2026-04-01",
        "2026-09-30",
        "a" * 64,
    )


def test_the_old_two_field_shape_still_loads() -> None:
    """Every committed EBD record carries only file_name + date; they must keep loading."""
    doc = SourceDocument.model_validate({"file_name": "EBD.pdf", "date": "2026-01-16"})
    assert doc.document_version is None and doc.valid_from is None and doc.sha256 is None


@pytest.mark.parametrize("bad", ["abc", "A" * 64, "0" * 63])
def test_a_hash_is_64_lowercase_hex_characters(bad: str) -> None:
    with pytest.raises(ValidationError):
        SourceDocument(file_name="x.pdf", sha256=bad)


def test_unquoted_yaml_dates_in_the_validity_window_come_back_as_iso_strings() -> None:
    """Hand-written bundle YAML carries unquoted dates, which a YAML 1.1 loader reads as ``date``."""
    doc = SourceDocument.model_validate(
        {"file_name": "x", "valid_from": datetime.date(2026, 4, 1), "valid_to": datetime.date(2026, 9, 30)}
    )
    assert (doc.valid_from, doc.valid_to) == ("2026-04-01", "2026-09-30")


def test_a_validity_window_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(ValidationError, match=r"2026-09-30.*2026-04-01"):
        SourceDocument(file_name="x.pdf", valid_from="2026-09-30", valid_to="2026-04-01")


@pytest.mark.parametrize(("valid_from", "valid_to"), [("2026-04-01", "2026-04-01"), ("2026-04-01", "9999-12-31")])
def test_a_one_day_window_and_an_open_end_are_both_ordered(valid_from: str, valid_to: str) -> None:
    doc = SourceDocument(file_name="x.pdf", valid_from=valid_from, valid_to=valid_to)
    assert (doc.valid_from, doc.valid_to) == (valid_from, valid_to)
