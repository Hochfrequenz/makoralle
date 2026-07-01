"""Pydantic models for EBD (Entscheidungsbaum-Diagramm) decision trees."""

from pydantic import BaseModel


class DecisionStep(BaseModel):
    """One decision-tree step: a check plus its yes/no outcomes (next step or code)."""

    nr: int
    check: str
    if_yes: int | None = None
    if_yes_result: str | None = None
    if_yes_code: str | None = None
    if_yes_hint: str | None = None
    if_yes_cluster: str | None = None
    if_no: int | None = None
    if_no_result: str | None = None
    if_no_code: str | None = None
    if_no_hint: str | None = None
    if_no_cluster: str | None = None


class DecisionTree(BaseModel):
    """A full EBD decision tree: identity/metadata plus its ordered decision steps."""

    id: str
    name: str
    role: str = ""
    source: str = ""
    steps: list[DecisionStep]
