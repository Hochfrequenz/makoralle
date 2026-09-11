"""Static configuration constants for makoralle (AHB deep links to the Prüfidentifikator tables)."""

import re

# A Formatversion's name: "FV" + YYMM. The one definition — the pydantic `Formatversion` type is built
# from it too, so the model and the link guard cannot drift apart. Kept here, not in the models, so this
# module stays stdlib-only and importable from anywhere without a cycle.
FORMATVERSION_PATTERN = r"^FV\d{4}$"

_AHB_BASE = "https://ahb-tabellen.hochfrequenz.de/ahb/"

# Per-Prüfidentifikator deep link to the Hochfrequenz AHB tables, for records that belong to no
# Formatversion. `current` resolves to whatever the newest published Formatversion is, so links
# in generated artifacts keep working when a new FV lands. Pinning the FV here instead (this was
# "FV2604") froze every rendered markdown file to the version it happened to be generated with,
# and those links go stale without anything noticing. A record that *does* belong to a bundle is
# pinned on purpose — that form lives in `ahb_pid_url`. {pid} is the 5-digit Prüfidentifikator.
AHB_PID_URL = _AHB_BASE + "current/{pid}"


def ahb_pid_url(pid: int | str, formatversion: str | None = None) -> str:
    """Deep link to a Prüfidentifikator in the AHB tables.

    ``current`` when the record belongs to no Formatversion (the reason AHB_PID_URL is not
    pinned: an unbundled artifact would freeze to the FV of its render day). Inside a bundle
    the link is pinned on purpose — that corpus *is* that Formatversion. Empty means unbundled; anything
    else that is not a Formatversion raises rather than falling back to ``current``, which inside a
    bundle would silently link the newest FV's tables.
    """
    if formatversion:
        if not re.fullmatch(FORMATVERSION_PATTERN, formatversion):
            raise ValueError(f"not a Formatversion (expected FV + 4 digits, e.g. FV2604): {formatversion!r}")
        return f"{_AHB_BASE}{formatversion}/{pid}"
    return AHB_PID_URL.format(pid=pid)
