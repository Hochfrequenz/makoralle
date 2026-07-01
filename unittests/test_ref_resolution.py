"""Tests for subprocess-ref resolution (Task 4.1).

Covers the pure resolver (`makoralle/ref_links.py`) — normalize_ref,
build_ref_map, resolve_ref, load_ref_overrides — and its wiring into
build_webapp_data (each ref step gains a `ref_target`; unresolved refs are
printed as a worklist).
"""

import json
import pathlib
from typing import Any

import yaml

from makoralle.ref_links import (
    build_ref_map,
    load_ref_overrides,
    normalize_ref,
    resolve_ref,
)
from makoralle.webapp_export import run

# A process "Stammdatenänderung" with three role-qualified SD variants, shaped
# the way the YAML emitter writes process diagrams (slug + name qualifier +
# source_heading). diagrams[0] is the default/first variant.
STAMM = {
    "id": "stammdatenänderung",
    "name": "Stammdatenänderung",
    "diagrams": [
        {
            "slug": "vom_nb_verantwortlich_ausgehend",
            "name": "vom NB (verantwortlich) ausgehend",
            "source_heading": "1.4.2 SD: Stammdatenänderung vom NB (verantwortlich) ausgehend",
        },
        {
            "slug": "vom_lf_verantwortlich_ausgehend",
            "name": "vom LF (verantwortlich) ausgehend",
            "source_heading": "1.4.3 SD: Stammdatenänderung vom LF (verantwortlich) ausgehend",
        },
    ],
}

# A single-SD process (no qualifier; legacy-shaped diagram with an empty slug).
NNA = {
    "id": "netznutzungsabrechnung",
    "name": "Netznutzungsabrechnung",
    "diagrams": [{"slug": "", "name": None}],
}


def _refmap() -> dict[str, dict[str, Any]]:
    return build_ref_map([STAMM, NNA])


# --- normalize_ref -----------------------------------------------------------


def test_normalize_ref_strips_ref_prefixes_and_parentheses() -> None:
    # "ref ", "ref:", "ref ref " prefixes all stripped; parentheses → spaces.
    assert (
        normalize_ref("ref Stammdatenänderung vom NB (verantwortlich) ausgehend")
        == "stammdatenänderung vom nb verantwortlich ausgehend"
    )
    assert normalize_ref("ref: Reklamation vom LF") == "reklamation vom lf"
    assert normalize_ref("ref ref Gerätewechsel") == "gerätewechsel"
    # a non-ref word that merely starts with "ref" is NOT stripped
    assert normalize_ref("Referenzwert") == "referenzwert"
    assert normalize_ref("") == ""


# --- build_ref_map -----------------------------------------------------------


def test_build_ref_map_role_qualified_maps_to_exact_variant() -> None:
    rm = _refmap()
    assert rm[normalize_ref("Stammdatenänderung vom LF (verantwortlich) ausgehend")] == {
        "uc": "stammdatenänderung",
        "sd": "vom_lf_verantwortlich_ausgehend",
    }


def test_build_ref_map_uc_level_ref_maps_to_first_diagram() -> None:
    rm = _refmap()
    # a bare UC name resolves to the UC's FIRST (default) variant
    assert rm[normalize_ref("Stammdatenänderung")] == {
        "uc": "stammdatenänderung",
        "sd": "vom_nb_verantwortlich_ausgehend",
    }
    # single-SD UC: uc name → its only (empty-slug) diagram
    assert rm[normalize_ref("Netznutzungsabrechnung")] == {"uc": "netznutzungsabrechnung", "sd": ""}


def test_build_ref_map_uc_default_not_hijacked_by_unqualified_non_first_variant() -> None:
    # The SECOND variant's source_heading lacks a role qualifier, so its full name
    # normalizes to the bare UC name. `ref <UC>` must STILL resolve to the FIRST
    # (default) variant, not the unqualified second one.
    proc = {
        "id": "uc",
        "name": "Foo",
        "diagrams": [
            {"slug": "vom_nb", "name": "vom NB", "source_heading": "1.1 SD: Foo vom NB"},
            {"slug": "default", "name": None, "source_heading": "1.2 SD: Foo"},  # full name == UC name
        ],
    }
    rm = build_ref_map([proc])
    assert resolve_ref("ref Foo", rm, {}) == {"uc": "uc", "sd": "vom_nb"}
    # the qualified variant still resolves to its own slug
    assert resolve_ref("ref Foo vom NB", rm, {}) == {"uc": "uc", "sd": "vom_nb"}


