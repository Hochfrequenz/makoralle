"""A process carries its Codelisten the way it carries its decision trees."""

from pathlib import Path

import yaml

from makoralle.models.codeliste import CodeEntry, Codeliste
from makoralle.models.process import Process
from makoralle.serialization.process_yaml import emit_yaml, load_yaml


def _process(**overrides: object) -> Process:
    data: dict[str, object] = {
        "id": "beginn_messstellenbetrieb",
        "name": "Beginn Messstellenbetrieb",
        "source": "2.3.1 UC: Beginn Messstellenbetrieb",
        "category": "WiM",
    }
    data.update(overrides)
    return Process(**data)  # type: ignore[arg-type]


def test_a_process_defaults_to_no_code_lists() -> None:
    assert _process().codelisten == []


def test_code_lists_are_serialised_beside_the_decision_trees(tmp_path: Path) -> None:
    process = _process(
        codelisten=[
            Codeliste(
                id="S_0056",
                name="Ablehnung Anmeldung MSB",
                source="EBD und Codelisten 4.1, Seite 540-540",
                ebd_id="E_0201",
                codes=[CodeEntry(code="E11", nutzung="O", name="Ablehnung (Messproblem)", kind="rejection")],
            )
        ]
    )

    emit_yaml(process, tmp_path)

    loaded = yaml.safe_load((tmp_path / "beginn_messstellenbetrieb.yaml").read_text(encoding="utf-8"))
    assert [c["id"] for c in loaded["codelisten"]] == ["S_0056"]
    assert loaded["codelisten"][0]["ebd_id"] == "E_0201"
    assert loaded["codelisten"][0]["codes"][0]["kind"] == "rejection"


def test_a_process_without_code_lists_writes_no_key(tmp_path: Path) -> None:
    emit_yaml(_process(), tmp_path)
    loaded = yaml.safe_load((tmp_path / "beginn_messstellenbetrieb.yaml").read_text(encoding="utf-8"))
    assert "codelisten" not in loaded


def test_code_lists_survive_a_yaml_round_trip(tmp_path: Path) -> None:
    """The webapp export reads processes back off disk, so the key must load as well as dump."""
    process = _process(
        codelisten=[
            Codeliste(
                id="S_0055",
                name="Bestätigung Anmeldung MSB",
                ebd_id="E_0201",
                codes=[CodeEntry(code="E15", nutzung="X", name="Zustimmung ohne Korrekturen", kind="approval")],
            )
        ]
    )
    path = emit_yaml(process, tmp_path)

    reloaded = load_yaml(path)

    assert [c["id"] for c in reloaded.codelisten] == ["S_0055"]
    assert reloaded.codelisten[0]["codes"][0]["kind"] == "approval"
