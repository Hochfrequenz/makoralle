"""The EBD flowchart's colours come from the palette, not from raw red and green (makoralle#23).

These four are the one place in this repo where colour carries meaning, so the #38 sweep that mapped
the sequence diagrams to brand lila deliberately skipped them: green = accept and red = reject on a
decision tree, and recolouring that destroys the reading. What they *can* be is the palette's own
semantic family — `--color-positive*`, `--color-negative*`, `--color-neutral*` — which exists for
exactly this.

Two things are pinned here. The values, because a hex nobody asserts drifts back; and the *contrast*
relation, because the obvious mapping (light fill, base stroke) would have left `accept` exactly as
invisible as the raw pair it replaces and made `reject` worse than its raw pair. The dark tokens are
a decision, not a default, and the ratio assertions are what make it one.
"""

from typing import Any

import pytest

from makoralle.serialization.markdown import _OUTCOME_CLASS, OUTCOME_STYLES, _render_ebd_flowchart

#: The tokens each class is built from, so the test names the palette rather than repeating a hex.
TOKENS = {
    "accept": ("--color-positive-light", "#b9cf85", "--color-positive-dark", "#44541f"),
    "reject": ("--color-negative-light", "#ffaaac", "--color-negative-dark", "#6d292b"),
    "info": ("--color-neutral-light", "#ffd495", "--color-neutral-dark", "#68491a"),
    "unknown": ("--neutral-grau", "#e7e6e5", "--weiches-schwarz", "#25141d"),
}
#: What shipped before, in dataset v0.0.15: 155 occurrences of each of the first two, across the 47
#: of 194 markdown files that carry a flowchart.
OFF_PALETTE = ("#ffcccc", "#cc0000", "#ccffcc", "#00cc00", "#e8eefc", "#5b7fbd", "#eeeeee", "#999999")


def _relative_luminance(colour: str) -> float:
    channels = [int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4) for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(one: str, other: str) -> float:
    first, second = _relative_luminance(one), _relative_luminance(other)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _flowchart() -> list[str]:
    """A tree that really produces one outcome node per class.

    The field names matter: `_render_ebd_flowchart` reads `check` / `if_yes_code` / `if_yes_cluster`,
    not `question` / `branches`. An invented shape renders a single questionless node and *no*
    outcomes — so the `classDef` header still prints and the assertions below pass while proving
    nothing about a node ever carrying the class. Copilot caught exactly that.
    """
    steps = [
        {
            "nr": 10 * (index + 1),
            "check": f"Frage {index}?",
            "if_yes_code": f"A0{index}",
            "if_yes_cluster": cluster,
            "if_no": 10 * (index + 2),
        }
        for index, cluster in enumerate(("Zustimmung", "Ablehnung", "Änderung der Daten", None))
    ]
    return _render_ebd_flowchart({"steps": steps})


@pytest.mark.parametrize("name", sorted(TOKENS))
def test_each_outcome_class_is_built_from_its_palette_tokens(name: str) -> None:
    fill_token, fill, stroke_token, stroke = TOKENS[name]
    assert OUTCOME_STYLES[name] == f"fill:{fill},stroke:{stroke}", (fill_token, stroke_token)


@pytest.mark.parametrize("name", sorted(TOKENS))
def test_each_class_reaches_the_rendered_flowchart(name: str) -> None:
    """Defined *and* applied: a `classDef` nobody references colours nothing."""
    rendered = _flowchart()
    assert f"    classDef {name} {OUTCOME_STYLES[name]}" in rendered
    assert [line for line in rendered if f":::{name}" in line], rendered


def test_no_off_palette_colour_survives() -> None:
    """The eight raw values this replaces, none of which belongs to any Hochfrequenz palette."""
    rendered = "\n".join(_flowchart())
    assert not [colour for colour in OFF_PALETTE if colour in rendered]


@pytest.mark.parametrize(("name", "floor"), [("accept", 4.0), ("reject", 4.0), ("info", 4.0)])
def test_a_coloured_outcome_is_legible_against_its_own_fill(name: str, floor: float) -> None:
    """The base token would give 1.94 / 1.42 / 1.31 — the mapping the issue proposed, and the reason
    the dark token is used instead. Anything above 4 is better than every pair that shipped."""
    fill, stroke = (part.split(":", 1)[1] for part in OUTCOME_STYLES[name].split(","))
    assert _contrast(fill, stroke) > floor


def test_the_uncoloured_outcome_is_the_one_that_may_be_loud() -> None:
    """`unknown` means the source classified nothing, so it gets ink rather than a hue — and the
    palette has no faint-but-visible grey stroke, so the choice is between invisible and dark."""
    fill, stroke = (part.split(":", 1)[1] for part in OUTCOME_STYLES["unknown"].split(","))
    assert stroke == "#25141d"
    assert _contrast(fill, stroke) > 10


def test_every_outcome_kind_has_a_style() -> None:
    """`_OUTCOME_CLASS` maps the EBD's own cluster vocabulary onto these classes; a kind with no
    classDef renders as an unstyled node, which reads as "no outcome" rather than as its own."""
    assert set(_OUTCOME_CLASS.values()) <= set(OUTCOME_STYLES)
