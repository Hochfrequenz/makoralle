import copy
import json
import pathlib
from typing import Any

import yaml

from makoralle.grouping import ad_artifact_key, sd_artifact_key
from makoralle.webapp_export import (
    build_detail,
    build_index_entry,
    diagram_source_text,
    export_makrake_inputs,
    run,
    sd_source_hash,
)

SAMPLE: dict[str, Any] = {
    "process": {
        "id": "abstimmung_der_netzzeitreihe",
        "name": "Abstimmung der Netzzeitreihe",
        "category": "MaBiS",
        "source": "1.2.3 UC: Abstimmung",
    },
    "use_case": {"roles": ["NB", "ÜNB"]},
    "sequence_diagram": {
        "participants": ["NB", "ÜNB"],
        "steps": [
            {"nr": 1, "sender": "NB", "receiver": "ÜNB", "deadline": "Unverzüglich", "pid_refs": [55002, 55001]},
            {"nr": 2, "sender": "ÜNB", "receiver": "NB", "pid_refs": [55001]},
        ],
    },
}

# A 2-SD process: a `diagrams` list with two distinct slugs/steps, plus the legacy
# `sequence_diagram` (the primary) that the back-compat top-level fields mirror.
TWO_SD: dict[str, Any] = {
    "process": {"id": "wechsel", "name": "Wechsel", "category": "GPKE", "source": "2.1 UC: Wechsel"},
    "use_case": {"roles": ["LF", "NB"]},
    "sequence_diagram": {
        "participants": ["LF", "NB"],
        "steps": [
            {"nr": 1, "sender": "LF", "receiver": "NB", "deadline": "Unverzüglich", "pid_refs": [11001]},
        ],
    },
    "diagrams": [
        {
            "slug": "lieferant",
            "name": "aus Sicht Lieferant",
            "participants": ["LF", "NB"],
            "steps": [
                {"nr": 1, "sender": "LF", "receiver": "NB", "deadline": "Unverzüglich", "pid_refs": [11001]},
            ],
        },
        {
            "slug": "netzbetreiber",
            "name": "aus Sicht Netzbetreiber",
            "participants": ["NB", "LF"],
            "steps": [
                {"nr": 1, "sender": "NB", "receiver": "LF", "pid_refs": [11002, 11003]},
            ],
        },
    ],
}


def test_build_index_entry_extracts_summary_fields() -> None:
    entry = build_index_entry(SAMPLE, has_bpmn=True, has_review=False, has_sequence=True)
    assert entry == {
        "id": "abstimmung_der_netzzeitreihe",
        "name": "Abstimmung der Netzzeitreihe",
        "category": "MaBiS",
        "roles": ["NB", "ÜNB"],
        "participants": ["NB", "ÜNB"],
        "pids": [55001, 55002],
        "pidNames": [],
        "stepCount": 2,
        "sdCount": 1,
        "hasDeadlines": True,
        "hasSequence": True,
        "hasBpmn": True,
        "hasReview": False,
        "approved": False,
        "source": "1.2.3 UC: Abstimmung",
    }


def test_build_detail_includes_usecase_steps_and_derived_tables() -> None:
    detail = build_detail(SAMPLE, review_notes=["Frist: manuelle Klärung"])
    assert detail["id"] == "abstimmung_der_netzzeitreihe"
    assert detail["useCase"]["roles"] == ["NB", "ÜNB"]
    assert detail["steps"][0]["deadline"] == "Unverzüglich"
    # derived deadline table: only steps that carry a deadline
    assert detail["deadlines"] == [{"nr": 1, "deadline": "Unverzüglich", "rule": None}]
    assert detail["reviewNotes"] == ["Frist: manuelle Klärung"]


def test_build_detail_pid_table_flattens_one_row_per_ref() -> None:
    proc = {
        "process": {"id": "x", "name": "X", "category": "GPKE", "source": ""},
        "use_case": {},
        "sequence_diagram": {
            "participants": ["A", "B"],
            "steps": [
                {
                    "nr": 1,
                    "sender": "A",
                    "receiver": "B",
                    "message": "Preisblatt",
                    "format": "PRICAT",
                    "pid_refs": [27003, 27004],
                },
                {"nr": 2, "sender": "B", "receiver": "A"},  # no pid_refs -> no rows
            ],
        },
    }
    detail = build_detail(proc, review_notes=[])
    assert detail["pids"] == [
        {"nr": 1, "pid": 27003, "name": None, "message": "Preisblatt", "format": "PRICAT"},
        {"nr": 1, "pid": 27004, "name": None, "message": "Preisblatt", "format": "PRICAT"},
    ]


