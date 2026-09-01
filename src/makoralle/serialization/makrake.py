"""The render input for `makrake <https://github.com/Hochfrequenz/makrake>`_.

makrake renders MaKo sequence diagrams natively — real ``<text>`` and real ``<a href>``,
in the Hochfrequenz palette, with compact inline Frist tags. It replaces the
websequencediagrams API, and this module replaces the ``.wsd`` DSL as the thing a renderer
is handed.

**Why this is not just a second dialect of** :func:`~makoralle.serialization.wsd.emit_wsd`.
The ``.wsd`` text was a *lossy* rendering instruction: a Frist became a German note
sentence, a PID list became "(FORMAT 17115/17116)", and a resolved subprocess reference
became nothing at all, because the DSL has no slot for it. Everything a consumer needed
back — which step a click belongs to, which PIDs it carries, where a ``ref`` box points —
had to be recovered afterwards by scraping the rendered HTML
(``webapp_export.extract_sd_overlay``, now deleted) or by grepping the DSL
(``extract_review_notes``, now :mod:`makoralle.review`). This shape hands the renderer the
model instead, so nothing has to be recovered: makrake emits the semantics into the SVG
itself as ``data-step`` / ``data-pids`` / ``data-ref-uc``.

``emit_wsd`` stays, and is deliberately untouched: makorele's ``p06`` Vision refine pass
renders a reconstruction of what it just read and shows it back to Claude alongside the
original page. That is an in-memory picture for a parser, not a published artifact, and it
has no reason to change when the webapp's renderer does.

**Input shape.** Every function here takes the diagram in its YAML/JSON *mapping* form —
what ``output/yaml`` ships and what :mod:`makoralle.webapp_export` already holds — rather
than the pydantic model. That is on purpose: the exporter is the only caller, it resolves
subprocess references itself (see :func:`makrake_diagram`'s ``ref_target``), and validating
196 processes into models to serialize them straight back out would buy nothing.
"""

import json
from typing import Any

from makoralle.models.deadline import deadline_from_rule
from makoralle.models.process import REF_PREFIX, DeadlineRule

#: makrake's ``Step.kind``. A ``ref`` step is drawn as a folded-corner box spanning the
#: lanes rather than as an arrow between two of them.
_KIND_MESSAGE = "message"
_KIND_PROCESS_REF = "process_ref"


def _pids(step: dict[str, Any]) -> list[int]:
    """The step's Prüfidentifikatoren, as ints.

    ``pid_refs`` is already a list of ints in the dataset, but a JSON round trip through a
    hand-edited override can leave strings, and makrake's ``Vec<u32>`` rejects those with a
    deserialization error naming a line number rather than a step.
    """
    out: list[int] = []
    for pid in step.get("pid_refs") or []:
        try:
            out.append(int(pid))
        except (TypeError, ValueError):
            continue
    return out


def _subprocess_ref_id(step: dict[str, Any]) -> str | None:
    """The referenced subprocess's template id, or ``None`` when it did not resolve.

    Reads the ``ref_target`` that :func:`makoralle.webapp_export.run` already put on the
    step — a ``(uc, sd)`` pair, or ``None``. The ``uc__sd`` spelling is makuna's template
    id and what makrake's ``{uc}`` / ``{sd}`` link placeholders split back apart, so a
    single-diagram target keeps its bare id rather than gaining an empty suffix.

    ``None`` is a real answer, not a failure: an unresolved reference gets a box with no
    link, which is honest. Guessing a target would send a reader to the wrong process.
    """
    target = step.get("ref_target")
    if not target:
        return None
    if isinstance(target, dict):
        uc, sd = target.get("uc") or "", target.get("sd") or ""
    else:
        uc, sd = [*list(target), "", ""][:2]
    if not uc:
        return None
    return f"{uc}__{sd}" if sd else str(uc)


def _prose(text: Any) -> str | None:
    """A step's Frist prose, or ``None`` when the source states none.

    ``deadline: "--"`` is how the corpus writes "no Frist" — 554 steps at v0.0.20, more
    than a third of all of them. It is a placeholder in a table cell, not a sentence, and
    passing it through makes the renderer draw `Frist: --` beside the arrow: a Frist
    asserted on every step whose source says there is not one. `lieferbeginn`'s three
    `par` branches showed exactly that.

    Only a dash-run counts. `"1 WT"` is real (2 steps), and so is any prose that merely
    contains a dash.
    """
    cleaned = " ".join(str(text or "").split())
    if not cleaned or set(cleaned) <= {"-", "\u2013", "\u2014"}:
        return None
    return cleaned


