"""`SDStep.subprocess_ref_id`: the resolved target of a ``ref`` step, carried in the process YAML.

Before this, `output/yaml` held only the ref's *name*, so a consumer had to rebuild makoralle's
resolver and the curated `sd_ref_links.yaml` to follow a ref (dataset #75). The id is the same
value the makrake render input already carries under the same name — ``uc`` or ``uc__sd`` — so
one field name never means two things.
"""

from typing import Any

import pytest
import yaml

from makoralle.models.process import NamedSD, Process, SDStep
from makoralle.ref_links import assign_subprocess_ref_ids, ref_target_id
from makoralle.serialization.process_yaml import process_to_yaml


def _ref(nr: int, name: str) -> SDStep:
    return SDStep(nr=nr, sender="NB", receiver="NB", message=f"ref {name}", subprocess_ref=name)


def _msg(nr: int) -> SDStep:
    return SDStep(nr=nr, sender="NB", receiver="LF", message="Anmeldung")


def _stamm() -> Process:
    """A three-variant target, shaped like the linker's output (slug + qualifier + heading)."""
    return Process(
        id="stammdatenänderung",
        name="Stammdatenänderung",
        source="",
        category="",
        diagrams=[
            NamedSD(
                slug=f"vom_{role.lower()}_verantwortlich_ausgehend",
                name=f"vom {role} (verantwortlich) ausgehend",
                source_heading=f"1.4.{i} SD: Stammdatenänderung vom {role} (verantwortlich) ausgehend",
                participants=["NB", "LF"],
                steps=[_msg(1)],
            )
            for i, role in enumerate(("NB", "LF"), start=2)
        ],
    )


def _caller(*steps: SDStep) -> Process:
    return Process(
        id="caller",
        name="Caller",
        source="",
        category="",
        diagrams=[NamedSD(slug="", name=None, participants=["NB", "LF"], steps=list(steps))],
    )


def _steps(process: Process) -> list[SDStep]:
    return process.diagrams[0].steps


def test_a_variant_ref_gets_its_uc_and_slug() -> None:
    caller = _caller(_ref(1, "Stammdatenänderung vom LF (verantwortlich) ausgehend"))
    assert assign_subprocess_ref_ids([caller, _stamm()], {}) == []
    assert _steps(caller)[0].subprocess_ref_id == "stammdatenänderung__vom_lf_verantwortlich_ausgehend"


def test_a_uc_level_ref_gets_the_first_variant() -> None:
    caller = _caller(_ref(1, "Stammdatenänderung"))
    assign_subprocess_ref_ids([caller, _stamm()], {})
    assert _steps(caller)[0].subprocess_ref_id == "stammdatenänderung__vom_nb_verantwortlich_ausgehend"


def test_an_override_with_an_empty_sd_gets_the_bare_uc() -> None:
    caller = _caller(_ref(1, "Stammdaten garbled"))
    overrides = {"stammdaten garbled": {"uc": "stammdatenänderung", "sd": ""}}
    assert assign_subprocess_ref_ids([caller, _stamm()], overrides) == []
    assert _steps(caller)[0].subprocess_ref_id == "stammdatenänderung"


def test_an_unresolved_ref_gets_no_id_and_is_reported() -> None:
    caller = _caller(_ref(1, "Mysterious Garbled Thing"))
    assert assign_subprocess_ref_ids([caller, _stamm()], {}) == ["Mysterious Garbled Thing"]
    assert _steps(caller)[0].subprocess_ref_id is None


def test_an_id_that_no_longer_resolves_is_cleared() -> None:
    """A re-run over a process read back from YAML must not keep a target the overrides dropped."""
    step = _ref(1, "Mysterious Garbled Thing")
    step.subprocess_ref_id = "stale"
    assign_subprocess_ref_ids([_caller(step)], {})
    assert step.subprocess_ref_id is None


def test_a_message_step_gets_no_id() -> None:
    caller = _caller(_msg(1), _ref(2, "Stammdatenänderung"))
    assign_subprocess_ref_ids([caller, _stamm()], {})
    assert _steps(caller)[0].subprocess_ref_id is None


def test_every_variant_of_the_calling_process_is_resolved() -> None:
    caller = _stamm()
    caller.diagrams[1].steps.append(_ref(2, "Caller"))
    assign_subprocess_ref_ids([caller, _caller(_msg(1))], {})
    assert caller.diagrams[1].steps[-1].subprocess_ref_id == "caller"


def test_the_primary_sequence_diagram_alias_carries_the_id_too() -> None:
    """`process_to_yaml` writes the first diagram's steps twice; both copies must agree."""
    caller = _caller(_ref(1, "Stammdatenänderung"))
    assign_subprocess_ref_ids([caller, _stamm()], {})
    assert caller.sequence_diagram is not None
    assert caller.sequence_diagram.steps[0].subprocess_ref_id == "stammdatenänderung__vom_nb_verantwortlich_ausgehend"


def test_the_yaml_carries_a_resolved_id_and_omits_an_unresolved_one() -> None:
    """Absent, never an empty string: "no target" must not look like a target."""
    caller = _caller(_ref(1, "Stammdatenänderung"), _ref(2, "Mysterious Garbled Thing"))
    assign_subprocess_ref_ids([caller, _stamm()], {})
    data = yaml.safe_load(process_to_yaml(caller))
    for steps in (data["diagrams"][0]["steps"], data["sequence_diagram"]["steps"]):
        assert steps[0]["subprocess_ref_id"] == "stammdatenänderung__vom_nb_verantwortlich_ausgehend"
        assert "subprocess_ref_id" not in steps[1]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param({"uc": "abrechnung", "sd": "zwischen_msb_und_lf"}, "abrechnung__zwischen_msb_und_lf", id="dict"),
        pytest.param({"uc": "lieferbeginn", "sd": ""}, "lieferbeginn", id="empty-sd"),
        pytest.param({"uc": "lieferbeginn"}, "lieferbeginn", id="no-sd"),
        pytest.param(["abrechnung", "zwischen_msb_und_lf"], "abrechnung__zwischen_msb_und_lf", id="pair"),
        pytest.param(["lieferbeginn"], "lieferbeginn", id="one-element"),
        pytest.param(None, None, id="unresolved"),
        pytest.param({"uc": "", "sd": "x"}, None, id="empty-uc"),
    ],
)
def test_ref_target_id(target: Any, expected: str | None) -> None:
    assert ref_target_id(target) == expected
