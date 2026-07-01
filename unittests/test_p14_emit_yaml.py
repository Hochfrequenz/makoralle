import yaml

from makoralle.models.process import NamedSD, Process, SDStep, SequenceDiagram, UseCase
from makoralle.serialization.process_yaml import process_to_yaml


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