def test_sd_source_hash_ignores_whitespace_churn_but_not_content() -> None:
    """The hash is taken over a diagram's canonical render input; the function itself only
    cares that cosmetic churn does not clear a badge while a content change does."""
    base = '{"id":"x","steps":[{"message":"Anmeldung"}]}'
    # leading/trailing whitespace + CRLF line endings normalize away
    assert sd_source_hash(base) == sd_source_hash(f"\n  {base}\r\n  ".replace("\n", "\r\n"))
    # a real content change yields a different hash
    assert sd_source_hash(base) != sd_source_hash(base.replace("Anmeldung", "Abmeldung"))
    # it is a hex sha256 digest
    h = sd_source_hash(base)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def _write(p: pathlib.Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_run_emits_index_detail_and_copies_svgs(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    # A copy, with one step's Frist left unstructured, so the worklist has something to
    # report. `type: "complex"` is prose nobody has reduced yet — what the old build
    # published as a `[REVIEW]` note and this one derives from the model.
    sample = copy.deepcopy(SAMPLE)
    sample["sequence_diagram"]["steps"][1]["deadline_rule"] = {"type": "complex", "raw": "Gemäß Rahmenvertrag."}
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(sample, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}.svg", "<svg>seq</svg>")
    _write(out / "bpmn" / f"{pid}.svg", "<svg>bpmn</svg>")

    run(output_dir=out, webapp_dir=web)

    index = json.loads((web / "src/data/processes.json").read_text("utf-8"))
    assert index[0]["id"] == pid and index[0]["hasBpmn"] and index[0]["hasReview"] and index[0]["hasSequence"]
    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    assert detail["reviewNotes"] == ["Gemäß Rahmenvertrag."]
    assert detail["reviewItems"] == [
        {"kind": "deadline_unstructured", "severity": "structure", "step": 2, "text": "Gemäß Rahmenvertrag."}
    ]
    assert (web / "public/diagrams/sequence" / f"{pid}.svg").read_text("utf-8") == "<svg>seq</svg>"
    assert (web / "public/diagrams/bpmn" / f"{pid}.svg").exists()


def test_run_flags_missing_artifacts_and_orders_index(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    # Process A: full artifacts (bpmn + sequence svg), category MaBiS.
    a_id = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{a_id}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "sequence_svg" / f"{a_id}.svg", "<svg>seq</svg>")
    _write(out / "bpmn" / f"{a_id}.svg", "<svg>bpmn</svg>")
    # Process B: only YAML, no bpmn svg / sequence svg. Category GPKE sorts first.
    b = {
        "process": {"id": "lieferbeginn", "name": "Lieferbeginn", "category": "GPKE", "source": ""},
        "use_case": {"roles": []},
        "sequence_diagram": {"participants": [], "steps": []},
    }
    _write(out / "yaml" / "lieferbeginn.yaml", yaml.safe_dump(b, allow_unicode=True))

    assert run(output_dir=out, webapp_dir=web) == 2

    index = json.loads((web / "src/data/processes.json").read_text("utf-8"))
    # sorted by (category, name.lower()): GPKE/Lieferbeginn before MaBiS/Abstimmung
    assert [e["id"] for e in index] == ["lieferbeginn", a_id]
    b_entry = index[0]
    assert b_entry["hasBpmn"] is False
    assert b_entry["hasSequence"] is False
    assert b_entry["hasReview"] is False
    # no svg copied for the artifact-less process
    assert not (web / "public/diagrams/sequence" / "lieferbeginn.svg").exists()
    assert not (web / "public/diagrams/bpmn" / "lieferbeginn.svg").exists()
    # but a detail json is still emitted
    assert (web / "src/data/processes/lieferbeginn.json").exists()


def test_run_marks_approved_only_when_the_hash_matches_the_current_diagram(tmp_path: pathlib.Path) -> None:
    """An approval vouches for a diagram's content, so it survives a rebuild that changes
    nothing and clears when the diagram moves.

    The subject is the canonical render input rather than a `.wsd` file, which is why the
    stamped hash comes from `diagram_source_text`: the approve command asks the exporter
    for the text instead of rebuilding it, so the two cannot drift apart.
    """
    out = tmp_path / "output"
    web = tmp_path / "webapp"

    ok = "abstimmung_der_netzzeitreihe"  # MaBiS, sorts after GPKE
    _write(out / "yaml" / f"{ok}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "sequence_svg" / f"{ok}.svg", "<svg>seq</svg>")

    stale = {
        "process": {"id": "lieferbeginn", "name": "Lieferbeginn", "category": "GPKE", "source": ""},
        "use_case": {"roles": []},
        "sequence_diagram": {"participants": ["NB", "LF"], "steps": [{"nr": 1, "sender": "NB", "receiver": "LF"}]},
    }
    _write(out / "yaml" / "lieferbeginn.yaml", yaml.safe_dump(stale, allow_unicode=True))
    _write(out / "sequence_svg" / "lieferbeginn.svg", "<svg>seq</svg>")

    approvals = {
        "approvals": {
            ok: {
                "sha256": sd_source_hash(diagram_source_text(out, ok) or ""),
                "approved_by": "Joscha Metze <joscha@metze.eu>",
                "approved_at": "2026-06-30",
                "note": "",
            },
            # stamped against a diagram that has since changed
            "lieferbeginn": {
                "sha256": sd_source_hash('{"id":"lieferbeginn","steps":[]}'),
                "approved_by": "Someone",
                "approved_at": "2026-01-01",
            },
        }
    }
    af = tmp_path / "sd_approvals.yaml"
    af.write_text(yaml.safe_dump(approvals, allow_unicode=True), "utf-8")

    run(output_dir=out, webapp_dir=web, approvals_file=af)

    index = {e["id"]: e for e in json.loads((web / "src/data/processes.json").read_text("utf-8"))}
    assert index[ok]["approved"] is True
    assert index["lieferbeginn"]["approved"] is False

    ok_detail = json.loads((web / f"src/data/processes/{ok}.json").read_text("utf-8"))
    assert ok_detail["approval"] == {"by": "Joscha Metze <joscha@metze.eu>", "at": "2026-06-30", "note": ""}
    stale_detail = json.loads((web / "src/data/processes/lieferbeginn.json").read_text("utf-8"))
    assert stale_detail["approval"] is None


def test_run_no_approvals_file_means_nothing_approved(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}.svg", "<svg>seq</svg>")

    run(output_dir=out, webapp_dir=web, approvals_file=tmp_path / "missing.yaml")

    index = json.loads((web / "src/data/processes.json").read_text("utf-8"))
    assert index[0]["approved"] is False
    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    assert detail["approval"] is None


# --- per-SD diagrams[] ------------------------------------------------------


def test_build_index_entry_sd_count_counts_diagrams() -> None:
    multi = build_index_entry(TWO_SD, has_bpmn=False, has_review=False, has_sequence=True)
    assert multi["sdCount"] == 2
    # single-SD fallback (no diagrams key, but a sequence_diagram is present) -> 1
    single = build_index_entry(SAMPLE, has_bpmn=False, has_review=False, has_sequence=True)
    assert single["sdCount"] == 1
    # no diagrams AND no sequence_diagram -> 0
    bare = {"process": {"id": "x", "name": "X", "category": "G", "source": ""}, "use_case": {}}
    assert build_index_entry(bare, has_bpmn=False, has_review=False, has_sequence=False)["sdCount"] == 0


def test_build_detail_emits_per_diagram_list_for_multi_sd() -> None:
    detail = build_detail(TWO_SD, review_notes=[])
    assert len(detail["diagrams"]) == 2
    # pylint: disable-next=unbalanced-tuple-unpacking  # dict[str, Any] value is a list at runtime
    d0, d1 = detail["diagrams"]
    assert d0["slug"] == "lieferant"
    assert d0["name"] == "aus Sicht Lieferant"
    assert d0["participants"] == ["LF", "NB"]
    assert d0["svg"] == "/diagrams/sequence/wechsel__lieferant.svg"
    # per-diagram deadline/pid tables derive from THAT diagram's steps
    assert d0["deadlines"] == [{"nr": 1, "deadline": "Unverzüglich", "rule": None}]
    assert d0["pids"] == [{"nr": 1, "pid": 11001, "name": None, "message": None, "format": None}]
    assert d1["slug"] == "netzbetreiber"
    assert d1["svg"] == "/diagrams/sequence/wechsel__netzbetreiber.svg"
    assert d1["deadlines"] == []
    assert d1["pids"] == [
        {"nr": 1, "pid": 11002, "name": None, "message": None, "format": None},
        {"nr": 1, "pid": 11003, "name": None, "message": None, "format": None},
    ]
    # the approval is attached by run(), where the filesystem is
    assert "approval" not in d0 and "approval" not in d1
    assert "approval" not in d0
    # back-compat: top-level fields mirror the primary (diagrams[0])
    assert detail["steps"] == TWO_SD["diagrams"][0]["steps"]
    assert detail["participants"] == ["LF", "NB"]
    assert detail["deadlines"] == [{"nr": 1, "deadline": "Unverzüglich", "rule": None}]


def test_build_detail_fallback_wraps_legacy_sequence_diagram() -> None:
    detail = build_detail(SAMPLE, review_notes=[])
    assert len(detail["diagrams"]) == 1
    d = detail["diagrams"][0]
    assert d["slug"] == ""
    assert d["name"] is None
    assert d["svg"] == "/diagrams/sequence/abstimmung_der_netzzeitreihe.svg"
    assert d["steps"] == SAMPLE["sequence_diagram"]["steps"]
    assert d["participants"] == ["NB", "ÜNB"]
    # back-compat top-level fields still present and unchanged
    assert detail["steps"] == SAMPLE["sequence_diagram"]["steps"]
    assert detail["participants"] == ["NB", "ÜNB"]
    assert detail["deadlines"] == [{"nr": 1, "deadline": "Unverzüglich", "rule": None}]


def test_run_emits_per_sd_diagrams_and_copies_all_svgs(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "wechsel"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    # per-SD svg for BOTH diagrams (keyed by {uc}__{slug})
    _write(out / "sequence_svg" / f"{pid}__lieferant.svg", "<svg>lf</svg>")
    _write(out / "sequence_svg" / f"{pid}__netzbetreiber.svg", "<svg>nb</svg>")

    assert run(output_dir=out, webapp_dir=web) == 1

    index = {e["id"]: e for e in json.loads((web / "src/data/processes.json").read_text("utf-8"))}
    assert index[pid]["sdCount"] == 2

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    assert len(detail["diagrams"]) == 2
    # pylint: disable-next=unbalanced-tuple-unpacking  # dict[str, Any] value is a list at runtime
    d0, d1 = detail["diagrams"]
    assert d0["svg"] == "/diagrams/sequence/wechsel__lieferant.svg"
    assert d1["svg"] == "/diagrams/sequence/wechsel__netzbetreiber.svg"
    # per-diagram deadlines/pids reflect each diagram's own steps
    assert d0["deadlines"] == [{"nr": 1, "deadline": "Unverzüglich", "rule": None}]
    assert d1["pids"] == [
        {"nr": 1, "pid": 11002, "name": None, "message": None, "format": None},
        {"nr": 1, "pid": 11003, "name": None, "message": None, "format": None},
    ]
    # both per-SD svgs copied into the webapp
    seq_dest = web / "public/diagrams/sequence"
    assert (seq_dest / "wechsel__lieferant.svg").read_text("utf-8") == "<svg>lf</svg>"
    assert (seq_dest / "wechsel__netzbetreiber.svg").read_text("utf-8") == "<svg>nb</svg>"


def test_run_single_sd_fallback_diagrams_and_back_compat(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}.svg", "<svg>seq</svg>")

    run(output_dir=out, webapp_dir=web)

    index = json.loads((web / "src/data/processes.json").read_text("utf-8"))
    assert index[0]["sdCount"] == 1
    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    assert len(detail["diagrams"]) == 1
    d = detail["diagrams"][0]
    assert d["slug"] == "" and d["name"] is None
    assert d["svg"] == f"/diagrams/sequence/{pid}.svg"
    # back-compat top-level fields still present
    assert detail["steps"] == SAMPLE["sequence_diagram"]["steps"]
    assert detail["participants"] == ["NB", "ÜNB"]
    # the {pid}.svg is copied (back-compat path + per-diagram path, same file)
    assert (web / "public/diagrams/sequence" / f"{pid}.svg").read_text("utf-8") == "<svg>seq</svg>"


def test_run_has_sequence_true_for_multi_sd_without_bare_svg(tmp_path: pathlib.Path) -> None:
    # Regression: a multi-SD process has only {pid}__{slug}.svg (no bare {pid}.svg);
    # hasSequence must still be True (else the webapp shows "kein Sequenzdiagramm").
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "wechsel"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}__lieferant.svg", "<svg>lf</svg>")
    _write(out / "sequence_svg" / f"{pid}__netzbetreiber.svg", "<svg>nb</svg>")

    run(output_dir=out, webapp_dir=web)

    index = {e["id"]: e for e in json.loads((web / "src/data/processes.json").read_text("utf-8"))}
    assert index[pid]["hasSequence"] is True
    assert index[pid]["sdCount"] == 2
    # no bare {pid}.svg exists, so none was fabricated/copied
    assert not (web / "public/diagrams/sequence" / f"{pid}.svg").exists()


def test_index_pids_and_participants_union_across_all_sds() -> None:
    entry = build_index_entry(TWO_SD, has_bpmn=False, has_review=False, has_sequence=True)
    # 11002/11003 live ONLY in the 2nd (non-primary) diagram, yet surface in the index
    assert entry["pids"] == [11001, 11002, 11003]
    # participants: ordered union across diagrams, de-duplicated
    assert entry["participants"] == ["LF", "NB"]


def test_run_review_items_aggregate_from_a_non_primary_variant(tmp_path: pathlib.Path) -> None:
    """A worklist entry earned by a NON-primary variant's step must still reach the process.

    The old build could only find one by grepping that variant's own `.wsd`; the item is now
    derived per diagram, and carries the step number a note could not.
    """
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "wechsel"
    two_sd = copy.deepcopy(TWO_SD)
    two_sd["diagrams"][1]["steps"][0]["deadline_rule"] = {"type": "complex", "raw": "Frist Variante."}
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(two_sd, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}__lieferant.svg", "<svg>lf</svg>")
    _write(out / "sequence_svg" / f"{pid}__netzbetreiber.svg", "<svg>nb</svg>")

    run(output_dir=out, webapp_dir=web)

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    assert detail["reviewNotes"] == ["Frist Variante."]
    assert detail["reviewItems"] == [
        {"kind": "deadline_unstructured", "severity": "structure", "step": 1, "text": "Frist Variante."}
    ]
    index = {e["id"]: e for e in json.loads((web / "src/data/processes.json").read_text("utf-8"))}
    assert index[pid]["hasReview"] is True


def test_index_has_deadlines_aggregates_from_non_primary_sd() -> None:
    # A deadline living ONLY in a non-primary SD must still flip the index flag.
    proc = {
        "process": {"id": "x", "name": "X", "category": "G", "source": ""},
        "use_case": {},
        "diagrams": [
            {
                "slug": "a",
                "name": "A",
                "participants": ["P"],
                "steps": [{"nr": 1, "sender": "P", "receiver": "Q"}],
            },  # primary: NO deadline
            {
                "slug": "b",
                "name": "B",
                "participants": ["P"],
                "steps": [{"nr": 1, "sender": "P", "receiver": "Q", "deadline": "Unverzüglich"}],
            },
        ],
    }
    entry = build_index_entry(proc, has_bpmn=False, has_review=False, has_sequence=True)
    assert entry["hasDeadlines"] is True


# --- per-SD approval (Task 3.5) ---------------------------------------------


def test_run_per_sd_partial_approval_is_not_fully_approved(tmp_path: pathlib.Path) -> None:
    # A 2-SD process where only ONE variant's hash matches an approval:
    # that diagram gets a non-null approval, the other stays null, and the index
    # "approved" flag is False (not fully approved).
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "wechsel"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}__lieferant.svg", "<svg>lf</svg>")
    _write(out / "sequence_svg" / f"{pid}__netzbetreiber.svg", "<svg>nb</svg>")
    # only the lieferant variant is approved (hash matches its current source)
    approvals = {
        "approvals": {
            f"{pid}__lieferant": {
                "sha256": sd_source_hash(diagram_source_text(out, f"{pid}__lieferant") or ""),
                "approved_by": "Joscha <j@x>",
                "approved_at": "2026-06-30",
            },
        }
    }
    af = tmp_path / "sd_approvals.yaml"
    af.write_text(yaml.safe_dump(approvals, allow_unicode=True), "utf-8")

    run(output_dir=out, webapp_dir=web, approvals_file=af)

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    # d0 = primary (lieferant), d1 = netzbetreiber
    # pylint: disable-next=unbalanced-tuple-unpacking  # dict[str, Any] value is a list at runtime
    d0, d1 = detail["diagrams"]
    expected = {"by": "Joscha <j@x>", "at": "2026-06-30", "note": ""}
    assert d0["approval"] == expected
    assert d1["approval"] is None
    # detail.approval mirrors the PRIMARY diagram's approval (back-compat)
    assert detail["approval"] == expected
    index = {e["id"]: e for e in json.loads((web / "src/data/processes.json").read_text("utf-8"))}
    assert index[pid]["approved"] is False  # one variant still unapproved


def test_run_single_sd_approval_back_compat(tmp_path: pathlib.Path) -> None:
    # Single-SD approval keyed by the bare {pid}: diagram[0].approval set,
    # detail.approval set, index "approved" True (unchanged from before Task 3.5).
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}.svg", "<svg>seq</svg>")
    approvals = {
        "approvals": {
            pid: {
                "sha256": sd_source_hash(diagram_source_text(out, pid) or ""),
                "approved_by": "Joscha <j@x>",
                "approved_at": "2026-06-30",
                "note": "ok",
            }
        }
    }
    af = tmp_path / "sd_approvals.yaml"
    af.write_text(yaml.safe_dump(approvals, allow_unicode=True), "utf-8")

    run(output_dir=out, webapp_dir=web, approvals_file=af)

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    expected = {"by": "Joscha <j@x>", "at": "2026-06-30", "note": "ok"}
    assert detail["diagrams"][0]["approval"] == expected
    assert detail["approval"] == expected
    index = json.loads((web / "src/data/processes.json").read_text("utf-8"))
    assert index[0]["approved"] is True


def test_run_per_sd_full_approval_marks_index_approved(tmp_path: pathlib.Path) -> None:
    # Both renderable variants approved (each diagram's hash matches its entry):
    # every diagram gets an approval and the index "approved" flag is True.
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "wechsel"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}__lieferant.svg", "<svg>lf</svg>")
    _write(out / "sequence_svg" / f"{pid}__netzbetreiber.svg", "<svg>nb</svg>")
    approvals = {
        "approvals": {
            f"{pid}__lieferant": {
                "sha256": sd_source_hash(diagram_source_text(out, f"{pid}__lieferant") or ""),
                "approved_by": "Joscha <j@x>",
                "approved_at": "2026-06-30",
            },
            f"{pid}__netzbetreiber": {
                "sha256": sd_source_hash(diagram_source_text(out, f"{pid}__netzbetreiber") or ""),
                "approved_by": "Joscha <j@x>",
                "approved_at": "2026-06-30",
            },
        }
    }
    af = tmp_path / "sd_approvals.yaml"
    af.write_text(yaml.safe_dump(approvals, allow_unicode=True), "utf-8")

    run(output_dir=out, webapp_dir=web, approvals_file=af)

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    expected = {"by": "Joscha <j@x>", "at": "2026-06-30", "note": ""}
    assert all(d["approval"] == expected for d in detail["diagrams"])
    assert detail["approval"] == expected  # mirrors the primary
    index = {e["id"]: e for e in json.loads((web / "src/data/processes.json").read_text("utf-8"))}
    assert index[pid]["approved"] is True  # fully approved


