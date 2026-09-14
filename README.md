# django-consent-trail

Versioned, multilingual legal documents for Django — with timestamped proof of
**who accepted what, and when**.

> Status: **alpha**, private. The API may still change without notice.

## Why another one

Two good packages already exist — [django-termsandconditions][tc] and
[django-tos][tos]. Both were evaluated and run against Django 6 before this one
was written. Two gaps drove the decision:

**1. Neither has any concept of language.** The only multilingual path is one
slug per language, but acceptance is a foreign key to one specific row — so a
user who accepts the terms in French and then switches the UI to English reads
as never having accepted. That is wrong: you accept *the document*, not *a
translation of it*.

`consent_trail` stores acceptance as the coordinates `(doc_type, version)`.
Version numbers are shared across languages, so consent survives a language
switch.

**2. Neither can publish a cosmetic edit without re-prompting everyone.**
Fixing a typo would wall off every user at their next login. Here,
`requires_reacceptance` is a per-version flag: substantive change, everyone
re-accepts; typo fix, nobody is disturbed.

`django-tos` additionally enforces exactly one globally active document, so it
cannot hold a legal notice *and* a privacy policy *and* terms of use.

[tc]: https://github.com/cyface/django-termsandconditions
[tos]: https://github.com/revsys/django-tos

## Install

```bash
pip install django-consent-trail
```

```python
# settings.py
INSTALLED_APPS = [
    ...,
    "consent_trail.apps.ConsentTrailConfig",
]

MIDDLEWARE = [
    ...,
    # Last: getting a user through signup and 2FA matters more than a terms update.
    "consent_trail.middleware.AcceptanceMiddleware",
]
```

```python
# urls.py
path("legal/", include("consent_trail.urls")),
```

```bash
python manage.py migrate
```

## Settings

Every one is optional.

| Setting | Default | What it does |
|---|---|---|
| `CONSENT_TRAIL_BASE_TEMPLATE` | `"consent_trail/base.html"` | Template the public pages extend. Point it at your own layout. |
| `CONSENT_TRAIL_FALLBACK_LANGUAGE` | `"fr"` | Served when the requested language has no published version. |
| `CONSENT_TRAIL_IP_HEADER_NAME` | `"HTTP_CF_CONNECTING_IP"` | **Read this one.** See below. |
| `CONSENT_TRAIL_CACHE_SECONDS` | `300` | Caches "which documents currently require consent" — the middleware runs on every request. |
| `CONSENT_TRAIL_EXCLUDE_SUPERUSERS` | `True` | Never lock an admin out of their own site over a bad flag. |
| `CONSENT_TRAIL_EXEMPT_PREFIXES` | `("/legal/", "/accounts/", ...)` | Paths the middleware must not intercept. |
| `CONSENT_TRAIL_SANITIZER` | `"consent_trail.sanitizer.clean_html"` | Dotted path to `f(str) -> str`. |
| `CONSENT_TRAIL_ADMIN_EDITOR_CSS` / `_JS` | `()` | Static paths for a rich-text editor in the admin. Empty = plain textarea. |

### About the IP header

Behind a reverse proxy or a CDN, `REMOTE_ADDR` is the proxy, not the visitor.
Left unchanged, **every consent record stores the same wrong address**, which
makes the proof worthless the day it matters.

Set `CONSENT_TRAIL_IP_HEADER_NAME` to whatever your edge actually sends —
`HTTP_CF_CONNECTING_IP` behind Cloudflare, `HTTP_X_FORWARDED_FOR` behind most
others. Falls back to `REMOTE_ADDR` when the header is absent.

> Only trust a forwarding header you control end to end: a client can forge one
> if requests can reach your app without passing through your proxy.

## Consent at signup

With django-allauth:

```python
ACCOUNT_SIGNUP_FORM_CLASS = "consent_trail.forms.ConsentForm"
```

Any other stack: call `form.record_consent(user, request=request)` once the
user row exists. Validation is server-side — an HTML `required` attribute only
stops a browser.

## Data model

```
LegalDocument   doc_type, language, version, title, body_html,
                is_current, published_at,
                requires_acceptance, requires_reacceptance

Acceptance      user, doc_type, version,        # coordinates, not a FK
                language_shown, accepted_at, ip_address, user_agent
```

`(cgu, fr, 3)` and `(cgu, en, 3)` are the same document rendered twice.
Accepting version 3 satisfies both.

Policy fields belong to the *version*, not the translation — saving one
language row propagates them to its siblings so they cannot drift apart.

## Security

- Bodies are sanitized with [nh3][nh3] on write **and** on render.
- The allowlist is narrow on purpose: no `img`, no `iframe`, no `script`.
  A contract is text.
- Redirect targets are validated with `url_has_allowed_host_and_scheme`. The
  acceptance screen is seen by every user after an update, which makes it a
  prime phishing target.
- The acceptance log is read-only in the admin. It is evidence.

[nh3]: https://github.com/messense/nh3

## Tests

```bash
python tests/manage.py test tests
```

## License

MIT
