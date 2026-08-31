"""Pydantic model for a Prüfidentifikator (PID) mapping row from the AHB."""

# Several attribute names are German domain terms that carry non-ASCII characters
# (ü, ä); renaming them would break the mapping to the source columns.
# pylint: disable=non-ascii-name

from pydantic import BaseModel


class PIDMapping(BaseModel):
    """One AHB Prüfidentifikator mapping row (PID → communication / process metadata)."""

    lfd_nr: int
    ahb: str
    anwendungsfall: str
    #: Column 5 of the PID workbook, verbatim: the BDEW document a row belongs to
    #: ("GeLi Gas 2.0", "AWH WiM Gas 2.0", "Marktraumumstellung", …). Named to parallel
    #: :attr:`prozessbeschreibung_kapitel`, which is the NEXT column (6) and holds a
    #: chapter reference, not a document name — the two are easy to confuse.
    #:
    #: Per the PID 4.0 workbook this is what the "Sparte Strom"/"Sparte Gas" columns are
    #: computed from, which would make it the authoritative signal and them a derived
    #: view. That workbook is not pinned by this toolchain and arrives out-of-band, so
    #: this repo cannot check the claim — treat it as reported, not verified.
    prozessbeschreibung_dokument: str | None = None
    #: The workbook's "Sparte Strom" / "Sparte Gas" markers. Two fields rather than one
    #: enum because a row can carry both. Note the cells hold "X"/"--", which pydantic
    #: will NOT coerce to bool — a parser must map them explicitly or validation fails.
    #: :attr:`sparten` is the usable view; :attr:`sparte_recorded` says whether the row
    #: carried the columns at all.
    sparte_strom: bool | None = None
    sparte_gas: bool | None = None
    prüfidentifikator: int
    reaktion_auf_prüfidentifikator: str | None = None
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
    übertragungsweg: str | None = None
    api_kennung: str | None = None

    @property
    def sparten(self) -> frozenset[str]:
        """The Sparten this row applies to: ``{"Strom"}``, ``{"Gas"}``, both, or empty.

        Empty deliberately conflates "the workbook had no Sparte columns" with "it had
        them and marked neither" — both mean *this row makes no usable sparte claim*, and
        a caller scoping PIDs must treat both as **unscoped** rather than as "applies to
        neither". Silently dropping every row of an older workbook layout would be a far
        worse failure than the leak this field exists to stop (makorele#165).

        Use :attr:`sparte_recorded` when the two cases must be told apart — e.g. to warn
        that a workbook carried no sparte information at all.
        """
        return frozenset(name for name, flag in (("Strom", self.sparte_strom), ("Gas", self.sparte_gas)) if flag)

    @property
    def sparte_recorded(self) -> bool:
        """Whether this row carried the Sparte columns at all.

        The distinction :attr:`sparten` collapses: ``False`` means the workbook layout had
        no such columns, so a caller cannot conclude anything about sparte and should say
        so loudly rather than scope on silence.
        """
        return self.sparte_strom is not None or self.sparte_gas is not None