def test_run_counts_stale_on_hash_mismatch_with_steps(tmp_path: pathlib.Path, capsys: Any) -> None:
    # An approval entry whose diagram exists but no longer hashes to the stamped
    # value: the diagram's approval is null AND the entry is counted stale. (The
    # other stale fixture is stepless and never exercises this mismatch path.)
    # Edge: a stepless PRIMARY can diverge (no renderable diagram → not "approved")
    # — low likelihood, left uncovered by design.
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}.svg", "<svg>seq</svg>")
    approvals = {
        "approvals": {
            pid: {
                "sha256": sd_source_hash("title OLD\nNB->ÜNB: original\n"),
                "approved_by": "Someone",
                "approved_at": "2026-01-01",
            }
        }
    }
    af = tmp_path / "sd_approvals.yaml"
    af.write_text(yaml.safe_dump(approvals, allow_unicode=True), "utf-8")

    run(output_dir=out, webapp_dir=web, approvals_file=af)

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    assert detail["diagrams"][0]["approval"] is None
    assert detail["approval"] is None
    index = json.loads((web / "src/data/processes.json").read_text("utf-8"))
    assert index[0]["approved"] is False
    assert "1 stale" in capsys.readouterr().out  # reported, not silently dropped


def test_run_reports_orphaned_approval_entries(tmp_path: pathlib.Path, capsys: Any) -> None:
    # An approval entry whose artifact key matches NO current diagram (variant
    # removed / slug renamed) is reported as orphaned, not silently dropped.
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "sequence_svg" / f"{pid}.svg", "<svg>seq</svg>")
    approvals = {
        "approvals": {"ghost__variant": {"sha256": "deadbeef", "approved_by": "A", "approved_at": "2026-01-01"}}
    }
    af = tmp_path / "sd_approvals.yaml"
    af.write_text(yaml.safe_dump(approvals, allow_unicode=True), "utf-8")

    run(output_dir=out, webapp_dir=web, approvals_file=af)

    out_text = capsys.readouterr().out
    assert "orphaned" in out_text and "ghost__variant" in out_text


