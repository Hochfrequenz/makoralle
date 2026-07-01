"""Static configuration constants for makoralle (AHB deep-link URL template)."""

# Per-Prüfidentifikator deep link to the Hochfrequenz AHB tables.
# FV2604 is the format version; {pid} is the 5-digit Prüfidentifikator.
AHB_PID_URL = "https://ahb-tabellen.hochfrequenz.de/ahb/FV2604/{pid}"
