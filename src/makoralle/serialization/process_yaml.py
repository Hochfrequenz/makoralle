"""Serialize a :class:`Process` to YAML and write it to disk."""

from pathlib import Path
from typing import Any

import yaml

from makoralle.models.process import Process


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
        data["decision_trees"] = [dt.model_dump(exclude_none=True) for dt in process.decision_trees]
    if process.pid_mappings:
        data["pid_mappings"] = [p.model_dump(exclude_none=True) for p in process.pid_mappings]
    if process.activity_diagram:
        if isinstance(process.activity_diagram, dict):
            data["activity_diagram"] = process.activity_diagram
        else:
            data["activity_diagram"] = process.activity_diagram.model_dump(exclude_none=True)
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


def process_from_dict(data: dict[str, Any]) -> Process:
    """Inverse of :func:`process_to_yaml`'s dict shape: rebuild a :class:`Process`.

    ``process_to_yaml`` nests ``id``/``name``/``source``/``category`` under a
    ``process`` key and ``related_processes``/``source_documents`` under
    ``cross_references``, both for on-disk readability; :class:`Process` itself
    declares all of those as top-level fields. This splices the two wrapper dicts
    back up before handing the result to :meth:`Process.model_validate`.
    """
    flat = dict(data)
    flat.update(flat.pop("process", {}))
    flat.update(flat.pop("cross_references", {}))
    return Process.model_validate(flat)


def process_from_yaml(yaml_str: str) -> Process:
    """Parse ``yaml_str`` (as produced by :func:`process_to_yaml`) into a :class:`Process`."""
    return process_from_dict(yaml.safe_load(yaml_str))


def load_yaml(path: Path) -> Process:
    """Read a process YAML file (as written by :func:`emit_yaml`) into a :class:`Process`."""
    return process_from_yaml(path.read_text(encoding="utf-8"))
