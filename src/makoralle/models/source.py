"""Where a record was read from: the published document, by file and date."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


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
