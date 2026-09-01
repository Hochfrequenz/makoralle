"""The "Prüfung nötig" worklist, computed from the model.

This replaces ``webapp_export.extract_review_notes``, which built the list by
regex-grepping ``[REVIEW]`` out of rendered ``.wsd`` text. Every fact that list
reports is one the model already holds; the round trip through a German note
string and back out of it bought nothing and cost three things:

* **It could only report what someone remembered to encode as a note.** The
  worklist flagged the corpus Fristen nobody has structured, and said nothing
  about the 110 whose structure is present but incomplete (``coverage:
  "partial"``) — the population a conformance suite must refuse to check, and
  the reason :data:`~makoralle.models.deadline.Coverage` exists. Those are now
  :attr:`Severity.UNCHECKABLE`.
* **It could not say which step an entry was about,** because a note is a
  sentence and a sentence carries no step number. ``run`` therefore aggregated a
  process's notes across its diagrams and de-duplicated them *by text* — which
  silently merges two diagrams that state the same Frist on different steps. 27
  entries in the corpus collide that way. An item carries :attr:`ReviewItem.step`
  instead, so nothing has to be guessed and nothing is merged.
* **It made an output dialect's incidental details an API.** ``_REVIEW_RE``
  parsed makoralle's own emitter, so the marker's spelling and the note's word
  order could not change without breaking the webapp.

The severities are deliberately different claims, and conflating them is the
trap this module exists to avoid: :attr:`Severity.STRUCTURE` means *a human must
go structure this*, while :attr:`Severity.UNCHECKABLE` means *a machine cannot
check this*. A ``reference`` Frist is the case that separates them — it is real
but irreducible, pointing at a contract or another table, so it is uncheckable
forever, and putting it on a human's worklist asks for work that cannot be done.
That is also why ``coverage`` alone is not enough to build this list:
``opaque`` covers both the 30 ``complex`` Fristen and the 104 ``reference``
ones, and only the first are anybody's task.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from makoralle.models.deadline import deadline_from_rule
from makoralle.models.process import DeadlineRule, is_known_actor

#: makorele's ``p12_link`` marks a contaminated sequence diagram it could not split
#: automatically with a diagram-level note carrying this marker. Detecting it here is
#: still a string check, but on a *model* note rather than on rendered output — and the
#: note is makorele's own to spell. A boolean on the diagram would be better; that is
#: makorele's call to make, and this reads whichever way it decides.
REVIEW_MARKER = "[REVIEW]"


class Severity(StrEnum):
    """What kind of attention an item wants."""

    #: The pipeline read the source wrongly or incompletely. A defect in the data, not a
    #: property of the process: fixing it means re-parsing or hand-correcting.
    DEFECT = "defect"
    #: Real prose nobody has reduced to structure yet. Actionable by a human who can read
    #: the regulation.
    STRUCTURE = "structure"
    #: Structured, but not completely enough to evaluate — the prose states more than the
    #: structure holds. Nothing to *do*; it is a standing warning that a conformance test
    #: must not treat this obligation as checked.
    UNCHECKABLE = "uncheckable"


#: Most-actionable first. Explicit rather than relying on declaration order, because the
#: sort below is what keeps the exported JSON stable across runs.
_SEVERITY_ORDER = {Severity.DEFECT: 0, Severity.STRUCTURE: 1, Severity.UNCHECKABLE: 2}


class ReviewItem(BaseModel):
    """One entry on the worklist."""

    #: Stable machine-readable discriminator, e.g. ``"deadline_unstructured"``. What a
    #: consumer should branch on; :attr:`text` is for a reader.
    kind: str
    severity: Severity
    #: The step this concerns, or ``None`` for a diagram-level item.
    step: int | None = None
    #: German prose for a reader — the sentence the old ``[REVIEW]`` note carried, without
    #: the marker.
    text: str


def _clean(text: Any) -> str:
    """Collapse whitespace so a multi-line ``raw`` reads as one line."""
    return " ".join(str(text or "").split())


def _deadline_item(step: dict[str, Any]) -> ReviewItem | None:
    """The worklist entry a step's Frist earns, or ``None``.

    Judged on the lifted :class:`~makoralle.models.deadline.Deadline` rather than on the
    flat rule's ``type`` string, so the verdict is made against the structure a consumer
    actually gets — and so ``coverage`` and ``kind`` are read from one place.
    """
    raw_rule = step.get("deadline_rule")
    if not raw_rule:
        return None
    rule = raw_rule if isinstance(raw_rule, DeadlineRule) else DeadlineRule.model_validate(raw_rule)
    deadline = deadline_from_rule(rule)
    if deadline is None:
        return None
    text = _clean(rule.raw) or _clean(step.get("deadline"))
    if not text:
        # A Frist with no prose at all is nothing a reader could act on. The model makes
        # `raw` required, so this is defensive rather than reachable from the corpus.
        return None
    kinds = {a.kind for a in deadline.alternatives}

    if deadline.coverage == "opaque":
        # `reference` is irreducible on purpose — uncheckable, but not a task. `complex` is
        # the task. A conditional Frist mixing the two counts as the task, since the part
        # somebody can structure is the part that matters.
        if kinds == {"reference"}:
            kind, severity = "deadline_reference", Severity.UNCHECKABLE
        else:
            kind, severity = "deadline_unstructured", Severity.STRUCTURE
    elif deadline.coverage == "partial":
        kind, severity = "deadline_partial", Severity.UNCHECKABLE
    else:
        return None
    return ReviewItem(kind=kind, severity=severity, step=step.get("nr"), text=text)


def _endpoint_item(step: dict[str, Any]) -> ReviewItem | None:
    """The worklist entry an unread endpoint earns, or ``None``.

    Deliberately not "Absender"/"Empfänger unbekannt": when two identically labelled
    lifelines collapse into one, which endpoint keeps the surviving role is arbitrary, so
    naming the missing side would state a direction the data cannot support. Same wording
    rule ``emit_wsd``'s note followed, for the same reason.
    """
    known = (is_known_actor(step.get("sender")), is_known_actor(step.get("receiver")))
    if all(known):
        return None
    message = _clean(step.get("message")) or "(ohne Bezeichnung)"
    kind, side = ("endpoint_unread", "Gegenstelle") if any(known) else ("endpoints_unread", "beide Endpunkte")
    return ReviewItem(kind=kind, severity=Severity.DEFECT, step=step.get("nr"), text=f"{message} — {side} ungelesen")


def review_items(diagram: dict[str, Any]) -> list[ReviewItem]:
    """The worklist for one sequence diagram, most-actionable first.

    ``diagram`` is the YAML/JSON mapping form (``participants`` / ``steps`` / ``notes``) —
    what the dataset ships and what ``webapp_export`` reads.
    """
    items: list[ReviewItem] = []
    for note in diagram.get("notes") or []:
        text = _clean(note.get("text") if isinstance(note, dict) else getattr(note, "text", ""))
        if REVIEW_MARKER in text:
            items.append(
                ReviewItem(
                    kind="diagram_unsplit",
                    severity=Severity.DEFECT,
                    text=_clean(text.replace(REVIEW_MARKER, "")),
                )
            )
    for step in diagram.get("steps") or []:
        items.extend(item for item in (_endpoint_item(step), _deadline_item(step)) if item is not None)

    # Sorted rather than grouped: a stable key keeps the exported JSON byte-identical across
    # runs, and within one severity the step number is the reader's own ordering.
    return sorted(items, key=lambda i: (_SEVERITY_ORDER[i.severity], i.step if i.step is not None else -1))
