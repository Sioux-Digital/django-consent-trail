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