def test_ad_artifact_key_uses_a_single_underscore() -> None:
    """p11 names activity diagrams `{pid}_{slug}` where the SDs use `{pid}__{slug}`.
    Conflating the two strands every variant's diagram."""
    assert ad_artifact_key("wechsel", "lieferant", 1) == "wechsel"
    assert ad_artifact_key("wechsel", "lieferant", 3) == "wechsel_lieferant"
    assert ad_artifact_key("wechsel", "lieferant", 3) != sd_artifact_key("wechsel", "lieferant", 3)


def test_run_links_per_variant_activity_diagrams(tmp_path: pathlib.Path) -> None:
    """A multi-SD process's activity diagrams live at {pid}_{slug}; each variant gets
    its own, and a variant without one gets None rather than a 404 link."""
    out, web = tmp_path / "output", tmp_path / "webapp"
    pid = "wechsel"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    # only the first variant has an activity diagram rendered
    _write(out / "bpmn" / f"{pid}_lieferant.svg", "<svg>ad-lieferant</svg>")

    run(output_dir=out, webapp_dir=web)

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    by_slug = {d["slug"]: d["activitySvg"] for d in detail["diagrams"]}
    assert by_slug["lieferant"] == f"/diagrams/bpmn/{pid}_lieferant.svg"
    assert by_slug["netzbetreiber"] is None
    assert json.loads((web / "src/data/processes.json").read_text("utf-8"))[0]["hasBpmn"] is True
    assert (web / f"public/diagrams/bpmn/{pid}_lieferant.svg").exists()


