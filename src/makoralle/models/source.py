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


class SourceDocument(BaseModel):
    """The source file a record was parsed out of.

    ``file_name`` is the published file's own name
    (``EBD_und_Codelisten_4_1_Fehlerkorrektur_20260116.pdf``) and ``date`` the publication date it
    carries, ISO 8601 (``"2026-01-16"``). The version number is the record's own ``format_version``,
    not repeated here: a Fehlerkorrektur keeps the version and changes the date, so the two answer
    different questions.
    """

    file_name: str
    date: IsoDate | None = None
