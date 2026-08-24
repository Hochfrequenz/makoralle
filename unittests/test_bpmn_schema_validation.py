"""Validate makoralle's generated BPMN 2.0 XML against the real, official OMG schema —
the same pattern used by machine-readable_mako-prozesse's CI to check process YAML
against makoralle's models, applied here to BPMN against its actual spec instead of a
pydantic model (bpmn.py has none; it builds XML directly).

Fixtures are hand-authored PlantUML snippets, not real dataset content — this package
is public, machine-readable_mako-prozesse is private.

Also covers several bugs found by validating all 135 real files in the (private)
machine-readable_mako-prozesse dataset against this same vendored schema: a lane name
containing a space produced an invalid xs:ID; two lane markers differing only in
whitespace (``|MSB|`` / ``|MSB |``, or an internal run like ``|weiterer  MSB|``) were
treated as two distinct lanes, which either collided once sanitized (a document-wide
duplicate id) or, worse, silently rendered as two separate lanes; two DIFFERENT lane
names can also sanitize to the same id (e.g. "Lane A" and "Lane_A"), needing their own
disambiguation; and a fork/decision split with two or more empty branches (nothing
between the split and the next `fork again`/`else`) emitted a duplicate
sequenceFlow/edge id.
"""

import logging
import re
from pathlib import Path

import pytest
from lxml import etree

from makoralle.serialization.bpmn import _ncname, plantuml_to_bpmn

XSD_DIR = Path(__file__).parent / "fixtures" / "bpmn_xsd"


@pytest.fixture(scope="module")
def bpmn_schema() -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(XSD_DIR / "BPMN20.xsd")))


def _assert_schema_valid(xml: str, schema: etree.XMLSchema) -> None:
    doc = etree.fromstring(xml.encode("utf-8"))
    if not schema.validate(doc):
        # lxml-stubs types _ErrorLog as an opaque `...` (no __iter__), so str() is what
        # mypy allows; it happens to also be lxml's own multi-line rendering of the log.
        pytest.fail(str(schema.error_log))
    _assert_all_ids_unique(doc)


def _assert_all_ids_unique(doc: etree._Element) -> None:
    """xs:ID is unique document-wide; the schema itself enforces this (a duplicate is a
    validation error), but asserting it directly, on every fixture, is what actually
    caught bug 1 (duplicate sequenceFlow ids) here rather than via an opaque schema
    error — and it would just as well catch a future lane-id collision (see the
    disambiguating allocator in plantuml_to_bpmn) on any fixture, not just the ones
    written specifically to exercise it."""
    matches = doc.xpath("//@id")
    assert isinstance(matches, list)  # this expression always yields a node-set, never a bool/float/str
    ids = [str(i) for i in matches]
    assert len(ids) == len(set(ids)), f"duplicate id(s): {sorted({i for i in ids if ids.count(i) > 1})}"


PUML_NO_LANES = """
@startuml
start
:Anfrage stellen;
:Antwort prüfen;
stop
@enduml
"""

PUML_WITH_LANES = """
@startuml
|LF|
start
:Anfrage stellen;
|NB|
:Antwort pruefen;
:Bestaetigung senden/
|LF|
stop
@enduml
"""

PUML_WITH_DECISION = """
@startuml
|LF|
start
:Pruefung durchfuehren;
if (Ergebnis positiv?) then (ja)
  :Bestaetigung senden;
else (nein)
  :Ablehnung senden;
endif
:Abschluss;
stop
@enduml
"""

PUML_WITH_SUBPROCESS = """
@startuml
|LF|
start
#FFFACD:Unterprozess XY|
:Weiterverarbeitung;
stop
@enduml
"""

PUML_WITH_STEREOTYPES = """
@startuml
|MSB|
start
:Normale Aufgabe;
:Nachricht an Marktpartner;<<save>>
|NB|
:Aufruf eines Unterprozesses;<<procedure>>
stop
@enduml
"""

PUML_WITH_UNKNOWN_STEREOTYPE = """
@startuml
|MSB|
start
:Etwas Neues;<<future>>
stop
@enduml
"""

PUML_WITH_SPLIT = """
@startuml
|LF|
start
split
:Zweig A;
split again
:Zweig B;
end split
:Zusammenführung;
stop
@enduml
"""

