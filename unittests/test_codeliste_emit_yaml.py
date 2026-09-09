"""Emitting Codelisten beside the EBDs: per-list YAML, and entries in the shared index."""

import json
from pathlib import Path
from typing import Any

import yaml

from makoralle.serialization.ebd_yaml import (
    build_answer_codes_index,
    emit_all,
    write_per_codeliste_yaml,
)


def _write_codeliste_json(directory: Path, list_id: str, **overrides: Any) -> None:
    payload: dict[str, Any] = {
        "id": list_id,
        "name": "Ablehnung Anmeldung MSB",
        "source": "EBD und Codelisten 4.1, Seite 540-540",
        "ebd_id": "E_0201",
        "codes": [
            {
                "code": "E11",
                "nutzung": "O",
                "bedingung": None,
                "name": "Ablehnung (Messproblem)",
                "description": "Der Absender lehnt die Transaktion ab.",
                "kind": "rejection",
            },
            {
                "code": "ZB6",
                "nutzung": "O",
                "bedingung": None,
                "name": "Erforderliche Versicherung fehlt",
                "description": None,
                "kind": "rejection",
            },
        ],
    }
    payload.update(overrides)
    (directory / f"{list_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_ebd_json(directory: Path, ebd_id: str) -> None:
    (directory / f"{ebd_id}.json").write_text(
        json.dumps(
            {
                "id": ebd_id,
                "name": f"Test {ebd_id}",
                "role": "LF",
                "source": "test",
                "steps": [
                    {"nr": 10, "check": "?", "if_no_code": "A07", "if_no_cluster": "Ablehnung", "if_no_hint": "nope"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_per_list_yaml_is_written_for_every_prefix(tmp_path: Path) -> None:
    for list_id in ("S_0056", "G_0001", "GS_002"):
        _write_codeliste_json(tmp_path, list_id)

    written = write_per_codeliste_yaml(tmp_path)

    assert {p.name for p in written} == {"S_0056.yaml", "G_0001.yaml", "GS_002.yaml"}
    loaded = yaml.safe_load((tmp_path / "yaml" / "S_0056.yaml").read_text(encoding="utf-8"))
    assert loaded["id"] == "S_0056"
    assert loaded["ebd_id"] == "E_0201"
    assert [c["code"] for c in loaded["codes"]] == ["E11", "ZB6"]
    assert loaded["codes"][0]["description"] == "Der Absender lehnt die Transaktion ab."


def test_a_null_bedingung_is_dropped_rather_than_written(tmp_path: Path) -> None:
    _write_codeliste_json(tmp_path, "S_0056")
    write_per_codeliste_yaml(tmp_path)
    loaded = yaml.safe_load((tmp_path / "yaml" / "S_0056.yaml").read_text(encoding="utf-8"))
    assert "bedingung" not in loaded["codes"][0]


def test_the_index_carries_code_lists_beside_the_ebds(tmp_path: Path) -> None:
    _write_ebd_json(tmp_path, "E_0201")
    _write_codeliste_json(tmp_path, "S_0056")

    index = build_answer_codes_index(tmp_path)

    assert "E_0201" in index, "the EBD entries must survive"
    assert index["S_0056"] == {
        "E11": {"hint": "Ablehnung (Messproblem)", "kind": "rejection"},
        "ZB6": {"hint": "Erforderliche Versicherung fehlt", "kind": "rejection"},
    }


def test_emit_all_writes_the_code_lists_too(tmp_path: Path) -> None:
    _write_ebd_json(tmp_path, "E_0201")
    _write_codeliste_json(tmp_path, "S_0056")

    emit_all(tmp_path)

    assert (tmp_path / "yaml" / "S_0056.yaml").exists()
    index = yaml.safe_load((tmp_path / "answer_codes.yaml").read_text(encoding="utf-8"))
    assert "S_0056" in index
