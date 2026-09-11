"""Where a record was read from: the published document, by file and date."""

import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, StringConstraints


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
