"""Formatversionen: the half-yearly BDEW release bundles.

A *Formatversion* (``FV2604``) is not a document but a bundle: for every document key the parser
knows, the edition that applies. edi-energy documents (EBD, PID, Codelisten) are published per FV;
the BNetzA process descriptions (GPKE, WiM, MaBiS) span several. So a bundle is a *selection* of
editions, declared by hand next to the data it was built from, and the table of bundles says from
which day each one is in force. The dates come from efoli (Hochfrequenz), which encodes them:
FV2504 became valid on 2025-06-06, not 2025-04-01. A hand-written ``gueltig_ab`` that disagrees
with efoli is rejected — to move a date, bump efoli, not this table.
"""

import datetime
import itertools
import json
from pathlib import Path
from typing import Annotated, Self

import yaml
from efoli import EdifactFormatVersion, get_edifact_format_version_valid_from
from pydantic import BaseModel, Field, StringConstraints, model_validator

from makoralle.config import FORMATVERSION_PATTERN
from makoralle.models.source import IsoDate, SourceDocument

Formatversion = Annotated[str, StringConstraints(pattern=FORMATVERSION_PATTERN)]
CategoryLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _efoli_gueltig_ab(fv: str) -> str:
    """The FV's start date as efoli encodes it, as an ISO string.

    Both failure modes are wrapped so the message tells the reader what to do: an FV
    efoli's enum does not know (a future ``FV2704``) and one whose start efoli leaves
    undefined (``FV2104``) both raise ``ValueError`` — makoralle never silently
    tolerates an unknown bundle, because coupling dataset validity to efoli releases
    is the point (makoralle#79).
    """
    try:
        version = EdifactFormatVersion(fv)
    except ValueError as e:
        raise ValueError(f"{fv} is not known to efoli — bump efoli") from e
    try:
        return get_edifact_format_version_valid_from(version).isoformat()
    except KeyError as e:
        # efoli's earliest version (FV2104) has no start date and never will: the map is
        # derived from upper thresholds, and the oldest version has no lower bound. A bump
        # cannot fix it — the table simply must not list it.
        raise ValueError(
            f"{fv}: efoli knows the version but not its start date (efoli never defines one "
            "for its earliest version) — don't list it in the table"
        ) from e


class Bundle(BaseModel):
    """One Formatversion's editions, keyed by makorele document key (``gpke_teil1``, ``ebd`` …).

    Lives at ``<dataset>/<FV>/bundle.yaml``, next to the ``output/`` and ``pipeline/`` it produced,
    so the directory is self-describing and the parser reads it from its own data root.

    ``categories`` is the bundle's category table: for a document key, the category label
    (``GPKE``, ``WiM``, ``MaBiS``, ``Sonstige`` today; a plain string, as ``Process.category`` is)
    the processes cut from that document are meant to get. The dataset declares it per bundle
    (dataset#74); the intended reader is makorele, which is to stamp
    ``process.category = bundle.categories.get(doc_key, "")`` for the document key the use case
    was cut from — nothing in makoralle itself reads the table. A document without an entry
    is meant to give its processes ``""``; a blank label (``mabis: ""``) is rejected, because a
    gate that checks only that the key is present would otherwise let the empty category it is
    there to end survive. An empty table is valid, so every existing ``bundle.yaml`` keeps
    validating; it is spelled ``categories: {}`` — a bare ``categories:`` header is a YAML null
    and is rejected, as a bare ``documents:`` is.
    """

    fv: Formatversion
    documents: dict[str, SourceDocument]
    categories: dict[str, CategoryLabel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _categories_name_documents(self) -> Self:
        """Every key of ``categories`` must be a key of ``documents``.

        The table is looked up by the document key a use case was cut from, so a
        category under a key no document has is dead text that reaches no process — most
        likely a typo (``gpke_teil_2`` for ``gpke_teil2``) that would otherwise leave every
        process of that document with ``""`` and nothing to say why.
        """
        unknown = sorted(set(self.categories) - set(self.documents))
        if unknown:
            raise ValueError(
                f"categories name document keys the bundle does not have: {unknown}; "
                f"its documents are {sorted(self.documents)}"
            )
        return self


class FormatversionEntry(BaseModel):
    """One row of the table: the bundle's name, from when it is in force, and who says so.

    ``gueltig_ab`` is derived from efoli and may be omitted; a hand-written date is
    accepted only where it agrees with efoli, so curation drift cannot happen quietly
    (makoralle#79). ``quelle`` records who listed the bundle — not the date.
    """

    fv: Formatversion
    gueltig_ab: IsoDate | None = None
    quelle: str = ""

    @model_validator(mode="after")
    def _from_efoli(self) -> Self:
        expected = _efoli_gueltig_ab(self.fv)
        if self.gueltig_ab is not None and self.gueltig_ab != expected:
            raise ValueError(
                f"{self.fv}: gueltig_ab {self.gueltig_ab!r} disagrees with efoli ({expected}) — "
                "efoli is the source of truth; bump efoli, not this table"
            )
        # Plain assignment, not a validated one: this model must never enable
        # validate_assignment (the assignment would re-enter this validator and recurse).
        self.__dict__["gueltig_ab"] = expected
        return self


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
        # Entry validation has already normalised every gueltig_ab to efoli's date.
        dates = [b.gueltig_ab for b in self.bundles if b.gueltig_ab is not None]
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
            # The None guard is for unvalidated construction (model_construct/model_copy);
            # entry validation always leaves the date set, as in _consistent above.
            if entry.gueltig_ab is not None and entry.gueltig_ab <= day:
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
