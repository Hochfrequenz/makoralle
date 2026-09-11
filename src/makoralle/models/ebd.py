"""Pydantic models for EBD (Entscheidungsbaum-Diagramm) decision trees.

A tree is closed when every step's branches end somewhere: in another step (``if_yes``/``if_no``),
in an outcome (``*_result``/``*_code``), or -- for a row the document prints with no ja/nein at all
-- in ``next``. A consumer walking the tree as a decision engine can rely on that shape.

Not every ``E_`` id the document names has a tree. The section may hold only code lists, or say
that no tree is needed, or send the reader to another EBD. Those ids still get a ``DecisionTree``,
with ``steps == []`` and a ``kind`` saying which of those it is, so a process's reference to one
resolves to a statement instead of to nothing.
"""

import warnings
from typing import Annotated, Literal, Self

from pydantic import AliasChoices, BaseModel, Field, StringConstraints, model_validator

from makoralle.models.formatversion import Formatversion
from makoralle.models.source import SourceDocument

TreeKind = Literal[
    "tree",
    "codelist_only",
    "no_tree_aperak",
    "no_tree_no_answer",
    "use_other_ebd",
    "codelist_in_format",
    "unclassified",
]
"""What an ``E_`` section holds, as its own body text says.

* ``tree`` -- a Prüfschritt table; ``steps`` is the tree.
* ``codelist_only`` -- the decision is a choice of code from the lists under the section
  (``8.2.1 E_0201`` holds ``S_0055``/``S_0056``); ``DecisionTree.codelisten`` names them.
* ``no_tree_aperak`` -- "Derzeit ist für diese Entscheidung kein Entscheidungsbaum notwendig, da die
  Ablehnung über eine APERAK erfolgt." (E_0031, E_0032, E_0033).
* ``no_tree_no_answer`` -- the same sentence ending "…, da keine Antwort gegeben wird." (E_0005,
  E_0621): nobody answers, so there is nothing to decide.
* ``use_other_ebd`` -- "Es ist das EBD E_0539 zu nutzen." (E_0541); ``DecisionTree.use_ebd`` is the
  id to follow.
* ``codelist_in_format`` -- "Diese Codeliste befindet sich noch im Datenformat." (E_0217): the codes
  are in the EDIFACT format documentation, not in this document.
* ``unclassified`` -- a section with no tree whose body matches none of the above. It is emitted
  rather than guessed at, and ``note`` carries whatever text there is.

A consumer on an older makoralle refuses a kind it does not know, so a parser meeting a new sentence
says ``unclassified`` rather than inventing a value.
"""

StepKind = Literal["message_content", "process_history", "external"]
"""What a Prüfschritt examines. Curated by the consumer, never derived: the dataset ships ``None``."""

StepRefKind = Literal["segment", "answer_code", "frist", "date"]

BRANCH_FIELDS = tuple(
    f"{branch}{part}"
    for branch in ("if_yes", "if_no")
    for part in ("", "_result", "_code", "_hint", "_cluster", "_sunset")
)
"""Every field a ja/nein branch of a :class:`DecisionStep` carries."""

Sunset = Annotated[str, StringConstraints(pattern=r"^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}|offen)$")]
"""When a code stops being usable: ISO 8601 local date-time (``"2026-04-01T00:00"``) or ``"offen"``.

The document prints ``01.04.2026 00:00 Uhr`` and ``01.04.2026, 00:00 Uhr``; the pattern refuses both,
so a parser that forgets to normalise fails loudly instead of shipping two spellings. It is a string
and not a ``datetime`` because the parser writes ``json.dumps(record.model_dump())``.
"""


class StepRef(BaseModel):
    """One thing a Prüfschritt's text names, found by pattern and quoted verbatim.

    ``segment`` is an EDIFACT segment with its qualifiers (``SG4 STS+7++E02``), ``answer_code`` an
    answer code (``A30``), ``frist`` a deadline phrase (``10 WT``, ``Vorlauffrist``), ``date`` a
    calendar date (``01.04.2026``). The pattern finds them; it does not interpret them -- ``text``
    is the source's own wording, and a consumer building predicates starts from that.
    """

    kind: StepRefKind
    text: str


