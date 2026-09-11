"""``format_version`` meant the document's own version ("4.1"); now that a real Formatversion
("FV2604") exists on the same record, the old name is a misnomer. One release keeps it as an
input alias so every committed record still loads."""

import warnings

import pytest
from pydantic import ValidationError

from makoralle.models.codeliste import Codeliste
from makoralle.models.ebd import DecisionTree
from makoralle.models.source import SourceDocument


def _edition(document_version: str | None) -> SourceDocument:
    return SourceDocument(file_name="EBD_und_Codelisten_4_1.pdf", document_version=document_version)


def test_new_name_on_construction_and_dump() -> None:
    tree = DecisionTree(id="E_0401", name="x", document_version="4.2", formatversion="FV2604")
    dumped = tree.model_dump()
    assert dumped["document_version"] == "4.2" and dumped["formatversion"] == "FV2604"
    assert "format_version" not in dumped


def test_codeliste_new_name_on_construction_and_dump() -> None:
    liste = Codeliste(id="S_0055", name="x", codes=[], document_version="4.2", formatversion="FV2604")
    dumped = liste.model_dump()
    assert dumped["document_version"] == "4.2" and dumped["formatversion"] == "FV2604"
    assert "format_version" not in dumped


def test_the_renamed_fields_stay_where_format_version_was() -> None:
    """Moving them would reorder the keys of every committed tree and list in the dataset."""
    tree_keys = list(DecisionTree(id="E_0401", name="x").model_dump())
    assert tree_keys[tree_keys.index("note") + 1 : tree_keys.index("steps")] == [
        "document_version",
        "formatversion",
        "source_document",
    ]
    liste_keys = list(Codeliste(id="S_0055", name="x", codes=[]).model_dump())
    assert liste_keys[liste_keys.index("ebd_name") + 1 : liste_keys.index("codes")] == [
        "document_version",
        "formatversion",
        "source_document",
    ]


def test_old_key_still_validates_into_the_new_field() -> None:
    tree = DecisionTree.model_validate({"id": "E_0401", "name": "x", "format_version": "4.1"})
    assert tree.document_version == "4.1"
    assert "format_version" not in tree.model_dump()
    liste = Codeliste.model_validate({"id": "S_0055", "name": "x", "codes": [], "format_version": "4.1"})
    assert liste.document_version == "4.1"
    assert "format_version" not in liste.model_dump()


def test_old_attribute_reads_through_with_a_deprecation_warning() -> None:
    tree = DecisionTree(id="E_0401", name="x", document_version="4.1")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert tree.format_version == "4.1"
    assert caught and issubclass(caught[0].category, DeprecationWarning)
    assert "DecisionTree.format_version is now document_version" in str(caught[0].message)


def test_codeliste_old_attribute_reads_through_with_a_deprecation_warning() -> None:
    liste = Codeliste(id="S_0055", name="x", codes=[], document_version="4.1")
    with pytest.warns(DeprecationWarning, match="Codeliste.format_version is now document_version"):
        assert liste.format_version == "4.1"


def test_formatversion_is_validated() -> None:
    with pytest.raises(ValidationError):
        DecisionTree(id="E_0401", name="x", formatversion="4.1")
    with pytest.raises(ValidationError):
        Codeliste(id="S_0055", name="x", codes=[], formatversion="4.1")


def test_a_tree_whose_version_disagrees_with_its_edition_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"E_0401.*'4\.2'.*'4\.1'"):
        DecisionTree(id="E_0401", name="x", document_version="4.2", source_document=_edition("4.1"))


def test_a_codeliste_whose_version_disagrees_with_its_edition_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"S_0055.*'4\.2'.*'4\.1'"):
        Codeliste(id="S_0055", name="x", codes=[], document_version="4.2", source_document=_edition("4.1"))


@pytest.mark.parametrize(
    ("document_version", "edition"),
    [("4.1", None), ("4.1", _edition(None)), (None, _edition("4.1")), ("4.1", _edition("4.1")), (None, None)],
)
def test_versions_that_do_not_contradict_each_other_are_accepted(
    document_version: str | None, edition: SourceDocument | None
) -> None:
    tree = DecisionTree(id="E_0401", name="x", document_version=document_version, source_document=edition)
    assert tree.document_version == document_version
    liste = Codeliste(id="S_0055", name="x", codes=[], document_version=document_version, source_document=edition)
    assert liste.document_version == document_version
