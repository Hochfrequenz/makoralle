# Design: Fix the four open issues as four reviewed PRs

Date: 2026-10-07
Status: Approved (design decision record)
Scope: makoralle issues #67, #81, #79, #36 — one PR each, in that order.

## Context

makoralle serialises the machine-readable MaKo process corpus (editions, EBDs, PIDs,
Codelisten, Formatversionen) into models and four emitters (WSD, Mermaid/markdown,
EBD-YAML, webapp JSON). Four issues are open. Each gets its own PR, merged before the
next begins, because #81 is a breaking change that must not share a diff with anything.

Every PR follows the same review loop, which the user fixed as policy:

1. Branch from fresh `main`, implement (tests first where behaviour changes).
2. Open a PR whose description argues its claims with pinned evidence (dataset tags,
   line references, counts) — the house style the issues themselves use.
3. GitHub Copilot (`copilot-pull-request-reviewer`) reviews; implement its findings.
4. An Opus reviewer (Claude subagent, model `opus`) reviews; implement its findings.
5. A further round by either reviewer only if necessary (e.g. a finding reshaped
   substantial code).
6. Poll `gh pr checks` until CI is green; merge; move to the next issue.

PR titles follow conventional commits with a scope (`fix(markdown): …`); the body
ends with `Fixes #<n>`.

## PR 1 — #67: correct the `prozessbeschreibung_dokument` docstring (docs-only)

`PIDMapping.prozessbeschreibung_dokument` (`src/makoralle/models/pid.py`, field
comment lines 25–27) hedges that the field is *reported* to be what the Sparte
columns are computed from, unverifiable because the PID 4.0 workbook is out-of-band.
Issue #67 refutes the claim from data this toolchain *does* ship: at dataset v0.0.20,
`mehr-_mindermengenabrechnung_zwischen_nb_und_lf` and `…_nb_und_mgv` share PID 31004,
Anwendungsfall `'Stornorechnung'` and identical `prozessbeschreibung_dokument`, yet
carry opposite Sparte cells; `33001`/`33002` repeat the shape, and `37000`–`37006` vs
`37008`–`37011` refute any keyword derivation independently. A value computed from
this field cannot take two values for one input.

**Change:** keep the first paragraph (the confusion with
`prozessbeschreibung_kapitel` is real and useful); replace the second paragraph with
the issue's refutation text — the counter-example and the conclusion: treat the field
as a document label, not a Sparte signal. No behaviour, no schema, no serialised
output changes. CI must pass without touching anything else.

Not assigned to anyone else's work: the issue is assigned to lord-haffi, but filed
and requested by the repo owner; proceed, and note the assignee in the PR.

## PR 2 — #81: remove the deprecated `format_version` alias and property (breaking)

0.0.23 renamed `format_version` → `document_version` on `DecisionTree` and
`Codeliste`, keeping an input alias (`AliasChoices`) and a warning read-only property
"scheduled for removal in 0.0.24". 0.0.24 shipped without the removal; this is the
tracked removal, released as **0.1.0** (the first release after 0.0.24; 0.0.x never
carried it), strictly alone
in its PR.

The issue's own verification makes it safe: dataset v0.0.35 contains **0** files with
a `format_version` key under any FV; makorele has no reference; mako-twin's two hits
were checked (issue comment) and are false positives — efoli/MIG format versions, not
this field.

**Change:**

- `src/makoralle/models/ebd.py` (~159–174) and `src/makoralle/models/codeliste.py`
  (~51–66): `document_version` becomes a plain `str | None` field (drop
  `validation_alias=AliasChoices(...)`); delete both `format_version` properties and
  the now-unused `warnings` / `AliasChoices` imports; update the stale "kept as an
  input alias" comments.
- `unittests/test_document_version_rename.py`: rewrite from pinning the alias +
  warning to pinning the new contract — a record that still says `format_version`
  loads with `document_version = None` and no error (models ignore unknown keys).
- `README.md` "Breaking in 0.0.23" paragraph (lines 104–113): rewrite as the removal
  record — the alias and property are gone as of 0.1.0; re-save stored YAML/JSON
  that still spells the old key.

Grep gates: no `format_version` left in `src/` afterwards; in `unittests/`, the
rewritten `test_document_version_rename.py` is the *sole* allowed mention (its input
record must contain the legacy key to pin the silent-`None` behaviour) — no
`AliasChoices(..., "format_version")`, no `def format_version`, no
`DeprecationWarning` text anywhere. The emitters already write `document_version`,
so no serialised output changes.

## PR 3 — #79: efoli as source of truth for `gueltig_ab` (feature, tests first)

`src/makoralle/models/formatversion.py` hand-maintains the `gueltig_ab` dates in
`formatversionen.yaml`; its docstring says the dates are "curated, not derived".
The user decided the opposite coupling: **efoli becomes the source of truth** for
these dates, so curation drift becomes impossible rather than detectable.

