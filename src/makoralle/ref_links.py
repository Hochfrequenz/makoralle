"""Resolve subprocess ``ref`` steps to a precise ``(uc_id, slug)`` target.

A sequence-diagram step can be a subprocess reference: its message starts with
``ref``/``ref:``/``ref ref`` and names another process's SD (e.g.
``"ref Stammdatenänderung vom NB (verantwortlich) ausgehend"``). The linker
stores the cleaned name in ``step.subprocess_ref``. Now that every SD variant is
a navigable ``(uc_id, slug)`` we can resolve each ref to its target.

This module is intentionally dependency-light (``re``/``logging``/``yaml`` +
``_normalize_for_matching`` from :mod:`makoralle.grouping`) so the renderer
(Task 4.2) and the webapp-data build can both import it. There is NO fuzzy
matching: a ref resolves via a curated override or an exact normalized hit, or
not at all — a wrong link is worse than none.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

# p12_link does NOT import this module, so this is not a cycle; render_process_sds
# (the Task-4.2 consumer) already imports p12_link, so reusing its normalizer here
# adds no new dependency and keeps a single source of truth for normalization.
from makoralle.grouping import _normalize_for_matching
from makoralle.models.process import Process

logger = logging.getLogger(__name__)

#: Strips one or more leading ref-prefixes: "ref ", "ref:", "ref. ", "ref ref ".
_REF_PREFIX = re.compile(r"^(ref[:.\s]+)+", re.I)


def normalize_ref(text: str) -> str:
    """Normalize a ref / SD name for matching.

    Strips any leading ``ref``/``ref:``/``ref ref`` prefix (robust to the stray
    leading ``ref`` the linker sometimes leaves on ``subprocess_ref``), then
    applies the same normalization the rest of the codebase uses for matching
    (lowercase, punctuation incl. parentheses → spaces, whitespace collapsed).
    """
    if not text:
        return ""
    return _normalize_for_matching(_REF_PREFIX.sub("", text))


def _sd_full_name(source_heading: str | None) -> str | None:
    """The full SD name from a section heading: text after ``SD:`` (e.g.
    ``"1.4.2 SD: Stammdatenänderung vom NB ..."`` → ``"Stammdatenänderung vom
    NB ..."``). ``None`` when there is no heading / no ``SD:`` marker."""
    if not source_heading or "SD:" not in source_heading:
        return None
    return source_heading.split("SD:")[-1].strip()


def build_ref_map(processes: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map every diagram's normalized name(s) → its ``{"uc", "sd"}`` target.

    ``processes`` is an iterable of dicts shaped ``{"id", "name", "diagrams"}``
    where each diagram carries ``slug``, ``name`` (variant qualifier or ``None``)
    and optionally ``source_heading``. For every diagram we register, pointing at
    that diagram's ``(uc_id, slug)``:

    * ``normalize_ref(source_heading-after-SD)`` — the exact source text, and
    * ``normalize_ref(uc_name + " " + diagram.name)`` — the reconstructed full
      name (covers diagrams with no ``source_heading``, e.g. legacy single-SD).

    Additionally ``normalize_ref(uc_name)`` maps to the UC's FIRST diagram so a
    UC-level ref resolves to the default variant.

    On a normalized-key collision the FIRST registration wins (a differing
    target is logged, never silently remapped).
    """
    ref_map: dict[str, dict[str, Any]] = {}

    def _add(key: str, value: dict[str, Any]) -> None:
        if not key:
            return
        existing = ref_map.get(key)
        if existing is not None:
            if existing != value:
                logger.warning(
                    "ref_map collision on %r: keeping %r, ignoring %r",
                    key,
                    existing,
                    value,
                )
            return
        ref_map[key] = value

    for proc in processes:
        uc_id = proc.get("id")
        uc_name = proc.get("name") or ""
        diagrams = proc.get("diagrams") or []
        if not diagrams:
            continue
        # Register the UC-level default (first variant) FIRST so keep-first locks it
        # in: a NON-first diagram whose full name lacks a role qualifier normalizes
        # to the bare UC name, and must not hijack `ref <UC>` away from the
        # documented default (first) variant.
        first_slug = diagrams[0].get("slug", "") or ""
        _add(normalize_ref(uc_name), {"uc": uc_id, "sd": first_slug})
        for d in diagrams:
            target = {"uc": uc_id, "sd": d.get("slug", "") or ""}
            full = _sd_full_name(d.get("source_heading"))
            if full:
                _add(normalize_ref(full), target)
            qualifier = d.get("name")
            reconstructed = f"{uc_name} {qualifier}".strip() if qualifier else uc_name
            _add(normalize_ref(reconstructed), target)

    return ref_map


def resolve_ref(
    subprocess_ref: str, ref_map: dict[str, dict[str, Any]], overrides: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Resolve a ``subprocess_ref`` to its ``{"uc", "sd"}`` target, or ``None``.

    Lookup order (no fuzzy matching anywhere):
      1. ``overrides`` (keyed by normalized ref text) — curated, wins always;
      2. an exact ``ref_map`` hit on the normalized ref;
      3. otherwise ``None`` (unresolved — a wrong link is worse than none).
    """
    if not subprocess_ref:
        return None
    key = normalize_ref(subprocess_ref)
    if not key:
        return None
    if key in overrides:
        return overrides[key]
    return ref_map.get(key)


def ref_target_id(target: Mapping[str, Any] | Sequence[str] | None) -> str | None:
    """A resolved target as one id: ``uc__sd``, or the bare ``uc`` for the default diagram.

    The ``uc__sd`` spelling is makuna's template id and what makrake's ``{uc}`` / ``{sd}`` link
    placeholders split back apart, so an empty ``sd`` keeps the bare id rather than gaining an
    empty suffix. Accepts the ``{"uc", "sd"}`` mapping :func:`resolve_ref` returns or a
    ``(uc, sd)`` pair. ``None`` when the target is ``None`` or names no ``uc``.

    ``None`` is a real answer, not a failure: an unresolved reference gets no link, which is
    honest. Guessing a target would send a reader to the wrong process.
    """
    if not target:
        return None
    if isinstance(target, Mapping):
        uc, sd = target.get("uc") or "", target.get("sd") or ""
    else:
        uc, sd = [*list(target), "", ""][:2]
    if not uc:
        return None
    return f"{uc}__{sd}" if sd else str(uc)


def assign_subprocess_ref_ids(processes: Iterable[Process], overrides: dict[str, dict[str, Any]]) -> list[str]:
    """Set ``subprocess_ref_id`` on every step of ``processes``; return the refs that did not resolve.

    Resolution has to see the whole corpus at once, because a ``ref`` names another process's
    diagram. Every step is (re)assigned, so an id a previous run wrote is cleared when its ref
    no longer resolves. ``overrides`` is what :func:`load_ref_overrides` returns.

    The primary ``sequence_diagram`` alias is walked as well as ``diagrams``: the YAML writes
    both, and they must not disagree. The returned names are unique, in first-seen order.
    """
    procs = list(processes)
    ref_map = build_ref_map(
        {
            "id": p.id,
            "name": p.name,
            "diagrams": [{"slug": d.slug, "name": d.name, "source_heading": d.source_heading} for d in p.diagrams]
            or ([{"slug": "", "name": None}] if p.sequence_diagram else []),
        }
        for p in procs
    )
    unresolved: dict[str, None] = {}
    for p in procs:
        steps = [s for d in p.diagrams for s in d.steps]
        if p.sequence_diagram is not None:
            steps.extend(p.sequence_diagram.steps)
        for step in steps:
            if not step.subprocess_ref:
                step.subprocess_ref_id = None
                continue
            step.subprocess_ref_id = ref_target_id(resolve_ref(step.subprocess_ref, ref_map, overrides))
            if step.subprocess_ref_id is None:
                unresolved[step.subprocess_ref] = None
    return list(unresolved)


def load_ref_overrides(path: Path | None) -> dict[str, dict[str, Any]]:
    """Read ``sd_ref_links.yaml`` → ``{normalize_ref(key): {"uc", "sd"}}``.

    Returns ``{}`` when the file is absent or blank. Keys are normalized on load
    so curated entries match the same way :func:`resolve_ref` normalizes a ref.

    Values are validated so a typo can never produce a broken nav link: an entry
    MUST carry a non-empty ``uc`` (else it is skipped with a warning), and ``sd``
    defaults to ``""`` (the documented "default variant") when absent.
    """
    if not path or not Path(path).exists():
        return {}
    data = yaml.safe_load(Path(path).read_text("utf-8")) or {}
    raw = data.get("overrides") or {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if not isinstance(v, dict) or not v.get("uc"):
            logger.warning("ref override %r missing a 'uc' target; skipping", k)
            continue
        out[normalize_ref(k)] = {"uc": v["uc"], "sd": v.get("sd") or ""}
    return out
