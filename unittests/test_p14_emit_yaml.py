from pathlib import Path

import pytest
import yaml

from makoralle.models.activity import ActivityDiagram, ADNode
from makoralle.models.ebd import DecisionStep, DecisionTree
from makoralle.models.pid import PIDMapping
from makoralle.models.process import (
    CrossReference,
    NamedSD,
    Process,
    SDStep,
    SequenceDiagram,
    SourceDocuments,
    UseCase,
)
from makoralle.models.source import SourceDocument
from makoralle.serialization.process_yaml import (
    emit_yaml,
    flatten_process_dict,
    load_yaml,
    process_from_dict,
    process_from_yaml,
    process_to_yaml,
)


def test_process_to_yaml() -> None:
    proc = Process(
        id="lieferbeginn",
        name="Lieferbeginn",
        source="GPKE Teil 2, Kapitel 2.1",
        category="Zuordnungsprozesse",
        use_case=UseCase(
            goal="Zuordnung eines LF",
            description="Anmeldung",
            roles=["LF", "NB"],
            preconditions=["Vertrag liegt vor"],
        ),
        sequence_diagram=SequenceDiagram(
            participants=["LF", "NB"],
            steps=[
                SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung"),
            ],
        ),
    )
    yaml_str = process_to_yaml(proc)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["process"]["id"] == "lieferbeginn"
    assert parsed["use_case"]["goal"] == "Zuordnung eines LF"
    assert len(parsed["sequence_diagram"]["steps"]) == 1


def test_process_to_yaml_serializes_diagrams() -> None:
    proc = Process(
        id="lieferbeginn",
        name="Lieferbeginn",
        source="GPKE Teil 2, Kapitel 2.1",
        category="Zuordnungsprozesse",
        diagrams=[
            NamedSD(
                slug="vom_nb_ausgehend",
                name="vom NB ausgehend",
                participants=["LF", "NB"],
                steps=[
                    SDStep(nr=1, sender="NB", receiver="LF", message="Info"),
                ],
            ),
            NamedSD(
                slug="vom_lf_ausgehend",
                name="vom LF ausgehend",
                participants=["LF", "NB"],
                steps=[
                    SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung"),
                    SDStep(nr=2, sender="NB", receiver="LF", message="Bestätigung"),
                ],
            ),
        ],
    )
    yaml_str = process_to_yaml(proc)
    parsed = yaml.safe_load(yaml_str)

    # diagrams[] serialized with slug/name/steps and distinct shapes
    assert "diagrams" in parsed
    assert [d["slug"] for d in parsed["diagrams"]] == [
        "vom_nb_ausgehend",
        "vom_lf_ausgehend",
    ]
    assert [d["name"] for d in parsed["diagrams"]] == [
        "vom NB ausgehend",
        "vom LF ausgehend",
    ]
    assert [len(d["steps"]) for d in parsed["diagrams"]] == [1, 2]

    # backward-compat: sequence_diagram still present
    assert "sequence_diagram" in parsed
    assert len(parsed["sequence_diagram"]["steps"]) == 1


def test_process_from_yaml_round_trips() -> None:
    proc = Process(
        id="lieferbeginn",
        name="Lieferbeginn",
        source="GPKE Teil 2, Kapitel 2.1",
        category="Zuordnungsprozesse",
        use_case=UseCase(
            goal="Zuordnung eines LF",
            description="Anmeldung",
            roles=["LF", "NB"],
            preconditions=["Vertrag liegt vor"],
        ),
        sequence_diagram=SequenceDiagram(
            participants=["LF", "NB"],
            steps=[
                SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung"),
            ],
        ),
        related_processes=[CrossReference(id="kuendigung", relation="folgt_auf")],
        source_documents=SourceDocuments(uc_sd=SourceDocument(file_name="Anlage1b_GPKE_Teil2.pdf")),
    )
    restored = process_from_yaml(process_to_yaml(proc))
    assert restored == proc


def test_process_from_dict_minimal() -> None:
    """No wrappers, no optional fields — the branch where the wrapper ``.pop(..., None)``
    default matters."""
    restored = process_from_dict({"id": "x", "name": "X", "source": "s", "category": "c"})
    assert restored == Process(id="x", name="X", source="s", category="c")


