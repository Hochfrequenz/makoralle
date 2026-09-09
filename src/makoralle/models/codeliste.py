"""Pydantic models for Codelisten — the flat answer-code tables of the EBD document.

A Codeliste is what the document ships where a decision *tree* would not fit: the whole
decision is "pick one of these codes". Chapter 8 uses them for the MSB processes
(``S_0056_Ablehnung Anmeldung MSB``), chapter 11 for the Gas ones (``G_0001``), and the
AHB points at them by list id, so a consumer needs the contents to know the admissible
Ablehnungsgründe of a step.
"""

from pydantic import BaseModel


class CodeEntry(BaseModel):
    """One row of a Codeliste: the code, how it may be used, and what it means."""

    code: str
    nutzung: str = ""
    bedingung: str | None = None
    name: str
    description: str | None = None
    kind: str = "unknown"


class Codeliste(BaseModel):
    """A full answer-code table: identity/metadata plus its rows."""

    id: str
    name: str
    source: str = ""
    ebd_id: str | None = None
    codes: list[CodeEntry]
