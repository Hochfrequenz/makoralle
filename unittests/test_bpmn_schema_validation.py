"""Validate makoralle's generated BPMN 2.0 XML against the real, official OMG schema —
the same pattern used by machine-readable_mako-prozesse's CI to check process YAML
against makoralle's models, applied here to BPMN against its actual spec instead of a
pydantic model (bpmn.py has none; it builds XML directly).

Fixtures are hand-authored PlantUML snippets, not real dataset content — this package
is public, machine-readable_mako-prozesse is private.

Known NOT yet covered here (separate root causes, tracked for a follow-up fix): a lane
name containing a space produces an invalid xs:ID (``lane_<name>`` isn't sanitized), and
some fork/parallel-gateway shapes emit a duplicate sequenceFlow/edge id. Every fixture
below avoids both so this suite exercises exactly what it fixes: well-formedness and the
lane-set shape's required Bounds child.
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


@pytest.mark.parametrize(
    "puml",
    [
        pytest.param(PUML_NO_LANES, id="no_lanes"),
        pytest.param(PUML_WITH_LANES, id="with_lanes"),
        pytest.param(PUML_WITH_DECISION, id="with_decision_gateway"),
        pytest.param(PUML_WITH_SUBPROCESS, id="with_subprocess_ref"),
    ],
)
def test_plantuml_to_bpmn_is_well_formed_and_schema_valid(puml: str, bpmn_schema: etree.XMLSchema) -> None:
    xml = plantuml_to_bpmn(puml, "Test Process")
    _assert_schema_valid(xml, bpmn_schema)  # fromstring above already proves well-formedness


def test_plantuml_to_bpmn_declares_each_namespace_prefix_at_most_once() -> None:
    """Regression test for the bug this suite exists to catch: `_generate_diagram`'s
    Clark-notation elements made ElementTree re-declare bpmndi/dc/di on <definitions>,
    on top of the ones already hardcoded there — the same attribute twice on one tag,
    which is not well-formed XML (lxml refuses to even parse it; the schema check above
    can't run at all until this is fixed first)."""
    xml = plantuml_to_bpmn(PUML_WITH_LANES, "Test Process")
    header = xml.split(">", 1)[0]
    for prefix in ("xmlns:bpmndi", "xmlns:dc", "xmlns:di", "xmlns="):
        assert header.count(prefix) <= 1, f"{prefix!r} declared more than once in: {header}"


def test_lane_set_shape_has_bounds() -> None:
    """Regression test: the laneSet's own BPMNShape was missing the Bounds child every
    BPMN 2.0 shape requires (schema fails with 'Missing child element(s)' without it)."""
    xml = plantuml_to_bpmn(PUML_WITH_LANES, "Test Process")
    doc = etree.fromstring(xml.encode("utf-8"))
    ns = {"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI", "dc": "http://www.omg.org/spec/DD/20100524/DC"}
    lane_set_shapes = doc.findall(".//bpmndi:BPMNShape[@bpmnElement='laneSet_1']", ns)
    assert len(lane_set_shapes) == 1
    assert lane_set_shapes[0].find("dc:Bounds", ns) is not None
