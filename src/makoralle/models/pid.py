"""Pydantic model for a Prüfidentifikator (PID) mapping row from the AHB."""

# Several attribute names are German domain terms that carry non-ASCII characters
# (ü, ä); renaming them would break the mapping to the source columns.
# pylint: disable=non-ascii-name

from typing import Literal

from pydantic import BaseModel


class PIDMapping(BaseModel):
    """One AHB Prüfidentifikator mapping row (PID → communication / process metadata)."""

    lfd_nr: int
    ahb: str
    anwendungsfall: str
    prüfidentifikator: int
    reaktion_auf_prüfidentifikator: str | None = None
    #: Column 5: the BDEW document a row belongs to ("GeLi Gas 2.0", "AWH WiM Gas 2.0",
    #: "Marktraumumstellung", …). Named to parallel :attr:`prozessbeschreibung_kapitel`,
    #: the NEXT column, which holds a chapter reference rather than a document name — the
    #: two are easy to confuse.
    #:
    #: Reported (PID 4.0 workbook) to be what the Sparte columns are computed from, which
    #: would make it the authoritative signal and them a derived view. That workbook is not
    #: pinned by this toolchain and arrives out-of-band, so this repo cannot check it.
    prozessbeschreibung_dokument: str | None = None
    prozessbeschreibung_kapitel: str | None = None
    bezeichnung_sequenzdiagramm: str | None = None
    prozessschritt_sequenzdiagramm: int | None = None  # SD step number (col I)
    aktion: str | None = None
    kommunikation_von: str | None = None
    kommunikation_an: str | None = None
    zuordnung_objekt: str | None = None
    zuordnung_geschäftsvorfall: str | None = None
    erweiterte_zuordnung: str | None = None
    objekteigenschaft: str | None = None
    #: The workbook's Sparte markers (reported as headed "Sparte Strom"/"Sparte Gas";
    #: makorele's column comment only labels them "Strom"/"Gas", so the exact heading is
    #: unverified here). Reported to hold "X"/"--" — pydantic coerces neither, nor "", so a
    #: parser must map them explicitly and should reject an unexpected marker loudly rather
    #: than default it to ``False``.
    #:
    #: An absent or empty cell MUST map to ``None``, never ``False``. ``False`` asserts that
    #: the workbook recorded a Sparte column and left it unmarked; a positional reader that
    #: returns "" for a column past the end of the row would otherwise make
    #: :attr:`sparte_recorded` claim a layout that is not there.
    #:
    #: Two fields rather than one enum because ``None`` (not recorded) and ``False``
    #: (recorded, unmarked) are different claims and no enum expresses both. See
    #: :attr:`sparten` for the usable view.
    sparte_strom: bool | None = None
    sparte_gas: bool | None = None
    übertragungsweg: str | None = None
    api_kennung: str | None = None

    # @property, deliberately NOT pydantic's computed_field: a computed field lands in
    # `model_dump()`, and this change's whole compatibility argument — that it adds nothing
    # to the ~905 serialized PID rows in the dataset — depends on these staying out of it.
    # `test_pid_mapping_serialization_is_unchanged_for_rows_without_sparte` pins that.
    @property
    def sparten(self) -> frozenset[Literal["Strom", "Gas"]]:
        """The Sparten this row applies to: ``{"Strom"}``, ``{"Gas"}``, both, or empty.

        Empty deliberately conflates "the workbook had no Sparte columns" with "it had
        them and marked neither" — both mean *this row makes no usable sparte claim*, and
        a caller scoping PIDs must treat both as **unscoped** rather than as "applies to
        neither". Silently dropping every row of an older workbook layout would be a far
        worse failure than the leak this field exists to stop (makorele#165).

        Use :attr:`sparte_recorded` when the two cases must be told apart — e.g. to warn
        that a workbook carried no sparte information at all.
        """
        pairs: tuple[tuple[Literal["Strom", "Gas"], bool | None], ...] = (
            ("Strom", self.sparte_strom),
            ("Gas", self.sparte_gas),
        )
        return frozenset(name for name, flag in pairs if flag)

    @property
    def sparte_recorded(self) -> bool:
        """Whether this row carried the Sparte columns at all.

        The distinction :attr:`sparten` collapses. ``False`` means *this row* carries
        neither marker — and with a parser that maps an absent column to ``None`` (see the
        field comment, which the model cannot enforce), that is the per-row signal a caller
        aggregates to conclude the layout carried no Sparte columns at all. It is not by
        itself a statement about the workbook.
        """
        return self.sparte_strom is not None or self.sparte_gas is not None
