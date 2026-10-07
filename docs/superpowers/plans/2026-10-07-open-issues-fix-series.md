# Open-Issues Fix Series (#67 → #81 → #79 → #36 + release) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix makoralle's four open issues as four squash-merged PRs (each with the Copilot→Opus review loop), then cut the v0.1.0 minor release with auto-generated notes.

**Architecture:** Four strictly sequential, individually mergeable PRs: two docs-only fixes (#67, #36), one breaking API removal (#81), one feature adding efoli as the source of truth for `gueltig_ab` (#79). Each PR goes through the review loop recorded in the spec: Copilot review → implement findings → Opus review → implement findings → further rounds iff necessary → CI green → squash-merge.

**Tech Stack:** Python 3.11+ (CI matrix 3.11–3.14), pydantic v2, pytest, ruff (check+format), mypy `--strict`, uv, hatch-vcs (version from git tags), efoli 2.4.1 (new dependency in PR 3).

**Spec:** `docs/superpowers/specs/2026-10-07-open-issues-fix-series-design.md` (approved, review loop passed).

**Environment notes for the executor (Windows workstation, this repo):**
- ALWAYS run the test suite as `PYTHONUTF8=1 uv run pytest -q`. Without `PYTHONUTF8=1`, five unrelated tests fail with `UnicodeDecodeError` (Linux CI is unaffected).
- `unittests/test_p14_emit_yaml.py::test_load_yaml_error_names_the_file` fails locally **even with** `PYTHONUTF8=1` — a pre-existing test bug (it feeds a Windows path into a `pytest.raises(match=...)` regex; `\g` is a bad escape). Linux CI never trips it. Expect exactly this 1 failure locally; the CI gate is `gh pr checks`, not the local run.
- The repo allows **squash merges only** (merge/rebase disabled) and auto-deletes merged branches.

---

## Task 0: One-time setup

**Rule: never push to main directly.** Main is protected (repo ruleset: required status checks, squash-only) and the user forbids it: every change — including specs/plans — reaches main through a PR with green CI.

- [ ] **Step 0.1: Carry the docs commits in PR 1**

The approved spec (`3e92558`) and plan (`0eeceb8`) are local commits on main. **Do NOT push them to main.** They ride in PR 1's branch:

```bash
git checkout docs/67-pid-docstring-sparte-claim   # after Step 1.1 creates it
git cherry-pick 3e92558 0eeceb8                    # or: git rebase main keeps them on top
```

(Concretely: after branching from local main — which already has both commits — the branch contains them automatically; just do not `git push origin main`.) The docs commits then land on main via PR 1's squash-merge, together with the #67 fix. Note this in PR 1's body ("carries the series' design spec + plan docs").

- [ ] **Step 0.2: Re-baseline**

```bash
git checkout main && git pull origin main
uv sync --group dev
PYTHONUTF8=1 uv run pytest -q
```

Expected: `736 passed, 1 skipped, 1 failed` — the 1 failure must be exactly `test_load_yaml_error_names_the_file` (see environment notes). Any other failure: stop and investigate. (Local main may be behind remote by the two docs commits — that's fine; the branch in Step 1.1 cuts from local main and brings them.)

---

## Task 1: PR 1 — #67 PIDMapping docstring refutation (docs-only)

**Files:**
- Modify: `src/makoralle/models/pid.py:25-27` (field comment only)
- Branch: `docs/67-pid-docstring-sparte-claim`
- PR title: `docs(models): refute the Sparte-derivation claim in PIDMapping.prozessbeschreibung_dokument`

- [ ] **Step 1.1: Create the branch**

```bash
git checkout main && git pull origin main && git checkout -b docs/67-pid-docstring-sparte-claim
```

- [ ] **Step 1.2: Replace the hedged paragraph with the refutation**

In `src/makoralle/models/pid.py`, the field comment currently reads (lines 25–27):

```python
    #: Reported (PID 4.0 workbook) to be what the Sparte columns are computed from, which
    #: would make it the authoritative signal and them a derived view. That workbook is not
    #: pinned by this toolchain and arrives out-of-band, so this repo cannot check it.
```

Replace those three `#:` lines with (keep the first paragraph above them — the `prozessbeschreibung_kapitel` confusion warning — untouched):

```python
    #: Sometimes *reported* to be what the Sparte columns are computed from. The shipped
    #: corpus refutes that: ``mehr-_mindermengenabrechnung_zwischen_nb_und_lf`` and
    #: ``…_nb_und_mgv`` each carry 31004 ``'Stornorechnung'`` with identical Anwendungsfall
    #: and identical ``prozessbeschreibung_dokument``, and opposite Sparte cells (dataset
    #: v0.0.20). Treat this as a document label, not as a sparte signal.
```

- [ ] **Step 1.3: Verify nothing else changed and gates pass**

```bash
git diff --stat
PYTHONUTF8=1 uv run pytest -q
uv run ruff check src/makoralle unittests && uv run ruff format --check .
uv run mypy --show-error-codes src/makoralle --strict
```

Expected: diff touches only `pid.py`; tests as in Step 0.2; ruff/mypy clean.

- [ ] **Step 1.4: Commit, push, open the PR**

```bash
git add src/makoralle/models/pid.py
git commit -m "docs(models): refute the Sparte-derivation claim in PIDMapping.prozessbeschreibung_dokument"
git push -u origin docs/67-pid-docstring-sparte-claim
gh pr create --title "docs(models): refute the Sparte-derivation claim in PIDMapping.prozessbeschreibung_dokument" --body "<body below>"
```

PR body (evidence-argued, house style; ends with the fix reference):

```markdown
`PIDMapping.prozessbeschreibung_dokument`'s docstring reported (PID 4.0 workbook) that
this field is what the Sparte columns are computed from — hedged as unverifiable because
the workbook arrives out-of-band. The claim is checkable from the data this toolchain
serialises, and it is false.

At dataset tag v0.0.20 (`machine-readable_mako-prozesse`, `output/yaml/*.yaml`,
`pid_mappings`), these pairs share a Prüfidentifikator, an Anwendungsfall **and** a
`prozessbeschreibung_dokument`, and ship **opposite** Sparte cells:

| process | PID | Anwendungsfall | `sparte_strom` / `sparte_gas` |
|---|---|---|---|
| `mehr-_mindermengenabrechnung_zwischen_nb_und_lf` | 31004 | `'Stornorechnung'` | `true` / `false` |
| `mehr-_mindermengenabrechnung_zwischen_nb_und_mgv` | 31004 | `'Stornorechnung'` | `false` / `true` |

`33001 'Bestätigung'` and `33002 'Abweisung'` repeat the shape across the same two
processes; independently, `übermittlung_von_informationen` carries `37000`–`37006`
(`'GPKE Teil 4'` — no "Gas" in the string) as Strom while `37008`–`37011` sit in the same
PARTIN block as Gas. A value computed from this field cannot take two values for one
input, and any keyword derivation over the name would have that pair backwards.

The docstring now keeps the first paragraph (the confusion with
`prozessbeschreibung_kapitel` is real) and replaces the claim with the refutation:
treat this as a document label, not as a sparte signal.

Docs-only: no behaviour, no schema, no serialised output change. (Filed by @hf-kklein;
nominally assigned to @lord-haffi — proceeding on the filer's instruction.)

Fixes #67
```

- [ ] **Step 1.5: Review loop (applies to every PR in this plan)**

1. **Copilot:** poll `gh pr view <n> --json reviews --jq '.reviews[] | "\(.author.login) \(.state)"'` until `copilot-pull-request-reviewer` appears. Read its findings (inline comments: `gh api repos/Hochfrequenz/makoralle/pulls/<n>/comments --jq '.[] | .path, .body, ---'`). Implement valid findings, push. Dismiss/argue invalid ones in a PR comment.
2. **Opus:** dispatch a review subagent (model `opus`) with the PR number and instruction to review the full diff against this plan's PR section + the spec; implement valid findings, push.
3. **Another round** by either reviewer **ONLY if necessary** (Iff — e.g. a finding reshaped substantial code or introduced a new defect surface); not by default.
4. **CI:** poll `gh pr checks <n>` until every check passes (required: pytest 3.11–3.14, lint, type_check, coverage, packaging, spell_check, format). Never push to main directly; merge only `gh pr merge <n> --squash` after green.

- [ ] **Step 1.6: Squash-merge and reset**

```bash
gh pr merge <n> --squash
git checkout main && git pull origin main
```

---

## Task 2: PR 2 — #81 remove the deprecated `format_version` alias and property (breaking)

**Files:**
- Modify: `src/makoralle/models/ebd.py:13,16,159-174`
- Modify: `src/makoralle/models/codeliste.py:10,13,51-66`
- Rewrite: `unittests/test_document_version_rename.py`
- Modify: `README.md:104-113`
- Branch: `refactor/81-remove-format-version-alias`
- PR title: `refactor(models)!: remove the deprecated format_version alias and property`

- [ ] **Step 2.1: Branch**

```bash
git checkout main && git pull origin main && git checkout -b refactor/81-remove-format-version-alias
```

- [ ] **Step 2.2: Pre-removal verification grep**

```bash
grep -rn "format_version" src/ unittests/ README.md
```

Expected hits: `ebd.py` (alias + property), `codeliste.py` (alias + property), the rename test (12), README §"Breaking in 0.0.23". Nothing in serializers/webapp. If a new unexpected hit appears, check it reads `document_version` instead before proceeding.

- [ ] **Step 2.3: Rewrite the test to the new contract FIRST (red)**

Replace the two warning tests and the alias test in `unittests/test_document_version_rename.py`:

- Update the module docstring to: the alias shipped in 0.0.23–0.0.24 is removed; a record that still spells the old key loads with `document_version = None` and no error, because the models ignore unknown keys.
- Delete `test_old_key_still_validates_into_the_new_field`, `test_old_attribute_reads_through_with_a_deprecation_warning`, `test_codeliste_old_attribute_reads_through_with_a_deprecation_warning`, and the now-unused `import warnings`.
- Add:

```python
def test_the_removed_key_is_no_longer_read() -> None:
    """The alias is gone: an old record loads with ``document_version = None`` and no error."""
    tree = DecisionTree.model_validate({"id": "E_0401", "name": "x", "format_version": "4.1"})
    assert tree.document_version is None
    liste = Codeliste.model_validate({"id": "S_0055", "name": "x", "codes": [], "format_version": "4.1"})
    assert liste.document_version is None
```

Keep every other test as is.

```bash
PYTHONUTF8=1 uv run pytest unittests/test_document_version_rename.py -q
```

Expected: FAIL — the alias still populates `document_version` (`"4.1" is not None`).

- [ ] **Step 2.4: Remove alias + property from `ebd.py`**

- Line 13: delete `import warnings` (unused afterwards).
- Line 16: drop `AliasChoices` from the pydantic import.
- Lines 159–163: replace the two comment lines + aliased field with:

```python
    document_version: str | None = None
```

- Lines 170–174: delete the `format_version` property entirely.

- [ ] **Step 2.5: Remove alias + property from `codeliste.py`**

Same pattern: delete `import warnings` (line 10), drop `AliasChoices` from the import (line 13), replace lines 51–55 (comment + aliased field) with `document_version: str | None = None`, delete the property (lines 62–66).

- [ ] **Step 2.6: Green**

```bash
PYTHONUTF8=1 uv run pytest unittests/test_document_version_rename.py -q
PYTHONUTF8=1 uv run pytest -q
```

Expected: rename test file fully green; full suite as in Step 0.2.

- [ ] **Step 2.7: Update the README paragraph (lines 104–113)**

Replace the whole "**Breaking in 0.0.23:** …" paragraph with:

```markdown
**Breaking in 0.0.23, removed in 0.1.0:** on `DecisionTree` and `Codeliste`, `format_version`
is renamed to `document_version`, because the field always held the document's version
(`"4.1"`) and never a Formatversion. 0.0.23 and 0.0.24 kept the old key as an input alias and
a deprecated read-only property; both are now removed. A stored record that still says
`format_version` loads with `document_version = None` and no error, because the models ignore
unknown keys — re-save stored YAML/JSON with `document_version`.
```

- [ ] **Step 2.8: Grep gate**

```bash
grep -rn "format_version" src/          # expect: no output
grep -rln "format_version" unittests/   # expect: only unittests/test_document_version_rename.py
```

Then the full gate set (Step 1.3's commands; run all four). Expected: clean, suite as baseline.

- [ ] **Step 2.9: Commit, push, PR**

```bash
git add -A
git commit -m "refactor(models)!: remove the deprecated format_version alias and property"
git push -u origin refactor/81-remove-format-version-alias
gh pr create --title "refactor(models)!: remove the deprecated format_version alias and property" --body "<body below>"
```

PR body:

```markdown
0.0.23 (#78) renamed `format_version` to `document_version` on `DecisionTree` and
`Codeliste`, keeping the old key as an input alias and a deprecated read-only property,
"scheduled for removal in 0.0.24". 0.0.24 shipped without the removal; this PR does it.

**Why it is safe to remove now** (verified in #81 and its comments):
- dataset `machine-readable_mako-prozesse` v0.0.35+ contains **0** files with a
  `format_version` key under any FV; `pipeline/09_ebds` carries `document_version`;
- makorele has no reference in `src/`, `tools/`, `unittests/`;
- mako-twin's two hits were checked and are false positives (an efoli import and a
  comment about efoli's thresholds — EDIFACT format versions, not this field).

**What this changes:** the `AliasChoices("document_version", "format_version")` alias and
both `format_version` properties (with their `DeprecationWarning`) are gone. A stored
record that still spells the old key now loads with `document_version = None` and no
error (the models ignore unknown keys) — pinned by
`test_the_removed_key_is_no_longer_read`. Serialised output is unchanged: the emitters
already write `document_version`.

**Migration:** re-save stored YAML/JSON with `document_version` (README updated).

**BREAKING CHANGE:** `DecisionTree(format_version=...)` / `Codeliste(format_version=...)`
no longer populate `document_version`, and the `.format_version` properties are gone.

Fixes #81
```

- [ ] **Step 2.10: Review loop** (exactly Step 1.5) → **Step 2.11: squash-merge and reset** (exactly Step 1.6).

---

## Task 3: PR 3 — #79 efoli as source of truth for `gueltig_ab` (feature, TDD)

**Files:**
- Modify: `pyproject.toml` + `uv.lock` (new dependency)
- Modify: `src/makoralle/models/formatversion.py` (derivation + drift check + docstrings)
- Modify: `unittests/test_formatversion_model.py` (new tests + one date tweak)
- Branch: `feat/79-efoli-gueltig-ab`
- PR title: `feat(models): derive gueltig_ab from efoli`

**Mechanism note (refines the spec, intent preserved):** the spec sketched a
`@computed_field`; the plan uses the simpler equivalent — `gueltig_ab` stays a real
`IsoDate` field but becomes optional, and a `mode="after"` validator on
`FormatversionEntry` normalises `None` to efoli's date and **rejects** a hand-written
date that disagrees. All three spec guarantees hold: derived (absent → efoli), loud
drift rejection (mismatch → `ValueError` naming efoli), and `model_dump()`/`write_json`
still emit the date (it is a plain field, so the webapp twin and the JSON round-trip
keep working untouched). `_consistent` and `in_force` are literally unchanged — the
field remains an ISO string, so their string comparisons still type-check. Using efoli's
`>=2.4.1` floor (not `==`) matches the repo's dependency style and lets "bump efoli"
upgrade dates without editing makoralle.

- [ ] **Step 3.1: Branch**

```bash
git checkout main && git pull origin main && git checkout -b feat/79-efoli-gueltig-ab
```

- [ ] **Step 3.2: Add the dependency**

```bash
uv add "efoli>=2.4.1"
uv run python -c "from efoli import EdifactFormatVersion, get_edifact_format_version_valid_from; print(get_edifact_format_version_valid_from(EdifactFormatVersion('FV2504')))"
```

Expected: `2025-06-06`. (efoli pulls in `pytz` — mention the new transitive dependency in the PR body.)

- [ ] **Step 3.3: Write the failing tests**

Append to `unittests/test_formatversion_model.py` (extend the existing `makoralle.models.formatversion` import with `FormatversionEntry`):

```python
def test_gueltig_ab_is_derived_from_efoli_when_absent() -> None:
    """The table no longer carries hand-maintained dates: efoli is the source of truth."""
    assert FormatversionEntry(fv="FV2510", quelle="x").gueltig_ab == "2025-10-01"
    assert FormatversionEntry(fv="FV2604").gueltig_ab == "2026-04-01"
    assert FormatversionEntry(fv="FV2610").gueltig_ab == "2026-10-01"


def test_a_hand_written_date_that_disagrees_with_efoli_is_rejected() -> None:
    with pytest.raises(ValidationError, match="efoli"):
        FormatversionEntry(fv="FV2510", gueltig_ab="2025-10-02")


def test_an_fv_efoli_does_not_know_is_rejected() -> None:
    with pytest.raises(ValidationError, match="bump efoli"):
        FormatversionEntry(fv="FV2704")


def test_fv2104_whose_start_efoli_does_not_know_is_rejected() -> None:
    """efoli knows FV2104 but not its start date — the same loud failure, not a KeyError."""
    with pytest.raises(ValidationError, match="bump efoli"):
        FormatversionEntry(fv="FV2104")


def test_the_drift_check_runs_before_the_table_checks() -> None:
    """Entry validation precedes the table's sorted/unique check: the drift error wins."""
    with pytest.raises(ValidationError, match="efoli"):
        Formatversionen.model_validate(
            {
                "default": "FV2510",
                "bundles": [
                    {"fv": "FV2604", "gueltig_ab": "2026-04-02"},
                    {"fv": "FV2510", "gueltig_ab": "2025-10-01"},
                ],
            }
        )


def test_a_derived_table_dumps_and_round_trips() -> None:
    table = Formatversionen(default="FV2604", bundles=[{"fv": "FV2604"}, {"fv": "FV2610"}])
    dumped = table.model_dump(mode="json")
    assert dumped["bundles"][0]["gueltig_ab"] == "2026-04-01"
    assert Formatversionen.model_validate(dumped) == table
```

And fix the pre-existing trip-wire the reviewer found: in `test_bundles_are_sorted_and_unique`, change the "twice" case's second date `"2025-10-02"` → `"2025-10-01"` (a wrong date now dies in the drift check before `_consistent` sees the duplicates; the case only needs a duplicate name, and an efoli-agreeing date lets it reach the right error).

```bash
PYTHONUTF8=1 uv run pytest unittests/test_formatversion_model.py -q
```

Expected: the five new tests FAIL (`gueltig_ab` currently required / no efoli logic); the tweaked "twice" case still passes.

- [ ] **Step 3.4: Implement in `src/makoralle/models/formatversion.py`**

- Imports:

```python
from efoli import EdifactFormatVersion, get_edifact_format_version_valid_from
```

- Module docstring: replace the last sentence ("The dates are curated, not derived from the name: FV2504 started on 2025-06-06, not 2025-04-01.") with: "The dates come from efoli (Hochfrequenz), which encodes them: FV2504 became valid on 2025-06-06, not 2025-04-01. A hand-written `gueltig_ab` that disagrees with efoli is rejected — to move a date, bump efoli, not this table."
- Add the lookup helper (before `FormatversionEntry`):

```python
def _efoli_gueltig_ab(fv: str) -> str:
    """The FV's start date as efoli encodes it, as an ISO string.

    Both failure modes are wrapped so the message tells the reader what to do: an FV
    efoli's enum does not know (a future ``FV2704``) and one whose start efoli leaves
    undefined (``FV2104``) both raise ``ValueError`` — makoralle never silently
    tolerates an unknown bundle, because coupling dataset validity to efoli releases
    is the point (makoralle#79).
    """
    try:
        version = EdifactFormatVersion(fv)
    except ValueError as e:
        raise ValueError(f"{fv} is not known to efoli — bump efoli") from e
    try:
        return get_edifact_format_version_valid_from(version).isoformat()
    except KeyError as e:
        raise ValueError(f"{fv}: efoli knows the version but not its start date — bump efoli") from e
```

- `FormatversionEntry`: field becomes optional, plus the validator:

```python
class FormatversionEntry(BaseModel):
    """One row of the table: the bundle's name, from when it is in force, and who says so.

    ``gueltig_ab`` is derived from efoli and may be omitted; a hand-written date is
    accepted only where it agrees with efoli, so curation drift cannot happen quietly
    (makoralle#79). ``quelle`` records who listed the bundle — not the date.
    """

    fv: Formatversion
    gueltig_ab: IsoDate | None = None
    quelle: str = ""

    @model_validator(mode="after")
    def _from_efoli(self) -> Self:
        expected = _efoli_gueltig_ab(self.fv)
        if self.gueltig_ab is not None and self.gueltig_ab != expected:
            raise ValueError(
                f"{self.fv}: gueltig_ab {self.gueltig_ab!r} disagrees with efoli ({expected}) — "
                "efoli is the source of truth; bump efoli, not this table"
            )
        self.gueltig_ab = expected
        return self
```

- `IsoDate` is already importable from `makoralle.models.source` (extend the existing import there).
- `in_force`, `_consistent`, `load_*`, `write_json`: **no changes**.
- Ordering guarantee (pinning test 5): pydantic validates nested entries before the parent `model_validator(mode="after")` on `Formatversionen`, so a doubly-bad table raises the drift error first.

```bash
PYTHONUTF8=1 uv run pytest unittests/test_formatversion_model.py -q
```

Expected: all green.

- [ ] **Step 3.5: Full gates + shipped-data sanity**

```bash
PYTHONUTF8=1 uv run pytest -q
uv run ruff check src/makoralle unittests && uv run ruff format --check .
uv run mypy --show-error-codes src/makoralle --strict && uv run mypy --show-error-codes unittests --strict
```

Expected: suite as baseline; ruff/mypy clean. (The shipped dataset's table — FV2510 `2025-10-01`, FV2604 `2026-04-01`, FV2610 `2026-10-01`, verified against efoli 2.4.1 at tag v0.0.37 — loads unchanged.)

- [ ] **Step 3.6: Commit, push, PR**

```bash
git add -A
git commit -m "feat(models): derive gueltig_ab from efoli"
git push -u origin feat/79-efoli-gueltig-ab
gh pr create --title "feat(models): derive gueltig_ab from efoli" --body "<body below>"
```

PR body:

```markdown
`formatversionen.yaml`'s `gueltig_ab` dates were hand-maintained and the docstring said
so ("curated, not derived"). This makes efoli the source of truth instead: the dates are
derived from efoli's `get_edifact_format_version_valid_from`, and a table that carries a
hand-written date disagreeing with efoli is rejected loudly, naming efoli — curation
drift becomes impossible rather than detectable.

**Evidence the shipped data survives:** the dataset's `formatversionen.yaml` at tag
v0.0.37 carries FV2510 → 2025-10-01, FV2604 → 2026-04-01, FV2610 → 2026-10-01 — all
agree with efoli 2.4.1, and its `quelle` strings already say "abgeleitet aus efoli
v2.3.4". The hand-derivation this table documented is now enforced code.

**Semantics kept loud:** an FV efoli does not know (future FV2704) and FV2104 (whose
start efoli leaves undefined) both raise with "bump efoli" — dataset snapshots newer
than the installed efoli fail validation until efoli is bumped. That coupling is the
point of this change. `in_force` and the table's sorted/unique checks are unchanged;
`gueltig_ab` stays an ISO string, so `write_json` and the stdlib webapp twin are
untouched. FV2610's date is a forecast per the dataset's own comment: if BDEW
postpones it, the fix is an efoli release, then a dataset regen — not a table edit.

New dependency: `efoli>=2.4.1` (floor pin, matching repo style, so bumping efoli
upgrades dates without a makoralle edit; pulls in `pytz` transitively).

Fixes #79
```

- [ ] **Step 3.7: Review loop** (exactly Step 1.5) → **Step 3.8: squash-merge and reset** (exactly Step 1.6).

---

## Task 4: PR 4 — #36 record the decided ref-step split (docs-only)

**Files:**
- Modify: `src/makoralle/models/process.py:71-93` (`is_ref_step` docstring)
- Modify: `src/makoralle/serialization/wsd.py:489-497` (comment)
- Branch: `docs/36-record-ref-split-decision`
- PR title: `docs(models): record makoralle#36's decision to keep the ref-step split`

- [ ] **Step 4.1: Branch** (as Steps 1.1/2.1, branch `docs/36-record-ref-split-decision`)

- [ ] **Step 4.2: Update `is_ref_step`'s docstring**

Two edits, no output change:

1. "The *shape* of a fully readable ref step is a separate question, and the two emitters **still differ** there:" → "The *shape* of a fully readable ref step is a separate question, and the two emitters **differ there by decision** (makoralle#36):" (rest of that sentence unchanged).
2. Final sentence: "…which is a decision about what the diagram should say rather than a cleanup: makoralle#36." → "…which makoralle#36 decided: the split stays — a readable `ref` names its receiver in prose on WSD's single-lifeline self-message, and Mermaid draws the arrow the title spells out."

- [ ] **Step 4.3: Update the `wsd.py` comment (lines ~489–497)**

"Unifying the shape for readable steps is a separate question, filed as makoralle#36." → "Unifying the shape for readable steps was decided against in makoralle#36: the split is deliberate."

- [ ] **Step 4.4: Prove the output is unchanged, then gates**

```bash
PYTHONUTF8=1 uv run pytest unittests/test_p17_emit_wsd.py unittests/test_p15_emit_markdown.py -q
PYTHONUTF8=1 uv run pytest -q
uv run ruff check src/makoralle unittests && uv run ruff format --check .
uv run mypy --show-error-codes src/makoralle --strict
```

Expected: the shape-pinning tests (WSD self-messages, the 7 Mermaid arrows, "Subprocess call" note) pass untouched; suite as baseline; ruff/mypy clean.

- [ ] **Step 4.5: Commit, push, PR**

```bash
git add -A
git commit -m "docs(models): record makoralle#36's decision to keep the ref-step split"
git push -u origin docs/36-record-ref-split-decision
gh pr create --title "docs(models): record makoralle#36's decision to keep the ref-step split" --body "<body below>"
```

PR body:

```markdown
#36 asked whether a `ref` step naming **both** endpoints is a self-message on the
invoking lane or an arrow to the named one, and required the emitters to agree or the
docstring to stop claiming they do. Decision: **keep the split, on the record.**

- `emit_wsd` keeps drawing the readable `"ref "` step as a self-message on the sender
  (a ref is a subprocess box on one lifeline; Vision's extraction unanimously emits
  single-lane self-messages for refs — five cache entries, two model versions).
- The Mermaid emitter keeps drawing `sender → receiver` plus the subprocess note when
  the ref title names the receiver explicitly (7 shipped arrows say *"vom BIKO an NB"*).
- Where an endpoint was **not** read at all, both already agree via the #78 rule:
  self-message on the lane that *is* named.

`is_ref_step`'s docstring and the WSD emitter's comment now state this as a settled
decision (makoralle#36) instead of an open question. Docs-only: the shape-pinning tests
(`test_p17_emit_wsd.py`, `test_p15_emit_markdown.py`) pass untouched — no serialised
output changes. makorele#164 (lane placement for unread-endpoint refs) is unaffected.

Fixes #36
```

- [ ] **Step 4.6: Review loop** (exactly Step 1.5) → **Step 4.7: squash-merge and reset** (exactly Step 1.6).

---

## Task 5: Release v0.1.0 (minor, auto-generated notes)

- [ ] **Step 5.1: Confirm all four PRs are squash-merged to main**

```bash
git checkout main && git pull origin main
gh pr list --state open          # expect: empty
gh log --oneline -8              # the four squash commits on top of the spec commit
```

- [ ] **Step 5.2: Tag and create the GitHub release**

hatch-vcs derives the version from the tag, so `v0.1.0` → package version `0.1.0`.
Semver check: #81 removes a public alias/property (breaking) — in `0.x`, a minor bump is the conventional carrier for breaking changes; this is the first release after v0.0.24 and carries #67 (fix), #79 (feature), #36 (docs) besides.

```bash
git tag v0.1.0 && git push origin v0.1.0
gh release create v0.1.0 --verify-tag --generate-notes --title "v0.1.0"
```

`--generate-notes` produces GitHub's auto-generated notes (PR titles + contributors) — per the user's request.

- [ ] **Step 5.3: Poll the publish pipeline until green**

The `release: created` event triggers `.github/workflows/python-publish.yml` (tests → ruff → mypy → coverage → `uv build` → PyPI trusted publishing, environment `release`).

```bash
gh run list --workflow=python-publish.yml --limit 1
gh run watch <run-id> --exit-status
```

Expected: the run completes green.

- [ ] **Step 5.4: Verify the publication**

```bash
curl -s https://pypi.org/pypi/makoralle/json | grep -o '"version":"[^"]*"' | head -1
```

Expected: `"version":"0.1.0"`. If the publish job failed, read its logs (`gh run view <run-id> --log-failed`), fix on a new PR, re-release.

---

## Task 6: Handoff to makorele

After the release is green: switch to `C:\github\makorele` and repeat the same manner (pull → read open issues → brainstorm → one reviewed PR per issue), **restricted to the clearly-refined, decision-free issues** from the classification pass (delivered separately; saved in session memory `work-queue-makoralle-then-makorele.md`). Do not start this task until Step 5.4 passes.

**Unattended-work protocol (user is away, effective now):** do not wait for the user with questions; make the reasonable call and proceed. If a PR blocks (review loop can't complete, CI fails for external reasons, a decision is genuinely needed), post a blocker comment on that issue/PR (self-reviewed before posting: what was attempted, what failed, where exactly work stranded), then **switch to the next topic in the queue** and continue. After makorele's refined issues are done — or if none remain actionable — create a new makorele release the same way (auto-generated notes; check makorele's own release workflow before tagging).