PUML_WITH_EMPTY_IF_CONDITION = """
@startuml
|LF|
start
:Prüfung durchführen;
if () then (ja)
  :Bestaetigung senden;
else ()
  :Ablehnung senden;
endif
:Abschluss;
stop
@enduml
"""

PUML_WITH_FORK = """
@startuml
|LF|
start
fork
:Prüfung A durchführen;
fork again
:Prüfung B durchführen;
end fork
:Zusammenführung;
stop
@enduml
"""

PUML_EMPTY = """
@startuml
@enduml
"""

PUML_WITH_LANE_NAME_SPACE = """
@startuml
|weiterer MSB|
start
:Etwas tun;
stop
@enduml
"""

PUML_WITH_INCONSISTENT_LANE_WHITESPACE = """
@startuml
|MSB|
start
:Erste Aufgabe;
|MSB |
:Zweite Aufgabe;
stop
@enduml
"""

PUML_WITH_TWO_EMPTY_FORK_BRANCHES = """
@startuml
|NB|
start
fork
fork again
fork again
:Aufgabe C;
end fork
stop
@enduml
"""

PUML_WITH_COLLIDING_LANE_NAMES = """
@startuml
|Lane A|
start
:Erste Aufgabe;
|Lane_A|
:Zweite Aufgabe;
stop
@enduml
"""

PUML_WITH_INTERNAL_LANE_WHITESPACE = """
@startuml
|weiterer MSB|
start
:Erste Aufgabe;
|weiterer  MSB|
:Zweite Aufgabe;
stop
@enduml
"""


@pytest.mark.parametrize(
    "puml",
    [
        pytest.param(PUML_NO_LANES, id="no_lanes"),
        pytest.param(PUML_WITH_LANES, id="with_lanes"),
        pytest.param(PUML_WITH_DECISION, id="with_decision_gateway"),
        pytest.param(PUML_WITH_SUBPROCESS, id="with_subprocess_ref"),
        pytest.param(PUML_WITH_STEREOTYPES, id="with_save_and_procedure_stereotypes"),
        pytest.param(PUML_WITH_UNKNOWN_STEREOTYPE, id="with_unknown_stereotype"),
        pytest.param(PUML_WITH_SPLIT, id="with_split_join"),
        pytest.param(PUML_WITH_EMPTY_IF_CONDITION, id="with_empty_if_condition"),
        pytest.param(PUML_WITH_FORK, id="with_fork_join"),
        pytest.param(PUML_EMPTY, id="empty_diagram"),
        pytest.param(PUML_WITH_LANE_NAME_SPACE, id="lane_name_with_space"),
        pytest.param(PUML_WITH_INCONSISTENT_LANE_WHITESPACE, id="inconsistent_lane_whitespace"),
        pytest.param(PUML_WITH_TWO_EMPTY_FORK_BRANCHES, id="two_empty_fork_branches"),
        pytest.param(PUML_WITH_COLLIDING_LANE_NAMES, id="colliding_lane_names"),
        pytest.param(PUML_WITH_INTERNAL_LANE_WHITESPACE, id="internal_lane_whitespace"),
    ],
)
def test_plantuml_to_bpmn_is_well_formed_and_schema_valid(puml: str, bpmn_schema: etree.XMLSchema) -> None:
    xml = plantuml_to_bpmn(puml, "Test Process")
    _assert_schema_valid(xml, bpmn_schema)  # fromstring above already proves well-formedness


