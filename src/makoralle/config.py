"""Static configuration constants for makoralle (AHB deep-link URL template)."""

# Per-Prüfidentifikator deep link to the Hochfrequenz AHB tables.
# `current` resolves to whatever the newest published Formatversion is, so links
# in generated artifacts keep working when a new FV lands. Pinning the FV instead
# (this was "FV2604") froze every rendered viewer and markdown file to the version
# it happened to be generated with, and those links go stale without anything
# noticing. {pid} is the 5-digit Prüfidentifikator.
AHB_PID_URL = "https://ahb-tabellen.hochfrequenz.de/ahb/current/{pid}"
