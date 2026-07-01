import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from makoralle.serialization.ebd_yaml import (
    build_answer_codes_index,
    emit_all,
    write_answer_codes_index,
    write_per_ebd_summary,
    write_per_ebd_yaml,
)


def _write_ebd_json(directory: Path, ebd_id: str, steps: list[dict[str, Any]]) -> None:
    (directory / f"{ebd_id}.json").write_text(
        json.dumps(
            {
                "id": ebd_id,
                "name": f"Test {ebd_id}",
                "role": "LF",
                "source": "test",
                "steps": steps,
            },
            ensure_ascii=False,
        )
    )


def test_build_answer_codes_index_classifies_zustimmung_as_approval(tmp_path: Path) -> None:
    # Reproduces the E_0624/A36 bug case: the parser stored result="Ablehnung"
    # but the hint text classifies the code as Zustimmung (approval).
    _write_ebd_json(
        tmp_path,
        "E_0624",
        [
            {
                "nr": 90,
                "check": "Bleibt das Vertragsverhältnis bestehen?",
                "if_yes": None,
                "if_yes_result": "Ablehnung",
                "if_yes_code": "A35",
                "if_yes_hint": "Cluster: Ablehnung Es besteht eine Vertragsbindung",
                "if_no": None,
                "if_no_result": "Ablehnung",
                "if_no_code": "A36",
                "if_no_hint": "Cluster: Zustimmung Vertragsverhältnis wurde beendet.",
            },
        ],
    )
    index = build_answer_codes_index(tmp_path)
    assert index["E_0624"]["A35"]["kind"] == "rejection"
    assert index["E_0624"]["A35"]["cluster"] == "Ablehnung"
    assert index["E_0624"]["A35"]["steps"] == [90]
    assert index["E_0624"]["A35"]["hint"] == "Es besteht eine Vertragsbindung"
    assert index["E_0624"]["A36"]["kind"] == "approval"
    assert index["E_0624"]["A36"]["cluster"] == "Zustimmung"
    assert index["E_0624"]["A36"]["steps"] == [90]


def test_build_answer_codes_index_handles_structured_cluster_field(tmp_path: Path) -> None:
    # When the parser has been fixed (Phase 2), the JSON carries an
    # explicit if_*_cluster field. The emitter should prefer it over
    # parsing the hint.
    _write_ebd_json(
        tmp_path,
        "E_0001",
        [
            {
                "nr": 1,
                "check": "x",
                "if_yes": None,
                "if_yes_result": "Zustimmung",
                "if_yes_code": "Z01",
                "if_yes_cluster": "Zustimmung",
                "if_yes_hint": "Already cleaned",
                "if_no": None,
                "if_no_result": None,
                "if_no_code": None,
                "if_no_hint": None,
            },
        ],
    )
    index = build_answer_codes_index(tmp_path)
    assert index["E_0001"]["Z01"]["kind"] == "approval"
    assert index["E_0001"]["Z01"]["hint"] == "Already cleaned"
    assert index["E_0001"]["Z01"]["steps"] == [1]


def test_build_answer_codes_index_skips_branches_without_codes(tmp_path: Path) -> None:
    _write_ebd_json(
        tmp_path,
        "E_0002",
        [
            {
                "nr": 1,
                "check": "x",
                "if_yes": 2,
                "if_yes_result": None,
                "if_yes_code": None,
                "if_yes_hint": None,
                "if_no": None,
                "if_no_result": None,
                "if_no_code": None,
                "if_no_hint": None,
            },
        ],
    )
    index = build_answer_codes_index(tmp_path)
    assert "E_0002" not in index


def test_build_answer_codes_index_unknown_cluster(tmp_path: Path) -> None:
    _write_ebd_json(
        tmp_path,
        "E_0003",
        [
            {
                "nr": 1,
                "check": "x",
                "if_yes": None,
                "if_yes_result": None,
                "if_yes_code": "X99",
                "if_yes_hint": "no cluster prefix here",
                "if_no": None,
                "if_no_result": None,
                "if_no_code": None,
                "if_no_hint": None,
            },
        ],
    )
    index = build_answer_codes_index(tmp_path)
    assert index["E_0003"]["X99"]["kind"] == "unknown"
    assert index["E_0003"]["X99"]["cluster"] is None
    assert index["E_0003"]["X99"]["steps"] == [1]


def test_build_answer_codes_index_merges_same_code_in_one_ebd(tmp_path: Path) -> None:
    """A code appearing at multiple steps must merge into one entry with all steps listed."""
    _write_ebd_json(
        tmp_path,
        "E_0456",
        [
            {
                "nr": 7,
                "check": "x",
                "if_yes": None,
                "if_yes_result": "Ablehnung",
                "if_yes_code": "A05",
                "if_yes_hint": "Cluster: Ablehnung auf Positionsebene Preis weicht ab",
                "if_no": 10,
                "if_no_result": None,
                "if_no_code": None,
                "if_no_hint": None,
            },
            {
                "nr": 10,
                "check": "y",
                "if_yes": None,
                "if_yes_result": "Ablehnung",
                "if_yes_code": "A05",
                "if_yes_hint": "Cluster: Ablehnung auf Positionsebene Menge weicht ab",
                "if_no": None,
                "if_no_result": None,
                "if_no_code": None,
                "if_no_hint": None,
            },
        ],
    )
    index = build_answer_codes_index(tmp_path)
    assert list(index["E_0456"].keys()) == ["A05"]
    entry = index["E_0456"]["A05"]
    assert entry["kind"] == "rejection"
    assert entry["cluster"] == "Ablehnung auf Positionsebene"
    assert entry["steps"] == [7, 10]


