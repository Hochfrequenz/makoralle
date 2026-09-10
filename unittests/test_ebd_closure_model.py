"""The EBD model can say where every branch ends, and why an ``E_`` id has no tree.

Dataset v0.0.29 shipped 146 branch targets that were no step and 281 branches that ended nowhere
(machine-readable_mako-prozesse#65), and 20 referenced ``E_`` ids with no file at all (#66). The
parser repairs are makorele's; these fields are what lets the result be stated rather than implied.
"""

import datetime
from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

from makoralle.models.codeliste import CodeEntry, Codeliste
from makoralle.models.ebd import BRANCH_FIELDS, DecisionStep, DecisionTree, StepRef, TreeKind
from makoralle.models.source import SourceDocument

EBD_4_1 = SourceDocument(file_name="EBD_und_Codelisten_4_1_Fehlerkorrektur_20260116.pdf", date="2026-01-16")


def test_a_v0_0_29_step_still_loads_and_gains_nothing() -> None:
    """Every new field defaults, so a file written before them reads back unchanged."""
    shipped = {"nr": 10, "check": "Ist die Marktlokation bekannt?", "if_yes": 20, "if_no_code": "A01"}
    step = DecisionStep.model_validate(shipped)
    assert step.next is None
    assert step.if_yes_sunset is None and step.if_no_sunset is None
    assert step.refs is None
    assert step.kind is None
    assert step.model_dump(exclude_none=True) == shipped


def test_a_v0_0_29_tree_still_loads_as_a_tree() -> None:
    tree = DecisionTree.model_validate({"id": "E_0622", "name": "Prüfen", "steps": [{"nr": 10, "check": "x"}]})
    assert tree.kind == "tree"
    assert tree.codelisten is None and tree.use_ebd is None and tree.note is None
    assert tree.format_version is None and tree.source_document is None


def test_an_unconditional_row_carries_next_and_no_branch() -> None:
    """E_0594 105: '[Adressprüfung] … → 110' has no ja/nein to put the target under."""
    step = DecisionStep(nr=105, check="[Adressprüfung]", next=110)
    assert step.next == 110
    assert step.if_yes is None and step.if_no is None


@pytest.mark.parametrize("sunset", ["2026-04-01T00:00", "offen"])
def test_a_branch_carries_its_sunset(sunset: str) -> None:
    step = DecisionStep(nr=60, check="Ist ein Fehler aufgetreten?", if_yes_code="A99", if_yes_sunset=sunset)
    assert step.if_yes_sunset == sunset
    assert step.if_no_sunset is None


@pytest.mark.parametrize("kind", ["segment", "answer_code", "frist", "date"])
def test_a_step_ref_of_every_kind_is_accepted(kind: str) -> None:
    ref = StepRef.model_validate({"kind": kind, "text": "SG5 LOC+Z22"})
    assert ref.kind == kind


@pytest.mark.parametrize("kind", ["", "qualifier", "Segment", "code"])
def test_a_step_ref_of_an_unknown_kind_is_refused(kind: str) -> None:
    with pytest.raises(ValidationError):
        StepRef.model_validate({"kind": kind, "text": "A30"})


@pytest.mark.parametrize("kind", ["message_content", "process_history", "external"])
def test_a_curated_step_kind_is_accepted(kind: str) -> None:
    assert DecisionStep.model_validate({"nr": 1, "check": "x", "kind": kind}).kind == kind


@pytest.mark.parametrize("kind", ["", "message-content", "tree"])
def test_a_step_kind_outside_the_curated_set_is_refused(kind: str) -> None:
    with pytest.raises(ValidationError):
        DecisionStep.model_validate({"nr": 1, "check": "x", "kind": kind})


def test_a_codelist_only_stub_names_its_lists_and_has_no_steps() -> None:
    """8.2.1 E_0201 holds S_0055 and S_0056 and nothing else."""
    stub = DecisionTree(
        id="E_0201",
        name="Anmeldung Messstellenbetrieb prüfen",
        kind="codelist_only",
        codelisten=["S_0055", "S_0056"],
        format_version="4.1",
        source_document=EBD_4_1,
    )
    assert stub.steps == []
    assert stub.codelisten == ["S_0055", "S_0056"]
    assert stub.source_document is not None and stub.source_document.date == "2026-01-16"