class DecisionStep(BaseModel):
    """One decision-tree step: a check plus its yes/no outcomes (next step or code).

    ``*_result`` is a closed set: a cluster word from the Hinweis column (``Ablehnung``,
    ``Zustimmung``, ``Ablehnung auf Kopfebene``, …, the vocabulary of
    :data:`makoralle.ebd_clusters.CLUSTER_KIND`), ``"Ende"`` for a leaf the document prints as
    ``ja → Ende`` without a cluster, ``"Aktion"`` for a leaf whose only content is an instruction
    in the Hinweis column (E_0544 step 20 ``nein``: "Übersicht der Zählzeitdefinition versenden"),
    or ``None`` -- a coded branch whose Hinweis names no cluster, or a branch the document does not
    print at all.

    ``next`` is for the rows that have no ja/nein at all -- E_0594's Trefferliste runs
    ``105 [Adressprüfung] → 110`` -- so the target is not written into both branches as if the
    check had been asked. A step with ``next`` set carries nothing on either branch -- no target,
    result, code, hint, cluster or sunset -- and ``next_hint`` is what the Hinweis column says beside
    such a row ("Aufnahme von 0..n Treffern in die Trefferliste auf Basis eines Kriteriums"); both
    are enforced.

    ``*_sunset`` is the branch's ``Nutzungsmöglichkeit Ende:`` (see :data:`Sunset`), and ``None``
    where the document says nothing.
    """

    nr: int
    check: str
    if_yes: int | None = None
    if_yes_result: str | None = None
    if_yes_code: str | None = None
    if_yes_hint: str | None = None
    if_yes_cluster: str | None = None
    if_yes_sunset: Sunset | None = None
    if_no: int | None = None
    if_no_result: str | None = None
    if_no_code: str | None = None
    if_no_hint: str | None = None
    if_no_cluster: str | None = None
    if_no_sunset: Sunset | None = None
    next: int | None = None
    next_hint: str | None = None
    refs: list[StepRef] | None = None
    kind: StepKind | None = None

    @model_validator(mode="after")
    def _next_stands_alone(self) -> Self:
        if self.next is not None and any(getattr(self, field) is not None for field in BRANCH_FIELDS):
            raise ValueError(f"step {self.nr}: 'next' excludes everything on 'if_yes'/'if_no'")
        if self.next_hint is not None and self.next is None:
            raise ValueError(f"step {self.nr}: 'next_hint' needs 'next'")
        return self


class DecisionTree(BaseModel):
    """A full EBD decision tree: identity/metadata plus its ordered decision steps.

    ``kind`` says whether there is a tree at all (see :data:`TreeKind`). Everything but ``tree``
    has ``steps == []``; ``codelisten`` lists the code lists a ``codelist_only`` section holds, in
    document order, ``use_ebd`` names the tree a ``use_other_ebd`` section defers to, and ``note``
    is the section's own sentence, verbatim, for every kind whose body is a sentence. ``use_ebd`` and
    ``codelisten`` belong to their own kind only, and that kind cannot do without its field -- a
    ``use_other_ebd`` stub pointing nowhere is not a statement; both are enforced. ``note`` is not
    restricted.

    ``document_version`` is the document's version (``"4.1"``), ``formatversion`` the BDEW
    Formatversion it was bundled for (``"FV2604"``), and ``source_document`` the file it was read
    from, so a tree can be told apart from the same id in the next Lesefassung. Where both
    ``document_version`` and ``source_document.document_version`` are set they must agree.
    """

    id: str
    name: str
    role: str = ""
    source: str = ""
    kind: TreeKind = "tree"
    codelisten: list[str] | None = None
    use_ebd: str | None = None
    note: str | None = None
    # The document's own version ("4.1"). Was `format_version` until 0.0.23 -- kept as an input
    # alias for one release because every committed record spells it that way.
    document_version: str | None = Field(
        default=None, validation_alias=AliasChoices("document_version", "format_version")
    )
    # The BDEW Formatversion the bundle was built for ("FV2604"). None for records parsed
    # outside a bundle (a bare `makorele run-docs` with no bundle.yaml).
    formatversion: Formatversion | None = None
    source_document: SourceDocument | None = None
    steps: list[DecisionStep] = []

    @property
    def format_version(self) -> str | None:
        """Deprecated spelling of :attr:`document_version`; removed in 0.0.24."""
        warnings.warn("DecisionTree.format_version is now document_version", DeprecationWarning, stacklevel=2)
        return self.document_version

    @model_validator(mode="after")
    def _versions_agree(self) -> Self:
        # The edition carries its version since 0.0.23; the record repeats it, so nothing else keeps the two in step.
        edition = self.source_document.document_version if self.source_document is not None else None
        if self.document_version is not None and edition is not None and self.document_version != edition:
            raise ValueError(
                f"{self.id}: document_version {self.document_version!r} disagrees with "
                f"source_document.document_version {edition!r}"
            )
        return self

    @model_validator(mode="after")
    def _a_stub_is_a_statement(self) -> Self:
        if self.kind != "tree" and self.steps:
            raise ValueError(f"{self.id}: a {self.kind!r} section has no steps")
        if self.use_ebd is not None and self.kind != "use_other_ebd":
            raise ValueError(f"{self.id}: 'use_ebd' belongs to kind 'use_other_ebd', not {self.kind!r}")
        if self.codelisten is not None and self.kind != "codelist_only":
            raise ValueError(f"{self.id}: 'codelisten' belongs to kind 'codelist_only', not {self.kind!r}")
        # After the ownership checks, so a field on the wrong kind reports that rather than this.
        if self.kind == "use_other_ebd" and not self.use_ebd:
            raise ValueError(f"{self.id}: a 'use_other_ebd' section names the EBD to use in 'use_ebd'")
        if self.kind == "codelist_only" and not self.codelisten:
            raise ValueError(f"{self.id}: a 'codelist_only' section names its lists in 'codelisten'")
        return self
