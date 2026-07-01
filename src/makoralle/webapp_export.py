"""Build the webapp's data from `output/`: turn the parsed YAML into the JSON the
SPA consumes and copy the diagram SVGs.

Library API — `run(output_dir=..., webapp_dir=..., approvals_file=...)`. The thin
`scripts/build_webapp_data.py` wrapper wires this to the repo's own paths.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

import yaml

from makoralle.grouping import sd_artifact_key
from makoralle.ref_links import build_ref_map, load_ref_overrides, resolve_ref


def sd_source_hash(wsd_text: str) -> str:
    """SHA-256 of the normalized .wsd source — the identity an approval is tied to.

    Normalizes line endings to LF and strips surrounding whitespace so cosmetic
    churn doesn't invalidate an approval, while any change to a step, label,
    deadline, or participant does. The approve command reuses this so the
    stamped hash and the build-time check can never disagree.
    """
    normalized = wsd_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _diagrams_source(process: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-SD diagram dicts to emit: ``process['diagrams']`` when present and
    non-empty, else the legacy ``sequence_diagram`` wrapped as one unnamed diagram
    (``slug=""``, ``name=None``), else ``[]`` when there is no SD at all.

    ``len(...)`` of the result doubles as the SD count: N for a multi-SD process,
    1 for a single-SD process (legacy or fallback), 0 when there is no diagram.
    """
    diagrams = process.get("diagrams")
    if diagrams:
        return diagrams  # type: ignore[no-any-return]
    sd = process.get("sequence_diagram")
    if sd:
        return [
            {"slug": "", "name": None, "participants": sd.get("participants") or [], "steps": sd.get("steps") or []}
        ]
    return []


def _ordered_union(lists: Iterable[list[Any] | None]) -> list[Any]:
    """Flatten an iterable of lists into a de-duplicated list, preserving order of
    first appearance (dict keys keep insertion order)."""
    out: dict[Any, None] = {}
    for lst in lists:
        for item in lst or []:
            out.setdefault(item, None)
    return list(out)


def build_index_entry(
    process: dict[str, Any], *, has_bpmn: bool, has_review: bool, has_sequence: bool, approved: bool = False
) -> dict[str, Any]:
    """Build the compact list-view entry (one row of ``processes.json``) for a process."""
    p = process.get("process") or {}
    uc = process.get("use_case") or {}
    diagrams = _diagrams_source(process)
    # stepCount mirrors the PRIMARY SD (diagrams[0], the same primary build_detail
    # uses) so index and detail never disagree about which SD is primary.
    primary_steps = diagrams[0]["steps"] if diagrams else []
    # hasDeadlines, PIDs, and participants aggregate across ALL SDs so a deadline,
    # PID, or role living only in a non-primary variant stays discoverable in the
    # list / PID search.
    has_deadlines = any(s.get("deadline") or s.get("deadline_rule") for d in diagrams for s in (d.get("steps") or []))
    all_pids = sorted({pid for d in diagrams for s in (d.get("steps") or []) for pid in (s.get("pid_refs") or [])})
    participants = _ordered_union(d.get("participants") or [] for d in diagrams)
    return {
        "id": p.get("id") or "",
        "name": p.get("name") or "",
        "category": p.get("category") or "",
        "roles": uc.get("roles") or [],
        "participants": participants,
        "pids": all_pids,
        "stepCount": len(primary_steps),
        "sdCount": len(diagrams),
        "hasDeadlines": has_deadlines,
        "hasSequence": has_sequence,
        "hasBpmn": has_bpmn,
        "hasReview": has_review,
        "approved": approved,
        "source": p.get("source") or "",
    }


