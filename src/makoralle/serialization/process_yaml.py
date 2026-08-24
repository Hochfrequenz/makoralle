"""Serialize a :class:`Process` to YAML and write it to disk."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from makoralle.models.process import Process


def _dump(item: Any) -> Any:
    """``item.model_dump(exclude_none=True)``, or ``item`` unchanged if it is already a
    plain dict — ``decision_trees``/``pid_mappings``/``activity_diagram`` are typed loosely
    on :class:`Process`, so a round-tripped process holds plain dicts there, not model
    instances (:func:`process_from_dict` only validates the fields ``Process`` itself types
    strictly)."""
    return item if isinstance(item, dict) else item.model_dump(exclude_none=True)


def process_to_yaml(process: Process) -> str:
    """Serialize a :class:`Process` into its canonical YAML string representation."""
    data: dict[str, Any] = {}
    data["process"] = {
        "id": process.id,
        "name": process.name,
        "source": process.source,
        "category": process.category,
    }
    if process.use_case:
        data["use_case"] = process.use_case.model_dump(exclude_none=True)
    if process.sequence_diagram:
        data["sequence_diagram"] = process.sequence_diagram.model_dump(exclude_none=True)
    if process.diagrams:
        data["diagrams"] = [d.model_dump(exclude_none=True) for d in process.diagrams]
    if process.decision_trees:
        data["decision_trees"] = [_dump(dt) for dt in process.decision_trees]
    if process.pid_mappings:
        data["pid_mappings"] = [_dump(p) for p in process.pid_mappings]
    if process.activity_diagram:
        data["activity_diagram"] = _dump(process.activity_diagram)
    if process.related_processes:
        data.setdefault("cross_references", {})["related_processes"] = [
            r.model_dump() for r in process.related_processes
        ]
    if process.source_documents:
        data.setdefault("cross_references", {})["source_documents"] = process.source_documents.model_dump(
            exclude_none=True
        )

    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def emit_yaml(process: Process, output_dir: Path) -> Path:
    """Write ``process`` as ``<output_dir>/<process.id>.yaml`` and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    yaml_str = process_to_yaml(process)
    output_path = output_dir / f"{process.id}.yaml"
    output_path.write_text(yaml_str, encoding="utf-8")
    return output_path


def flatten_process_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    """Undo the on-disk nesting :func:`process_to_yaml` adds for readability.

    It nests ``id``/``name``/``source``/``category`` under a ``process`` key and
    ``related_processes``/``source_documents`` under ``cross_references``; :class:`Process`
    itself declares all of those as top-level fields. Splices both wrappers back up,
    tolerating a bare (``key:`` with no value, i.e. ``None``) or absent wrapper. A key
    present both at top level and inside a wrapper resolves to the wrapper's value.
    """
    flat = dict(data)
    flat.update(flat.pop("process", None) or {})
    flat.update(flat.pop("cross_references", None) or {})
    return flat


def process_from_dict(data: Mapping[str, Any]) -> Process:
    """Inverse of the nested dict shape :func:`process_to_yaml` writes: rebuild a
    :class:`Process`, via :func:`flatten_process_dict`.

    Raises :class:`ValueError` if, once flattened, ``data`` carries a key
    :class:`Process` doesn't declare — pydantic's default ``extra="ignore"`` would
    otherwise drop a typo'd or unrecognized field silently rather than fail loudly.
    """
    flat = flatten_process_dict(data)
    if unknown := set(flat) - set(Process.model_fields):
        raise ValueError(f"process dict carries unknown field(s): {sorted(unknown)}")
    return Process.model_validate(flat)


def process_from_yaml(yaml_str: str) -> Process:
    """Parse ``yaml_str`` (as produced by :func:`process_to_yaml`) into a :class:`Process`."""
    data = yaml.safe_load(yaml_str)
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML mapping at the top level, got {type(data).__name__}: {data!r}")
    return process_from_dict(data)


def load_yaml(path: Path) -> Process:
    """Read a process YAML file (as written by :func:`emit_yaml`) into a :class:`Process`."""
    try:
        return process_from_yaml(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
