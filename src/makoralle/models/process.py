"""Pydantic models for MaKo processes (use cases, sequence diagrams, and steps)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class DeadlineRule(BaseModel):
    """Structured deadline derived from free-text Frist."""

    type: str  # "unverzüglich", "parallel", "none", "complex",
    # "terminiert" (fixed relative to an external anchor), "reference" (real but
    # irreducible — kept as a note, without a [REVIEW] flag).
    latest_time: str | None = None  # e.g. "07:00"
    business_days: int | None = None  # e.g. 1 for "1. WT"
    reference_step: int | None = None  # step number this deadline is relative to
    reference_event: str | None = None  # "ÜT" (Übertragungstag) or "ÜZ" (Übertragungszeitpunkt)
    direction: Literal["vor", "nach"] | None = None  # WT count before/after the anchor
    anchor: str | None = None  # external anchor when it is not a step ("Änderungstermin", "Zahlungsziel", …)
    recurring: bool = False  # "täglich …" recurring obligation
    #: How often, in the source's own word: "täglich" or "werktäglich". A bool cannot tell the
    #: two apart, and rendering both as "täglich" claims a weekend obligation the source does
    #: not impose — MaBiS's Netzgangzeitreihe says "Werktäglich für den Vortag bzw. Vortage bis
    #: 12:00 Uhr", and two shipped steps read it as a daily duty (makorele#101). Kept beside
    #: ``recurring`` rather than replacing it, so a dataset written before this field still
    #: parses; readers that only ask "is it recurring?" need no change.
    recurrence: str | None = None
    raw: str = ""  # original free-text deadline


#: What the pipeline writes for an endpoint it could not read: neither the step's action
#: text nor Vision named the actor (makorele p08 ``extract_roles_from_action``). It is a
#: placeholder, not a name — every consumer that reasons about actors already skips it,
#: but a serializer that draws a lifeline per actor has no such notion: naming it makes
#: the renderer place a lane called "?" that no participant list declares and that a
#: reader cannot tell from a real actor (makorele#78).
UNKNOWN_ENDPOINT = "?"


def is_known_actor(role: str | None) -> bool:
    """True if ``role`` names an actor rather than standing in for one we could not read.

    Lives beside the fields it judges, because it is a property of the model rather than
    of one output dialect: the WSD and the Mermaid serializer both need the same rule.

    ``"NB"`` is an actor; ``"?"`` and ``""`` are not.
    """
    return bool(role) and role != UNKNOWN_ENDPOINT


#: "ref Aufbereitung …" and "ref: Aktivierung …" — the source tables write the marker both
#: ways, and a check for "ref " alone missed the colon form.
REF_PREFIX = re.compile(r"^ref\b", re.I)


def is_ref_step(message: str | None, subprocess_ref: str | None = None) -> bool:
    """True if the step is a reference to a subprocess rather than a message to an actor.

    Two markers say so and they do not always agree: the parsed ``subprocess_ref``, and a
    message that opens with "ref" as the source tables write it (with a space, a colon or a
    dot). Both serializers read this when deciding what an *unread* endpoint means — a ref's
    other end never named an actor, so it must not become a note about a missing
    counterpart in one output and a self-message in the other.

    The *shape* of a fully readable ref step is a separate question, and the two emitters
    still differ there: WSD draws a self-message for the "ref " form only, Mermaid an arrow
    plus a "Subprocess call" note. 13 shipped steps show the difference. Unifying it would
    reshape 7 arrows whose ref title names their receiver, so it is a decision about the
    diagram rather than a cleanup — makoralle#36.
    """
    return bool(subprocess_ref) or bool(REF_PREFIX.match((message or "").strip()))


class SDStep(BaseModel):
    """A single sequence-diagram step (one message from a sender to a receiver)."""

    nr: int
    sender: str
    receiver: str
    message: str
    format: str | None = None
    description: str = ""
    deadline: str | None = None
    deadline_rule: DeadlineRule | None = None
    ebd_ref: str | None = None
    subprocess_ref: str | None = None  # name of referenced subprocess
    pid_refs: list[int] = []  # linked Prüfidentifikatoren
    # UML message style. `line` is detected from the diagram (solid message /
    # dashed reply). `arrowhead` is derived structurally, not detected: open by
    # default, filled only on a synchronous-call request that immediately precedes
    # a dashed reply (see derive_arrowheads). Hence the open default here.
    line: Literal["solid", "dashed"] = "solid"
    arrowhead: Literal["filled", "open"] = "open"


class SDBranch(BaseModel):
    """One branch of a fragment. alt has >=2 branches; opt/loop/par have one."""

    condition: str | None = None
    step_nrs: list[int] = []
    fragments: list[SDFragment] = []


class SDFragment(BaseModel):
    """A combined fragment (alt/opt/loop/par) grouping one or more branches."""

    type: str  # "alt" | "opt" | "loop" | "par"
    label: str | None = None
    branches: list[SDBranch]


class SDNote(BaseModel):
    """A note annotation attached to one or more participants in a sequence diagram."""

    position: str  # "over" | "left" | "right"
    participants: list[str]
    text: str
    after_step: int | None = None


class SequenceDiagram(BaseModel):
    """A sequence diagram: participants, ordered steps, fragments, and notes."""

    participants: list[str]
    steps: list[SDStep]
    fragments: list[SDFragment] = []
    notes: list[SDNote] = []


class NamedSD(SequenceDiagram):
    """A sequence diagram with its identity within a Use Case."""

    slug: str = ""  # per-UC id, e.g. "vom_nb_verantwortlich_ausgehend"
    name: str | None = None  # switcher label, e.g. "vom NB (verantwortlich) ausgehend"
    source_heading: str | None = None


class UseCase(BaseModel):
    """The use-case description of a process (goal, roles, pre/postconditions)."""

    goal: str
    description: str
    roles: list[str]
    preconditions: list[str] = []
    triggers: list[str] = []
    postconditions_success: list[str] = []
    postconditions_failure: list[str] = []
    additional_requirements: list[str] = []


class CrossReference(BaseModel):
    """A typed reference from one process to another related process."""

    id: str
    relation: str
    description: str = ""


class SourceDocuments(BaseModel):
    """References to the source documents a process was derived from."""

    uc_sd: str | None = None
    ebd: str | None = None
    pid: str | None = None
    ad: str | None = None


class Process(BaseModel):
    """A complete MaKo process: identity, use case, sequence diagrams, and cross-references."""

    id: str
    name: str
    source: str
    category: str
    use_case: UseCase | None = None
    sequence_diagram: SequenceDiagram | None = None
    diagrams: list[NamedSD] = []
    decision_trees: list[Any] = []
    pid_mappings: list[Any] = []
    activity_diagram: dict[str, Any] | None = None
    related_processes: list[CrossReference] = []
    source_documents: SourceDocuments | None = None

    @model_validator(mode="after")
    def _primary_sd(self) -> Process:
        if self.diagrams and self.sequence_diagram is None:
            d = self.diagrams[0]
            self.sequence_diagram = SequenceDiagram(
                participants=d.participants, steps=d.steps, fragments=d.fragments, notes=d.notes
            )
        return self
