"""Build the webapp's data from `output/`: turn the parsed YAML into the JSON the
SPA consumes and copy the diagram SVGs.

Library API — `run(output_dir=..., webapp_dir=..., approvals_file=...)`. The thin
`scripts/build_webapp_data.py` wrapper wires this to the repo's own paths.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from makoralle.grouping import ad_artifact_key, sd_artifact_key
from makoralle.ref_links import build_ref_map, load_ref_overrides, resolve_ref
from makoralle.review import ReviewItem, is_actionable, review_items
from makoralle.serialization.makrake import canonical_json, makrake_diagram


def sd_source_hash(source_text: str) -> str:
    """SHA-256 of a diagram's canonical source — the identity an approval is tied to.

    ``source_text`` is the canonical makrake render input
    (:func:`~makoralle.serialization.makrake.canonical_json`). It used to be the ``.wsd``
    DSL, which was the wrong subject twice over: the DSL dropped facts the diagram states
    (a resolved subprocess reference has no slot in it), so a change to one could not
    invalidate an approval; and it carried rendering directives (``# style:``) that could,
    even though a reader would see no difference.

    Still hashed as text rather than over the object, because the approve command must be
    able to recompute it from what the build wrote without reimplementing the serializer —
    that is what keeps the stamped hash and the build-time check from ever disagreeing.
    Line endings are normalized and surrounding whitespace stripped so cosmetic churn does
    not clear a badge, while any change to a step, label, deadline, participant or resolved
    ref target does.
    """
    normalized = source_text.replace("\r\n", "\n").replace("\r", "\n").strip()
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
    # The list view searches the index, so a reader who does not already know the number needs
    # the Anwendungsfall here too — that is what makorele#52 was asked for and mako_prozesse#167
    # is missing. Restricted to the PIDs the diagrams actually reference: `pid_mappings` is the
    # process's slice of the official list and can name one no step shows, which would make the
    # process findable under a word its page never displays. Distinct, because 23 processes
    # reference several PIDs sharing one Anwendungsfall, and sorted, because this list is
    # committed to the dataset repo and an unordered one would churn on every regeneration.
    variants = _pid_name_variants(process.get("pid_mappings") or [])
    all_pid_names = sorted({name for pid in all_pids for name in variants.get(pid, ())})
    participants = _ordered_union(d.get("participants") or [] for d in diagrams)
    return {
        "id": p.get("id") or "",
        "name": p.get("name") or "",
        "category": p.get("category") or "",
        "roles": uc.get("roles") or [],
        "participants": participants,
        "pids": all_pids,
        "pidNames": all_pid_names,
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


def _pid_names(mappings: list[dict[str, Any]]) -> dict[int, str]:
    """Prüfidentifikator -> the Anwendungsfall the official PID list gives it.

    The number alone does not say what a PID is for, so a reader checking which one applies to them
    has to leave the page (makorele#52). The name is already in the data — `anwendungsfall` on each
    `pid_mappings` row — and was simply not carried into the payload.

    One PID can appear on several rows — a different Zuordnungsobjekt or Objekteigenschaft per row —
    almost always with the same Anwendungsfall. Two of the 429 named PIDs in dataset v0.0.15 disagree
    and both disagreements are a typo rather than a meaning: 19101 has three rows and reads "Ablehnung
    der Anfrage␣␣Stammdaten" on the first, one space on the other two; 55672 reads "Abr.-Daten
    BK-Abr. erz. Malo" against "erz.. MaLo". So the first row wins — the label has one line to live
    on, and joining two spellings of one name would put text in it that no document contains. Note
    what that means here: the row that wins is the one carrying the double space, because it is the
    one the file lists first.

    This map is built per process, which matters for exactly one of those two: 19101's three rows are
    all in `geschäftsdatenanfrage`, so `setdefault` really does resolve it, while 55672's two spellings
    sit in two different processes and each keeps its own. Nothing joins across processes, so a PID
    cannot pick up a name from a process that does not reference it.

    Per *process*, though, and not per diagram: 57 (process, PID) pairs in v0.0.15 have rows under
    more than one `bezeichnung_sequenzdiagramm`, and **56** of the 57 carry the same name in each.
    The 57th is 19101 again — those same three rows, under `Geschäftsdatenanfrage`, `… vom LF an NB`
    and `… vom MSB an NB` — the conflict named two paragraphs above, resolved the same way. So
    nothing is mis-attributed today, but only because that one disagreement is whitespace: a row need
    not describe the diagram whose step carries the number, and a real disagreement there would
    resolve to whichever row the file happens to list first.

    A row whose Prüfidentifikator is **0** is not a PID: the 9 such rows in v0.0.15 describe API
    paths (`/steuerbefehl/initialZustand/`, `/maloID/request/`) which the official list carries in
    the *Anwendungsfall* column with no number of their own. They contribute no name, and no step
    references PID 0.
    """
    names: dict[int, str] = {}
    for number, name in _pid_name_rows(mappings):
        names.setdefault(number, name)
    return names


def _pid_name_rows(mappings: list[dict[str, Any]]) -> Iterator[tuple[int, str]]:
    """Every usable (Prüfidentifikator, Anwendungsfall) pair, in file order and undeduplicated.

    Split out so the two callers can disagree about collisions: a label has one line to live on and
    takes the first row (`_pid_names`), while a search text has no such constraint and takes them all
    (`_pid_name_variants`).
    """
    for row in mappings:
        raw = row.get("prüfidentifikator")
        name = (row.get("anwendungsfall") or "").strip()
        # `not raw` is what fires on the corpus: it rejects Prüfidentifikator 0, the placeholder on
        # the nine API-path rows. `not name` matters too — a blank Anwendungsfall claiming the number
        # would block a later row that has one, turning a real name into the empty string this
        # function is careful to distinguish from "no row".
        if not raw or not name:
            continue
        try:
            number = int(str(raw).strip())
        except ValueError:  # defensive: every value in v0.0.15 is an integer, but the column is text
            continue
        yield number, name


def _pid_name_variants(mappings: list[dict[str, Any]]) -> dict[int, set[str]]:
    """Prüfidentifikator -> *every* spelling its rows give the Anwendungsfall.

    `_pid_names` resolves a PID whose rows disagree to the first row, because a label has one line
    and joining two spellings would put text in it that no document contains. A search text is under
    no such pressure, so it carries both: dropping one means a reader who types the losing spelling
    gets no hit at all. That is not hypothetical — 19101 in `geschäftsdatenanfrage` reads "Ablehnung
    der Anfrage␣␣Stammdaten" on the row that wins and the ordinary single space on its other two, and
    the webapp's search neither collapses whitespace nor matches loosely.
    """
    variants: dict[int, set[str]] = {}
    for number, name in _pid_name_rows(mappings):
        variants.setdefault(number, set()).add(name)
    return variants


def _pid_table(steps: list[dict[str, Any]], names: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """Per-step Prüfidentifikator rows, one per referenced PID."""
    names = names or {}
    out: list[dict[str, Any]] = []
    for s in steps:
        for pid in s.get("pid_refs") or []:
            out.append(
                {
                    "nr": s.get("nr"),
                    "pid": pid,
                    # None rather than "" when the PID list has no row for this number: the webapp
                    # can then tell "no name recorded" from "a name that is empty".
                    "name": names.get(pid),
                    "message": s.get("message"),
                    "format": s.get("format"),
                }
            )
    return out


def _distinct_pids(steps: list[dict[str, Any]]) -> list[int]:
    """Distinct, sorted PID numbers referenced across all steps (for list search)."""
    pids = {pid for s in steps for pid in (s.get("pid_refs") or [])}
    return sorted(pids)


def build_detail(
    process: dict[str, Any], *, review_notes: list[str], review: list[ReviewItem] | None = None
) -> dict[str, Any]:
    """Build the full per-process detail record (``processes/<id>.json``).

    ``review`` is the structured worklist (:mod:`makoralle.review`); ``review_notes`` is
    the same list flattened to its prose, kept because the webapp still reads that field.
    Both are passed in rather than computed here for the reason the whole module works this
    way: an item's severity depends on a resolved subprocess ref, and resolution needs
    every process in scope.
    """
    p = process.get("process") or {}
    pid_names = _pid_names(process.get("pid_mappings") or [])
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
                "pids": _pid_table(d_steps, pid_names),
                "svg": f"/diagrams/sequence/{key}.svg",
                # Attached by run(), which can see which artifact actually exists;
                # build_detail has no filesystem, so it emits None rather than a
                # path that may 404 (same contract as `approval` below).
                "activitySvg": None,
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
        "pids": _pid_table(primary_steps, pid_names),
        "diagrams": diagrams,
        "reviewNotes": review_notes or [],
        # The same worklist with its severity, kind and step intact. `reviewNotes` above is
        # this list's prose, and goes when the webapp reads `reviewItems` instead.
        "reviewItems": [i.model_dump(mode="json") for i in (review or [])],
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


def approval_for(source_text: str | None, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """The webapp-facing approval ({by, at, note}) iff `entry` was stamped against the
    diagram's *current* canonical source; None otherwise (no entry, no source, stale hash)."""
    if not entry or source_text is None:
        return None
    if entry.get("sha256") != sd_source_hash(source_text):
        return None
    return {"by": entry.get("approved_by") or "", "at": entry.get("approved_at") or "", "note": entry.get("note") or ""}


class ResolvedProcess(NamedTuple):
    """A process with its subprocess refs resolved and its artifact keys computed.

    Resolution has to see every process at once — a ``ref`` names another process's SD,
    which may sort later — so it cannot be done per process as the exporter walks them.
    Both :func:`run` and :func:`export_makrake_inputs` need the resolved form, and doing it
    twice risks the two disagreeing about a target, which is precisely the kind of drift
    that leaves a link pointing somewhere the diagram does not.
    """

    pid: str
    process: dict[str, Any]
    #: One entry per SD variant, with ``ref_target`` filled in on every ``subprocess_ref``
    #: step. These are the process's own step dicts, mutated in place, so anything reading
    #: ``process`` afterwards sees the resolved targets too.
    diagrams: list[dict[str, Any]]
    #: Artifact key per diagram, positionally aligned with :attr:`diagrams`.
    keys: list[str]

    def payload(self, index: int) -> dict[str, Any]:
        """The makrake render input for ``diagrams[index]``."""
        diagram = self.diagrams[index]
        name = (self.process.get("process") or {}).get("name") or self.pid
        title = f"{name} — {diagram['name']}" if diagram.get("name") else name
        return makrake_diagram(diagram, diagram_id=self.keys[index], name=title)


def load_resolved(output_dir: Path, ref_links_file: Path | None = None) -> tuple[list[ResolvedProcess], set[str]]:
    """Every process in ``output_dir/yaml``, refs resolved. Also the refs that did not.

    An unresolved ref stays ``None`` rather than becoming a fuzzy guess: a box with no link
    is honest, a box linking to the wrong process is not. Curate those in
    ``sd_ref_links.yaml``.
    """
    loaded: list[tuple[str, dict[str, Any]]] = []
    for yfile in sorted((output_dir / "yaml").glob("*.yaml")):
        process = yaml.safe_load(yfile.read_text("utf-8"))
        if not process:
            print(f"skipping empty YAML: {yfile.name}")
            continue
        loaded.append(((process.get("process") or {}).get("id") or yfile.stem, process))

    ref_overrides = load_ref_overrides(ref_links_file)
    ref_map = build_ref_map(
        {"id": pid, "name": (p.get("process") or {}).get("name") or "", "diagrams": _diagrams_source(p)}
        for pid, p in loaded
    )

    resolved: list[ResolvedProcess] = []
    unresolved: set[str] = set()
    for pid, process in loaded:
        diagrams = _diagrams_source(process)
        for diagram in diagrams:
            for step in diagram.get("steps") or []:
                ref = step.get("subprocess_ref")
                if not ref:
                    continue
                step["ref_target"] = resolve_ref(ref, ref_map, ref_overrides)
                if step["ref_target"] is None:
                    unresolved.add(ref)
        keys = [sd_artifact_key(pid, d.get("slug", ""), len(diagrams)) for d in diagrams]
        resolved.append(ResolvedProcess(pid=pid, process=process, diagrams=diagrams, keys=keys))
    return resolved, unresolved


def diagram_source_text(output_dir: Path, key: str, ref_links_file: Path | None = None) -> str | None:
    """The canonical source text of one diagram, by artifact key — or ``None`` if unknown.

    What :func:`sd_source_hash` is taken over, exposed because stamping an approval and
    checking one at build time must never disagree: the approve command asks for the text
    rather than rebuilding it, so there is one serializer and one resolution pass behind
    both. That is also why it takes ``ref_links_file`` — a diagram's canonical form
    includes its resolved ref targets, so an approval stamped without the overrides loaded
    would be stale the moment the build applied them.
    """
    resolved, _ = load_resolved(output_dir, ref_links_file)
    for entry in resolved:
        for i, entry_key in enumerate(entry.keys):
            if entry_key == key:
                return canonical_json(entry.payload(i))
    return None


def export_makrake_inputs(*, output_dir: Path, dest: Path, ref_links_file: Path | None = None) -> int:
    """Write one ``<artifact key>.json`` render input per diagram into ``dest``.

    This is what replaced ``output/sequence/*.wsd``, and unlike the ``.wsd`` it is **not**
    a committed artifact: it is fully derivable from ``output/yaml`` plus
    ``sd_ref_links.yaml``, and the ``.wsd`` was only ever committed because the render was
    a call to a third-party API and the approval hash was taken over the file. Neither is
    true now, so the pipeline writes these into a scratch directory, renders them, and
    throws them away — one less generated tree to drift.

    Returns the number of diagrams written.
    """
    dest.mkdir(parents=True, exist_ok=True)
    resolved, unresolved = load_resolved(output_dir, ref_links_file)
    written = 0
    for entry in resolved:
        for i, key in enumerate(entry.keys):
            (dest / f"{key}.json").write_text(canonical_json(entry.payload(i)) + "\n", "utf-8")
            written += 1
    print(f"wrote {written} makrake render inputs → {dest}")
    if unresolved:
        print(f"unresolved refs: {len(unresolved)} (add to sd_ref_links.yaml)")
    return written


def run(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    *, output_dir: Path, webapp_dir: Path, approvals_file: Path | None = None, ref_links_file: Path | None = None
) -> int:
    """Build the webapp data (index + per-process JSON) and copy diagram SVGs.

    Reads parsed YAML/rendered artifacts from ``output_dir`` and writes the SPA's
    ``src/data`` JSON plus ``public/diagrams`` SVGs into ``webapp_dir``. Returns the
    number of processes written.
    """
    seq_svg, bpmn_svg = (output_dir / "sequence_svg", output_dir / "bpmn")
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
    # Activity-diagram artifact -> the process that claims it. Whatever is left over
    # is still copied and indexed, but is not reachable from a process page. Two
    # processes claiming one artifact means p11's naming is ambiguous (a bare id that
    # looks like another process's {pid}_{slug}), so record it rather than absorb it.
    claimed_ads: dict[str, str] = {}
    contested_ads: list[str] = []

    loaded, unresolved_refs = load_resolved(output_dir, ref_links_file)

    index = []
    for entry in loaded:
        pid, process, diagrams, keys = entry
        # Activity diagrams are keyed per SD variant ({pid}_{slug}), with the bare
        # {pid} as fallback — checking only the bare name leaves every variant's
        # diagram unreachable. Record which artifacts got claimed so the leftovers
        # can be listed (and still shipped) below.
        ad_keys = [ad_artifact_key(pid, d.get("slug", ""), len(diagrams)) for d in diagrams]
        ad_for_slug: list[str | None] = []
        for ad_key in ad_keys:
            found = next((k for k in (ad_key, pid) if (bpmn_svg / f"{k}.svg").exists()), None)
            ad_for_slug.append(found)
            if found and claimed_ads.setdefault(found, pid) != pid:
                contested_ads.append(f"{found} (claimed by {claimed_ads[found]} and {pid})")
        # A process with no sequence diagram at all still gets its bare activity
        # diagram: p11 renders ADs independently of SDs, and `any([])` would have
        # dropped it — the exact silent-drop this change exists to remove.
        bare_only = not diagrams and (bpmn_svg / f"{pid}.svg").exists()
        if bare_only:
            claimed_ads.setdefault(pid, pid)
        has_bpmn = any(ad_for_slug) or bare_only
        has_seq = any((seq_svg / f"{key}.svg").exists() for key in keys)
        # The worklist is computed per diagram, so an item knows which step it is about;
        # a process's list is its diagrams' concatenated, in diagram order.
        review = [item for i in range(len(diagrams)) for item in review_items(diagrams[i])]
        # `reviewNotes` is the prose of the same list, de-duplicated as the webapp's current
        # field has always been. It goes once the webapp reads `reviewItems`.
        review_notes: list[str] = []
        for item in review:
            if item.text not in review_notes:
                review_notes.append(item.text)
        detail = build_detail(process, review_notes=review_notes, review=review)
        # Per-SD: attach each diagram's approval and copy its .svg into the webapp. The
        # artifact key is the svg path's stem (one source of truth with build_detail).
        #
        # An approval is now checked against the diagram's canonical render input rather
        # than against a `.wsd` file on disk — so the check no longer depends on an
        # intermediate artifact existing, and it covers the resolved ref targets the DSL
        # could not express.
        payload_by_key = {key: entry.payload(i) for i, key in enumerate(keys)}
        for diagram in detail["diagrams"]:
            key = Path(diagram["svg"]).stem
            consulted_keys.add(key)
            payload = payload_by_key.get(key)
            source_text = canonical_json(payload) if payload is not None else None
            approval_entry = approvals.get(key)
            diagram["approval"] = approval_for(source_text, approval_entry)
            # Stale = an approval ENTRY for a diagram that still exists but no longer
            # hashes to the stamped value (a real change, not a missing source).
            if approval_entry is not None and source_text is not None and diagram["approval"] is None:
                stale_count += 1
            d_svg = seq_svg / f"{key}.svg"
            if d_svg.exists():
                shutil.copyfile(d_svg, dest_seq / f"{key}.svg")
        # Point each diagram at the activity artifact that actually exists (None
        # when this variant has none), so the app never links a 404.
        for diagram, resolved_ad in zip(detail["diagrams"], ad_for_slug, strict=True):
            diagram["activitySvg"] = f"/diagrams/bpmn/{resolved_ad}.svg" if resolved_ad else None
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
                process,
                has_bpmn=has_bpmn,
                # Actionable only. Every `uncheckable` item would also be "review needed"
                # by the letter of the word, and the flag would then be on for 120 of 196
                # processes where 21 have work to do.
                has_review=is_actionable(review),
                has_sequence=has_seq,
                approved=fully_approved,
            )
        )
        (detail_dir / f"{pid}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=2), "utf-8")
        # Back-compat: keep the bare {pid}.svg copy when it exists (single-SD); guard
        # on the file itself, not has_seq (multi-SD has only {pid}__{slug}.svg).
        if (seq_svg / f"{pid}.svg").exists():
            shutil.copyfile(seq_svg / f"{pid}.svg", dest_seq / f"{pid}.svg")

    # Copy EVERY rendered activity diagram, not just the ones a process page links:
    # anything unlinked used to be dropped here without a word. The ones that resolve
    # to no process/variant stay reachable through activity_diagrams.json (browse view).
    all_ads = sorted(p.stem for p in bpmn_svg.glob("*.svg")) if bpmn_svg.exists() else []
    for ad_key in all_ads:
        shutil.copyfile(bpmn_svg / f"{ad_key}.svg", dest_bpmn / f"{ad_key}.svg")
    unclaimed = [k for k in all_ads if k not in claimed_ads]
    (data_dir / "activity_diagrams.json").write_text(
        json.dumps(
            [{"name": k, "svg": f"/diagrams/bpmn/{k}.svg", "linked": k in claimed_ads} for k in all_ads],
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )
    print(
        f"activity diagrams: {len(all_ads)} copied, {len(claimed_ads)} linked to a process, {len(unclaimed)} unlinked"
    )
    # One artifact wanted by two processes: p11's {pid}_{slug} is indistinguishable
    # from a bare id that ends in that slug. First claim wins (processes are walked in
    # sorted order, so it is at least deterministic), but say so rather than hide it.
    if contested_ads:
        print(f"ambiguous activity-diagram names: {len(contested_ads)}")
        for contested in contested_ads:
            print(f"  - {contested}")

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
    # Worklist: rendered activity diagrams that resolve to no process/variant —
    # mostly p11 names predating the UC de-truncation (see the dataset's
    # REGENERATION.md). They ship, but only the browse view reaches them.
    if unclaimed:
        print(f"unlinked activity diagrams: {len(unclaimed)}")
        for ad_key in unclaimed:
            print(f"  - {ad_key}")
    if unresolved_refs:
        print(f"unresolved refs: {len(unresolved_refs)} (add to sd_ref_links.yaml):")
        for ref in sorted(unresolved_refs):
            print(f"  - {ref}")
    return len(index)
