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

The models live under `makoralle.models` (`process`, `ebd`, `pid`, `activity`, `chunk`,
`deadline`, `codeliste`, `source`, `formatversion`) and the serializers under
`makoralle.serialization`.

### Deadlines

A step's Frist is available in two shapes. `DeadlineRule` (in `models.process`) is the
flat one the parser writes today. `Deadline` (in `models.deadline`) is the structured one:
a list of alternatives, each with its own condition, immediacy anchor and backstop, which
is what the prose actually says — a MaKo Frist routinely states *act without undue delay*
**and** *no later than X*, and the flat rule has one field set for both.

```python
from makoralle.models.deadline import Deadline, deadline_from_rule

deadline = deadline_from_rule(step.deadline_rule)   # None when there is no Frist
if deadline and deadline.states_a_backstop:
    ...
```

The lift is faithful, not complete: it recovers everything the flat rule holds, and cannot
invent what it never held — a condition, a second alternative, or an offset in Stunden.
`raw` remains the full record until the parser fills the structure (see #57).

### Formatversionen

A *Formatversion* (`FV2604`) is BDEW's half-yearly release, and it is a bundle rather than a
document. A `Bundle` (in `models.formatversion`) names, for each document key (`gpke_teil1`,
`ebd`, …), the edition that applies. `Formatversionen` is the table of bundles: each row has a
`gueltig_ab` (curated, not derived from the name), and the table names a `default`. `in_force`
returns the name of the newest bundle in force on a given day, or of the oldest one before the
first `gueltig_ab`. `write_json` writes a model as JSON with None fields left out. A dataset is a
directory laid out as `formatversionen.yaml` plus one `<FV>/bundle.yaml` per Formatversion; the
loaders accept any path.

```python
from pathlib import Path
from makoralle.models.formatversion import load_bundle, load_formatversionen

dataset = Path("dataset")                           # formatversionen.yaml + <FV>/bundle.yaml
table = load_formatversionen(dataset / "formatversionen.yaml")
fv = table.in_force()                               # today; pass a datetime.date for another day
bundle = load_bundle(dataset / fv / "bundle.yaml")
edition = bundle.documents["ebd"]                   # a SourceDocument
```

An edition is a `SourceDocument` (in `models.source`). It has a `file_name` and, optionally, the
publication `date`, the `document_version`, a `valid_from`/`valid_to` window and the file's
`sha256`. Since 0.0.23, `Process.source_documents` (`uc_sd`, `ebd`, `pid`, `ad`) holds editions
instead of free text, and `Process`, `DecisionTree` and `Codeliste` carry an optional
`formatversion`, set when the record was built inside a bundle.

**Breaking in 0.0.23:** on `DecisionTree` and `Codeliste`, `format_version` is renamed to
`document_version`, because the field always held the document's version (`"4.1"`) and never a
Formatversion. The old key still validates as input, and a read-only `format_version` property
returns the value with a `DeprecationWarning`; both are scheduled for removal in 0.0.24. Once they
are gone, a stored record that still says `format_version` loads with `document_version = None`
and no error, because the models ignore unknown keys, so re-save stored YAML/JSON with
`document_version` now. The alias also only works at runtime: a type checker without the pydantic
mypy plugin rejects `DecisionTree(format_version=...)` as an unexpected keyword, and mypy then
suggests `formatversion`, which is a different field. A `document_version` that disagrees with its
`source_document.document_version` is rejected.

`config.ahb_pid_url(pid, formatversion)` pins AHB links to `…/ahb/<FV>/<pid>`, and
`webapp_export.run(..., fv=…)` scopes diagram URLs to `/diagrams/<FV>/…`. Both raise `ValueError`
on a value that is not `FV` plus four ASCII digits, but they treat an empty value differently:
`ahb_pid_url` reads `""` as unbundled and links to `current`, while `run(fv="")` raises. `run` also
refuses a process record whose own `formatversion` differs from `fv`.

## Development

This project uses the Hochfrequenz [`src`-layout Python template](https://github.com/Hochfrequenz/python_template_repository)
with [`uv`](https://docs.astral.sh/uv/). To set up a development environment:

```bash
uv sync --group dev
```

Run the unit tests, linting, type checks and coverage (matching what CI runs):

```bash
uv run --group tests pytest
uv run --group linting ruff check src/makoralle unittests
uv run --group linting ruff format --check .
uv run --group type_check mypy --strict src/makoralle
uv run --group type_check mypy --strict unittests
cd unittests && uv run --group coverage coverage run -m pytest && cd ..
```
