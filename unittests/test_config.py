import re

from makoralle.config import AHB_PID_URL


def test_ahb_deep_link_is_not_pinned_to_a_formatversion() -> None:
    """AHB links must target `current`, not a frozen Formatversion.

    A pinned FV (this was FV2604) freezes every generated viewer and markdown file
    to whatever version it was rendered with, and the links rot silently when the
    next FV publishes. Both the markdown serializer here and makorele's
    sequence-diagram viewer template read this one constant, so this is the single
    place the whole pipeline can regress.

    The `/FV\\d+/` check is not redundant with the equality above: it also rejects
    a value that keeps `current` but reintroduces an FV segment beside it.
    """
    assert AHB_PID_URL == "https://ahb-tabellen.hochfrequenz.de/ahb/current/{pid}"
    assert not re.search(r"/FV\d+/", AHB_PID_URL)
