"""Validate makoralle's generated BPMN 2.0 XML against the real, official OMG schema —
the same pattern used by machine-readable_mako-prozesse's CI to check process YAML
against makoralle's models, applied here to BPMN against its actual spec instead of a
pydantic model (bpmn.py has none; it builds XML directly).

Fixtures are hand-authored PlantUML snippets, not real dataset content — this package
is public, machine-readable_mako-prozesse is private.

Known NOT yet covered here (separate root causes, tracked for a follow-up fix): a lane
name containing a space produces an invalid xs:ID (``lane_<name>`` isn't sanitized), and
some fork/parallel-gateway shapes emit a duplicate sequenceFlow/edge id. Every fixture
below avoids both — PUML_WITH_FORK included, verified against the vendored schema to not
trigger the duplicate-id case — so this suite exercises exactly what it fixes:
well-formedness and the (now removed, see PUML_WITH_LANES's test) invalid laneSet shape.
"""

from pathlib import Path

import pytest
from lxml import etree

from makoralle.serialization.bpmn import plantuml_to_bpmn

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


@pytest.mark.parametrize(
    "puml",
    [
        pytest.param(PUML_NO_LANES, id="no_lanes"),
        pytest.param(PUML_WITH_LANES, id="with_lanes"),
        pytest.param(PUML_WITH_DECISION, id="with_decision_gateway"),
        pytest.param(PUML_WITH_SUBPROCESS, id="with_subprocess_ref"),
        pytest.param(PUML_WITH_FORK, id="with_fork_join"),
        pytest.param(PUML_EMPTY, id="empty_diagram"),
    ],
)
def test_plantuml_to_bpmn_is_well_formed_and_schema_valid(puml: str, bpmn_schema: etree.XMLSchema) -> None:
    xml = plantuml_to_bpmn(puml, "Test Process")
    _assert_schema_valid(xml, bpmn_schema)  # fromstring above already proves well-formedness


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
    individual lane below already gets its own correctly-bounded shape."""
    xml = plantuml_to_bpmn(PUML_WITH_LANES, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI", "dc": "http://www.omg.org/spec/DD/20100524/DC"}
    assert doc.findall(".//bpmndi:BPMNShape[@bpmnElement='laneSet_1']", ns) == []
    lane_shapes = doc.findall(".//bpmndi:BPMNShape[@isHorizontal='true']", ns)
    assert len(lane_shapes) == 2  # LF, NB
    for shape in lane_shapes:
        assert shape.find("dc:Bounds", ns) is not None