def test_build_ref_map_collision_keeps_first() -> None:
    # Two processes whose names normalize identically: first registration wins.
    a = {"id": "first", "name": "Gerätewechsel", "diagrams": [{"slug": "", "name": None}]}
    b = {"id": "second", "name": "Gerätewechsel", "diagrams": [{"slug": "", "name": None}]}
    rm = build_ref_map([a, b])
    assert rm[normalize_ref("Gerätewechsel")] == {"uc": "first", "sd": ""}


def test_build_ref_map_uses_reconstructed_name_without_source_heading() -> None:
    # A diagram lacking source_heading still registers via uc_name + qualifier.
    proc = {"id": "uc", "name": "Foo", "diagrams": [{"slug": "vom_nb", "name": "vom NB"}]}
    rm = build_ref_map([proc])
    assert rm[normalize_ref("Foo vom NB")] == {"uc": "uc", "sd": "vom_nb"}


# --- resolve_ref -------------------------------------------------------------


def test_resolves_role_qualified_ref_exactly() -> None:
    refmap = _refmap()
    tgt = resolve_ref("ref Stammdatenänderung vom NB (verantwortlich) ausgehend", refmap, {})
    assert tgt == {"uc": "stammdatenänderung", "sd": "vom_nb_verantwortlich_ausgehend"}


def test_override_wins_and_unresolved_is_none() -> None:
    refmap = _refmap()
    overrides = {normalize_ref("ref Reklamation vom LF"): {"uc": "reklamation_einer_definition_des_lf", "sd": ""}}
    resolved = resolve_ref("ref Reklamation vom LF", refmap, overrides)
    assert resolved is not None
    assert resolved["uc"] == "reklamation_einer_definition_des_lf"
    assert resolve_ref("ref totally unknown thing", refmap, {}) is None


def test_override_beats_an_exact_ref_map_hit() -> None:
    refmap = _refmap()
    # the override redirects a name that WOULD otherwise resolve via the map
    overrides = {normalize_ref("Stammdatenänderung"): {"uc": "elsewhere", "sd": "x"}}
    assert resolve_ref("ref Stammdatenänderung", refmap, overrides) == {"uc": "elsewhere", "sd": "x"}


def test_resolve_ref_handles_empty_and_stray_double_ref() -> None:
    refmap = _refmap()
    assert resolve_ref("", refmap, {}) is None
    # a stray leading "ref" left on subprocess_ref still resolves
    assert resolve_ref("ref Netznutzungsabrechnung", refmap, {}) == {"uc": "netznutzungsabrechnung", "sd": ""}


# --- load_ref_overrides ------------------------------------------------------


