"""The Sparte (energy carrier) a process belongs to."""

from typing import Literal

#: ``strom`` or ``gas``, lower case. A process gets one from the document it was cut from
#: (``Bundle.sparten``) or a per-process override (``Bundle.sparte_overrides``); a consumer picks
#: the process for a message by the message's Sparte, because WiM Strom and WiM Gas share PIDs.
Sparte = Literal["strom", "gas"]
