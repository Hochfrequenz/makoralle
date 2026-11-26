"""The process-level Sparte: the model field, the bundle's tables, and the YAML round trip."""

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from makoralle.models.formatversion import Bundle
from makoralle.models.process import Process
from makoralle.models.source import SourceDocument
from makoralle.serialization.process_yaml import process_from_yaml, process_to_yaml

DOCS = {
    "gpke_teil1": SourceDocument(file_name="a.pdf"),
    "mmma": SourceDocument(file_name="b.pdf"),
    "geli_gas": SourceDocument(file_name="c.pdf"),
}


def _process(sparte: Any = None) -> Process:
    return Process.model_validate(
        {"id": "lieferbeginn", "name": "Lieferbeginn", "source": "GPKE", "category": "GPKE", "sparte": sparte}
    )


def test_sparte_is_optional_and_absent_by_default() -> None:
    assert _process().sparte is None
    assert "sparte" not in yaml.safe_load(process_to_yaml(_process()))["process"]


@pytest.mark.parametrize("sparte", ["strom", "gas"])
def test_sparte_round_trips_under_the_process_key(sparte: str) -> None:
    text = process_to_yaml(_process(sparte=sparte))
    assert yaml.safe_load(text)["process"]["sparte"] == sparte
    assert process_from_yaml(text).sparte == sparte


@pytest.mark.parametrize("bad", ["Strom", "GAS", "wasser", ""])
def test_sparte_rejects_anything_but_the_two_lowercase_values(bad: str) -> None:
    with pytest.raises(ValidationError):
        _process(sparte=bad)


def test_bundle_tables_default_to_empty() -> None:
    bundle = Bundle(fv="FV2604", documents=DOCS)
    assert bundle.sparten == {} and bundle.sparte_overrides == {}
    assert bundle.sparte_for("gpke_teil1", "lieferbeginn") is None


def test_sparte_for_reads_the_document_then_lets_the_override_win() -> None:
    bundle = Bundle(
        fv="FV2604",
        documents=DOCS,
        sparten={"gpke_teil1": "strom", "mmma": "strom", "geli_gas": "gas"},
        sparte_overrides={"abonnieren_der_marktlokationsscharfen_allokationsliste_gas": "gas"},
    )
    assert bundle.sparte_for("gpke_teil1", "lieferbeginn") == "strom"
    assert bundle.sparte_for("geli_gas", "lieferbeginn_gas") == "gas"
    assert bundle.sparte_for("mmma", "abonnieren_der_marktlokationsscharfen_allokationsliste_gas") == "gas"
    # An override applies whatever the document, and a missing document gives None.
    assert bundle.sparte_for(None, "abonnieren_der_marktlokationsscharfen_allokationsliste_gas") == "gas"
    assert bundle.sparte_for(None, "lieferbeginn") is None
    assert bundle.sparte_for("ebd", "lieferbeginn") is None


def test_sparten_must_name_document_keys() -> None:
    with pytest.raises(ValidationError, match="gpke_teil_1"):
        Bundle(fv="FV2604", documents=DOCS, sparten={"gpke_teil_1": "strom"})


def test_sparten_reject_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Bundle.model_validate({"fv": "FV2604", "documents": DOCS, "sparten": {"gpke_teil1": "Strom"}})
    with pytest.raises(ValidationError):
        Bundle.model_validate({"fv": "FV2604", "documents": DOCS, "sparte_overrides": {"x": "wasser"}})


def test_a_bare_header_is_rejected_as_for_categories() -> None:
    with pytest.raises(ValidationError):
        Bundle.model_validate({"fv": "FV2604", "documents": DOCS, "sparten": None})


def test_category_for_reads_the_document_then_lets_the_override_win() -> None:
    bundle = Bundle(
        fv="FV2510",
        documents=DOCS,
        categories={"mmma": "GPKE", "gpke_teil1": "GPKE"},
        category_overrides={"abonnieren_der_marktlokationsscharfen_allokationsliste_gas": "GeLi Gas"},
    )
    assert bundle.category_for("mmma", "lieferbeginn") == "GPKE"
    # The label need not be a row of the table (FV2510 has no GeLi Gas document).
    assert bundle.category_for("mmma", "abonnieren_der_marktlokationsscharfen_allokationsliste_gas") == "GeLi Gas"
    assert bundle.category_for(None, "abonnieren_der_marktlokationsscharfen_allokationsliste_gas") == "GeLi Gas"
    assert bundle.category_for(None, "lieferbeginn") == ""
    assert bundle.category_for("geli_gas", "lieferbeginn") == ""


def test_category_overrides_default_empty_and_change_nothing() -> None:
    bundle = Bundle(fv="FV2604", documents=DOCS, categories={"mmma": "GPKE"})
    assert bundle.category_overrides == {}
    assert bundle.category_for("mmma", "x") == "GPKE"


@pytest.mark.parametrize("bad", ["GeLi Gass", "geli gas", "GeLi  Gas", "Gas"])
def test_category_overrides_reject_a_misspelt_label(bad: str) -> None:
    with pytest.raises(ValidationError):
        Bundle.model_validate({"fv": "FV2604", "documents": DOCS, "category_overrides": {"x": bad}})


@pytest.mark.parametrize("bad", ["", "   "])
def test_category_overrides_reject_blank_labels_and_bare_header(bad: str) -> None:
    with pytest.raises(ValidationError):
        Bundle.model_validate({"fv": "FV2604", "documents": DOCS, "category_overrides": {"x": bad}})
    with pytest.raises(ValidationError):
        Bundle.model_validate({"fv": "FV2604", "documents": DOCS, "category_overrides": None})


def test_category_overrides_round_trip_through_yaml() -> None:
    bundle = Bundle(fv="FV2604", documents=DOCS, category_overrides={"übermittlung_x": "GeLi Gas"})
    text = yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True)
    assert Bundle.model_validate(yaml.safe_load(text)) == bundle
