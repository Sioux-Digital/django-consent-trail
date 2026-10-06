# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.1.0] — 2026-10-06

First release on PyPI.

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
- Translations for the package's own UI strings, shipped in
  `consent_trail/locale/` (fr, es, ja). Django merges an installed app's
  catalogue automatically, so a host project configures nothing — and can
  override any single string from its own `LOCALE_PATHS`.

### Fixed
- The prevalence notice hardcoded the word "French" in its msgid, so setting a
  different authoritative language changed which document was served while the
  notice kept telling the reader that French prevailed. It now names the
  configured language, written in the reader's own language — a Japanese reader
  reading German terms is told "ドイツ語". A legal notice must not state
  something the configuration contradicts.

### Changed
- `CONSENT_TRAIL_FALLBACK_LANGUAGE` is now
  `CONSENT_TRAIL_AUTHORITATIVE_LANGUAGE`. It always carried both meanings — the
  text that legally prevails, and therefore the one to fall back to — and the
  old name only described the second. Renamed before the first release rather
  than carrying a misleading name through a deprecation cycle.
