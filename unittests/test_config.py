import re

from makoralle.config import AHB_PID_URL


def test_ahb_deep_link_is_not_pinned_to_a_formatversion() -> None:
    """AHB links must target `current`, not a frozen Formatversion.

    A pinned FV (this was FV2604) freezes every generated viewer and markdown file
    to whatever version it was rendered with, and the links rot silently when the
    next FV publishes. Both the markdown serializer here and makorele's
    sequence-diagram viewer template read this one constant, so this is the single
    place the whole pipeline can regress.

    The `/FV\\d+/` check is redundant while the equality assertion stands — nothing
    can satisfy that and still contain an FV segment. It is kept because it encodes
    the actual rule ("never pin a Formatversion") rather than one exact string: a
    legitimate future edit, say moving the host, would update the equality and this
    would go on guarding the part that matters.
    """
    assert AHB_PID_URL == "https://ahb-tabellen.hochfrequenz.de/ahb/current/{pid}"
    assert not re.search(r"/FV\d+/", AHB_PID_URL)
