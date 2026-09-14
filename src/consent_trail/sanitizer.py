"""HTML sanitization for legal document bodies.

Deliberately separate from ``core.html_sanitizer``: that one filters ``img src``
down to the ticket-attachment endpoint, which would silently strip any image in
a legal document. Different content, different allowlist.

The editor is convenience only — this is the XSS boundary. Applied on WRITE
(admin form) *and* on RENDER, same belt-and-braces rule as the design notes.
"""

import nh3

#: Structural tags a legal document actually needs. No img, no iframe, no
#: form: a contract is text. Narrower allowlist = smaller attack surface.
ALLOWED_TAGS = {
    "p", "br", "strong", "em", "u", "s",
    "ul", "ol", "li", "blockquote",
    "h1", "h2", "h3", "h4",
    "a",
    "table", "thead", "tbody", "tr", "th", "td",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href"},
}

URL_SCHEMES = {"http", "https", "mailto"}


def clean_html(html):
    """Sanitize a legal document body; the result is safe to ``mark_safe``."""
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