def test_load_ref_overrides_normalizes_keys(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "sd_ref_links.yaml"
    f.write_text('overrides:\n  "ref Reklamation vom LF": {uc: rekla, sd: ""}\n', encoding="utf-8")
    ov = load_ref_overrides(f)
    # keyed by the normalized form so resolve_ref matches it
    assert ov[normalize_ref("Reklamation vom LF")] == {"uc": "rekla", "sd": ""}


def test_load_ref_overrides_validates_values(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "sd_ref_links.yaml"
    f.write_text(
        "overrides:\n"
        '  "ref Has uc no sd": {uc: foo}\n'  # sd missing → default ""
        '  "ref Missing uc": {sd: bar}\n',  # no uc → skipped
        encoding="utf-8",
    )
    ov = load_ref_overrides(f)
    # sd defaults to "" (the documented default variant), never a broken link
    assert ov[normalize_ref("Has uc no sd")] == {"uc": "foo", "sd": ""}
    # an entry without a uc target is dropped, not returned
    assert normalize_ref("Missing uc") not in ov
    assert len(ov) == 1


def test_load_ref_overrides_missing_or_blank_is_empty(tmp_path: pathlib.Path) -> None:
    # pylint: disable=use-implicit-booleaness-not-comparison  # assert the exact empty-dict shape
    assert load_ref_overrides(tmp_path / "nope.yaml") == {}
    blank = tmp_path / "blank.yaml"
    blank.write_text("overrides: {}\n", encoding="utf-8")
    assert load_ref_overrides(blank) == {}


# --- build_webapp_data integration ------------------------------------------


def _write(p: pathlib.Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_run_attaches_ref_target_and_prints_unresolved_worklist(tmp_path: pathlib.Path, capsys: Any) -> None:
    out = tmp_path / "output"
    web = tmp_path / "webapp"

    # Target process: a multi-SD UC whose variant a ref will point at.
    target = {
        "process": {
            "id": "stammdatenänderung",
            "name": "Stammdatenänderung",
            "category": "GPKE",
            "source": "1.4 UC: Stammdatenänderung",
        },
        "use_case": {"roles": ["NB"]},
        "diagrams": [
            {
                "slug": "vom_nb_verantwortlich_ausgehend",
                "name": "vom NB (verantwortlich) ausgehend",
                "source_heading": "1.4.2 SD: Stammdatenänderung vom NB (verantwortlich) ausgehend",
                "participants": ["NB"],
                "steps": [{"nr": 1, "sender": "NB", "receiver": "NB", "message": "do"}],
            },
        ],
    }
    # Caller process: one ref that RESOLVES, one that does NOT.
    caller = {
        "process": {"id": "caller", "name": "Caller", "category": "GPKE", "source": ""},
        "use_case": {"roles": ["NB"]},
        "sequence_diagram": {
            "participants": ["NB"],
            "steps": [
                {
                    "nr": 1,
                    "sender": "NB",
                    "receiver": "NB",
                    "message": "ref Stammdatenänderung vom NB (verantwortlich) ausgehend",
                    "subprocess_ref": "Stammdatenänderung vom NB (verantwortlich) ausgehend",
                },
                {
                    "nr": 2,
                    "sender": "NB",
                    "receiver": "NB",
                    "message": "ref Mysterious Garbled Thing",
                    "subprocess_ref": "Mysterious Garbled Thing",
                },
                {"nr": 3, "sender": "NB", "receiver": "NB", "message": "plain step"},
            ],
        },
    }
    _write(out / "yaml" / "stammdatenänderung.yaml", yaml.safe_dump(target, allow_unicode=True))
    _write(out / "yaml" / "caller.yaml", yaml.safe_dump(caller, allow_unicode=True))

    run(output_dir=out, webapp_dir=web)

    detail = json.loads((web / "src/data/processes/caller.json").read_text("utf-8"))
    steps = detail["diagrams"][0]["steps"]
    # resolved ref → precise (uc, sd) target
    assert steps[0]["ref_target"] == {"uc": "stammdatenänderung", "sd": "vom_nb_verantwortlich_ausgehend"}
    # unresolved ref → explicit None (never a fuzzy guess)
    assert steps[1]["ref_target"] is None
    # a non-ref step gets no ref_target key at all
    assert "ref_target" not in steps[2]
    # back-compat top-level steps mirror the primary diagram (same objects)
    assert detail["steps"][0]["ref_target"] == steps[0]["ref_target"]

    # the unresolved ref is surfaced in the printed worklist
    out_text = capsys.readouterr().out
    assert "unresolved refs: 1" in out_text
    assert "Mysterious Garbled Thing" in out_text


def test_run_override_resolves_otherwise_unresolved_ref(tmp_path: pathlib.Path, capsys: Any) -> None:
    out = tmp_path / "output"
    web = tmp_path / "webapp"
    caller = {
        "process": {"id": "caller", "name": "Caller", "category": "GPKE", "source": ""},
        "use_case": {"roles": ["NB"]},
        "sequence_diagram": {
            "participants": ["NB"],
            "steps": [
                {
                    "nr": 1,
                    "sender": "NB",
                    "receiver": "NB",
                    "message": "ref Reklamation vom ÜNB ref garbled",
                    "subprocess_ref": "Reklamation vom ÜNB ref garbled",
                },
            ],
        },
    }
    _write(out / "yaml" / "caller.yaml", yaml.safe_dump(caller, allow_unicode=True))
    rl = tmp_path / "sd_ref_links.yaml"
    rl.write_text(
        'overrides:\n  "Reklamation vom ÜNB ref garbled": {uc: reklamation, sd: vom_uenb}\n', encoding="utf-8"
    )

    run(output_dir=out, webapp_dir=web, ref_links_file=rl)

    detail = json.loads((web / "src/data/processes/caller.json").read_text("utf-8"))
    assert detail["diagrams"][0]["steps"][0]["ref_target"] == {"uc": "reklamation", "sd": "vom_uenb"}
    # nothing unresolved → no worklist line
    assert "unresolved refs" not in capsys.readouterr().out
