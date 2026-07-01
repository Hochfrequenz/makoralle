# makoralle

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
with `tox`. To set up a development environment:

```bash
tox -e dev
```

Run the unit tests, linting, type checks and coverage:

```bash
tox -e tests
tox -e linting
tox -e type_check
tox -e coverage
```