def test_a_use_other_ebd_stub_names_the_tree_to_follow() -> None:
    stub = DecisionTree(
        id="E_0541", name="x", kind="use_other_ebd", use_ebd="E_0539", note="Es ist das EBD E_0539 zu nutzen."
    )
    assert stub.use_ebd == "E_0539"
    assert stub.note == "Es ist das EBD E_0539 zu nutzen."


@pytest.mark.parametrize(
    "kind",
    [
        "tree",
        "codelist_only",
        "no_tree_aperak",
        "no_tree_no_answer",
        "use_other_ebd",
        "codelist_in_format",
        "unclassified",
    ],
)
def test_every_tree_kind_is_accepted(kind: str) -> None:
    content = {"codelist_only": {"codelisten": ["S_0055"]}, "use_other_ebd": {"use_ebd": "E_0539"}}.get(kind, {})
    assert DecisionTree.model_validate({"id": "E_0001", "name": "x", "kind": kind, **content}).kind == kind


@pytest.mark.parametrize(
    ("kind", "content", "message"),
    [
        ("use_other_ebd", {}, "names the EBD to use"),
        ("use_other_ebd", {"use_ebd": ""}, "names the EBD to use"),
        ("codelist_only", {}, "names its lists"),
        ("codelist_only", {"codelisten": []}, "names its lists"),
    ],
)
def test_a_stub_that_points_nowhere_is_refused(kind: str, content: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        DecisionTree.model_validate({"id": "E_0541", "name": "x", "kind": kind, **content})


@pytest.mark.parametrize("kind", ["", "stub", "codelist-only", "no_tree"])
def test_a_tree_kind_outside_the_set_is_refused(kind: str) -> None:
    with pytest.raises(ValidationError):
        DecisionTree.model_validate({"id": "E_0001", "name": "x", "kind": kind})


def test_a_codeliste_carries_its_provenance() -> None:
    liste = Codeliste(
        id="S_0056",
        name="Ablehnung Anmeldung MSB",
        format_version="4.1",
        source_document=EBD_4_1,
        codes=[CodeEntry(code="E11", name="Ablehnung (Messproblem)")],
    )
    assert liste.format_version == "4.1"
    assert liste.source_document == EBD_4_1


def test_a_v0_0_29_codeliste_still_loads() -> None:
    liste = Codeliste.model_validate({"id": "S_0056", "name": "x", "codes": []})
    assert liste.format_version is None and liste.source_document is None


def test_a_source_document_needs_its_file_name() -> None:
    with pytest.raises(ValidationError):
        SourceDocument.model_validate({"date": "2026-01-16"})


def test_a_source_document_date_is_optional() -> None:
    assert SourceDocument(file_name="x.pdf").date is None


def test_a_source_document_date_yaml_read_as_a_date_is_taken_back_as_iso() -> None:
    """``date: 2026-01-16`` unquoted is a ``datetime.date`` to PyYAML."""
    liste = SourceDocument.model_validate({"file_name": "x.pdf", "date": datetime.date(2026, 1, 16)})
    assert liste.date == "2026-01-16"


@pytest.mark.parametrize(
    "date", ["16.01.2026", "2026-1-16", "20260116", 20260116, "x2026-01-16", "2026-01-16T00:00", "２０２６-01-16"]
)
def test_a_source_document_date_that_is_not_iso_is_refused(date: object) -> None:
    with pytest.raises(ValidationError):
        SourceDocument.model_validate({"file_name": "x.pdf", "date": date})


@pytest.mark.parametrize(
    "sunset",
    [
        "01.04.2026, 00:00 Uhr",
        "01.04.2026 00:00 Uhr",
        "2026-04-01",
        "Offen",
        20260401,
        "x2026-04-01T00:00",
        "2026-04-01T00:00 Uhr",
        "nicht offen",
        "offen.",
        "2026-04-01 00:00",
        "2026-04-01T00",
        "٢٠٢٦-٠٤-٠١T٠٠:٠٠",
    ],
)
@pytest.mark.parametrize("branch", ["if_yes_sunset", "if_no_sunset"])
def test_a_sunset_the_parser_did_not_normalise_is_refused(branch: str, sunset: object) -> None:
    with pytest.raises(ValidationError):
        DecisionStep.model_validate({"nr": 1, "check": "x", branch: sunset})


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (DecisionStep, {"nr": 1, "check": "x", "next": "zehn"}),
        (DecisionStep, {"nr": 1, "check": "x", "next": 2, "next_hint": 3}),
        (DecisionTree, {"id": "E_1", "name": "x", "kind": "use_other_ebd", "use_ebd": 539}),
        (DecisionTree, {"id": "E_1", "name": "x", "note": 1}),
        (DecisionTree, {"id": "E_1", "name": "x", "kind": "codelist_only", "codelisten": "S_0055"}),
        (DecisionTree, {"id": "E_1", "name": "x", "format_version": 4.1}),
        (DecisionTree, {"id": "E_1", "name": "x", "source_document": "EBD.pdf"}),
        (Codeliste, {"id": "S_1", "name": "x", "codes": [], "format_version": 4.1}),
        (Codeliste, {"id": "S_1", "name": "x", "codes": [], "source_document": "EBD.pdf"}),
    ],
)
def test_a_new_field_of_the_wrong_type_is_refused(model: type[BaseModel], data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize("branch", [{"if_yes": 3}, {"if_no": 4}, {"if_yes": 3, "if_no": 4}])
def test_next_and_a_branch_target_exclude_each_other(branch: dict[str, int]) -> None:
    with pytest.raises(ValidationError, match="'next' excludes"):
        DecisionStep.model_validate({"nr": 105, "check": "x", "next": 110, **branch})


@pytest.mark.parametrize("field", [field for field in BRANCH_FIELDS if not field.endswith(("_sunset", "yes", "no"))])
def test_next_excludes_every_leaf_on_a_branch(field: str) -> None:
    """A row that only moves on has no ja/nein: a code or hint beside ``next`` would draw two exits."""
    with pytest.raises(ValidationError, match="'next' excludes"):
        DecisionStep.model_validate({"nr": 105, "check": "x", "next": 110, field: "x"})


@pytest.mark.parametrize("field", ["if_yes_sunset", "if_no_sunset"])
def test_next_excludes_a_sunset_on_a_branch(field: str) -> None:
    with pytest.raises(ValidationError, match="'next' excludes"):
        DecisionStep.model_validate({"nr": 105, "check": "x", "next": 110, field: "offen"})


def test_branch_fields_are_every_field_of_a_branch() -> None:
    """Pins the list the validator walks against the model, so a new branch field cannot slip past."""
    branch_like = {name for name in DecisionStep.model_fields if name.startswith(("if_yes", "if_no"))}
    assert set(BRANCH_FIELDS) == branch_like


def test_a_next_hint_sits_beside_its_next() -> None:
    """E_0594 105: the Hinweis beside '→ 110' belongs to the row, not to a branch."""
    step = DecisionStep(nr=105, check="[Adressprüfung]", next=110, next_hint="Aufnahme von 0..n Treffern")
    assert step.next_hint == "Aufnahme von 0..n Treffern"


def test_a_next_hint_needs_its_next() -> None:
    with pytest.raises(ValidationError, match="'next_hint' needs 'next'"):
        DecisionStep.model_validate({"nr": 105, "check": "x", "next_hint": "Aufnahme von 0..n Treffern"})


@pytest.mark.parametrize("kind", [kind for kind in get_args(TreeKind) if kind != "tree"])
def test_a_stub_with_steps_is_refused(kind: str) -> None:
    with pytest.raises(ValidationError, match="has no steps"):
        DecisionTree.model_validate({"id": "E_1", "name": "x", "kind": kind, "steps": [{"nr": 1, "check": "x"}]})


@pytest.mark.parametrize(
    ("field", "value", "owner"),
    [("use_ebd", "E_0539", "use_other_ebd"), ("codelisten", ["S_0055"], "codelist_only")],
)
@pytest.mark.parametrize("kind", get_args(TreeKind))
def test_a_stub_field_belongs_to_its_own_kind(field: str, value: object, owner: str, kind: str) -> None:
    data = {"id": "E_1", "name": "x", "kind": kind, field: value}
    if kind == owner:
        assert getattr(DecisionTree.model_validate(data), field) == value
        return
    with pytest.raises(ValidationError, match=f"belongs to kind '{owner}'"):
        DecisionTree.model_validate(data)
