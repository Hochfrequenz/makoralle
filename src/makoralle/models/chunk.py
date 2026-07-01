"""Pydantic models for parsed source-document chunks (pages, sections, tables)."""

from typing import Literal

from pydantic import BaseModel


class PageInfo(BaseModel):
    """Per-page classification and extracted content of a source document."""

    document: str
    page_number: int
    classification: Literal["text", "table", "diagram", "mixed"]
    has_text: bool = False
    has_table: bool = False
    has_diagram: bool = False
    text_content: str | None = None
    image_path: str | None = None


class Section(BaseModel):
    """A document section identified by heading, level, and page span."""

    document: str
    heading: str
    heading_level: int
    start_page: int
    end_page: int
    content_types: list[str]
    section_id: str | None = None


class TableData(BaseModel):
    """A parsed table (headers + rows) located within a document section."""

    document: str
    section_heading: str
    page_number: int
    headers: list[str]
    rows: list[list[str]]
    table_index: int = 0
    end_page: int | None = None
