"""Static configuration constants for makoralle (AHB deep links to the Prüfidentifikator tables)."""

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
    the link is pinned on purpose — that corpus *is* that Formatversion.
    """
    if formatversion:
        return f"{_AHB_BASE}{formatversion}/{pid}"
    return AHB_PID_URL.format(pid=pid)
