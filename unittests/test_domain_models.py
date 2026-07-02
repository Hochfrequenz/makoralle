from makoralle.models.activity import ActivityDiagram, ADEdge, ADNode
from makoralle.models.ebd import DecisionStep, DecisionTree
from makoralle.models.pid import PIDMapping
from makoralle.models.process import (
    DeadlineRule,
    NamedSD,
    Process,
    SDBranch,
    SDFragment,
    SDNote,
    SDStep,
    SequenceDiagram,
    UseCase,
)


def test_deadline_rule_defaults_for_new_fields() -> None:
    """The anchor/direction/recurring fields default to None/None/False so existing
    (pre-extension) rules deserialize unchanged."""
    rule = DeadlineRule(type="unverzüglich", raw="Unverzüglich")
    assert rule.direction is None
    assert rule.anchor is None
    assert rule.recurring is False


def test_deadline_rule_terminiert_roundtrips_external_anchor() -> None:
    """A 'terminiert' rule carrying a WT count relative to an external, non-step
    anchor round-trips through model_dump/model_validate."""
    rule = DeadlineRule(
        type="terminiert",
        direction="vor",
        business_days=20,
        reference_event="ÜT",
        anchor="Änderungstermin",
        raw="Spätester ÜT ist der 20. WT vor dem gewünschten Änderungstermin.",
    )
    back = DeadlineRule.model_validate(rule.model_dump())
    assert back.type == "terminiert"
    assert back.direction == "vor"
    assert back.business_days == 20
    assert back.anchor == "Änderungstermin"
    assert back.recurring is False


def test_use_case() -> None:
    uc = UseCase(
        goal="Zuordnung eines LF zu einer Marktlokation",
        description="Der LF meldet sich beim NB an",
        roles=["LF", "NB"],
        preconditions=["Vertrag liegt vor"],
        triggers=["LF sendet Anmeldung"],
        postconditions_success=["LF ist zugeordnet"],
        postconditions_failure=["Ablehnung"],
    )
    assert "LF" in uc.roles


def test_sequence_diagram() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(
                nr=1,
                sender="LF",
                receiver="NB",
                message="Anmeldung",
                format="UTILMD",
                description="LF sendet Anmeldung",
            ),
        ],
    )
    assert sd.steps[0].nr == 1
    assert sd.steps[0].sender == "LF"


def test_sequence_diagram_with_fragments_roundtrips() -> None:
    sd = SequenceDiagram(
        participants=["LF", "NB"],
        steps=[
            SDStep(nr=1, sender="LF", receiver="NB", message="Anmeldung", format="UTILMD"),
            SDStep(nr=2, sender="NB", receiver="LF", message="Antwort", ebd_ref="E_0401"),
            SDStep(nr=3, sender="NB", receiver="NB", message="ref Subprozess", subprocess_ref="kuendigung"),
        ],
        fragments=[
            SDFragment(
                type="alt",
                branches=[
                    SDBranch(condition="Zustimmung", step_nrs=[2]),
                    SDBranch(condition="Ablehnung", step_nrs=[]),
                ],
            ),
        ],
        notes=[SDNote(position="over", participants=["LF", "NB"], text="Hinweis", after_step=1)],
    )
    dumped = sd.model_dump()
    restored = SequenceDiagram(**dumped)
    assert restored.fragments[0].type == "alt"
    assert restored.fragments[0].branches[0].condition == "Zustimmung"
    assert restored.fragments[0].branches[0].step_nrs == [2]
    assert restored.notes[0].after_step == 1
    assert restored.steps[0].format == "UTILMD"
    assert restored.steps[1].ebd_ref == "E_0401"
    assert restored.steps[2].subprocess_ref == "kuendigung"


def test_sdstep_no_longer_has_step_type() -> None:
    fields = SDStep.model_fields
    # pylint: disable=unsupported-membership-test  # model_fields is a dict at runtime
    assert "step_type" not in fields
    assert "condition" not in fields


def test_decision_tree() -> None:
    dt = DecisionTree(
        id="E_0622",
        name="Prüfen, ob Anmeldung direkt ablehnbar",
        source="EBD 4.1, Kap. 6.6.1",
        steps=[
            DecisionStep(
                nr=1,
                check="Ist die Marktlokation bekannt?",
                if_yes=2,
                if_no_result="Ablehnung",
                if_no_code="A01",
            ),
        ],
    )
    assert dt.id == "E_0622"
    assert dt.steps[0].if_no_code == "A01"


def test_pid_mapping() -> None:
    # pylint: disable=non-ascii-name  # German domain field names carry ü/ä by design
    pid = PIDMapping(
        lfd_nr=170,
        ahb="UTILMD AHB Gas",
        anwendungsfall="Anmeldung NN",
        prüfidentifikator=44001,
        prozessbeschreibung_kapitel="Kap. B 3.3 Nr. 1",
        bezeichnung_sequenzdiagramm="Anmeldung",
        kommunikation_von="LF",
        kommunikation_an="NB",
        übertragungsweg="AS4",
    )
    assert pid.prüfidentifikator == 44001


def test_activity_diagram() -> None:
    ad = ActivityDiagram(
        participants=["LF", "NB"],
        nodes=[
            ADNode(id="start", type="start"),
            ADNode(id="act1", type="action", role="LF", label="Anmeldung senden"),
        ],
        edges=[
            ADEdge(source="start", target="act1"),
        ],
    )
    assert len(ad.nodes) == 2
    assert ad.edges[0].source == "start"


def test_process() -> None:
    proc = Process(
        id="lieferbeginn",
        name="Lieferbeginn",
        source="GPKE Teil 2, Kapitel 2.1",
        category="Zuordnungsprozesse",
    )
    assert proc.id == "lieferbeginn"


def test_named_sd_carries_slug_and_name() -> None:
    sd = NamedSD(
        slug="vom_nb",
        name="vom NB (verantwortlich) ausgehend",
        source_heading="1.4.2 SD: …",
        participants=["NB"],
        steps=[],
    )
    assert sd.slug == "vom_nb"
    assert sd.name is not None
    assert sd.name.startswith("vom NB")


def test_process_holds_multiple_diagrams_and_primary_alias() -> None:
    a = NamedSD(slug="vom_nb", participants=["NB"], steps=[SDStep(nr=1, sender="NB", receiver="LF", message="x")])
    b = NamedSD(slug="vom_lf", participants=["LF"], steps=[])
    p = Process(id="u", name="U", source="s", category="GPKE", diagrams=[a, b])
    assert len(p.diagrams) == 2
    # backward-compat: primary alias is the first diagram as a plain SequenceDiagram
    assert p.sequence_diagram is not None
    assert p.sequence_diagram.steps[0].message == "x"
