"""makoralle — pydantic models for the German MaKo processes and serialization
of those models to the output formats (YAML, WSD sequence-diagram DSL, BPMN,
Markdown).

Public serialization API:

    from makoralle import emit_yaml, emit_wsd, emit_markdown, emit_bpmn

These names are resolved lazily (PEP 562): importing ``makoralle`` — or a
lightweight submodule such as ``makoralle.grouping`` — does NOT eagerly pull the
serialization stack (and thus pydantic), so minimal environments (e.g. the
Cloudflare Pages webapp-data build, which only needs ``grouping``/``ref_links``)
stay importable. The heavy module loads only when its symbol is first accessed.
"""

# The names in __all__ are provided lazily via the PEP 562 __getattr__ below, so
# they are intentionally NOT defined at module scope for static analysis to see.
# pylint: disable=undefined-all-variable

# public name -> module that defines it
_API = {
    "process_to_yaml": "makoralle.serialization.process_yaml",
    "emit_yaml": "makoralle.serialization.process_yaml",
    "emit_wsd": "makoralle.serialization.wsd",
    "emit_all_wsd": "makoralle.serialization.wsd",
    "emit_markdown": "makoralle.serialization.markdown",
    "yaml_to_markdown": "makoralle.serialization.markdown",
    "emit_bpmn": "makoralle.serialization.bpmn",
    "plantuml_to_bpmn": "makoralle.serialization.bpmn",
}

__all__ = list(_API)


def __getattr__(name: str) -> object:
    try:
        module = _API[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib  # pylint: disable=import-outside-toplevel  # lazy import is the point of __getattr__

    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
