"""An edition is one published file: version, validity window, the bytes themselves."""

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
    assert (doc.document_version, doc.valid_from, doc.valid_to) == ("4.2", "2026-04-01", "2026-09-30")


def test_the_old_two_field_shape_still_loads() -> None:
    """Every committed EBD record carries only file_name + date; they must keep loading."""
    doc = SourceDocument.model_validate({"file_name": "EBD.pdf", "date": "2026-01-16"})
    assert doc.document_version is None and doc.valid_from is None and doc.sha256 is None


@pytest.mark.parametrize("bad", ["abc", "A" * 64, "0" * 63])
def test_a_hash_is_64_lowercase_hex_characters(bad: str) -> None:
    with pytest.raises(ValidationError):
        SourceDocument(file_name="x.pdf", sha256=bad)
