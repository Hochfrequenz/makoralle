"""The makrake render input — what replaced the `.wsd` DSL as the renderer's input."""

import json
from typing import Any

from makoralle.serialization.makrake import canonical_json, makrake_diagram


def _diagram(*steps: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {"participants": ["LF", "NB"], "steps": list(steps), **over}


def _payload(*steps: dict[str, Any], **over: Any) -> dict[str, Any]:
    return makrake_diagram(_diagram(*steps, **over), diagram_id="lieferbeginn", name="Lieferbeginn")


def test_a_step_carries_its_endpoints_message_and_number() -> None:
    p = _payload({"nr": 3, "sender": "LF", "receiver": "NB", "message": "Anmeldung"})
    assert p["id"] == "lieferbeginn" and p["name"] == "Lieferbeginn"
    assert p["participants"] == ["LF", "NB"]
    (step,) = p["steps"]
    assert step["number"] == 3
    assert (step["sender"], step["receiver"], step["message"]) == ("LF", "NB", "Anmeldung")
    assert step["kind"] == "message"


def test_pids_are_ints_even_when_the_source_holds_strings() -> None:
    """makrake's `Vec<u32>` rejects a string with a deserialization error naming a line
    number rather than a step, so the coercion happens here where the step is in scope."""
    (step,) = _payload({"nr": 1, "pid_refs": [55001, "55002", None, "x"]})["steps"]
    assert step["pids"] == [55001, 55002]


def test_a_pid_less_step_omits_the_field_rather_than_sending_an_empty_list() -> None:
    assert "pids" not in _payload({"nr": 1})["steps"][0]


def test_a_subprocess_ref_becomes_a_ref_step_with_its_resolved_target() -> None:
    """The fact the `.wsd` DSL had no slot for, and the reason the overlay had to be scraped
    back out of rendered HTML: where a `ref` box points."""
    (step,) = _payload(
        {
            "nr": 7,
            "message": "ref Abrechnung",
            "subprocess_ref": "Abrechnung",
            "ref_target": {"uc": "abrechnung", "sd": "zwischen_msb_und_lf"},
        }
    )["steps"]
    assert step["kind"] == "process_ref"
    assert step["subprocess_ref"] == "Abrechnung"
    assert step["subprocess_ref_id"] == "abrechnung__zwischen_msb_und_lf"
    # The `ref` marker was a rendering instruction the DSL needed inline; `kind` carries it
    # now, so the message keeps only what the source says.
    assert step["message"] == "Abrechnung"


def test_a_single_diagram_target_keeps_its_bare_id() -> None:
    """`uc__sd` is makuna's template id and what makrake's `{uc}`/`{sd}` split back apart —
    an empty `sd` must not leave a trailing separator, which would resolve to nothing."""
    (step,) = _payload({"nr": 1, "subprocess_ref": "X", "ref_target": {"uc": "lieferbeginn", "sd": ""}})["steps"]
    assert step["subprocess_ref_id"] == "lieferbeginn"


def test_a_ref_target_may_arrive_as_a_pair() -> None:
    """`resolve_ref` returns a mapping, but the dataset round-trips through YAML, where a
    tuple comes back as a list."""
    (step,) = _payload({"nr": 1, "subprocess_ref": "X", "ref_target": ["abrechnung", "zwischen_msb_und_lf"]})["steps"]
    assert step["subprocess_ref_id"] == "abrechnung__zwischen_msb_und_lf"


def test_an_unresolved_ref_gets_no_target() -> None:
    """A box with no link is honest; a box linking to the wrong process is not."""
    (step,) = _payload({"nr": 1, "message": "ref Unbekannt", "subprocess_ref": "Unbekannt", "ref_target": None})[
        "steps"
    ]
    assert step["kind"] == "process_ref" and "subprocess_ref_id" not in step


def test_a_frist_is_emitted_as_both_prose_and_structure() -> None:
    """Both, not either: makrake decides from the STRUCTURE whether the Frist reduces to a
    compact inline tag, and shows the PROSE as a note when it does not."""
    (step,) = _payload(
        {
            "nr": 1,
            "deadline_rule": {
                "type": "unverzüglich",
                "business_days": 2,
                "reference_step": 1,
                "reference_event": "ÜT",
                "raw": "Unverzüglich, jedoch spätester ÜT ist der 2. WT nach dem ÜT von Nr. 1.",
            },
        }
    )["steps"]
    assert step["deadline"] == "Unverzüglich, jedoch spätester ÜT ist der 2. WT nach dem ÜT von Nr. 1."
    rule = step["deadline_rule"]
    assert rule["coverage"] == "complete"
    (alt,) = rule["alternatives"]
    assert alt["kind"] == "immediate"
    assert alt["backstop"]["offset"] == {"amount": 2, "unit": "werktage", "direction": "nach"}
    assert alt["backstop"]["anchor"] == {"kind": "step", "steps": [1], "event": "ÜT"}


def test_the_structured_frist_matches_makunas_wire_shape() -> None:
    """The compatibility surface, asserted rather than assumed.

    makrake deserializes this into makuna's `Deadline`, whose `alternatives` and `coverage`
    are both required and whose `Anchor` is an internally-tagged enum keyed on `kind`. An
    extra key or a missing one is a render-time error naming a JSON column, so it is worth
    pinning here where the failure names the field. `raw` in particular must NOT appear:
    makuna's `Deadline` has no such field, and the prose lives on the step as `deadline`.
    """
    (step,) = _payload({"nr": 1, "deadline_rule": {"type": "terminiert", "latest_time": "07:00", "raw": "Bis 07:00."}})[
        "steps"
    ]
    rule = step["deadline_rule"]
    assert set(rule) == {"alternatives", "coverage"}
    (alt,) = rule["alternatives"]
    assert set(alt) <= {"kind", "condition", "immediacy", "backstop"}
    assert set(alt["backstop"]["anchor"]) >= {"kind"}


def test_a_frist_the_source_does_not_state_emits_no_structure() -> None:
    """An empty structure would make makrake draw a tag for an obligation that does not
    exist."""
    (step,) = _payload({"nr": 1, "deadline_rule": {"type": "none", "raw": "--"}})["steps"]
    assert "deadline_rule" not in step


def test_fragments_are_translated_recursively_with_makrakes_field_names() -> None:
    """`condition` is makrake's `guard` and `step_nrs` its `step_numbers`; a nested fragment
    keeps its branch's steps, which is what makes a nested `alt` draw inside its parent."""
    p = _payload(
        {"nr": 1},
        fragments=[
            {
                "type": "alt",
                "label": "Fall",
                "branches": [
                    {"condition": "a", "step_nrs": [1], "fragments": []},
                    {
                        "condition": "b",
                        "step_nrs": [],
                        "fragments": [{"type": "opt", "branches": [{"condition": "c", "step_nrs": [2]}]}],
                    },
                ],
            }
        ],
    )
    (frag,) = p["fragments"]
    assert frag["type"] == "alt" and frag["label"] == "Fall"
    assert frag["branches"][0] == {"guard": "a", "step_numbers": [1], "fragments": []}
    assert frag["branches"][1]["fragments"][0]["branches"][0]["step_numbers"] == [2]


def test_notes_keep_their_anchor_and_position() -> None:
    p = _payload({"nr": 1}, notes=[{"position": "right", "participants": ["NB"], "text": "Hinweis", "after_step": 1}])
    assert p["notes"] == [{"position": "right", "participants": ["NB"], "text": "Hinweis", "after_step": 1}]


def test_a_note_without_a_position_defaults_to_over() -> None:
    assert _payload({"nr": 1}, notes=[{"text": "x"}])["notes"][0]["position"] == "over"


def test_canonical_json_is_stable_under_key_order() -> None:
    """What an approval's hash is taken over: a hash that moved when a dict's insertion order
    did would clear every "Überprüft" badge on a rebuild that changed nothing."""
    a = canonical_json({"b": 1, "a": [2, 3]})
    b = canonical_json({"a": [2, 3], "b": 1})
    assert a == b == '{"a":[2,3],"b":1}'


def test_canonical_json_keeps_german_readable() -> None:
    """The inputs are read by a human debugging a render, so escaping every umlaut to \\uXXXX
    would make them useless for that."""
    assert canonical_json({"x": "Änderungstermin"}) == '{"x":"Änderungstermin"}'


def test_the_payload_round_trips_through_json() -> None:
    """It is written to disk and read by another process, so nothing in it may be a type only
    Python understands."""
    p = _payload({"nr": 1, "pid_refs": [1], "deadline_rule": {"type": "complex", "raw": "x"}})
    assert json.loads(canonical_json(p)) == p


def test_the_dash_placeholder_is_not_a_frist() -> None:
    """`deadline: "--"` is how the corpus writes "no Frist" — 554 steps at v0.0.20, more
    than a third of all of them.

    It is a placeholder in a table cell, not a sentence. Passed through, makrake draws
    `Frist: --` beside the arrow: a Frist asserted on every step whose source says there
    is none. Caught by looking at a rendered page (`lieferbeginn`'s three `par` branches),
    not by a test — hence this one.
    """
    for dash in ("--", "—", " – ", "---"):
        (step,) = _payload({"nr": 1, "deadline": dash, "deadline_rule": {"type": "none", "raw": dash}})["steps"]
        assert "deadline" not in step, dash
        assert "deadline_rule" not in step, dash


def test_real_prose_that_is_short_or_contains_a_dash_survives() -> None:
    """The complement, so the placeholder check cannot grow into eating content. `"1 WT"`
    is a real Frist on two corpus steps."""
    (short,) = _payload({"nr": 1, "deadline": "1 WT"})["steps"]
    assert short["deadline"] == "1 WT"
    (dashed,) = _payload({"nr": 1, "deadline": "Unverzüglich — spätestens 2 WT"})["steps"]
    assert dashed["deadline"] == "Unverzüglich — spätestens 2 WT"
