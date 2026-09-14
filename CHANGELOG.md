# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Versioned, multilingual legal documents (`LegalDocument`).
- Timestamped proof of acceptance (`Acceptance`) keyed on `(doc_type, version)`
  rather than a foreign key, so consent is independent of the language shown.
- Per-version `requires_reacceptance` flag: publish a typo fix without walling
  off every user at their next login.
- Middleware forcing re-acceptance, with configurable exempt paths.
- Public document pages with language fallback and a prevalence notice.
- Signup consent form hook.
- Client IP read from a configurable header, for proof behind a reverse proxy.
- HTML sanitization via nh3 on write and on render.
- Audience targeting via a pluggable resolver, so re-acceptance can be aimed at
  a subset of users without this package knowing what an organisation is.
- `/my-consents/` page listing what a user accepted and when.
- Admin view of users who have *not* accepted the current version.
- Acceptance screen renders documents inline in scrollable panes and only
  enables the checkbox once each has been read to the end.
- Settings are resolved lazily, so `override_settings` works in a host
  project's test suite.
