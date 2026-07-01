from makoralle.models.chunk import PageInfo, Section, TableData
from makoralle.models.ebd import DecisionStep


def test_page_info_creation() -> None:
    page = PageInfo(
        document="gpke_teil2",
        page_number=12,
        classification="table",
        has_text=True,
        has_table=True,
        has_diagram=False,
    )
    assert page.document == "gpke_teil2"
    assert page.classification == "table"


def test_section_creation() -> None:
    section = Section(
        document="gpke_teil2",
        heading="2.1. Use-Case: Lieferbeginn",
        heading_level=2,
        start_page=12,
        end_page=23,
        content_types=["text", "table", "diagram"],
    )
    assert section.start_page == 12
    assert "table" in section.content_types


def test_table_data_creation() -> None:
    table = TableData(
        document="gpke_teil2",
        section_heading="2.1.1. UC: Lieferbeginn",
        page_number=12,
        headers=["Use-Case-Name", "Lieferbeginn"],
        rows=[
            ["Prozessziel", "Zuordnung eines LF..."],
            ["Rollen", "LF, NB, MSB"],
        ],
    )
    assert len(table.rows) == 2
    assert table.headers[0] == "Use-Case-Name"


def test_decision_step_accepts_cluster_fields() -> None:
    step = DecisionStep(
        nr=1,
        check="x",
        if_yes_cluster="Zustimmung",
        if_no_cluster="Ablehnung",
    )
    assert step.if_yes_cluster == "Zustimmung"
    assert step.if_no_cluster == "Ablehnung"


def test_decision_step_cluster_defaults_to_none() -> None:
    step = DecisionStep(nr=1, check="x")
    assert step.if_yes_cluster is None
    assert step.if_no_cluster is None
