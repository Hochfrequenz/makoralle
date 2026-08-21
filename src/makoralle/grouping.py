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

#: What makes a heading a use case. The documents spell the marker three ways — measured over the
#: 379 headings of ``BK6-24-174_MaBiS_Lesefassung.pdf``: ``UC:`` 101x (the leaf section),
#: ``Use-Case:`` 105x (its parent, and the only marker on four use cases), ``Use Case:`` once
#: (10.2) — and the table of contents prints them upper-cased, hence the case-insensitive match.
#: The same pattern as ``makorele.pipeline.wrapped_text.UC_HEADING_MARKER``, which is the other
#: half of makoralle#28; that repo should import this one rather than keep its copy.
UC_HEADING_MARKER = re.compile(r"\b(?:UC|Use[\s-]?Case)\s*:", re.I)

#: The *leaf* section's marker, the short spelling only — the section p07 keeps as canonical. A
#: normal use case carries both spellings, one per section level, so this is what tells the leaf
#: from its parent. Keying on the long spelling as an equal alternative would give every use case
#: two entries; it is a fallback instead, for a parent with no leaf below it.
LEAF_UC_MARKER = re.compile(r"\bUC\s*:", re.I)


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
    """Derive the canonical process id (slug) from a use-case section heading.

    Everything after the *last* marker, in any of its spellings. ``rsplit("UC:")[-1]`` returned the
    whole heading for a ``Use-Case:`` one — number, marker and all — so the slug it derived was not
    the id anything else uses. A heading with no marker keeps its whole text, as before.
    """
    markers = list(UC_HEADING_MARKER.finditer(uc_heading))
    return _slug(uc_heading[markers[-1].end() :] if markers else uc_heading)


def sd_slug_and_name(sd_heading: str, uc_name: str | None) -> tuple[str, str | None]:
    """Derive an SD's per-UC ``slug`` and human ``name`` from its heading.

    Strips the UC name prefix (case-insensitive) to isolate the role qualifier
    that distinguishes SD variants within one UC. The prefix is only stripped at
    a word boundary (next char is a separator or end-of-string), never mid-word.
    When the SD's full name equals the UC name (a single-SD UC), there is no
    qualifier so ``name`` is ``None``.
    """
    full = sd_heading.rsplit("SD:", maxsplit=1)[-1].strip()
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


def ad_artifact_key(uc_id: str, slug: str, n_sds: int) -> str:
    """Artifact filename key for an activity diagram (``output/bpmn/``).

    Same shape as :func:`sd_artifact_key` but with a SINGLE underscore, because
    p11 names the activity diagrams after the document's own AD headings:
    ``bestellung_zur_stammdatenänderung_an_lf_verantwortlich`` next to the SD's
    ``bestellung_zur_stammdatenänderung__an_lf_verantwortlich``. Getting this
    separator wrong silently strands every variant's diagram, so it is spelled out
    here rather than inlined at the call site.
    """
    return uc_id if n_sds <= 1 else f"{uc_id}_{slug}"


def _parent(section_id: str) -> str:
    return section_id.rsplit(".", 1)[0] if "." in section_id else section_id


def uc_sd_section_groups(segmented: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """{uc_process_id: [SD section dicts]} grouped by shared parent section."""
    secs = segmented.get("sections", [])
    ucs: dict[str, dict[str, Any]] = {}
    for s in secs:
        if not LEAF_UC_MARKER.search(s.get("heading", "")):
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
    # A use case whose only marker is the long spelling: MaBiS 6.7, 6.8, 8.5 and 12.4, where the
    # parent reads "Use-Case: …" and no child carries "UC:" (12.4.1 reads "UC Austausch …" with no
    # colon, which is not a marker). Its SDs are its *children*, so it keys on its own section id
    # rather than its parent's — and only where the leaf pass claimed nothing, so a use case with
    # both spellings still produces one group.
    for s in secs:
        heading = s.get("heading", "")
        if LEAF_UC_MARKER.search(heading) or not UC_HEADING_MARKER.search(heading):
            continue
        section_id = s["section_id"]
        if section_id in ucs or any(other.startswith(f"{section_id}.") for other in ucs):
            continue
        ucs[section_id] = s

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