def test_save_and_procedure_stereotypes_are_not_silently_dropped() -> None:
    """Regression test: real dataset source marks some actions with a PlantUML
    stereotype instead of the older dedicated syntaxes this parser otherwise
    recognizes — ":text;<<save>>" (a message crossing a swimlane, per this dataset's
    own GENERATED_WITH.json provenance notes) and ":text;<<procedure>>" (a subprocess
    call, in a second lane here — the fixture spans two lanes so lane membership for a
    stereotyped action is also pinned, not just its element type). A line ending in
    ">>" matched neither the ":text/" (send) nor the ":text;" (task) rule, so before
    this fix the entire line — and the activity it names — was silently dropped: found
    by comparing element counts before/after regenerating a real dataset's output/bpmn/
    with this fix, not by inspecting the parser code.

    Asserts connectivity, not just that the right element types exist: the original bug
    also meant "no connecting sequenceFlow" — a fix that emitted the right element but
    left it unlinked would still pass a name/type-only check."""
    xml = plantuml_to_bpmn(PUML_WITH_STEREOTYPES, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    tasks = {t.get("name"): t.get("id") for t in doc.findall(".//m:task", MODEL_NS)}
    sends = {t.get("name"): t.get("id") for t in doc.findall(".//m:sendTask", MODEL_NS)}
    calls = {t.get("name"): t.get("id") for t in doc.findall(".//m:callActivity", MODEL_NS)}
    assert set(tasks) == {"Normale Aufgabe"}
    assert set(sends) == {"Nachricht an Marktpartner"}
    assert set(calls) == {"Aufruf eines Unterprozesses"}

    flows = {(sf.get("sourceRef"), sf.get("targetRef")) for sf in doc.findall(".//m:sequenceFlow", MODEL_NS)}
    task_id = tasks["Normale Aufgabe"]
    send_id = sends["Nachricht an Marktpartner"]
    call_id = calls["Aufruf eines Unterprozesses"]
    assert (task_id, send_id) in flows
    assert (send_id, call_id) in flows

    # the sendTask (first lane) and callActivity (second lane) each belong to their own lane
    lanes = {}
    for lane in doc.findall(".//m:lane", MODEL_NS):
        lanes[lane.get("name")] = {ref.text for ref in lane.findall("m:flowNodeRef", MODEL_NS)}
    assert send_id in lanes["MSB"]
    assert call_id in lanes["NB"]


def test_unknown_action_stereotype_degrades_to_a_plain_task(caplog: pytest.LogCaptureFixture) -> None:
    """A stereotype other than <<save>>/<<procedure>> is not (yet) modeled — but per the
    lesson of the bug above, an unrecognized construct must never disappear silently.
    It degrades to a plain task (a lost distinction, not a lost node) and is logged."""
    with caplog.at_level(logging.WARNING):
        xml = plantuml_to_bpmn(PUML_WITH_UNKNOWN_STEREOTYPE, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    tasks = {t.get("name") for t in doc.findall(".//m:task", MODEL_NS)}
    assert tasks == {"Etwas Neues"}
    assert "future" in caplog.text


def test_split_join_is_not_silently_flattened() -> None:
    """Regression test: PlantUML's "split"/"split again"/"end split" is the same
    parallel-branch construct as "fork"/"fork again"/"end fork" under a different
    keyword. Real source uses both, but only "fork" was recognized — "split" matched no
    rule, so the branches were silently flattened into one linear path with no
    parallelGateway at all (found in the same real-corpus audit as the stereotype bug,
    54 lines across 9 of 87 real files)."""
    xml = plantuml_to_bpmn(PUML_WITH_SPLIT, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    assert len(doc.findall(".//m:parallelGateway", MODEL_NS)) == 2  # split + merge
    tasks = {t.get("name") for t in doc.findall(".//m:task", MODEL_NS)}
    assert tasks == {"Zweig A", "Zweig B", "Zusammenführung"}


def test_empty_if_condition_still_creates_a_gateway() -> None:
    """Regression test: real source has "if () then (label)" — an empty condition.
    `.+?` (at least one character) matched nothing, so the ENTIRE decision — both
    branches, the merge, the branch labels — silently vanished, concatenating the
    branches into one linear path (found in the same audit, 39 occurrences across 15 of
    87 real files). Fixed with `[^)]*` (zero or more)."""
    xml = plantuml_to_bpmn(PUML_WITH_EMPTY_IF_CONDITION, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    assert len(doc.findall(".//m:exclusiveGateway", MODEL_NS)) == 2  # split + merge
    tasks = {t.get("name") for t in doc.findall(".//m:task", MODEL_NS)}
    assert tasks == {"Prüfung durchführen", "Bestaetigung senden", "Ablehnung senden", "Abschluss"}


def _definitions_open_tag(xml: str) -> str:
    """The literal ``<definitions ...>`` open tag, as written — NOT ``xml.split(">", 1)[0]``,
    which only reaches the ``<?xml ...?>`` declaration that precedes it and would make a
    duplicate-attribute check on the actual root tag silently vacuous (caught in review:
    reinjecting the original bug into this test still passed)."""
    return xml.split("<definitions", 1)[1].split(">", 1)[0]


def test_plantuml_to_bpmn_declares_each_namespace_prefix_exactly_once() -> None:
    """Regression test for the bug this suite exists to catch: `_generate_diagram`'s
    Clark-notation elements made ElementTree re-declare bpmndi/dc/di on <definitions>,
    on top of the ones already hardcoded there — the same attribute twice on one tag,
    which is not well-formed XML (lxml refuses to even parse it; the schema check above
    can't run at all until this is fixed first)."""
    tag = _definitions_open_tag(plantuml_to_bpmn(PUML_WITH_LANES, "Test Process"))
    for prefix in ("xmlns:bpmndi=", "xmlns:dc=", "xmlns:di=", "xmlns="):
        assert tag.count(prefix) == 1, f"{prefix!r} not declared exactly once in: {tag}"


def test_no_shape_for_the_lane_set_itself() -> None:
    """Regression test: a BPMNShape for the laneSet itself (id=laneSet_1_di,
    bpmnElement=laneSet_1) used to be emitted without the Bounds child every BPMNShape
    requires, failing schema validation. BPMN DI depicts pools/lanes/flow nodes, not a
    LaneSet, so the fix removes the shape rather than inventing geometry for it — each
    individual lane below already gets its own shape with the required Bounds (not a claim
    that the bounds contain that lane's node shapes -- a separate, pre-existing geometry
    mismatch, out of scope here)."""
    xml = plantuml_to_bpmn(PUML_WITH_LANES, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI", "dc": "http://www.omg.org/spec/DD/20100524/DC"}
    assert doc.findall(".//bpmndi:BPMNShape[@bpmnElement='laneSet_1']", ns) == []
    lane_shapes = doc.findall(".//bpmndi:BPMNShape[@isHorizontal='true']", ns)
    assert len(lane_shapes) == 2  # LF, NB
    for shape in lane_shapes:
        assert shape.find("dc:Bounds", ns) is not None


MODEL_NS = {"m": "http://www.omg.org/spec/BPMN/20100524/MODEL"}


def test_lane_name_with_a_space_gets_a_valid_ncname_id() -> None:
    """Regression test: lane ids were built as f"lane_{lane_name}" with the PlantUML
    source text used verbatim — a real dataset lane name like "weiterer MSB" produced
    the id "lane_weiterer MSB", not a legal xs:ID (NCName forbids whitespace)."""
    xml = plantuml_to_bpmn(PUML_WITH_LANE_NAME_SPACE, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    lane = doc.find(".//m:lane", MODEL_NS)
    assert lane is not None
    assert lane.get("id") == "lane_weiterer_MSB"
    assert lane.get("name") == "weiterer MSB"  # the human-readable name is untouched


def test_inconsistent_lane_whitespace_is_one_lane_not_two() -> None:
    """Regression test: real dataset source has both "|MSB|" and "|MSB |" (trailing
    space) for what's clearly meant to be one actor. Before normalizing, that produced
    two distinct <lane> elements whose ids then collided once whitespace was correctly
    stripped when sanitizing each into an NCName — a real dataset file
    (reklamation_von_werten_beim_msb) failed schema validation on exactly this."""
    xml = plantuml_to_bpmn(PUML_WITH_INCONSISTENT_LANE_WHITESPACE, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    lanes = doc.findall(".//m:lane", MODEL_NS)
    assert len(lanes) == 1
    assert lanes[0].get("name") == "MSB"
    # start, both tasks (one per swimlane marker), and stop all belong to the single lane
    assert len(lanes[0].findall("m:flowNodeRef", MODEL_NS)) == 4


def test_internal_lane_whitespace_is_one_lane_not_two() -> None:
    """Same bug as the leading/trailing-whitespace case above, but for a run of
    whitespace INSIDE the name ("weiterer MSB" vs "weiterer  MSB") — .strip() alone
    would not catch this; the fix normalizes the whole name via " ".join(...split())."""
    xml = plantuml_to_bpmn(PUML_WITH_INTERNAL_LANE_WHITESPACE, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    lanes = doc.findall(".//m:lane", MODEL_NS)
    assert len(lanes) == 1
    assert lanes[0].get("name") == "weiterer MSB"


def test_colliding_lane_names_get_distinct_ids() -> None:
    """Regression test: two DIFFERENT lane names can sanitize to the same id ("Lane A"
    and "Lane_A" both -> "lane_Lane_A") — a document-wide duplicate xs:ID, which
    invalidates the whole file, not just the lane. The allocator in plantuml_to_bpmn
    disambiguates with a numeric suffix."""
    xml = plantuml_to_bpmn(PUML_WITH_COLLIDING_LANE_NAMES, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    lanes = doc.findall(".//m:lane", MODEL_NS)
    assert len(lanes) == 2
    ids = [lane.get("id") for lane in lanes]
    assert len(ids) == len(set(ids)), f"duplicate lane id(s): {ids}"
    names = {lane.get("name") for lane in lanes}
    assert names == {"Lane A", "Lane_A"}


def test_two_empty_fork_branches_do_not_duplicate_the_merge_sequence_flow() -> None:
    """Regression test: a fork branch with no content before the next `fork again`
    never advances past the split gateway's own id, so two such empty branches both
    record that same id as "where this branch ends" — emitting one sequenceFlow per
    recorded end then wrote the same (id, sourceRef, targetRef) twice. A real dataset
    file (beginn_der_ersatz-_grundversorgung) had this exact duplicate.

    Asserts more than "no duplicate ids": a fix that just dropped every entry but the
    first would also produce unique ids while silently deleting the real Aufgabe-C
    branch's edge. Pin exactly which two edges reach the merge gateway — the split's own
    id once (both empty branches collapsed to the one real edge) and the non-empty
    branch's task once."""
    xml = plantuml_to_bpmn(PUML_WITH_TWO_EMPTY_FORK_BRANCHES, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    flow_ids = [sf.get("id") for sf in doc.findall(".//m:sequenceFlow", MODEL_NS)]
    assert len(flow_ids) == len(set(flow_ids)), f"duplicate sequenceFlow id(s) in: {flow_ids}"

    merge = doc.find(".//m:parallelGateway[@gatewayDirection='Converging']", MODEL_NS)
    split = doc.find(".//m:parallelGateway[@gatewayDirection='Diverging']", MODEL_NS)
    task = doc.find(".//m:task", MODEL_NS)
    assert merge is not None
    assert split is not None
    assert task is not None
    merge_id = merge.get("id", "")
    sources = sorted(
        sf.get("sourceRef", "") for sf in doc.findall(".//m:sequenceFlow", MODEL_NS) if sf.get("targetRef") == merge_id
    )
    assert sources == sorted([split.get("id", ""), task.get("id", "")])


_NCNAME_START_RE = re.compile(r"^[A-Za-z_][\w.\-]*$")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MSB", "MSB"),
        ("MSB ", "MSB"),
        ("weiterer MSB", "weiterer_MSB"),
        ("München", "München"),  # Unicode letters pass through unchanged, stay readable
        ("Prüfung/Änderung", "Prüfung_Änderung"),
        ("9 Partei", "_9_Partei"),  # leading digit AFTER sanitizing, not just raw[0]
        ("0abc", "_0abc"),
        (".x", "_.x"),
        ("-x", "_-x"),
        ("", "_"),
        ("   ", "_"),
        ("!!!", "___"),
    ],
)
def test_ncname_exact_output(raw: str, expected: str) -> None:
    assert _ncname(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1st lane",  # leading digit after sanitizing — found in round-1 review (Copilot)
        "9",
        "weiterer MSB",
        "  MSB  ",
        "!!!",
        "",
        "   ",
        "München",
    ],
)
def test_ncname_always_produces_a_valid_ncname(raw: str) -> None:
    """Property check alongside the exact-value table above: whatever the input, the
    result must start with a legal NCName start character."""
    result = _ncname(raw)
    assert _NCNAME_START_RE.match(result), f"{result!r} (from {raw!r}) is not a valid NCName"
