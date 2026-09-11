"""Every derived view of an EBD shows when a code is retired (#76).

Since 0.0.21 a branch's "Nutzungsmöglichkeit Ende: …" is its own field, ``if_yes_sunset`` /
``if_no_sunset``, and the parser takes the sentence out of the hint. The answer-code index, the
per-EBD summary and the process pages' step list read only the hint, so dataset v0.0.31 lost it
in all three: 107 index entries, 117 summary rows, 116 step-list lines in 27 pages.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from makoralle.serialization.ebd_yaml import build_answer_codes_index, write_answer_codes_index, write_per_ebd_summary
from makoralle.serialization.markdown import _render_ebd_steps, yaml_to_markdown

RETIRED = "2026-04-01T00:00"


def _write_tree(directory: Path, *steps: dict[str, Any]) -> None:
    tree = {"id": "E_0608", "name": "x", "role": "NB", "source": "test", "steps": list(steps)}
    (directory / "E_0608.json").write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")


def _coded(nr: int, sunset: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"nr": nr, "check": "x", "if_yes_code": "A99", "if_yes_hint": "Cluster: Ablehnung Sonstiges"}
    if sunset is not None:
        step["if_yes_sunset"] = sunset
    return step


# --- answer_codes.yaml ---------------------------------------------------------------------------
def test_an_entry_names_the_steps_that_retire_its_code(tmp_path: Path) -> None:
    """After E_0608 A99 in dataset v0.0.31: retired at step 130, not at step 610 -- one entry, and it says where."""
    _write_tree(tmp_path, _coded(130, RETIRED), _coded(610))
    entry = build_answer_codes_index(tmp_path)["E_0608"]["A99"]
    assert (entry["steps"], entry["sunsets"]) == ([130, 610], {130: RETIRED})


def test_every_retiring_step_of_an_entry_is_listed(tmp_path: Path) -> None:
    _write_tree(tmp_path, _coded(130, RETIRED), _coded(610, "offen"))
    assert build_answer_codes_index(tmp_path)["E_0608"]["A99"]["sunsets"] == {130: RETIRED, 610: "offen"}


@pytest.mark.parametrize("sunset", [RETIRED, "offen"])
def test_the_sunset_is_carried_as_stored(tmp_path: Path, sunset: str) -> None:
    _write_tree(tmp_path, _coded(2, sunset))
    assert build_answer_codes_index(tmp_path)["E_0608"]["A99"]["sunsets"] == {2: sunset}


def test_an_entry_no_step_retires_has_no_sunsets(tmp_path: Path) -> None:
    _write_tree(tmp_path, _coded(2), _coded(3))
    assert "sunsets" not in build_answer_codes_index(tmp_path)["E_0608"]["A99"]


def test_a_sunset_on_a_branch_without_a_code_makes_no_entry(tmp_path: Path) -> None:
    """Constructed: every sunset in EBD 4.1 sits on a coded branch, but the index is per code, so a branch
    without one adds nothing."""
    _write_tree(tmp_path, {"nr": 225, "check": "x", "if_yes": 230, "if_yes_sunset": "offen"})
    assert build_answer_codes_index(tmp_path) == {}


def test_the_written_index_keeps_the_step_numbers(tmp_path: Path) -> None:
    _write_tree(tmp_path, _coded(130, RETIRED), _coded(610))
    data = yaml.safe_load(write_answer_codes_index(tmp_path).read_text(encoding="utf-8"))
    assert data["E_0608"]["A99"]["sunsets"] == {130: RETIRED}


# --- summary/E_xxxx.md ---------------------------------------------------------------------------
def _summary(tmp_path: Path, *steps: dict[str, Any]) -> list[str]:
    _write_tree(tmp_path, *steps)
    (path,) = write_per_ebd_summary(tmp_path)
    return path.read_text(encoding="utf-8").splitlines()


def test_the_summary_has_a_sunset_column(tmp_path: Path) -> None:
    lines = _summary(tmp_path, _coded(2))
    assert "| Code | Kind | Cluster | Step | Hint | Sunset |" in lines
    assert "|------|------|---------|------|------|--------|" in lines


@pytest.mark.parametrize(("sunset", "cell"), [(RETIRED, f"| {RETIRED} |"), ("offen", "| offen |"), (None, "|  |")])
def test_a_summary_row_ends_with_its_sunset(tmp_path: Path, sunset: str | None, cell: str) -> None:
    (row,) = [line for line in _summary(tmp_path, _coded(2, sunset)) if line.startswith("| A99 ")]
    assert row == f"| A99 | rejection | Ablehnung | 2 | Sonstiges {cell}"


# --- the process pages' step list ----------------------------------------------------------------
def _step_list(**branch: Any) -> list[str]:
    return _render_ebd_steps({"id": "E_0406", "name": "x", "steps": [{"nr": 225, "check": "x", **branch}]})


@pytest.mark.parametrize(
    ("branch", "line"),
    [
        # E_0406 225 `ja → 230` (A99, "offen"): 40 of EBD 4.1's 124 sunsets sit on a branch that goes on to
        # another step. The step list draws such a branch as its goto, so that line has to carry the sunset.
        ({"if_yes": 230, "if_yes_sunset": "offen"}, "        - ✓ → Step 230 (Nutzungsmöglichkeit Ende: offen)"),
        (
            {"if_yes": 230, "if_yes_code": "A99", "if_yes_hint": "weiter", "if_yes_sunset": "offen"},
            "        - ✓ → Step 230 weiter (Nutzungsmöglichkeit Ende: offen)",
        ),
        # E_0510 2: a coded leaf, the sentence closing its Hinweis.
        (
            {"if_yes_code": "A99", "if_yes_hint": "Sonstiges", "if_yes_sunset": RETIRED},
            f"        - ✓ → A99 Sonstiges (Nutzungsmöglichkeit Ende: {RETIRED})",
        ),
        (
            {"if_no_code": "A99", "if_no_result": "Ablehnung", "if_no_sunset": RETIRED},
            f"        - ✗ → A99 Ablehnung (Nutzungsmöglichkeit Ende: {RETIRED})",
        ),
        # A code with neither hint nor result: the one space before the sunset, not two.
        ({"if_no_code": "A99", "if_no_sunset": RETIRED}, f"        - ✗ → A99 (Nutzungsmöglichkeit Ende: {RETIRED})"),
        (
            {"if_yes_result": "Ende", "if_yes_hint": "Rechnung offen", "if_yes_sunset": "offen"},
            "        - ✓ → Ende Rechnung offen (Nutzungsmöglichkeit Ende: offen)",
        ),
    ],
)
def test_the_step_list_ends_a_retired_branch_with_its_sunset(branch: dict[str, Any], line: str) -> None:
    assert line in _step_list(**branch)


@pytest.mark.parametrize(
    ("branch", "line"),
    [
        ({"if_yes": 230}, "        - ✓ → Step 230"),
        ({"if_yes_code": "A99", "if_yes_hint": "Sonstiges"}, "        - ✓ → A99 Sonstiges"),
        ({"if_no_code": "A99"}, "        - ✗ → A99 "),  # the trailing space of a bare code stays as it was
        ({"if_yes_result": "Ende"}, "        - ✓ → Ende"),
    ],
)
def test_a_branch_without_a_sunset_renders_as_before(branch: dict[str, Any], line: str) -> None:
    assert _step_list(**branch)[-1] == line


def test_a_retired_branch_reaches_the_rendered_page() -> None:
    step = {"nr": 2, "check": "x", "if_yes_code": "A99", "if_yes_hint": "Sonstiges", "if_yes_sunset": RETIRED}
    doc = {
        "process": {"id": "p", "name": "P", "source": "", "category": ""},
        "decision_trees": [{"id": "E_0510", "name": "x", "steps": [step]}],
    }
    md = yaml_to_markdown(yaml.safe_dump(doc, allow_unicode=True))
    assert f"        - ✓ → A99 Sonstiges (Nutzungsmöglichkeit Ende: {RETIRED})\n" in md
