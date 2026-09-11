"""Where a record was read from: one edition of a published document (file, date, version, validity window, bytes)."""

import datetime
from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, StringConstraints, model_validator


def _date_to_iso(value: object) -> object:
    """A YAML 1.1 loader reads an unquoted ``2026-01-16`` as a ``date``; take it back as the string."""
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


IsoDate = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), BeforeValidator(_date_to_iso)]


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class SourceDocument(BaseModel):
    """The source file a record was parsed out of — one *edition* of a document.

    ``file_name`` is the published file's own name
    (``EBD_und_Codelisten_4_1_Fehlerkorrektur_20260116.pdf``) and ``date`` the publication date it
    carries, ISO 8601 (``"2026-01-16"``). ``document_version`` is the document's own version
    (``"4.1"``): a Fehlerkorrektur keeps the version and changes the date, so the two answer
    different questions. ``valid_from``/``valid_to`` are the validity window the publisher stamps
    on the edition (edi-energy names encode both; BNetzA Lesefassungen carry neither), and
    ``sha256`` the file's bytes, so a bundle can say exactly which file it was built from.

    Everything but ``file_name`` is optional: records written before makoralle 0.0.23 carry
    only the first two fields, and a BNetzA Lesefassung has no version to give.
    """

    file_name: str
    date: IsoDate | None = None
    document_version: str | None = None
    valid_from: IsoDate | None = None
    valid_to: IsoDate | None = None
    sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _validity_window_is_ordered(self) -> Self:
        # edi-energy names read <name>_<version>_<valid_from>_<valid_to>_…; a swapped pair while parsing one
        # should fail loudly here, not end up as a window that never applies. ISO dates compare correctly as
        # strings, and an open end (9999-12-31) is simply the latest.
        if self.valid_from is not None and self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError(f"valid_from {self.valid_from} is later than valid_to {self.valid_to}")
        return self