def _deadline_table(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-step deadline rows (only steps carrying a deadline / deadline_rule)."""
    out: list[dict[str, Any]] = []
    for s in steps:
        if s.get("deadline") or s.get("deadline_rule"):
            out.append({"nr": s.get("nr"), "deadline": s.get("deadline"), "rule": s.get("deadline_rule")})
    return out


def _pid_table(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-step Prüfidentifikator rows, one per referenced PID."""
    out: list[dict[str, Any]] = []
    for s in steps:
        for pid in s.get("pid_refs") or []:
            out.append({"nr": s.get("nr"), "pid": pid, "message": s.get("message"), "format": s.get("format")})
    return out


def _distinct_pids(steps: list[dict[str, Any]]) -> list[int]:
    """Distinct, sorted PID numbers referenced across all steps (for list search)."""
    pids = {pid for s in steps for pid in (s.get("pid_refs") or [])}
    return sorted(pids)


def build_detail(process: dict[str, Any], *, review_notes: list[str]) -> dict[str, Any]:
    """Build the full per-process detail record (``processes/<id>.json``)."""
    p = process.get("process") or {}
    pid = p.get("id") or ""
    diagrams_src = _diagrams_source(process)
    n = len(diagrams_src)
    diagrams: list[dict[str, Any]] = []
    for d in diagrams_src:
        slug = d.get("slug", "")
        d_steps = d.get("steps") or []
        key = sd_artifact_key(pid, slug, n)
        # Overlay is attached in run() (where the rendered .html lives), keyed by
        # the same artifact key — see run().
        diagrams.append(
            {
                "slug": slug,
                "name": d.get("name"),
                "participants": d.get("participants") or [],
                "steps": d_steps,
                "deadlines": _deadline_table(d_steps),
                "pids": _pid_table(d_steps),
                "svg": f"/diagrams/sequence/{key}.svg",
            }
        )
    # Back-compat: the top-level steps/deadlines/pids/participants mirror the
    # PRIMARY diagram (diagrams[0], or the legacy sequence_diagram via fallback).
    # Task 3.4 will drop these once the webapp reads diagrams[] exclusively.
    primary_steps = diagrams[0]["steps"] if diagrams else []
    primary_participants = diagrams[0]["participants"] if diagrams else []
    return {
        "id": pid,
        "name": p.get("name") or "",
        "category": p.get("category") or "",
        "source": p.get("source") or "",
        "useCase": process.get("use_case") or {},
        "participants": primary_participants,
        "steps": primary_steps,
        "deadlines": _deadline_table(primary_steps),
        "pids": _pid_table(primary_steps),
        "diagrams": diagrams,
        "reviewNotes": review_notes or [],
        # Per-diagram approval (and this primary-mirroring detail.approval) is
        # attached by run(); build_detail emits the field as None so the dict shape
        # is stable for callers/tests that build a detail without the filesystem.
        "approval": None,
    }


def load_approvals(approvals_file: Path | None) -> dict[str, Any]:
    """Read sd_approvals.yaml → {process_id: entry}. Empty when absent/blank."""
    if not approvals_file or not approvals_file.exists():
        return {}
    data = yaml.safe_load(approvals_file.read_text("utf-8")) or {}
    return data.get("approvals") or {}


def approval_for(wsd_text: str | None, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """The webapp-facing approval ({by, at, note}) iff `entry` was stamped against
    the *current* .wsd; None otherwise (no entry, no source, or stale hash)."""
    if not entry or wsd_text is None:
        return None
    if entry.get("sha256") != sd_source_hash(wsd_text):
        return None
    return {"by": entry.get("approved_by") or "", "at": entry.get("approved_at") or "", "note": entry.get("note") or ""}


_REVIEW_RE = re.compile(r"note\b.*?:\s*(.*?)\s*\[REVIEW\]\s*$")


def extract_review_notes(wsd_text: str) -> list[str]:
    """Extract the ``[REVIEW]`` note texts embedded in a .wsd source, in order."""
    notes = []
    for line in wsd_text.splitlines():
        m = _REVIEW_RE.match(line.strip())
        if m:
            notes.append(m.group(1).strip())
    return notes


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def extract_sd_overlay(  # pylint: disable=too-many-locals,too-many-branches,invalid-name
    html_text: str,
) -> dict[str, Any] | None:
    """Extract the interactive overlay model from a rendered sequence-diagram .html viewer.

    Returns a dict with the SVG viewBox size, the PID hit-rects (coords + data-nr +
    data-pids, in SVG coordinate space), deadline-ref tags, the per-step deadline
    tooltip JSON, and the AHB base URL — everything a native React overlay needs to
    reproduce the viewer's interactivity over the static .svg. Returns None if the
    viewer carries no interactive overlays.
    """
    vb = re.search(r'<svg[^>]*\bviewBox="([\d.\s-]+)"', html_text)
    if not vb:
        return None
    parts = vb.group(1).split()
    if len(parts) != 4:
        return None
    w, h = float(parts[2]), float(parts[3])

    # A single overlay rect often carries several classes
    # (e.g. "dl-box pid-hit dl-ref"). Classify each rect ONCE so the React overlay
    # has one element per region: a pid-hit rect owns click + deadline-hover and,
    # if it also references a step, the ref-highlight; only rects that are *purely*
    # dl-ref become standalone refs. (Emitting a combined rect into both lists would
    # make the second overlay element swallow the first's pointer events.)
    pids: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    refLinks: list[dict[str, Any]] = []
    for tag in re.findall(r'<rect class="[^"]*\b(?:pid-hit|dl-ref|ref-hit)\b[^"]*"[^>]*>', html_text):
        cls = _attr(tag, "class") or ""
        box = {
            "x": float(_attr(tag, "x") or 0),
            "y": float(_attr(tag, "y") or 0),
            "w": float(_attr(tag, "width") or 0),
            "h": float(_attr(tag, "height") or 0),
        }
        if "pid-hit" in cls.split():
            nr = _attr(tag, "data-nr")
            if nr is None:
                continue
            pid_list = [int(p) for p in (_attr(tag, "data-pids") or "").split(",") if p.strip().isdigit()]
            hit = {"nr": int(nr), "pids": pid_list, **box}
            refnr = _attr(tag, "data-refnr")
            if refnr is not None and refnr.isdigit():
                hit["refnr"] = int(refnr)
            pids.append(hit)
        elif "dl-ref" in cls.split():
            rn = _attr(tag, "data-refnr")
            if rn is None:
                continue
            refs.append({"refnr": int(rn), **box})
        # ref-hit is handled INDEPENDENTLY of the pid/dl classification above: a
        # subprocess-ref step's rect may ALSO be a pid-hit, in which case it must
        # appear in BOTH `pids` (above) and `refLinks` (here).
        if "ref-hit" in cls.split():
            nr = _attr(tag, "data-nr")
            if nr is not None and nr.isdigit():
                uc = _attr(tag, "data-ref-uc")
                sd = _attr(tag, "data-ref-sd")
                refLinks.append({"nr": int(nr), "uc": uc or "", "sd": sd or "", **box})

    deadlines: dict[str, Any] = {}
    dm = re.search(r'<script[^>]*id="deadline-data"[^>]*>(.*?)</script>', html_text, re.S)
    if dm:
        try:
            deadlines = json.loads(dm.group(1))
        except ValueError:
            deadlines = {}

    if not pids and not refs and not deadlines and not refLinks:
        return None

    ahb = re.search(r'const PRE = "([^"]*)"', html_text)
    return {
        "w": w,
        "h": h,
        "ahbBase": ahb.group(1) if ahb else "",
        "pids": pids,
        "refs": refs,
        "deadlines": deadlines,
        "refLinks": refLinks,
    }


def run(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    *, output_dir: Path, webapp_dir: Path, approvals_file: Path | None = None, ref_links_file: Path | None = None
) -> int:
    """Build the webapp data (index + per-process JSON) and copy diagram SVGs.

    Reads parsed YAML/rendered artifacts from ``output_dir`` and writes the SPA's
    ``src/data`` JSON plus ``public/diagrams`` SVGs into ``webapp_dir``. Returns the
    number of processes written.
    """
    yaml_dir = output_dir / "yaml"
    seq_svg, bpmn_svg, wsd_dir = (output_dir / "sequence_svg", output_dir / "bpmn", output_dir / "sequence")
    data_dir = webapp_dir / "src" / "data"
    detail_dir = data_dir / "processes"
    dest_seq = webapp_dir / "public" / "diagrams" / "sequence"
    dest_bpmn = webapp_dir / "public" / "diagrams" / "bpmn"
    # These dirs are 100% generated; wipe them so re-runs don't keep orphans.
    for gen_dir in (detail_dir, dest_seq, dest_bpmn):
        if gen_dir.exists():
            shutil.rmtree(gen_dir)
        gen_dir.mkdir(parents=True, exist_ok=True)

    approvals = load_approvals(approvals_file)
    approved_count = stale_count = 0
    # Every current diagram artifact key we consult, so after the loop we can spot
    # approval ENTRIES that match no diagram at all (variant removed / slug renamed).
    consulted_keys: set[str] = set()

    # Load every process up front so the subprocess-ref resolver sees ALL SD
    # variants (a ref names another process's SD, which may sort later).
    loaded: list[tuple[str, dict[str, Any]]] = []
    for yfile in sorted(yaml_dir.glob("*.yaml")):
        process = yaml.safe_load(yfile.read_text("utf-8"))
        if not process:
            print(f"skipping empty YAML: {yfile.name}")
            continue
        pid = (process.get("process") or {}).get("id") or yfile.stem
        loaded.append((pid, process))

    # Build the ref map ({normalized SD/UC name -> (uc, sd)}) across all processes
    # and load the curated overrides, so each `subprocess_ref` step can carry a
    # precise `ref_target` (None when it doesn't resolve — never a fuzzy guess).
    ref_overrides = load_ref_overrides(ref_links_file)
    ref_map = build_ref_map(
        {"id": pid, "name": (p.get("process") or {}).get("name") or "", "diagrams": _diagrams_source(p)}
        for pid, p in loaded
    )
    unresolved_refs: set[str] = set()

    index = []
    for pid, process in loaded:
        # Compute the per-SD diagrams and their artifact keys once; everything that
        # used to assume a bare {pid} artifact now spans all of these keys.
        diagrams = _diagrams_source(process)
        # Resolve every subprocess-ref step to its (uc, sd) target. Mutating the
        # shared step dicts here means build_detail picks up `ref_target` in both
        # diagrams[].steps and the back-compat top-level steps (same objects).
        for d in diagrams:
            for step in d.get("steps") or []:
                ref = step.get("subprocess_ref")
                if ref:
                    step["ref_target"] = resolve_ref(ref, ref_map, ref_overrides)
                    if step["ref_target"] is None:
                        unresolved_refs.add(ref)
        keys = [sd_artifact_key(pid, d.get("slug", ""), len(diagrams)) for d in diagrams]
        has_bpmn = (bpmn_svg / f"{pid}.svg").exists()
        has_seq = any((seq_svg / f"{key}.svg").exists() for key in keys)
        # [REVIEW] notes ("Prüfung nötig" worklist) can live in ANY SD's .wsd;
        # aggregate across all, de-duplicating while preserving order.
        review: list[str] = []
        for key in keys:
            kwsd = wsd_dir / f"{key}.wsd"
            if kwsd.exists():
                for note in extract_review_notes(kwsd.read_text("utf-8")):
                    if note not in review:
                        review.append(note)
        detail = build_detail(process, review_notes=review)
        seq_html = seq_svg / f"{pid}.html"
        if seq_html.exists():
            overlay = extract_sd_overlay(seq_html.read_text("utf-8"))
            if overlay:
                detail["sdOverlay"] = overlay  # back-compat: primary SD overlay
        # Per-SD: attach each diagram's approval + overlay (from its rendered .html)
        # and copy its .svg into the webapp. The artifact key is the svg path's stem
        # (one source of truth with build_detail). Each diagram's approval is tied to
        # ITS OWN {key}.wsd; for a single-SD process the key equals {pid}, so this
        # re-touches the same files/approval the back-compat block handles.
        for diagram in detail["diagrams"]:
            key = Path(diagram["svg"]).stem
            consulted_keys.add(key)
            kwsd = wsd_dir / f"{key}.wsd"
            k_text = kwsd.read_text("utf-8") if kwsd.exists() else None
            entry = approvals.get(key)
            diagram["approval"] = approval_for(k_text, entry)
            # Stale = an approval ENTRY whose .wsd still exists but no longer hashes
            # to the stamped value (a real diagram change, not a missing source).
            if entry is not None and k_text is not None and diagram["approval"] is None:
                stale_count += 1
            d_html = seq_svg / f"{key}.html"
            if d_html.exists():
                d_overlay = extract_sd_overlay(d_html.read_text("utf-8"))
                if d_overlay:
                    diagram["overlay"] = d_overlay
            d_svg = seq_svg / f"{key}.svg"
            if d_svg.exists():
                shutil.copyfile(d_svg, dest_seq / f"{key}.svg")
        # detail.approval = the PRIMARY diagram's approval (back-compat; single-SD
        # key == pid so this equals the old {pid}.wsd result).
        detail["approval"] = detail["diagrams"][0]["approval"] if detail["diagrams"] else None
        # Index "approved" = FULLY approved: there is >=1 renderable diagram (one
        # carrying steps) and EVERY renderable diagram has a non-null approval.
        # Single-SD: one diagram → same as the old per-process flag.
        renderable = [d for d in detail["diagrams"] if d.get("steps")]
        fully_approved = bool(renderable) and all(d["approval"] for d in renderable)
        if fully_approved:
            approved_count += 1
        index.append(
            build_index_entry(
                process, has_bpmn=has_bpmn, has_review=bool(review), has_sequence=has_seq, approved=fully_approved
            )
        )
        (detail_dir / f"{pid}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), "utf-8")
        # Back-compat: keep the bare {pid}.svg copy when it exists (single-SD); guard
        # on the file itself, not has_seq (multi-SD has only {pid}__{slug}.svg).
        if (seq_svg / f"{pid}.svg").exists():
            shutil.copyfile(seq_svg / f"{pid}.svg", dest_seq / f"{pid}.svg")
        if has_bpmn:
            shutil.copyfile(bpmn_svg / f"{pid}.svg", dest_bpmn / f"{pid}.svg")

    index.sort(key=lambda e: (e["category"], e["name"].lower()))
    (data_dir / "processes.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), "utf-8")
    print(f"Wrote {len(index)} processes → {data_dir}")
    # Orphaned = an approval entry whose artifact key matched NO current diagram
    # (its variant/slug was removed or renamed) — the badge it vouches for is gone.
    orphaned = sorted(set(approvals) - consulted_keys)
    notes = []
    if stale_count:
        notes.append(f"{stale_count} stale")
    if orphaned:
        notes.append(f"{len(orphaned)} orphaned: {', '.join(orphaned)}")
    note = f" ({'; '.join(notes)})" if notes else ""
    print(f"approved: {approved_count}/{len(index)}{note}")
    # Worklist: distinct subprocess refs that resolved to no target. Curate these
    # in sd_ref_links.yaml (ambiguous / garbled scenario-bundle refs).
    if unresolved_refs:
        print(f"unresolved refs: {len(unresolved_refs)} " f"(add to sd_ref_links.yaml):")
        for ref in sorted(unresolved_refs):
            print(f"  - {ref}")
    return len(index)
