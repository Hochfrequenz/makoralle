"""Emit YAML from parsed EBDs for downstream consumers (e.g. edifact_mapper).

Reads per-EBD JSON from `pipeline/09_ebds/E_xxxx.json`, writes:
  - `pipeline/09_ebds/yaml/E_xxxx.yaml`        — per-EBD YAML mirror
  - `pipeline/09_ebds/answer_codes.yaml`       — global (ebd_id, code) → kind index
  - `pipeline/09_ebds/summary/E_xxxx.md`       — human-readable per-EBD summary
"""

import json
import logging
from pathlib import Path
from typing import Any, Iterator

import yaml

from makoralle.ebd_clusters import cluster_to_kind, extract_cluster

logger = logging.getLogger(__name__)


def _resolve_cluster_and_hint(branch_prefix: str, step: dict[str, Any]) -> tuple[str | None, str | None]:
    """Prefer structured cluster field; fall back to parsing the hint."""
    cluster = step.get(f"{branch_prefix}_cluster")
    hint = step.get(f"{branch_prefix}_hint")
    if cluster is not None:
        return cluster, hint
    return extract_cluster(hint)


def _iter_ebd_json_files(ebd_dir: Path) -> Iterator[Path]:
    yield from sorted(ebd_dir.glob("E_*.json"))


def _load_ebd(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def build_answer_codes_index(ebd_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Walk every EBD JSON in `ebd_dir` and build a lookup index.

    Returns:
        {ebd_id: {code: {"kind": str, "cluster": str | None,
                         "hint": str | None, "steps": list[int]}}}

    The same code may appear at multiple steps within one EBD (observed in
    ~23 places in the real corpus). All occurrences merge into a single
    entry; `steps` lists every step number, and `cluster`/`kind`/`hint`
    come from the richest occurrence (preferring non-None cluster).
    Empty entries (EBDs with no code-bearing branches) are omitted.
    """
    index: dict[str, dict[str, dict[str, Any]]] = {}
    for path in _iter_ebd_json_files(ebd_dir):
        ebd = _load_ebd(path)
        ebd_id = ebd["id"]
        codes: dict[str, dict[str, Any]] = {}
        for step in ebd.get("steps", []):
            step_nr = step.get("nr")
            if step_nr is None:
                logger.warning("%s: step missing 'nr', skipping", path.name)
                continue
            for branch in ("if_yes", "if_no"):
                code = step.get(f"{branch}_code")
                if not code:
                    continue
                cluster, hint = _resolve_cluster_and_hint(branch, step)
                existing = codes.get(code)
                if existing is None:
                    codes[code] = {
                        "kind": cluster_to_kind(cluster),
                        "cluster": cluster,
                        "hint": hint,
                        "steps": [step_nr],
                    }
                else:
                    if step_nr not in existing["steps"]:
                        existing["steps"].append(step_nr)
                    # Prefer the entry with a real cluster
                    if existing["cluster"] is None and cluster is not None:
                        existing["cluster"] = cluster
                        existing["kind"] = cluster_to_kind(cluster)
                        existing["hint"] = hint
        for entry in codes.values():
            entry["steps"].sort()
        if codes:
            index[ebd_id] = codes
    logger.info("Built answer-codes index: %d EBDs, %d codes", len(index), sum(len(v) for v in index.values()))
    return index


def write_answer_codes_index(ebd_dir: Path) -> Path:
    """Write `<ebd_dir>/answer_codes.yaml` from the per-EBD JSONs."""
    index = build_answer_codes_index(ebd_dir)
    out_path = ebd_dir / "answer_codes.yaml"
    out_path.write_text(
        yaml.dump(index, allow_unicode=True, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    logger.info(
        "Wrote answer_codes.yaml with %d codes across %d EBDs",
        sum(len(v) for v in index.values()),
        len(index),
    )
    return out_path


def _strip_nulls(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(v) for v in obj]
    return obj


def write_per_ebd_yaml(ebd_dir: Path) -> list[Path]:
    """Write `<ebd_dir>/yaml/E_xxxx.yaml` for every EBD JSON in `ebd_dir`."""
    out_dir = ebd_dir / "yaml"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in _iter_ebd_json_files(ebd_dir):
        ebd = _load_ebd(path)
        compact = _strip_nulls(ebd)
        out_path = out_dir / f"{ebd['id']}.yaml"
        out_path.write_text(
            yaml.dump(compact, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        written.append(out_path)
    logger.info("Wrote %d per-EBD YAML files to %s", len(written), out_dir)
    return written


def write_per_ebd_summary(ebd_dir: Path) -> list[Path]:
    """Write `<ebd_dir>/summary/E_xxxx.md` — code | kind | cluster | step | hint."""
    out_dir = ebd_dir / "summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in _iter_ebd_json_files(ebd_dir):
        ebd = _load_ebd(path)
        rows: list[tuple[str, str, str, int, str]] = []
        for step in ebd.get("steps", []):
            for branch in ("if_yes", "if_no"):
                code = step.get(f"{branch}_code")
                if not code:
                    continue
                cluster, hint = _resolve_cluster_and_hint(branch, step)
                rows.append(
                    (
                        code,
                        cluster_to_kind(cluster),
                        cluster or "",
                        step["nr"],
                        (hint or "").replace("|", "\\|").replace("\n", " "),
                    )
                )
        rows.sort(key=lambda r: r[0])
        lines = [
            f"# {ebd['id']} — {ebd.get('name', '')}",
            "",
            f"Role: {ebd.get('role') or 'unknown'}",
            f"Source: {ebd.get('source', '')}",
            "",
            "| Code | Kind | Cluster | Step | Hint |",
            "|------|------|---------|------|------|",
        ]
        for code, kind, cluster, step_nr, hint in rows:
            lines.append(f"| {code} | {kind} | {cluster} | {step_nr} | {hint} |")
        out_path = out_dir / f"{ebd['id']}.md"
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(out_path)
    logger.info("Wrote %d per-EBD markdown summaries to %s", len(written), out_dir)
    return written


def emit_all(ebd_dir: Path) -> None:
    """Run all three emitters against `ebd_dir`."""
    write_answer_codes_index(ebd_dir)
    write_per_ebd_yaml(ebd_dir)
    write_per_ebd_summary(ebd_dir)
