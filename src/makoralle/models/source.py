"""Where a record was read from: the published document, by file and date."""

from pydantic import BaseModel


class SourceDocument(BaseModel):
    """The source file a record was parsed out of.

    ``file_name`` is the published file's own name
    (``EBD_und_Codelisten_4_1_Fehlerkorrektur_20260116.pdf``) and ``date`` the publication date it
    carries, ISO 8601 (``"2026-01-16"``). The version number is the record's own ``format_version``,
    not repeated here: a Fehlerkorrektur keeps the version and changes the date, so the two answer
    different questions.
    """

    file_name: str
    date: str | None = None