def test_run_falls_back_to_the_bare_pid_activity_diagram(tmp_path: pathlib.Path) -> None:
    """A multi-SD process whose activity diagram is named after the process only
    (no variant suffix) still resolves — every variant points at it."""
    out, web = tmp_path / "output", tmp_path / "webapp"
    pid = "wechsel"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    _write(out / "bpmn" / f"{pid}.svg", "<svg>ad</svg>")

    run(output_dir=out, webapp_dir=web)

    detail = json.loads((web / f"src/data/processes/{pid}.json").read_text("utf-8"))
    assert {d["activitySvg"] for d in detail["diagrams"]} == {f"/diagrams/bpmn/{pid}.svg"}


def test_run_ships_and_indexes_activity_diagrams_that_link_to_no_process(tmp_path: pathlib.Path) -> None:
    """Diagrams whose p11 name matches no process/variant (stale pre-de-truncation
    names) must still be copied and indexed — they used to be dropped silently."""
    out, web = tmp_path / "output", tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "bpmn" / f"{pid}.svg", "<svg>linked</svg>")
    _write(out / "bpmn" / "zuordnung_eines_bilanzkreises_zur_aufnah-.svg", "<svg>orphan</svg>")

    run(output_dir=out, webapp_dir=web)

    ads = json.loads((web / "src/data/activity_diagrams.json").read_text("utf-8"))
    by_name = {a["name"]: a for a in ads}
    assert by_name[pid]["linked"] is True
    orphan = by_name["zuordnung_eines_bilanzkreises_zur_aufnah-"]
    assert orphan["linked"] is False
    assert orphan["svg"] == "/diagrams/bpmn/zuordnung_eines_bilanzkreises_zur_aufnah-.svg"
    # shipped despite linking to nothing, so the browse view can reach it
    assert (web / "public/diagrams/bpmn/zuordnung_eines_bilanzkreises_zur_aufnah-.svg").exists()


def test_run_rewrites_activity_diagram_dir_without_orphans(tmp_path: pathlib.Path) -> None:
    """The dest dir is fully generated: a diagram removed upstream must not survive."""
    out, web = tmp_path / "output", tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "bpmn" / f"{pid}.svg", "<svg>ad</svg>")
    _write(web / "public/diagrams/bpmn/gone.svg", "<svg>stale</svg>")

    run(output_dir=out, webapp_dir=web)

    assert not (web / "public/diagrams/bpmn/gone.svg").exists()
    assert (web / f"public/diagrams/bpmn/{pid}.svg").exists()


NO_SD: dict[str, Any] = {
    "process": {"id": "nur_ad", "name": "Nur AD", "category": "GPKE", "source": ""},
    "use_case": {"roles": []},
}


