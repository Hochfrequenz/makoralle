# BPMN 2.0 XSD (vendored)

Copies of the official OMG BPMN 2.0 XML schema, fetched from
<https://www.omg.org/spec/BPMN/20100501/> and otherwise unmodified — except `DI.xsd`,
which shipped with a UTF-8 BOM the repo's "Prevent ByteOrderMarks" check rejects; that
BOM was stripped, no other byte changed:

- `BPMN20.xsd` — root schema, imports the other four
- `Semantic.xsd` — the BPMN element definitions
- `BPMNDI.xsd`, `DI.xsd`, `DC.xsd` — Diagram Interchange (visual layout)

Used by `unittests/test_bpmn_schema_validation.py` to validate
`makoralle.serialization.bpmn.plantuml_to_bpmn`'s output against the real
spec, fully offline. Vendored rather than fetched at test time so CI doesn't
depend on omg.org being reachable.
