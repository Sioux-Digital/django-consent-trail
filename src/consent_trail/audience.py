"""Audience targeting.

A document may be aimed at a subset of users — one organisation, one plan, one
country. This package must never learn what those things are, so the mapping
"user -> audience tags" is supplied by the host project through
``CONSENT_TRAIL_AUDIENCE_RESOLVER``.

A document whose ``audience`` is empty applies to everyone. That is the default
and covers the common "make all users re-accept" case, so projects that do not
need targeting configure nothing.
"""

from django.utils.module_loading import import_string

from . import conf

def everyone(user):
    """Default resolver: no tags, so only untargeted documents apply."""
    return set()


def tags_for(user):
    """Audience tags this user belongs to, via the configured resolver."""
    try:
        resolver = import_string(conf.AUDIENCE_RESOLVER)
        return set(resolver(user) or ())
    except Exception:
        # A broken resolver must not lock every user out of the site. Falling
        # back to "no tags" means targeted documents are skipped, never that
        # someone is trapped on the acceptance screen with no way forward.
        return set()


def applies_to(document_audience, user_tags):
    """True when a document with ``document_audience`` targets these tags."""
    return not document_audience or document_audience in user_tags
