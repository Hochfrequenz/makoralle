"""Pydantic models for Codelisten — the flat answer-code tables of the EBD document.

A Codeliste is what the document ships where a decision *tree* would not fit: the whole
decision is "pick one of these codes". Chapter 8 uses them for the MSB processes
(``S_0056_Ablehnung Anmeldung MSB``), chapter 11 for the Gas ones (``G_0001``), and the
AHB points at them by list id, so a consumer needs the contents to know the admissible
Ablehnungsgründe of a step.
"""

from pydantic import BaseModel

from makoralle.models.source import SourceDocument


class CodeEntry(BaseModel):
    """One row of a Codeliste: the code, how it may be used, and what it means."""

    code: str
    nutzung: str = ""
    bedingung: str | None = None
    name: str
    description: str | None = None
    kind: str = "unknown"


class Codeliste(BaseModel):
    """A full answer-code table: identity/metadata plus its rows.

    ``ebd_id`` and ``ebd_name`` name the EBD section of the document the list sits under —
    ``8.2.1 E_0201_Anmeldung Messstellenbetrieb prüfen`` for ``S_0055``/``S_0056``. A section like
    that holds nothing but its code lists: it has **no decision tree**, so no ``E_*`` file exists
    for ``ebd_id`` and the list itself is the decision. In EBD und Codelisten 4.1 that is true of
    every list with a parent section, so treat ``ebd_id`` as a label, not a link; ``ebd_name`` says
    what the section decides. Both are ``None`` for a list that sits under no EBD section.

    ``format_version`` and ``source_document`` say which Lesefassung the list was read from, as on
    :class:`~makoralle.models.ebd.DecisionTree`.
    """

    id: str
    name: str
    source: str = ""
    ebd_id: str | None = None
    ebd_name: str | None = None
    format_version: str | None = None
    source_document: SourceDocument | None = None
    codes: list[CodeEntry]
