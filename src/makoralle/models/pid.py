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
