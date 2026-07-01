"""Segmentation-driven UC->SD grouping.

Groups each ``… SD: …`` section with the ``… UC: …`` section under the same
parent (the ``… Use-Case: …`` heading), keyed by the UC's derived process id.

This grouping map is the authoritative source for *which* SDs belong to a UC,
replacing the prefix/fuzzy heuristics. ``_slug`` is the single canonical
process-id derivation reused by ``p06_extract_diagrams`` and
``p08_parse_sd._sd_process_id`` so UC/SD ids line up with existing
UC/SD json/yaml filenames.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _slug(text: str) -> str:
    s = text.strip().lower().replace(" ", "_")
    s = re.sub(r"[^a-zäöüß0-9_-]", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def _normalize_for_matching(text: str) -> str:
    """Normalize text for matching — strip all punctuation, lowercase, single spaces.

    Lives here (dependency-light: stdlib only) so consumers like
    ``build_webapp_data`` / ``ref_links`` can reuse it without importing
    ``p12_link`` (which pulls in pydantic models). ``p12_link`` re-exports it.
    """
    text = text.lower()
    text = re.sub(r"[^a-zäöüß0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def uc_process_id(uc_heading: str) -> str:
    """Derive the canonical process id (slug) from a ``… UC: …`` section heading."""
    return _slug(uc_heading.split("UC:")[-1])


def sd_slug_and_name(sd_heading: str, uc_name: str | None) -> tuple[str, str | None]:
    """Derive an SD's per-UC ``slug`` and human ``name`` from its heading.

    Strips the UC name prefix (case-insensitive) to isolate the role qualifier
    that distinguishes SD variants within one UC. The prefix is only stripped at
    a word boundary (next char is a separator or end-of-string), never mid-word.
    When the SD's full name equals the UC name (a single-SD UC), there is no
    qualifier so ``name`` is ``None``.
    """
    full = sd_heading.split("SD:")[-1].strip()
    name: str | None = full
    if uc_name:
        p = uc_name.strip()
        if full.lower().startswith(p.lower()):
            rest = full[len(p) :]
            if not rest or rest[0] in " -–—:":  # word boundary, not mid-word
                name = rest.strip(" -–—:") or None
    slug = _slug(name) if name else _slug(full)
    return slug, name


def sd_artifact_key(uc_id: str, slug: str, n_sds: int) -> str:
    """Artifact filename key: bare uc_id for single-SD UCs (zero churn for the
    ~139 existing processes); uc_id__slug when a UC has multiple SDs."""
    return uc_id if n_sds <= 1 else f"{uc_id}__{slug}"


def _parent(section_id: str) -> str:
    return section_id.rsplit(".", 1)[0] if "." in section_id else section_id


def uc_sd_section_groups(segmented: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """{uc_process_id: [SD section dicts]} grouped by shared parent section."""
    secs = segmented.get("sections", [])
    ucs: dict[str, dict[str, Any]] = {}
    for s in secs:
        if "UC:" not in s.get("heading", ""):
            continue
        parent = _parent(s["section_id"])
        if parent in ucs:
            logger.warning(
                "Duplicate UC parent section %r: %r overwrites %r; dropping the earlier UC.",
                parent,
                s.get("heading", ""),
                ucs[parent].get("heading", ""),
            )
        ucs[parent] = s
    # Every UC becomes a key (authoritative map), even if it has no SD siblings.
    out: dict[str, list[dict[str, Any]]] = {uc_process_id(u["heading"]): [] for u in ucs.values()}
    for s in secs:
        h = s.get("heading", "")
        if "SD:" not in h:
            continue
        uc = ucs.get(_parent(s["section_id"]))
        if not uc:
            continue
        out[uc_process_id(uc["heading"])].append(s)
    return out