def test_build_answer_codes_index_prefers_hint_bearing_collision_winner(tmp_path: Path) -> None:
    """When the same code appears twice, one with a hintless branch and one
    with a clean Cluster: hint, the entry with real classification data wins
    (reproduces the E_0286/A01 bug shape)."""
    _write_ebd_json(
        tmp_path,
        "E_0286",
        [
            {
                "nr": 10,
                "check": "x",
                "if_yes": None,
                "if_yes_result": "Ablehnung",
                "if_yes_code": "A01",
                "if_yes_hint": "Cluster: Ablehnung Fristüberschreitung",
                "if_no": None,
                "if_no_result": None,
                "if_no_code": "A01",
                "if_no_hint": None,
            },
        ],
    )
    entry = build_answer_codes_index(tmp_path)["E_0286"]["A01"]
    assert entry["kind"] == "rejection"  # NOT "unknown"
    assert entry["cluster"] == "Ablehnung"
    assert entry["hint"] == "Fristüberschreitung"
    assert entry["steps"] == [10]


def test_write_answer_codes_index(tmp_path: Path) -> None:
    _write_ebd_json(
        tmp_path,
        "E_0624",
        [
            {
                "nr": 90,
                "check": "x",
                "if_yes": None,
                "if_yes_result": "Ablehnung",
                "if_yes_code": "A35",
                "if_yes_hint": "Cluster: Ablehnung reason A35",
                "if_no": None,
                "if_no_result": "Ablehnung",
                "if_no_code": "A36",
                "if_no_hint": "Cluster: Zustimmung reason A36",
            },
        ],
    )
    out = write_answer_codes_index(tmp_path)
    assert out == tmp_path / "answer_codes.yaml"
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["E_0624"]["A36"]["kind"] == "approval"
    assert data["E_0624"]["A35"]["kind"] == "rejection"


def test_write_per_ebd_yaml(tmp_path: Path) -> None:
    _write_ebd_json(
        tmp_path,
        "E_0624",
        [
            {
                "nr": 1,
                "check": "Erste Frage?",
                "if_yes": 2,
                "if_yes_result": None,
                "if_yes_code": None,
                "if_yes_hint": None,
                "if_no": None,
                "if_no_result": "Ablehnung",
                "if_no_code": "A01",
                "if_no_hint": "Cluster: Ablehnung Begründung",
            },
        ],
    )
    paths = write_per_ebd_yaml(tmp_path)
    assert len(paths) == 1
    yaml_path = tmp_path / "yaml" / "E_0624.yaml"
    assert yaml_path.exists()
    parsed = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert parsed["id"] == "E_0624"
    assert len(parsed["steps"]) == 1
    # Null-valued keys are dropped for compactness
    assert "if_yes_code" not in parsed["steps"][0]
    # Code-bearing branch survives
    assert parsed["steps"][0]["if_no_code"] == "A01"


def test_write_per_ebd_summary(tmp_path: Path) -> None:
    _write_ebd_json(
        tmp_path,
        "E_0624",
        [
            {
                "nr": 90,
                "check": "x",
                "if_yes": None,
                "if_yes_result": "Ablehnung",
                "if_yes_code": "A35",
                "if_yes_hint": "Cluster: Ablehnung Es besteht eine Vertragsbindung",
                "if_no": None,
                "if_no_result": "Ablehnung",
                "if_no_code": "A36",
                "if_no_hint": "Cluster: Zustimmung Vertragsverhältnis wurde beendet.",
            },
        ],
    )
    paths = write_per_ebd_summary(tmp_path)
    assert len(paths) == 1
    md_path = tmp_path / "summary" / "E_0624.md"
    text = md_path.read_text(encoding="utf-8")
    assert "# E_0624" in text
    # Both codes present, with their derived kinds
    assert "A35" in text and "rejection" in text
    assert "A36" in text and "approval" in text
    # Cluster name is also visible for human review
    assert "Zustimmung" in text


def test_emit_all_against_real_ebds() -> None:
    real_dir = Path("pipeline/09_ebds")
    if not (real_dir / "E_0624.json").exists():
        pytest.skip("real EBD JSONs not present in this checkout")
    # Emit into a side directory so we don't pollute checked-in outputs
    emit_all(real_dir)
    index = yaml.safe_load((real_dir / "answer_codes.yaml").read_text(encoding="utf-8"))
    # The bug case from the original report: E_0624 / A36 must classify as approval
    assert index["E_0624"]["A36"]["kind"] == "approval"
    assert index["E_0624"]["A35"]["kind"] == "rejection"
    # Per-EBD outputs exist
    assert (real_dir / "yaml" / "E_0624.yaml").exists()
    assert (real_dir / "summary" / "E_0624.md").exists()