efoli 2.4.1 (latest PyPI; not currently a makoralle dependency at all) provides
`get_edifact_format_version_valid_from(EdifactFormatVersion)` → `datetime.date`
(Europe/Berlin inclusive start), raising `KeyError` for versions with no known start
(only FV2104). Its table encodes exactly the curated dates makoralle documents
(FV2504 → 2025-06-06, FV2604 → 2026-04-01).

**Change:**

- `pyproject.toml`: add `efoli==2.4.1` (spec style matching existing deps); lock with
  `uv sync`. Note for the PR description: efoli pulls in `pytz`, a new transitive
  runtime dependency.
- `FormatversionEntry.gueltig_ab` stops being a hand-maintained input: derived via
  efoli from `fv`. It becomes a `@computed_field` so `model_dump()` still ships the
  date to the stdlib-only webapp twin via `write_json` — the deliberate contrast with
  `PIDMapping.sparten`'s plain property, which exists to stay *out* of the dump;
  both sites get comments saying so. Type note: efoli returns `datetime.date` where
  today's field is an `IsoDate` string; `_consistent` and `in_force` compare
  isoformat strings, so they adapt at the comparison point (`.isoformat()`), and a
  `computed_field` date dumps as ISO under `mode="json"`, satisfying `write_json`
  and the JSON round-trip. "Logic unchanged" means behaviour unchanged.
- Failure modes, both wrapped so the message says "bump efoli": an FV outside
  efoli's enum (future FV2704) raises from the `EdifactFormatVersion` conversion, and
  the oldest FV2104 raises `KeyError` from `get_edifact_format_version_valid_from` —
  neither may surface raw.
- Loud drift check: a loaded table that still carries a hand-written `gueltig_ab`
  disagreeing with efoli raises `ValueError` naming efoli as the source. Today's
  shipped table agrees with efoli 2.4.1, so current data loads unchanged. One
  existing test needs a date tweak:
  `test_bundles_are_sorted_and_unique` (unittests/test_formatversion_model.py:107)
  feeds FV2510 `gueltig_ab: "2025-10-02"`, which the drift check now rejects before
  `_consistent` ever runs — change it to an efoli-agreeing date (the duplicate-name
  and unsorted cases it exercises don't need a wrong date). Also pin the validator
  ordering so it is deterministic which error a doubly-bad table raises: the drift
  check runs before `_consistent`.
- An FV efoli does not know (e.g. a future FV2704) fails loudly with "bump efoli" —
  no silent tolerance; that coupling is the point of the chosen option. Same for the
  efoli-unknown FV2104 edge (`KeyError` surfaces).
- `quelle` stays: it records who listed the bundle, not the date.
- Module docstring rewritten: dates derived from efoli, not curated; the FV2504
  example stays, now as evidence the derivation matches curation. `in_force` and
  `_consistent` logic unchanged.
- Tests first (red → green): FV2504 → 2025-06-06 and FV2604 → 2026-04-01 pinned;
  drift rejection; unknown-FV rejection; `model_dump`/`write_json` still emits
  `gueltig_ab`; existing fixture tables keep loading.

## PR 4 — #36: document the emitters' deliberate split on readable `ref` steps (docs-only)

For a `ref` step naming **both** endpoints whose message opens with `"ref "`,
`emit_wsd` draws a self-message on the sender (a ref is a subprocess box on one
lifeline; Vision mis-guesses receivers) while the Mermaid emitter draws
`sender → receiver` plus the subprocess note. Issue #36 was filed to settle this;
the user decided: **document the status quo** — no output changes, the discrepancy
stays, but `models.process.is_ref_step`'s docstring stops claiming the emitters
agree and states the deliberate split instead (historical shape for readable steps;
the #78 rule — self-message on the named lane — only where an endpoint was not read
at all). `src/makoralle/serialization/wsd.py`'s "filed as makoralle#36" comment
(~line 497) becomes "decided in makoralle#36: keep the split". (Since commit
e41b29f the docstring already states the emitters differ; what changes is framing
the split as a settled decision rather than an open question.)

The existing shape-pinning tests (7 shipped arrows, `.wsd` self-messages) are the
pinning of this decision; no new behaviour to test. makorele#164 is unaffected — it
assumes the self-message answer for unread-endpoint refs, which both emitters
already agree on.

## Out of scope

- Any change to serialised output beyond what #81's removal implies for *inputs*
  (none for outputs).
- efoli's own data (efoli.ts parity, new FVs) — upstream concern.
- The webapp's lane-placement bug behind mako_prozesse#172–174 (filed as
  makorele#164; only referenced here).

## Risks

- **#81:** a consumer outside the three checked repos still storing
  `format_version` would silently load `document_version = None`. Mitigated by the
  issue's dataset/consuumer survey and the README migration note; accepted by the
  issue explicitly.
- **#79:** dataset snapshots newer than the installed efoli now fail validation
  until efoli is bumped — intended (loud coupling), and the error message says so.
- **#36:** none — docs-only, output pinned unchanged by existing tests.
