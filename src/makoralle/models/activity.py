"""Pydantic models for activity diagrams (nodes, edges, and the diagram itself)."""

from typing import Literal

from pydantic import BaseModel


class ADNode(BaseModel):
    """A single activity-diagram node (start/end/action/decision/…)."""

    id: str
    type: Literal["start", "end", "action", "decision", "fork", "join", "merge", "signal", "ebd_reference"]
    role: str | None = None
    label: str | None = None


class ADEdge(BaseModel):
    """A directed edge between two activity-diagram nodes, with an optional condition."""

    source: str
    target: str
    condition: str | None = None


class ActivityDiagram(BaseModel):
    """An activity diagram: its participants plus its nodes and edges."""

    participants: list[str]
    nodes: list[ADNode]
    edges: list[ADEdge]
