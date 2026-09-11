"""Formatversionen: the half-yearly BDEW release bundles.

A *Formatversion* (``FV2604``) is not a document but a bundle: for every document key the parser
knows, the edition that applies. edi-energy documents (EBD, PID, Codelisten) are published per FV;
the BNetzA process descriptions (GPKE, WiM, MaBiS) span several. So a bundle is a *selection* of
editions, declared by hand next to the data it was built from, and the table of bundles says from
which day each one is in force. The dates are curated, not derived from the name: FV2504 started on
2025-06-06, not 2025-04-01.
"""

import datetime
import itertools
import json
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, StringConstraints, model_validator

from makoralle.models.source import IsoDate, SourceDocument

Formatversion = Annotated[str, StringConstraints(pattern=r"^FV\d{4}$")]


class Bundle(BaseModel):
    """One Formatversion's editions, keyed by makorele document key (``gpke_teil1``, ``ebd`` …).

    Lives at ``<dataset>/<FV>/bundle.yaml``, next to the ``output/`` and ``pipeline/`` it produced,
    so the directory is self-describing and the parser reads it from its own data root.
    """

    fv: Formatversion
    documents: dict[str, SourceDocument]


class FormatversionEntry(BaseModel):
    """One row of the table: the bundle's name, from when it is in force, and who says so."""

    fv: Formatversion
    gueltig_ab: IsoDate
    quelle: str = ""


class Formatversionen(BaseModel):
    """The table of bundles a dataset snapshot holds (``<dataset>/formatversionen.yaml``).

    ``default`` is the bundle the dataset's ``output`` symlink points at, for consumers that read
    one corpus and do not choose. The app chooses by date instead (:meth:`in_force`).
    """

    default: Formatversion
    bundles: list[FormatversionEntry]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        names = [b.fv for b in self.bundles]
        if len(set(names)) != len(names):
            raise ValueError("a Formatversion is listed twice")
        dates = [b.gueltig_ab for b in self.bundles]
        if any(a >= b for a, b in itertools.pairwise(dates)):
            raise ValueError("bundles must be sorted by gueltig_ab, no two on the same day")
        # Also rejects an empty table, which would leave in_force nothing to return.
        if self.default not in names:
            raise ValueError(f"default {self.default!r} is not one of the bundles {names}")
        return self

    def in_force(self, on: datetime.date | None = None) -> Formatversion:
        """The newest bundle whose ``gueltig_ab`` is on or before ``on`` (today when omitted).

        Before the first ``gueltig_ab`` there is nothing older to show, so the oldest bundle is it.
        """
        day = (on or datetime.date.today()).isoformat()
        current = self.bundles[0].fv
        for entry in self.bundles:
            if entry.gueltig_ab <= day:
                current = entry.fv
        return current


def load_formatversionen(path: Path) -> Formatversionen:
    """Read and validate a ``formatversionen.yaml`` table."""
    return Formatversionen.model_validate(yaml.safe_load(path.read_text("utf-8")) or {})


def load_bundle(path: Path) -> Bundle:
    """Read and validate one Formatversion's ``bundle.yaml``."""
    return Bundle.model_validate(yaml.safe_load(path.read_text("utf-8")) or {})


def write_json(model: BaseModel, dest: Path) -> None:
    """Write the model as JSON with None fields left out: the twin the stdlib-only app build reads."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json", exclude_none=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8", newline="\n")