def test_process_to_yaml_round_trips_loosely_typed_fields_after_load() -> None:
    """``decision_trees``/``pid_mappings``/``activity_diagram`` are ``list[Any]``/``dict[str,
    Any] | None`` on :class:`Process`, so a loaded ``Process`` holds plain dicts there, not
    model instances (unlike a freshly-constructed one, which is why this test builds ``proc``
    with dicts directly rather than model instances). Re-emitting such a loaded process used
    to crash: ``process_to_yaml`` called ``.model_dump()`` unconditionally on each
    ``decision_trees``/``pid_mappings`` entry."""
    proc = Process(
        id="lieferbeginn",
        name="Lieferbeginn",
        source="GPKE Teil 2, Kapitel 2.1",
        category="Zuordnungsprozesse",
        decision_trees=[
            DecisionTree(id="E_0003", name="Prüfung", steps=[DecisionStep(nr=1, check="ok?")]).model_dump(
                exclude_none=True
            ),
        ],
        pid_mappings=[
            PIDMapping(lfd_nr=1, ahb="GPKE", anwendungsfall="Lieferbeginn", prüfidentifikator=55001).model_dump(
                exclude_none=True
            ),
        ],
        activity_diagram=ActivityDiagram(
            participants=["LF"],
            nodes=[ADNode(id="n1", type="start")],
            edges=[],
        ).model_dump(exclude_none=True),
    )
    yaml_str = process_to_yaml(proc)  # would previously raise AttributeError on the dicts above
    restored = process_from_yaml(yaml_str)
    assert restored == proc
    assert process_to_yaml(restored) == yaml_str


def test_load_yaml_round_trips_through_a_file(tmp_path: Path) -> None:
    proc = Process(id="lieferbeginn", name="Lieferbeginn", source="s", category="c")
    path = emit_yaml(proc, tmp_path)
    assert load_yaml(path) == proc


def test_load_yaml_error_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match=str(path)):
        load_yaml(path)


def test_process_from_yaml_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="mapping"):
        process_from_yaml("")


def test_process_from_yaml_rejects_non_mapping_input() -> None:
    with pytest.raises(ValueError, match="mapping"):
        process_from_yaml("- a\n- b\n")


def test_flatten_process_dict_rejects_non_mapping_wrapper() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        flatten_process_dict({"process": ["a", "b"]})


def test_process_from_dict_tolerates_bare_wrapper_keys() -> None:
    """``process:`` or ``cross_references:`` with no value parses as ``None``, not ``{}``."""
    restored = process_from_dict(
        {"process": {"id": "x", "name": "X", "source": "s", "category": "c"}, "cross_references": None}
    )
    assert restored == Process(id="x", name="X", source="s", category="c")


def test_process_from_dict_rejects_unknown_field() -> None:
    with pytest.raises(ValueError, match="unknown"):
        process_from_dict({"process": {"id": "x", "name": "X", "source": "s", "category": "c"}, "use_cases": {}})


def test_flatten_process_dict_wrapper_key_wins_on_collision() -> None:
    flat = flatten_process_dict({"id": "top-level", "process": {"id": "wrapper"}})
    assert flat["id"] == "wrapper"


def test_formatversion_and_source_editions_round_trip() -> None:
    proc = Process(
        id="lieferbeginn",
        name="Lieferbeginn",
        source="2.1 UC: Lieferbeginn",
        category="GPKE",
        formatversion="FV2604",
        source_documents=SourceDocuments(
            uc_sd=SourceDocument(file_name="Anlage1b_GPKE_Teil2.pdf"),
            ebd=SourceDocument(
                file_name="EBD_4.2.pdf",
                document_version="4.2",
                date="2026-06-23",
                valid_from="2026-10-01",
                valid_to="9999-12-31",
                sha256="0" * 64,
            ),
        ),
    )
    text = process_to_yaml(proc)
    parsed = yaml.safe_load(text)
    assert parsed["process"]["formatversion"] == "FV2604"
    assert parsed["cross_references"]["source_documents"]["ebd"]["document_version"] == "4.2"
    assert "pid" not in parsed["cross_references"]["source_documents"]  # exclude_none, as before
    back = process_from_yaml(text)
    assert back.formatversion == "FV2604"
    assert back.source_documents is not None and back.source_documents.uc_sd is not None
    assert back.source_documents.uc_sd.file_name == "Anlage1b_GPKE_Teil2.pdf"
    assert back == proc  # model equality, as the dataset CI checks
    assert process_to_yaml(back) == text  # byte stability


def test_a_process_without_a_bundle_emits_no_formatversion_key() -> None:
    proc = Process(id="x", name="X", source="", category="")
    assert "formatversion" not in yaml.safe_load(process_to_yaml(proc))["process"]
