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


def test_recurrence_is_optional_so_older_datasets_still_parse() -> None:
    """`recurring` stays a bool: a dataset written before `recurrence` existed must still load."""
    old = DeadlineRule.model_validate({"type": "terminiert", "recurring": True, "latest_time": "14:00", "raw": "…"})
    assert old.recurring is True
    assert old.recurrence is None
    # and the new field survives a round trip
    new = DeadlineRule(type="terminiert", recurring=True, recurrence="werktäglich", raw="…")
    assert DeadlineRule.model_validate(new.model_dump()).recurrence == "werktäglich"


def test_pid_mapping_sparte_is_absent_by_default() -> None:
    """The three new fields are optional, so a tree parsed before makoralle#55 still loads
    and every existing caller keeps working."""
    # pylint: disable=non-ascii-name
    pid = PIDMapping(lfd_nr=1, ahb="UTILMD AHB Strom", anwendungsfall="x", prüfidentifikator=55001)
    assert pid.prozessbeschreibung_dokument is None
    assert (pid.sparte_strom, pid.sparte_gas) == (None, None)
    # Empty, NOT {"Strom","Gas"} and not an error: the row makes no sparte claim.
    assert pid.sparten == frozenset()


def test_pid_mapping_sparten_reads_the_markers() -> None:
    # pylint: disable=non-ascii-name
    gas = PIDMapping(
        lfd_nr=170,
        ahb="UTILMD AHB Gas",
        anwendungsfall="Anmeldung NN",
        prüfidentifikator=44001,
        prozessbeschreibung_dokument="GeLi Gas 2.0",
        sparte_strom=False,
        sparte_gas=True,
    )
    assert gas.sparten == frozenset({"Gas"})
    # frozenset, not set: `set(...) == frozenset(...)` in Python, so without this the
    # annotation would be decoration and a caller caching a scope could not hash it.
    assert isinstance(gas.sparten, frozenset)
    both = gas.model_copy(update={"sparte_strom": True})
    # A row CAN be dual-sparte, which is why this is not a single enum.
    assert both.sparten == frozenset({"Strom", "Gas"})
    # Explicitly unset is still "no claim", so a caller cannot tell it from a missing
    # column — and must therefore treat both as unscoped rather than as "neither".
    neither = gas.model_copy(update={"sparte_gas": False})
    assert neither.sparten == frozenset()


def test_pid_mapping_sparte_recorded_separates_absent_from_unmarked() -> None:
    """The distinction `sparten` deliberately collapses. A scoping rule needs it to tell
    "this workbook layout had no Sparte columns" from "it had them and marked neither",
    because only the first means it must not scope at all."""
    # pylint: disable=non-ascii-name
    base = dict(lfd_nr=1, ahb="UTILMD AHB Strom", anwendungsfall="x", prüfidentifikator=55001)
    assert PIDMapping(**base).sparte_recorded is False
    assert PIDMapping(**base, sparte_strom=False, sparte_gas=False).sparte_recorded is True
    # Both still yield "no claim" through the usable view.
    assert PIDMapping(**base, sparte_strom=False, sparte_gas=False).sparten == frozenset()


def test_pid_mapping_serialization_is_unchanged_for_rows_without_sparte() -> None:
    """The compatibility argument for this change, pinned.

    `serialization/process_yaml.py` dumps rows with `exclude_none=True`, so the three new
    fields add nothing to the ~905 serialized PID rows the parser does not populate — the
    next regeneration shows no diff from them. Without this test an `exclude_none`
    regression would quietly add three null keys to every row in the dataset.

    Also pins that the derived views stay out of the dump: `sparten` is a frozenset, which
    would serialize as a python-object tag rather than as YAML data.
    """
    # pylint: disable=non-ascii-name
    dumped = PIDMapping(lfd_nr=1, ahb="UTILMD AHB Strom", anwendungsfall="x", prüfidentifikator=55001).model_dump(
        exclude_none=True
    )
    assert "prozessbeschreibung_dokument" not in dumped
    assert "sparte_strom" not in dumped and "sparte_gas" not in dumped
    assert "sparten" not in dumped and "sparte_recorded" not in dumped
