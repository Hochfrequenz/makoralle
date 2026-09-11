"""Pydantic models for Codelisten — the flat answer-code tables of the EBD document.

A Codeliste is what the document ships where a decision *tree* would not fit: the whole
decision is "pick one of these codes". Chapter 8 uses them for the MSB processes
(``S_0056_Ablehnung Anmeldung MSB``), chapter 11 for the Gas ones (``G_0001``), and the
AHB points at them by list id, so a consumer needs the contents to know the admissible
Ablehnungsgründe of a step.
"""

import warnings
from typing import Self

from pydantic import AliasChoices, BaseModel, Field, model_validator

from makoralle.models.formatversion import Formatversion
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

    ``document_version`` is the document's version (``"4.1"``), ``formatversion`` the BDEW
    Formatversion it was bundled for (``"FV2604"``), and ``source_document`` the file it was read
    from, as on :class:`~makoralle.models.ebd.DecisionTree`; ``document_version`` must agree with
    ``source_document.document_version`` where both are set.
    """

    id: str
    name: str
    source: str = ""
    ebd_id: str | None = None
    ebd_name: str | None = None
    # The document's own version ("4.1"). Was `format_version` until 0.0.23 -- kept as an input
    # alias for one release because every committed record spells it that way.
    document_version: str | None = Field(
        default=None, validation_alias=AliasChoices("document_version", "format_version")
    )
    # The BDEW Formatversion the bundle was built for ("FV2604"). None for records parsed
    # outside a bundle (a bare `makorele run-docs` with no bundle.yaml).
    formatversion: Formatversion | None = None
    source_document: SourceDocument | None = None
    codes: list[CodeEntry]

    @property
    def format_version(self) -> str | None:
        """Deprecated spelling of :attr:`document_version`; scheduled for removal in 0.0.24."""
        warnings.warn("Codeliste.format_version is now document_version", DeprecationWarning, stacklevel=2)
        return self.document_version

    @model_validator(mode="after")
    def _versions_agree(self) -> Self:
        # The edition carries its version since 0.0.23; the record repeats it, so nothing else keeps the two in step.
        edition = self.source_document.document_version if self.source_document is not None else None
        if self.document_version is not None and edition is not None and self.document_version != edition:
            raise ValueError(
                f"{self.id}: document_version {self.document_version!r} disagrees with "
                f"source_document.document_version {edition!r}"
            )
        return self
