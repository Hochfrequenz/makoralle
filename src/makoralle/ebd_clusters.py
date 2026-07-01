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
