"""Pydantic models for EBD (Entscheidungsbaum-Diagramm) decision trees.

A tree is closed when every step's branches end somewhere: in another step (``if_yes``/``if_no``),
in an outcome (``*_result``/``*_code``), or -- for a row the document prints with no ja/nein at all
-- in ``next``. A consumer walking the tree as a decision engine can rely on that shape.

Not every ``E_`` id the document names has a tree. The section may hold only code lists, or say
that no tree is needed, or send the reader to another EBD. Those ids still get a ``DecisionTree``,
with ``steps == []`` and a ``kind`` saying which of those it is, so a process's reference to one
resolves to a statement instead of to nothing.
"""

from typing import Literal

from pydantic import BaseModel

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
"""

StepKind = Literal["message_content", "process_history", "external"]
"""What a Prüfschritt examines. Curated by the consumer, never derived: the dataset ships ``None``."""

StepRefKind = Literal["segment", "answer_code", "frist", "date"]


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
    check had been asked. A step with ``next`` set has neither ``if_yes`` nor ``if_no``.

    ``*_sunset`` is the branch's ``Nutzungsmöglichkeit Ende:`` -- when the code stops being usable.
    It is an ISO 8601 local date-time (``"2026-04-01T00:00"``, German legal time) or the literal
    ``"offen"`` where the document says the end is open, and ``None`` where it says nothing.
    """

    nr: int
    check: str
    if_yes: int | None = None
    if_yes_result: str | None = None
    if_yes_code: str | None = None
    if_yes_hint: str | None = None
    if_yes_cluster: str | None = None
    if_yes_sunset: str | None = None
    if_no: int | None = None
    if_no_result: str | None = None
    if_no_code: str | None = None
    if_no_hint: str | None = None
    if_no_cluster: str | None = None
    if_no_sunset: str | None = None
    next: int | None = None
    refs: list[StepRef] | None = None
    kind: StepKind | None = None


class DecisionTree(BaseModel):
    """A full EBD decision tree: identity/metadata plus its ordered decision steps.

    ``kind`` says whether there is a tree at all (see :data:`TreeKind`). Everything but ``tree``
    has ``steps == []``; ``codelisten`` lists the code lists a ``codelist_only`` section holds, in
    document order, ``use_ebd`` names the tree a ``use_other_ebd`` section defers to, and ``note``
    is the section's own sentence, verbatim, for every kind whose body is a sentence.

    ``format_version`` is the document's version (``"4.1"``) and ``source_document`` the file it was
    read from, so a tree can be told apart from the same id in the next Lesefassung.
    """

    id: str
    name: str
    role: str = ""
    source: str = ""
    kind: TreeKind = "tree"
    codelisten: list[str] | None = None
    use_ebd: str | None = None
    note: str | None = None
    format_version: str | None = None
    source_document: SourceDocument | None = None
    steps: list[DecisionStep] = []
