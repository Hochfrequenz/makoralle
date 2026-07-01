"""Pydantic models for MaKo processes (use cases, sequence diagrams, and steps)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator


class DeadlineRule(BaseModel):
    """Structured deadline derived from free-text Frist."""

    type: str  # "unverzüglich", "parallel", "none", "complex"
    latest_time: str | None = None  # e.g. "07:00"
    business_days: int | None = None  # e.g. 1 for "1. WT"
    reference_step: int | None = None  # step number this deadline is relative to
    reference_event: str | None = None  # "ÜT" (Übertragungstag) or "ÜZ" (Übertragungszeitpunkt)
    raw: str = ""  # original free-text deadline


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
    def _primary_sd(self) -> "Process":
        if self.diagrams and self.sequence_diagram is None:
            d = self.diagrams[0]
            self.sequence_diagram = SequenceDiagram(
                participants=d.participants, steps=d.steps, fragments=d.fragments, notes=d.notes
            )
        return self