def _deadline(step: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """The step's Frist as makrake takes it: the prose, and the structure.

    Both, not either. makrake decides from the *structure* whether the Frist reduces to a
    compact inline tag (``{4WT ÜT#1}``) and shows the *prose* as a note when it does not —
    so dropping either one silently changes what gets drawn.
    """
    raw_rule = step.get("deadline_rule")
    prose = _prose(step.get("deadline"))
    if not raw_rule:
        return prose, None
    rule = raw_rule if isinstance(raw_rule, DeadlineRule) else DeadlineRule.model_validate(raw_rule)
    lifted = deadline_from_rule(rule)
    if lifted is None:
        # `type: "none"` — the source says there is no Frist. Emitting an empty structure
        # would make makrake draw a tag for an obligation that does not exist.
        return prose, None
    # `by_alias` is not used and `exclude_none` is: makrake's Rust model defaults every
    # optional field, and a JSON `null` deserializes into `Option::None` anyway, so the
    # difference is only size — but `raw` has no counterpart in makuna's `Deadline` at all
    # (it lives on the step as `deadline`), so it must not be emitted here.
    structured = lifted.model_dump(mode="json", exclude_none=True, exclude={"raw"})
    return prose or _prose(lifted.raw), structured


def _step(step: dict[str, Any]) -> dict[str, Any]:
    """One step, in makrake's ``Step`` shape."""
    ref = step.get("subprocess_ref")
    prose, structured = _deadline(step)
    out: dict[str, Any] = {
        "number": step.get("nr"),
        "sender": step.get("sender") or "",
        "receiver": step.get("receiver") or "",
        # The `ref ` marker is a rendering instruction the DSL needed inline; makrake has
        # `kind` for it, so the message keeps only what the source says.
        "message": REF_PREFIX.sub("", step.get("message") or "").strip(),
        "kind": _KIND_PROCESS_REF if ref else _KIND_MESSAGE,
        "line": step.get("line") or "solid",
        "arrowhead": step.get("arrowhead") or "open",
    }
    if step.get("format"):
        out["format"] = step["format"]
    pids = _pids(step)
    if pids:
        out["pids"] = pids
    if ref:
        out["subprocess_ref"] = ref
        ref_id = _subprocess_ref_id(step)
        if ref_id:
            out["subprocess_ref_id"] = ref_id
    if prose:
        out["deadline"] = prose
    if structured:
        out["deadline_rule"] = structured
    return out


def _fragment(fragment: dict[str, Any]) -> dict[str, Any]:
    """One combined fragment, recursively. ``branches[].condition`` is makrake's ``guard``."""
    return {
        "type": fragment.get("type"),
        "label": fragment.get("label"),
        "branches": [
            {
                "guard": branch.get("condition"),
                "step_numbers": list(branch.get("step_nrs") or []),
                "fragments": [_fragment(f) for f in (branch.get("fragments") or [])],
            }
            for branch in (fragment.get("branches") or [])
        ],
    }


def makrake_diagram(diagram: dict[str, Any], *, diagram_id: str, name: str) -> dict[str, Any]:
    """One sequence diagram in makrake's ``--input`` shape.

    ``diagram_id`` is the artifact key (:func:`~makoralle.grouping.sd_artifact_key`): it
    becomes the output filename stem and the ``{process_id}`` link placeholder, and its
    ``uc__sd`` split feeds ``{uc}`` / ``{sd}``. ``name`` is drawn as the title.

    Expects each ``subprocess_ref`` step to already carry a resolved ``ref_target``; a step
    without one renders as an unlinked box. Resolution needs every process in scope, so it
    belongs to the caller, not here.
    """
    return {
        "id": diagram_id,
        "name": name,
        "participants": list(diagram.get("participants") or []),
        "steps": [_step(s) for s in (diagram.get("steps") or [])],
        "fragments": [_fragment(f) for f in (diagram.get("fragments") or [])],
        "notes": [
            {
                "position": note.get("position") or "over",
                "participants": list(note.get("participants") or []),
                "text": note.get("text") or "",
                "after_step": note.get("after_step"),
            }
            for note in (diagram.get("notes") or [])
        ],
    }


def canonical_json(payload: Any) -> str:
    """The bytes a diagram's identity is taken over, and what is written to disk.

    Sorted keys and no incidental whitespace, so that the same model always produces the
    same text: this is what an approval's hash is computed from (``webapp_export``), and a
    hash that moved when a dict's insertion order did would clear every "Überprüft" badge
    on a rebuild that changed nothing.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