def test_run_links_the_activity_diagram_of_a_process_without_any_sequence_diagram(
    tmp_path: pathlib.Path,
) -> None:
    """p11 renders activity diagrams independently of p06's sequence diagrams, so a
    process can have an AD and no SD. Resolving per variant must not drop it."""
    out, web = tmp_path / "output", tmp_path / "webapp"
    _write(out / "yaml" / "nur_ad.yaml", yaml.safe_dump(NO_SD, allow_unicode=True))
    _write(out / "bpmn" / "nur_ad.svg", "<svg>ad</svg>")

    run(output_dir=out, webapp_dir=web)

    entry = json.loads((web / "src/data/processes.json").read_text("utf-8"))[0]
    assert entry["sdCount"] == 0
    assert entry["hasBpmn"] is True
    ads = json.loads((web / "src/data/activity_diagrams.json").read_text("utf-8"))
    assert [a["linked"] for a in ads if a["name"] == "nur_ad"] == [True]


def test_run_reports_an_activity_diagram_two_processes_could_claim(tmp_path: pathlib.Path, capsys: Any) -> None:
    """`{pid}_{slug}` is ambiguous with a bare id that happens to contain the slug:
    `wechsel` + variant `lieferant` and a process named `wechsel_lieferant` both want
    wechsel_lieferant.svg. Report it instead of silently handing it to whoever sorts first."""
    out, web = tmp_path / "output", tmp_path / "webapp"
    _write(out / "yaml" / "wechsel.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    collider = {
        "process": {"id": "wechsel_lieferant", "name": "Wechsel Lieferant", "category": "GPKE", "source": ""},
        "use_case": {"roles": []},
        "sequence_diagram": {"participants": [], "steps": []},
    }
    _write(out / "yaml" / "wechsel_lieferant.yaml", yaml.safe_dump(collider, allow_unicode=True))
    _write(out / "bpmn" / "wechsel_lieferant.svg", "<svg>contested</svg>")

    run(output_dir=out, webapp_dir=web)

    printed = capsys.readouterr().out
    assert "ambiguous activity-diagram names: 1" in printed
    assert "wechsel_lieferant (claimed by" in printed


def test_run_prints_the_unlinked_activity_diagrams_as_a_worklist(tmp_path: pathlib.Path, capsys: Any) -> None:
    out, web = tmp_path / "output", tmp_path / "webapp"
    pid = "abstimmung_der_netzzeitreihe"
    _write(out / "yaml" / f"{pid}.yaml", yaml.safe_dump(SAMPLE, allow_unicode=True))
    _write(out / "bpmn" / f"{pid}.svg", "<svg>linked</svg>")
    _write(out / "bpmn" / "zuordnung_eines_bilanzkreises_zur_aufnah-.svg", "<svg>orphan</svg>")

    run(output_dir=out, webapp_dir=web)

    printed = capsys.readouterr().out
    assert "173 copied" not in printed  # sanity: this fixture has 2, not the real dataset
    assert "2 copied, 1 linked to a process, 1 unlinked" in printed
    assert "  - zuordnung_eines_bilanzkreises_zur_aufnah-" in printed


def test_a_pid_carries_the_anwendungsfall_the_official_list_gives_it() -> None:
    """makorele#52: the number alone does not say what a PID is for.

    "55001" tells a reader nothing about whether it is theirs; "55001 Anmeldung verb. MaLo" does. The
    name was already in the data — `anwendungsfall` on each `pid_mappings` row — and simply was not
    carried into the payload, so the webapp had nothing to show.
    """
    detail = build_detail(
        {
            "process": {"id": "lieferbeginn", "name": "Lieferbeginn"},
            "sequence_diagram": {
                "participants": ["LFN", "NB"],
                "steps": [
                    {"nr": 1, "sender": "LFN", "receiver": "NB", "message": "Anmeldung", "pid_refs": [55001, 55077]}
                ],
            },
            "pid_mappings": [
                {"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung verb. MaLo"},
                {"prüfidentifikator": "55077", "anwendungsfall": "Anmeldung erz. MaLo"},
            ],
        },
        review_notes=[],
    )
    assert [(row["pid"], row["name"]) for row in detail["pids"]] == [
        (55001, "Anmeldung verb. MaLo"),
        (55077, "Anmeldung erz. MaLo"),
    ]


def test_a_pid_with_no_row_in_the_list_reports_no_name_rather_than_an_empty_one() -> None:
    """`None` and `""` mean different things to whoever renders the label: "the list has no row for
    this number" is a data gap worth seeing, an empty string is a name."""
    detail = build_detail(
        {
            "process": {"id": "p"},
            "sequence_diagram": {"steps": [{"nr": 1, "message": "m", "pid_refs": [99999]}]},
            "pid_mappings": [{"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung"}],
        },
        review_notes=[],
    )
    assert detail["pids"] == [{"nr": 1, "pid": 99999, "name": None, "message": "m", "format": None}]


def test_a_pid_whose_rows_disagree_keeps_the_first_spelling() -> None:
    """The real instance: of the 429 named PIDs in dataset v0.0.15, exactly two disagree across their
    rows, and both disagreements are a typo rather than a meaning — 55672 reads "erz. Malo" on one
    row and "erz.. MaLo" on another; 19101 differs by a double space.

    So one spelling has to win, and it has to be the same one every build: the label has a single
    line, and joining two spellings of one name would put text in it that no document contains.
    """
    detail = build_detail(
        {
            "process": {"id": "p"},
            "sequence_diagram": {"steps": [{"nr": 1, "message": "m", "pid_refs": [55672]}]},
            "pid_mappings": [
                {
                    "prüfidentifikator": "55672",
                    "anwendungsfall": "Abr.-Daten BK-Abr. erz. Malo",
                    "zuordnung_objekt": "ZO-T1",
                },
                {
                    "prüfidentifikator": "55672",
                    "anwendungsfall": "Abr.-Daten BK-Abr. erz.. MaLo",
                    "zuordnung_objekt": "ZO-T2",
                },
            ],
        },
        review_notes=[],
    )
    assert [row["name"] for row in detail["pids"]] == ["Abr.-Daten BK-Abr. erz. Malo"]


def test_a_non_numeric_value_does_not_raise_on_the_way_in() -> None:
    """Defensive, and labelled as such: every `prüfidentifikator` in v0.0.15 is an integer.

    The API-path markers ("/steuerbefehl/konfig") live in the *Anwendungsfall* column, on rows whose
    number is 0 — see the test for that below. This one only says that a text column being text
    cannot take a build down.
    """
    detail = build_detail(
        {
            "process": {"id": "p"},
            "sequence_diagram": {"steps": [{"nr": 1, "message": "m", "pid_refs": [55001]}]},
            "pid_mappings": [
                {"prüfidentifikator": "/steuerbefehl/konfig", "anwendungsfall": "Etwas"},
                {"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung"},
            ],
        },
        review_notes=[],
    )
    assert [row["name"] for row in detail["pids"]] == ["Anmeldung"]


