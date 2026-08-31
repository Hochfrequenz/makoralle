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
    #: ("GeLi Gas 2.0", "AWH WiM Gas 2.0", "Marktraumumstellung", …). This is the
    #: authoritative sparte signal — the workbook's own "Sparte Strom"/"Sparte Gas"
    #: markers are Excel formulas derived FROM this column, not independent data.
    prozessbeschreibung: str | None = None
    #: The workbook's derived "Sparte Strom" / "Sparte Gas" markers, as read. Kept
    #: separate rather than folded into one enum because a row can carry both, and
    #: `None` (column absent from this workbook layout) is not the same claim as
    #: `False` (column present and unset). See :attr:`sparten` for the usable view.
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

        Empty means "not known from this row" — either the workbook layout carried no
        Sparte columns, or both were unset. Callers scoping PIDs to a process must treat
        an empty set as *unscoped*, never as "applies to neither": silently dropping
        every row of an older workbook would be a far worse failure than the leak this
        field exists to stop (makorele#165).
        """
        return frozenset(name for name, flag in (("Strom", self.sparte_strom), ("Gas", self.sparte_gas)) if flag)
