"""Cluster vocabulary used in EBD Hinweis cells.

The EBD PDF tags every coded outcome in the Hinweis column with a
`Cluster: <Word>` prefix that classifies the outcome (approval, rejection,
info, etc.). This module lifts that prefix into structured fields and maps
the German cluster vocabulary to a small consumer-facing `kind` enum.
"""

import re
from typing import Any

CLUSTER_KIND: dict[str, str] = {
    # rejection
    "Ablehnung auf Kopfebene": "rejection",
    "Ablehnung auf Positionsebene": "rejection",
    "Ablehnung auf Summenebene": "rejection",
    "Ablehnung der gesamten Liste": "rejection",
    "Ablehnung": "rejection",
    "Abweisung": "rejection",
    "gescheitert": "rejection",
    # approval
    "Zustimmung": "approval",
    "erfolgreich": "approval",
    # info
    "Änderung der Daten": "info",
    "keine Änderung der Daten": "info",
    "Keine Änderung der Daten": "info",
    "Korrekturliste wegen Ablehnung": "info",
}

_CLUSTER_PREFIX = re.compile(r"^\s*Cluster:\s*(.*)$", re.DOTALL)
# Precompute sorted-by-length-desc for longest-prefix matching
_KNOWN_CLUSTERS = sorted(CLUSTER_KIND.keys(), key=len, reverse=True)


def extract_cluster(hint: str | None) -> tuple[str | None, str | None]:
    """Split a hint string into (cluster, cleaned_hint).

    Returns (None, hint) if there is no `Cluster:` prefix or if the text
    after `Cluster:` does not start with a known cluster name.
    Whitespace and the prefix are stripped from the returned hint.
    """
    if hint is None:
        return None, None
    m = _CLUSTER_PREFIX.match(hint)
    if not m:
        return None, hint
    body = m.group(1)
    for name in _KNOWN_CLUSTERS:
        if body.startswith(name):
            end = len(name)
            # Require word boundary: end of string, whitespace, or punctuation
            if end == len(body) or body[end] in " \n\t.,:":
                rest = body[end:].lstrip(" \n\t.,:")
                return name, rest
    return None, hint


def cluster_to_kind(cluster: str | None) -> str:
    """Map a cluster string to {approval, rejection, info, unknown}."""
    if cluster is None:
        return "unknown"
    return CLUSTER_KIND.get(cluster, "unknown")


# EBDs where the source PDF omits the `Cluster:` prefix from Hinweis cells.
# Observed on REMADV-response EBDs (Storno verarbeiten, Prüfen ob Antwort auf
# Stornierung erforderlich, erneut Rechnung … prüfen) — BDEW authors these
# tables without the cluster classifier, even though the referencing REMADV-AHB
# treats every answer code on these EBDs as `Ablehnung auf Kopfebene` and
# conditions like [14]/[15]/[16]/[517]/[518] depend on it. We backfill the
# classifier so downstream consumers (edifact_mapper) can resolve those
# conditions instead of returning `unknown`.
EBD_CLUSTER_BACKFILL: dict[str, str] = {
    "E_0243": "Ablehnung auf Kopfebene",
    "E_0261": "Ablehnung auf Kopfebene",
    "E_0272": "Ablehnung auf Kopfebene",
    "E_0275": "Ablehnung auf Kopfebene",
    "E_0459": "Ablehnung auf Kopfebene",
    "E_0505": "Ablehnung auf Kopfebene",
    "E_0506": "Ablehnung auf Kopfebene",
    "E_0518": "Ablehnung auf Kopfebene",
    "E_0522": "Ablehnung auf Kopfebene",
    "E_0569": "Ablehnung auf Kopfebene",
    "E_0804": "Ablehnung auf Kopfebene",
    "E_0806": "Ablehnung auf Kopfebene",
}


def backfill_cluster(ebd_id: str, step: dict[str, Any]) -> None:
    """Assign the REMADV fallback cluster to any code-bearing branch that
    has no structured cluster. Mutates the step dict in place.

    No-op for EBDs that are not in `EBD_CLUSTER_BACKFILL` or for branches
    that already carry a cluster extracted from the hint.
    """
    cluster = EBD_CLUSTER_BACKFILL.get(ebd_id)
    if cluster is None:
        return
    for branch in ("if_yes", "if_no"):
        if step.get(f"{branch}_code") and not step.get(f"{branch}_cluster"):
            step[f"{branch}_cluster"] = cluster


# Leading words that classify a Codeliste row or a whole Codeliste. A code list carries no
# `Cluster:` prefix — the classification is in the German wording instead, and the same
# vocabulary as CLUSTER_KIND applies, so the two cannot drift apart on what "Ablehnung" means.
CODE_WORD_KIND: dict[str, str] = {
    "Ablehnung": "rejection",
    "Abweisung": "rejection",
    "Ablehnen": "rejection",
    "Zustimmung": "approval",
    "Bestätigung": "approval",
    "Fortführungsbestätigung": "approval",
    "Bestellbestätigung": "approval",
    "Statusmeldung": "info",
    "Mitteilung": "info",
    "Ankündigung": "info",
    "Antwort": "info",
}
_CODE_WORDS = sorted(CODE_WORD_KIND, key=len, reverse=True)


def _kind_from_wording(text: str | None) -> str | None:
    """The kind a German label announces, or None if it announces nothing."""
    if not text:
        return None
    for word in _CODE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return CODE_WORD_KIND[word]
    return None


def derive_code_kind(entry_name: str | None, list_name: str | None = None) -> str:
    """Classify one Codeliste row as {approval, rejection, info, unknown}.

    The row's own wording wins, so an `Ablehnung …` row inside a Bestätigung list is still
    a rejection. A row that says nothing either way inherits the list's wording: `ZB6
    Erforderliche Versicherung fehlt` is a rejection because it can only appear in
    `S_0056_Ablehnung Anmeldung MSB`.
    """
    return _kind_from_wording(entry_name) or _kind_from_wording(list_name) or "unknown"