def test_every_diagram_of_a_multi_sd_process_gets_the_names_too() -> None:
    """The per-diagram tables and the primary mirror are built by the same function, and a name that
    appears on only one of them is worse than none."""
    detail = build_detail(
        {
            "process": {"id": "p"},
            "diagrams": [
                {
                    "slug": "a",
                    "name": "A",
                    "participants": [],
                    "steps": [{"nr": 1, "message": "m", "pid_refs": [55001]}],
                },
                {
                    "slug": "b",
                    "name": "B",
                    "participants": [],
                    "steps": [{"nr": 1, "message": "m", "pid_refs": [55001]}],
                },
            ],
            "pid_mappings": [{"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung"}],
        },
        review_notes=[],
    )
    assert [row["name"] for diagram in detail["diagrams"] for row in diagram["pids"]] == ["Anmeldung", "Anmeldung"]
    assert [row["name"] for row in detail["pids"]] == ["Anmeldung"]


def test_a_pruefidentifikator_of_zero_is_not_a_pid() -> None:
    """The guard that actually fires on the corpus, and it was untested.

    Nine rows in v0.0.15 carry `prüfidentifikator: 0` — API-path processes whose official-list entry
    lives in the *Anwendungsfall* column ("/steuerbefehl/initialZustand/", "/maloID/request/") with
    no number of its own. Admitting 0 would put an API path in the map under a number no step
    references, and `if raw is None or not name` — the obvious rewrite — does exactly that.
    """
    detail = build_detail(
        {
            "process": {"id": "p"},
            "sequence_diagram": {"steps": [{"nr": 1, "message": "m", "pid_refs": [0, 55001]}]},
            "pid_mappings": [
                {"prüfidentifikator": 0, "anwendungsfall": "/steuerbefehl/initialZustand/"},
                {"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung"},
            ],
        },
        review_notes=[],
    )
    assert [(row["pid"], row["name"]) for row in detail["pids"]] == [(0, None), (55001, "Anmeldung")]


def test_a_blank_name_does_not_claim_the_number() -> None:
    """First-row-wins is only safe if a nameless row is not a row: otherwise a blank Anwendungsfall
    takes the number and blocks the later row that has the name, turning a real name into the empty
    string `None` exists to be distinguished from."""
    detail = build_detail(
        {
            "process": {"id": "p"},
            "sequence_diagram": {"steps": [{"nr": 1, "message": "m", "pid_refs": [55001]}]},
            "pid_mappings": [
                {"prüfidentifikator": "55001", "anwendungsfall": ""},
                {"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung"},
            ],
        },
        review_notes=[],
    )
    assert [row["name"] for row in detail["pids"]] == ["Anmeldung"]


def test_a_whitespace_only_name_does_not_claim_the_number_either() -> None:
    """Same defect wearing a space: `" "` is truthy, so without the strip it claims the number and
    the label renders blank."""
    detail = build_detail(
        {
            "process": {"id": "p"},
            "sequence_diagram": {"steps": [{"nr": 1, "message": "m", "pid_refs": [55001]}]},
            "pid_mappings": [
                {"prüfidentifikator": "55001", "anwendungsfall": "   "},
                {"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung"},
            ],
        },
        review_notes=[],
    )
    assert [row["name"] for row in detail["pids"]] == ["Anmeldung"]


def test_the_index_carries_the_names_of_the_pids_a_process_uses() -> None:
    """mako_prozesse#167: the list view's search reads the index, not the detail files, so a
    reader who does not already know the number cannot find a process by its Anwendungsfall —
    which is the whole reason the name was added (makorele#52). The names are already in the
    process payload; only the compact entry never carried them."""
    entry = build_index_entry(
        {
            **SAMPLE,
            "pid_mappings": [
                {"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung verb. MaLo"},
                {"prüfidentifikator": "55002", "anwendungsfall": "Abmeldung verb. MaLo"},
            ],
        },
        has_bpmn=False,
        has_review=False,
        has_sequence=True,
    )
    assert entry["pidNames"] == ["Abmeldung verb. MaLo", "Anmeldung verb. MaLo"]


def test_the_index_names_only_the_pids_the_process_actually_references() -> None:
    """`pid_mappings` is the process's slice of the official PID list and can name a
    Prüfidentifikator no step refers to. Carrying those would make the process findable under a
    name its diagram never shows — a false hit, and one the reader cannot then locate on the page."""
    entry = build_index_entry(
        {
            **SAMPLE,
            "pid_mappings": [
                {"prüfidentifikator": "55001", "anwendungsfall": "Anmeldung verb. MaLo"},
                {"prüfidentifikator": "99999", "anwendungsfall": "Nirgends referenziert"},
            ],
        },
        has_bpmn=False,
        has_review=False,
        has_sequence=True,
    )
    assert entry["pidNames"] == ["Anmeldung verb. MaLo"]


def test_the_index_carries_names_from_every_diagram_variant() -> None:
    """`pids` already aggregates across all SDs so a PID living only in a non-primary variant
    stays searchable; the names have to follow the same rule or search finds the number but not
    the word for it."""
    entry = build_index_entry(
        {
            **TWO_SD,
            "pid_mappings": [
                {"prüfidentifikator": "11001", "anwendungsfall": "Primär"},
                {"prüfidentifikator": "11003", "anwendungsfall": "Nur in der zweiten Sicht"},
            ],
        },
        has_bpmn=False,
        has_review=False,
        has_sequence=True,
    )
    assert entry["pidNames"] == ["Nur in der zweiten Sicht", "Primär"]


def test_a_process_without_pid_mappings_gets_an_empty_name_list() -> None:
    """An older extraction carries no mappings at all; the field must still exist so the webapp
    never has to distinguish "no names" from "field missing"."""
    entry = build_index_entry(SAMPLE, has_bpmn=False, has_review=False, has_sequence=True)
    assert entry["pidNames"] == []


