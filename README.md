# makoralle 🪸

![Unittests status badge](https://github.com/Hochfrequenz/makoralle/workflows/Unittests/badge.svg)
![Coverage status badge](https://github.com/Hochfrequenz/makoralle/workflows/Coverage/badge.svg)
![Linting status badge](https://github.com/Hochfrequenz/makoralle/workflows/Linting/badge.svg)
![Black status badge](https://github.com/Hochfrequenz/makoralle/workflows/Formatting/badge.svg)

`makoralle` provides [pydantic](https://docs.pydantic.dev/) models for the German
**MaKo** (*Marktkommunikation*) processes together with serializers that turn those
models into the output formats used downstream:

- **YAML** – process and EBD (*Entscheidungsbaum-Diagramm*) representations
- **WSD** – the [websequencediagrams](https://www.websequencediagrams.com/) DSL for sequence diagrams
- **BPMN** – business process model XML
- **Markdown** – human-readable process documentation

It is the shared, dependency-light foundation (only `pydantic` and `PyYAML`) consumed by
the private `makorele` parser and by the process-documentation webapp.

## Separation of concerns

Part of the Hochfrequenz MaKo tooling — **four repositories, one responsibility each**:

- **[makoralle](https://github.com/Hochfrequenz/makoralle)** (public, [PyPI](https://pypi.org/project/makoralle/)) — the **data model** + serializers. ← **this repo**
- **[makorele](https://github.com/Hochfrequenz/makorele)** (private) — the **parser** (BDEW PDFs → validated models).
- **[machine-readable_mako-prozesse](https://github.com/Hochfrequenz/machine-readable_mako-prozesse)** (private) — the generated **dataset**, consumed at a pinned tag.
- **[mako_prozesse](https://github.com/Hochfrequenz/mako_prozesse)** — the **web app** that presents the dataset.

Dependencies flow one way: `makorele` → `makoralle`; the dataset is produced by the tooling and consumed by the web app at a pinned tag. `makoralle` imports neither the parser nor the app.

## Installation

```bash
pip install makoralle
```

## Usage

The public serialization API is exposed at the package root and resolved lazily
(importing `makoralle`, or a light submodule like `makoralle.grouping`, does **not**
eagerly pull in the serialization stack):

```python
from makoralle import emit_yaml, emit_wsd, emit_markdown, emit_bpmn
from makoralle.models.process import Process

# build or load a Process model, then serialize it
yaml_text = emit_yaml(process)
wsd_text = emit_wsd(process.sequence_diagrams[0])
```

The models live under `makoralle.models` (`process`, `ebd`, `pid`, `activity`, `chunk`)
and the serializers under `makoralle.serialization`.

## Development

This project uses the Hochfrequenz [`src`-layout Python template](https://github.com/Hochfrequenz/python_template_repository)
with [`uv`](https://docs.astral.sh/uv/). To set up a development environment:

```bash
uv sync --group dev
```

Run the unit tests, linting, type checks and coverage (matching what CI runs):

```bash
uv run --group tests pytest
uv run --group linting pylint makoralle
uv run --group linting pylint unittests --rcfile=unittests/.pylintrc
uv run --group type_check mypy --strict src/makoralle
uv run --group type_check mypy --strict unittests
cd unittests && uv run --group coverage coverage run -m pytest && cd ..
```
