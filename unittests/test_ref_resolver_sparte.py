"""RefResolver: a ref resolves among the referring process's Sparte first (Gas P1).

GeLi Gas names its diagrams as GPKE names its own, so the corpus-wide keep-first map sends a ref
from a Gas process to the Strom diagram of the same name.
"""

from typing import Any

import pytest

from makoralle.models.process import NamedSD, Process, SDStep
from makoralle.models.sparte import Sparte
from makoralle.ref_links import RefResolver, assign_subprocess_ref_ids, normalize_ref


def _proc(pid: str, name: str, sparte: str | None) -> dict[str, Any]:
    return {"id": pid, "name": name, "sparte": sparte, "diagrams": [{"slug": "", "name": None}]}


CORPUS = [
    _proc("lieferende_von_nb_an_lf", "Lieferende von NB an LF", "strom"),
    _proc("lieferende_von_nb_an_lf_gas", "Lieferende von NB an LF", "gas"),
    _proc("wiederherstellung", "Wiederherstellung der Anschlussnutzung", "strom"),
    _proc("nur_gas", "Nur Gas", "gas"),
]


@pytest.mark.parametrize(
    ("sparte", "ref", "expected"),
    [
        # Each Sparte finds its own namesake.
        ("gas", "Lieferende von NB an LF", "lieferende_von_nb_an_lf_gas"),
        ("strom", "Lieferende von NB an LF", "lieferende_von_nb_an_lf"),
        # Without a Sparte it is resolve_ref: the corpus-wide keep-first map (Strom sorts first here).
        (None, "Lieferende von NB an LF", "lieferende_von_nb_an_lf"),
        # A name only the other Sparte has still resolves, through the corpus-wide map.
        ("gas", "Wiederherstellung der Anschlussnutzung", "wiederherstellung"),
        ("strom", "Nur Gas", "nur_gas"),
        # No target anywhere: None, never a guess.
        ("gas", "Gibt es nicht", None),
    ],
)
def test_resolve_prefers_the_referring_sparte(sparte: str | None, ref: str, expected: str | None) -> None:
    target = RefResolver(CORPUS, {}).resolve(ref, sparte)
    assert (target or {}).get("uc") == expected


def test_an_override_with_a_same_sparte_target_wins_over_the_map() -> None:
    overrides = {normalize_ref("Lieferende von NB an LF"): {"uc": "nur_gas", "sd": ""}}
    resolver = RefResolver(CORPUS, overrides)
    assert resolver.resolve("Lieferende von NB an LF", "gas") == {"uc": "nur_gas", "sd": ""}


def test_an_override_for_the_other_sparte_yields_to_a_same_sparte_hit() -> None:
    """A Strom-curated override must not pull a Gas ref with the same text onto the Strom target."""
    overrides = {normalize_ref("Lieferende von NB an LF"): {"uc": "lieferende_von_nb_an_lf", "sd": ""}}
    resolver = RefResolver(CORPUS, overrides)
    assert (resolver.resolve("Lieferende von NB an LF", "gas") or {}).get("uc") == "lieferende_von_nb_an_lf_gas"
    assert (resolver.resolve("Lieferende von NB an LF", "strom") or {}).get("uc") == "lieferende_von_nb_an_lf"


def test_an_override_still_wins_when_the_referring_sparte_has_no_hit() -> None:
    overrides = {normalize_ref("Garbled Ref"): {"uc": "wiederherstellung", "sd": ""}}
    assert RefResolver(CORPUS, overrides).resolve("Garbled Ref", "gas") == {"uc": "wiederherstellung", "sd": ""}


def _process(pid: str, name: str, sparte: Sparte, ref: str | None = None) -> Process:
    steps = [SDStep(nr=1, sender="LF", receiver="NB", message=f"ref {ref}", subprocess_ref=ref)] if ref else []
    return Process(
        id=pid,
        name=name,
        source="",
        category="",
        sparte=sparte,
        diagrams=[NamedSD(slug="", participants=["LF", "NB"], steps=steps)],
    )


def test_assign_subprocess_ref_ids_uses_the_process_sparte() -> None:
    procs = [
        _process("lieferende_von_nb_an_lf", "Lieferende von NB an LF", "strom"),
        _process("lieferende_von_nb_an_lf_gas", "Lieferende von NB an LF", "gas"),
        _process("lieferbeginn", "Lieferbeginn", "strom", ref="Lieferende von NB an LF"),
        _process("lieferbeginn_gas", "Lieferbeginn", "gas", ref="Lieferende von NB an LF"),
    ]
    assert assign_subprocess_ref_ids(procs, {}) == []
    assert procs[2].diagrams[0].steps[0].subprocess_ref_id == "lieferende_von_nb_an_lf"
    assert procs[3].diagrams[0].steps[0].subprocess_ref_id == "lieferende_von_nb_an_lf_gas"