def test_a_pid_whose_rows_disagree_is_searchable_under_every_spelling() -> None:
    """The label takes the first row, because it has one line to live on. A search text is under no
    such pressure, and dropping a spelling means whoever types it gets no hit at all. The real
    instance: 19101 in `geschäftsdatenanfrage` reads "Ablehnung der Anfrage  Stammdaten" with a
    double space on the row that wins, and the ordinary single space on its other two rows — and the
    webapp neither collapses whitespace nor matches loosely."""
    process = {
        **SAMPLE,
        "pid_mappings": [
            {"prüfidentifikator": "55001", "anwendungsfall": "Ablehnung der Anfrage  Stammdaten"},
            {"prüfidentifikator": "55001", "anwendungsfall": "Ablehnung der Anfrage Stammdaten"},
        ],
    }
    entry = build_index_entry(process, has_bpmn=False, has_review=False, has_sequence=True)
    assert entry["pidNames"] == ["Ablehnung der Anfrage  Stammdaten", "Ablehnung der Anfrage Stammdaten"]
    # …while the detail row, which is a label, still shows exactly one of them.
    detail = build_detail(process, review_notes=[])
    assert {row["name"] for row in detail["pids"] if row["pid"] == 55001} == {"Ablehnung der Anfrage  Stammdaten"}


def test_two_pids_sharing_an_anwendungsfall_are_named_once() -> None:
    """The common case, not an edge: 405 named PIDs in v0.0.17 carry only 314 distinct names, and 23
    processes reference several PIDs that share one — nine of the PIDs in
    `bestellung_zur_stammdatenänderung` read "Rückmeldung/Anfrage Daten der MaLo". Repeating them
    buys the search nothing and grows a file that is committed to the dataset repo."""
    entry = build_index_entry(
        {
            **SAMPLE,
            "pid_mappings": [
                {"prüfidentifikator": "55001", "anwendungsfall": "Abr.-Daten BK-Abr. verb. MaLo"},
                {"prüfidentifikator": "55002", "anwendungsfall": "Abr.-Daten BK-Abr. verb. MaLo"},
            ],
        },
        has_bpmn=False,
        has_review=False,
        has_sequence=True,
    )
    assert entry["pidNames"] == ["Abr.-Daten BK-Abr. verb. MaLo"]


def test_the_names_are_sorted_not_left_in_row_order() -> None:
    """Sortedness is load-bearing for a reason no reader sees: `processes.json` is committed to the
    dataset repo, so an order that follows set iteration would churn the file on every regeneration
    and bury the real diff. Four names, listed in an order that is not the alphabetical one."""
    entry = build_index_entry(
        {
            **TWO_SD,
            "pid_mappings": [
                {"prüfidentifikator": "11001", "anwendungsfall": "Wechselanfrage"},
                {"prüfidentifikator": "11002", "anwendungsfall": "Bestätigung"},
                {"prüfidentifikator": "11003", "anwendungsfall": "Ablehnung"},
                {"prüfidentifikator": "11003", "anwendungsfall": "Zustimmung"},
            ],
        },
        has_bpmn=False,
        has_review=False,
        has_sequence=True,
    )
    assert entry["pidNames"] == ["Ablehnung", "Bestätigung", "Wechselanfrage", "Zustimmung"]


def test_export_makrake_inputs_writes_one_render_input_per_diagram(tmp_path: pathlib.Path) -> None:
    """What replaced `output/sequence/*.wsd` — and unlike the `.wsd`, not a committed
    artifact: it is derivable from `output/yaml` plus `sd_ref_links.yaml`, so the pipeline
    writes it to a scratch dir, renders it and throws it away.

    The files are named by artifact key, because that is the stem makrake writes its SVG to
    and the `{process_id}` its links resolve.
    """
    out = tmp_path / "output"
    dest = tmp_path / "build" / "makrake"
    _write(out / "yaml" / "wechsel.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))

    assert export_makrake_inputs(output_dir=out, dest=dest) == 2
    assert sorted(p.name for p in dest.glob("*.json")) == ["wechsel__lieferant.json", "wechsel__netzbetreiber.json"]

    payload = json.loads((dest / "wechsel__lieferant.json").read_text("utf-8"))
    assert payload["id"] == "wechsel__lieferant"
    # The title joins the process and the variant, so a switcher's diagrams are tellable apart.
    assert payload["name"] == "Wechsel — aus Sicht Lieferant"
    assert [s["number"] for s in payload["steps"]] == [1]
    assert payload["steps"][0]["pids"] == [11001]


def test_export_makrake_inputs_resolves_refs_across_processes(tmp_path: pathlib.Path) -> None:
    """A `ref` names another process's SD, which may sort later — so resolution has to see
    every process at once. This is the fact the `.wsd` could not carry at all."""
    out = tmp_path / "output"
    dest = tmp_path / "build"
    referrer = {
        "process": {"id": "aaa_referrer", "name": "Referrer", "category": "GPKE", "source": ""},
        "use_case": {"roles": []},
        "sequence_diagram": {
            "participants": ["LF", "NB"],
            "steps": [{"nr": 1, "sender": "LF", "receiver": "NB", "subprocess_ref": "Zielprozess"}],
        },
    }
    target = {
        "process": {"id": "zzz_target", "name": "Zielprozess", "category": "GPKE", "source": ""},
        "use_case": {"roles": []},
        "sequence_diagram": {"participants": ["NB"], "steps": [{"nr": 1, "sender": "NB", "receiver": "NB"}]},
    }
    _write(out / "yaml" / "aaa_referrer.yaml", yaml.safe_dump(referrer, allow_unicode=True))
    _write(out / "yaml" / "zzz_target.yaml", yaml.safe_dump(target, allow_unicode=True))

    export_makrake_inputs(output_dir=out, dest=dest)

    payload = json.loads((dest / "aaa_referrer.json").read_text("utf-8"))
    step = payload["steps"][0]
    assert step["kind"] == "process_ref"
    assert step["subprocess_ref_id"] == "zzz_target"


def test_diagram_source_text_is_none_for_an_unknown_key(tmp_path: pathlib.Path) -> None:
    """So a stale approval entry reads as "no source" rather than raising mid-build."""
    out = tmp_path / "output"
    _write(out / "yaml" / "wechsel.yaml", yaml.safe_dump(TWO_SD, allow_unicode=True))
    assert diagram_source_text(out, "wechsel__geloescht") is None
    assert diagram_source_text(out, "wechsel__lieferant") is not None
