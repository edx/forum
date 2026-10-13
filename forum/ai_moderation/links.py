"""
Removal of trusted links from content before it is classified.

The classifier only ever sees the text of a post, never the course it was
posted in, so it cannot tell a learner sharing their CodePen in a CSS course
from someone dropping a link to advertise. Links to the domains a deployment
trusts are therefore taken out before classification. Everything else in the
post is still classified, so adding a trusted link to a scam does not get it
through, and a link to any other domain is left for the classifier to judge.
"""

import re
from functools import lru_cache
from typing import Iterable, Optional, Pattern

# An HTML anchor, as written by the discussions editor. An anchor pointing at a
# trusted domain is replaced by its text, so the classifier is not left looking
# at an empty link.
_ANCHOR_RE = re.compile(
    r"<a\b[^>]*?\bhref\s*=\s*([\"'])(?P<href>.*?)\1[^>]*>(?P<text>.*?)</a\s*>",
    re.IGNORECASE | re.DOTALL,
)

# Markup that carries nothing to classify: tags without attributes, such as the
# <p> and <br> wrapping a post. A tag with attributes, like an <img src=...>,
# is content in its own right.
_BARE_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*\s*/?>")


@lru_cache(maxsize=8)
def _trusted_link_pattern(domains: tuple[str, ...]) -> Optional[Pattern[str]]:
    """
    Build a pattern matching a URL on any of ``domains``, or a subdomain of one.

    The host has to end exactly at the trusted domain, so ``codepen.io`` matches
    neither ``codepen.io.example.com`` nor ``notcodepen.io``. The scheme is
    optional because learners often type ``codepen.io/...`` without one.
    """
    names = sorted(
        {domain.strip().strip(".").lower() for domain in domains if domain.strip()},
        key=len,
        reverse=True,
    )
    if not names:
        return None

    hosts = "|".join(re.escape(name) for name in names)
    return re.compile(
        rf"(?<![\w.@-])(?:(?:https?:)?//)?(?:[\w-]+\.)*(?:{hosts})(?::\d+)?"
        rf"(?![\w-]|\.[\w-])(?:[/?#][^\s<>\"']*)?",
        re.IGNORECASE,
    )


def strip_trusted_links(content: str, trusted_domains: Optional[Iterable[str]]) -> str:
    """
    Remove every link to a trusted domain from ``content``.

    Args:
        content: The text about to be classified. May contain HTML.
        trusted_domains: Domains whose links, including links to their
            subdomains, are removed.

    Returns:
        ``content`` without the trusted links. Links to any other domain, and
        all other text, are left exactly as they were.
    """
    if not content or not trusted_domains:
        return content

    pattern = _trusted_link_pattern(tuple(trusted_domains))
    if pattern is None:
        return content

    def unwrap_trusted_anchor(match: "re.Match[str]") -> str:
        if pattern.fullmatch(match.group("href").strip()):
            return match.group("text")
        return match.group(0)

    content = _ANCHOR_RE.sub(unwrap_trusted_anchor, content)
    return pattern.sub("", content)


def is_blank(content: str) -> bool:
    """Return whether ``content`` holds nothing but whitespace and bare tags."""
    text = _BARE_TAG_RE.sub("", content or "").replace("&nbsp;", " ")
    return not text.strip()
