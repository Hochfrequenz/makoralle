import re

import pytest

from makoralle.config import AHB_PID_URL, ahb_pid_url


def test_without_a_formatversion_the_link_targets_current() -> None:
    """Unbundled artifacts must not freeze to whatever FV happened to be newest at render time.

    A pinned FV (this was FV2604) freezes every generated markdown file to whatever version it
    was rendered with, and the links rot silently when the next FV publishes. The markdown
    serializer is the only reader of this constant (the sequence-diagram SVGs are rendered with
    their own link template), so this is the one place that regression would show up.

    The `/FV\\d+/` check is redundant while the equality assertion stands — nothing can satisfy
    that and still contain an FV segment. It is kept because it encodes the actual rule ("never
    pin a Formatversion for an unbundled record") rather than one exact string: a legitimate
    future edit, say moving the host, would update the equality and this would go on guarding
    the part that matters.
    """
    assert AHB_PID_URL == "https://ahb-tabellen.hochfrequenz.de/ahb/current/{pid}"
    assert ahb_pid_url(55001) == "https://ahb-tabellen.hochfrequenz.de/ahb/current/55001"
    assert not re.search(r"/FV\d+/", AHB_PID_URL)


def test_with_a_formatversion_the_link_is_pinned_to_it() -> None:
    """Inside a bundle the pin is the point: the FV2604 corpus links the FV2604 tables."""
    assert ahb_pid_url(55001, "FV2604") == "https://ahb-tabellen.hochfrequenz.de/ahb/FV2604/55001"


def test_an_empty_formatversion_means_unbundled() -> None:
    """Empty is how a record says it belongs to no bundle, the same test ``process_to_yaml`` applies."""
    assert ahb_pid_url(1, "") == "https://ahb-tabellen.hochfrequenz.de/ahb/current/1"


@pytest.mark.parametrize("formatversion", ["fv2604", "FV 2604", "FV26", "FV2604\n"])
def test_a_malformed_formatversion_raises(formatversion: str) -> None:
    """Falling back to `current` here would link the newest FV's tables from inside a bundle."""
    with pytest.raises(ValueError, match=re.escape(repr(formatversion))):
        ahb_pid_url(55001, formatversion)
