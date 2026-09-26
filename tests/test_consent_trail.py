"""Tests for the legal app.

Run with:  python tests/manage.py test tests
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from consent_trail.middleware import AcceptanceMiddleware
from consent_trail.models import Acceptance, LegalDocument, client_ip
from consent_trail.sanitizer import clean_html

User = get_user_model()


def make_doc(doc_type="cgu", language="fr", version=1, current=True, **kw):
    return LegalDocument.objects.create(
        doc_type=doc_type, language=language, version=version,
        title=f"{doc_type} {language} v{version}",
        body_html="<p>texte</p>", is_current=current, **kw,
    )


class ResolveTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_returns_requested_language(self):
        make_doc(language="fr")
        make_doc(language="en")
        doc, is_fallback = LegalDocument.resolve("cgu", "en")
        self.assertEqual(doc.language, "en")
        self.assertFalse(is_fallback)

    def test_falls_back_to_french_and_flags_it(self):
        make_doc(language="fr")
        doc, is_fallback = LegalDocument.resolve("cgu", "ja")
        self.assertEqual(doc.language, "fr")
        self.assertTrue(is_fallback)

    def test_a_regional_code_matches_its_base_language(self):
        """LANGUAGE_CODE is often "en-us"; documents are filed under "en"."""
        make_doc(doc_type="cgu", language="en")
        doc, is_fallback = LegalDocument.resolve("cgu", "en-us")
        self.assertEqual(doc.language, "en")
        self.assertFalse(is_fallback)

    def test_returns_none_when_nothing_published(self):
        doc, is_fallback = LegalDocument.resolve("cgv", "fr")
        self.assertIsNone(doc)
        self.assertFalse(is_fallback)


class VersioningTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_publishing_a_version_unsets_the_previous_one(self):
        v1 = make_doc(version=1)
        make_doc(version=2)
        v1.refresh_from_db()
        self.assertFalse(v1.is_current)

    def test_policy_fields_propagate_across_languages_of_one_version(self):
        fr = make_doc(language="fr", version=1)
        en = make_doc(language="en", version=1)
        fr.requires_reacceptance = True
        fr.save()
        en.refresh_from_db()
        self.assertTrue(
            en.requires_reacceptance,
            "policy belongs to the version, language rows must not drift",
        )

    def test_is_current_is_per_language(self):
        make_doc(language="fr", version=1)
        fr2 = make_doc(language="fr", version=2)
        en1 = make_doc(language="en", version=1)
        en1.refresh_from_db()
        self.assertTrue(en1.is_current, "publishing fr v2 must not unpublish en v1")
        self.assertTrue(fr2.is_current)


class AcceptanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("bob", password="x")

    def test_informational_documents_are_not_required(self):
        make_doc(doc_type="mentions", requires_acceptance=False)
        self.assertEqual(LegalDocument.acceptance_required(), {})

    def test_pending_until_accepted(self):
        make_doc(doc_type="cgu", version=1)
        self.assertEqual(Acceptance.pending_for(self.user), {"cgu": 1})
        Acceptance.record(self.user, "cgu", 1)
        self.assertEqual(Acceptance.pending_for(self.user), {})

    def test_a_substantive_new_version_makes_it_pending_again(self):
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        cache.clear()
        make_doc(doc_type="cgu", version=2, requires_reacceptance=True)
        self.assertEqual(Acceptance.pending_for(self.user), {"cgu": 2})

    def test_a_typo_fix_does_not_block_anyone(self):
        """The whole point of ``requires_reacceptance``.

        Without this, correcting a comma in the CGU walls every user of the site
        behind a consent screen. Previously asserted the opposite: a test named
        ``test_new_version_makes_it_pending_again`` published v2 with the flag
        left at its default and demanded re-acceptance, which is what let the
        defect ship — the flag was declared, propagated, exposed in the admin,
        and read by nothing.
        """
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        cache.clear()
        make_doc(doc_type="cgu", version=2)  # requires_reacceptance defaults False
        self.assertEqual(
            Acceptance.pending_for(self.user), {},
            "a non-substantive edit must not invalidate an existing consent",
        )

    def test_consent_stands_for_edits_published_after_a_substantive_one(self):
        """v2 substantive, accepted; v3 and v4 are typo fixes → still compliant."""
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        cache.clear()
        make_doc(doc_type="cgu", version=2, requires_reacceptance=True)
        Acceptance.record(self.user, "cgu", 2)
        cache.clear()
        make_doc(doc_type="cgu", version=3)
        make_doc(doc_type="cgu", version=4)
        cache.clear()
        self.assertEqual(Acceptance.pending_for(self.user), {})

    def test_a_missed_substantive_version_still_blocks_after_later_edits(self):
        """The trap: v2 was substantive and never accepted, v3 is a typo fix.

        Looking only at the current version's flag would let the user through
        having never consented to the substantive change.
        """
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        cache.clear()
        make_doc(doc_type="cgu", version=2, requires_reacceptance=True)
        cache.clear()
        make_doc(doc_type="cgu", version=3)
        cache.clear()
        self.assertEqual(
            Acceptance.pending_for(self.user), {"cgu": 3},
            "must still block, and on the CURRENT version — that is the text "
            "they have to be shown",
        )

    def test_a_brand_new_user_must_accept_even_with_no_flagged_version(self):
        make_doc(doc_type="cgu", version=1)
        make_doc(doc_type="cgu", version=2)
        cache.clear()
        self.assertEqual(Acceptance.pending_for(self.user), {"cgu": 2})

    def test_accepting_the_current_version_is_enough_when_it_is_flagged(self):
        make_doc(doc_type="cgu", version=1, requires_reacceptance=True)
        Acceptance.record(self.user, "cgu", 1)
        cache.clear()
        self.assertEqual(Acceptance.pending_for(self.user), {})

    def test_publishing_invalidates_the_floor_cache(self):
        """The floor is cached per doc_type; a stale floor silently unblocks."""
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        self.assertEqual(Acceptance.pending_for(self.user), {})  # primes the cache
        make_doc(doc_type="cgu", version=2, requires_reacceptance=True)
        self.assertEqual(
            Acceptance.pending_for(self.user), {"cgu": 2},
            "save() must drop the floor cache, without an explicit cache.clear()",
        )

    def test_acceptance_is_language_independent(self):
        """The design point behind building this instead of using a package.

        Accepting the French CGU must satisfy the requirement while the user
        browses in English — you accept the document, not a translation.
        """
        make_doc(doc_type="cgu", language="fr", version=1)
        make_doc(doc_type="cgu", language="en", version=1)
        Acceptance.record(self.user, "cgu", 1)
        self.assertEqual(Acceptance.pending_for(self.user), {})

    def test_record_is_idempotent(self):
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        Acceptance.record(self.user, "cgu", 1)
        self.assertEqual(Acceptance.objects.filter(user=self.user).count(), 1)


class ClientIpTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_reads_the_configured_header_not_remote_addr(self):
        req = self.rf.get("/", HTTP_CF_CONNECTING_IP="203.0.113.7", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(client_ip(req), "203.0.113.7")

    def test_falls_back_to_remote_addr(self):
        req = self.rf.get("/", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(client_ip(req), "10.0.0.1")

    def test_takes_the_first_hop_of_a_chained_header(self):
        req = self.rf.get("/", HTTP_CF_CONNECTING_IP="203.0.113.7, 70.41.3.18")
        self.assertEqual(client_ip(req), "203.0.113.7")


class MiddlewareTests(TestCase):
    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()
        self.user = User.objects.create_user("bob", password="x")
        self.mw = AcceptanceMiddleware(lambda r: "passed")

    def _get(self, path, user):
        req = self.rf.get(path)
        req.user = user
        return req

    def test_blocks_when_acceptance_is_pending(self):
        make_doc(doc_type="cgu", version=1)
        resp = self.mw(self._get("/dashboard/", self.user))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/consent/accept/", resp.url)

    def test_lets_through_once_accepted(self):
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        self.assertEqual(self.mw(self._get("/dashboard/", self.user)), "passed")

    def test_never_blocks_the_legal_pages_themselves(self):
        """Otherwise the redirect loops and the whole site is unreachable."""
        make_doc(doc_type="cgu", version=1)
        self.assertEqual(self.mw(self._get("/consent/cgu/", self.user)), "passed")
        self.assertEqual(self.mw(self._get("/consent/accept/", self.user)), "passed")

    def test_exemption_survives_the_i18n_language_prefix(self):
        make_doc(doc_type="cgu", version=1)
        self.assertEqual(self.mw(self._get("/fr/consent/cgu/", self.user)), "passed")
        self.assertEqual(self.mw(self._get("/ja/consent/cgu/", self.user)), "passed")

    def test_anonymous_visitors_are_never_blocked(self):
        make_doc(doc_type="cgu", version=1)

        class Anon:
            is_authenticated = False
            is_superuser = False

        self.assertEqual(self.mw(self._get("/", Anon())), "passed")

    @override_settings(CONSENT_TRAIL_EXCLUDE_SUPERUSERS=True)
    def test_superusers_are_excluded(self):
        make_doc(doc_type="cgu", version=1)
        su = User.objects.create_superuser("root", "root@example.com", "x")
        self.assertEqual(self.mw(self._get("/dashboard/", su)), "passed")


class SanitizerTests(TestCase):
    def test_strips_script(self):
        self.assertNotIn("<script", clean_html("<p>ok</p><script>alert(1)</script>"))

    def test_strips_event_handlers(self):
        self.assertNotIn("onerror", clean_html('<p onerror="alert(1)">x</p>'))

    def test_strips_images(self):
        """Legal documents are text; img is not in the allowlist."""
        self.assertNotIn("<img", clean_html('<p>x</p><img src="https://e.co/a.png">'))

    def test_keeps_structure_and_links(self):
        out = clean_html('<h2>T</h2><ul><li><a href="https://x.co">l</a></li></ul>')
        self.assertIn("<h2>", out)
        self.assertIn("<li>", out)
        self.assertIn('href="https://x.co"', out)

    def test_drops_javascript_urls(self):
        self.assertNotIn("javascript:", clean_html('<a href="javascript:alert(1)">x</a>'))


class DocumentViewTests(TestCase):
    """Exercises the templates for real — a syntax check proves much less."""

    def setUp(self):
        cache.clear()

    def test_anonymous_can_read_a_document(self):
        make_doc(doc_type="cgu", language="fr")
        resp = self.client.get("/consent/cgu/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cgu fr v1")

    def test_unknown_slug_is_404_not_500(self):
        self.assertEqual(self.client.get("/consent/nope/").status_code, 404)

    def test_unpublished_document_is_404(self):
        self.assertEqual(self.client.get("/consent/cgv/").status_code, 404)

    def test_fallback_shows_the_prevalence_notice(self):
        make_doc(doc_type="cgu", language="fr")
        with self.settings(LANGUAGE_CODE="ja"):
            resp = self.client.get("/consent/cgu/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "authoritative")

    def test_translation_says_it_is_not_the_binding_text(self):
        """Publishing a translation removes the fallback notice — something has
        to take its place, or the translated terms read as binding."""
        make_doc(doc_type="cgu", language="fr")
        make_doc(doc_type="cgu", language="en")
        with self.settings(LANGUAGE_CODE="en"):
            resp = self.client.get("/consent/cgu/")
        self.assertContains(resp, "information only")
        self.assertNotContains(resp, "not available in your language")

    def test_the_fallback_language_carries_no_notice(self):
        make_doc(doc_type="cgu", language="fr")
        with self.settings(LANGUAGE_CODE="fr"):
            resp = self.client.get("/consent/cgu/")
        self.assertNotContains(resp, "information only")
        self.assertNotContains(resp, "not available in your language")

    def test_body_is_sanitized_on_render(self):
        """Even if a row were tampered with directly in the DB."""
        doc = make_doc(doc_type="cgu", language="fr")
        LegalDocument.objects.filter(pk=doc.pk).update(
            body_html='<p>ok</p><script>alert(1)</script>'
        )
        resp = self.client.get("/consent/cgu/")
        self.assertNotContains(resp, "<script")


class AcceptViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("bob", password="pw")
        make_doc(doc_type="cgu", version=1)

    def test_requires_login(self):
        resp = self.client.get("/consent/accept/")
        self.assertEqual(resp.status_code, 302)

    def test_posting_no_document_records_nothing(self):
        """The HTML `required` attribute only stops a browser."""
        self.client.force_login(self.user)
        resp = self.client.post("/consent/accept/", {})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Acceptance.objects.count(), 0)

    def test_posting_a_document_that_is_not_pending_records_nothing(self):
        """A forged or stale doc_type must not create a phantom acceptance."""
        self.client.force_login(self.user)
        self.client.post("/consent/accept/", {"doc_type": "cgv"})
        self.assertEqual(Acceptance.objects.count(), 0)

    def test_the_consent_screen_flags_a_language_fallback(self):
        """Compact wording now, because the full notice lives on the document
        page the user is required to open. Previously this screen inlined the
        shared _language_notice.html; the caveat still travels with the binding
        text, it is simply no longer duplicated in a one-line list."""
        self.client.force_login(self.user)
        with self.settings(LANGUAGE_CODE="ja"):
            resp = self.client.get("/consent/accept/")
        self.assertContains(resp, "only the French version is binding")

    def test_signing_records_the_proof_and_returns_to_the_screen(self):
        """It no longer jumps straight to `next`: the user confirms with
        Continue, so signing several documents does not bounce them off after
        the first one."""
        self.client.force_login(self.user)
        resp = self.client.post(
            "/consent/accept/", {"doc_type": "cgu", "next": "/dashboard/"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/consent/accept/", resp.url)
        self.assertIn("next=%2Fdashboard%2F", resp.url)
        proof = Acceptance.objects.get(user=self.user, doc_type="cgu")
        self.assertEqual(proof.version, 1)
        self.assertIsNotNone(proof.accepted_at)

    def test_each_post_signs_one_document_only(self):
        """Why the timestamps end up genuinely different: one POST, one row.

        A single form over every document stamped them all the same second,
        which is a much weaker record than "privacy at 16:04, terms at 16:07".
        """
        make_doc(doc_type="cgv", version=1)
        cache.clear()
        self.client.force_login(self.user)

        self.client.post("/consent/accept/", {"doc_type": "cgu"})
        self.assertEqual(
            sorted(Acceptance.objects.values_list("doc_type", flat=True)), ["cgu"]
        )
        self.assertEqual(Acceptance.pending_for(self.user), {"cgv": 1})

        self.client.post("/consent/accept/", {"doc_type": "cgv"})
        self.assertEqual(
            sorted(Acceptance.objects.values_list("doc_type", flat=True)),
            ["cgu", "cgv"],
        )
        self.assertEqual(Acceptance.pending_for(self.user), {})

    def test_continue_is_inert_while_something_is_pending(self):
        self.client.force_login(self.user)
        resp = self.client.get("/consent/accept/")
        self.assertContains(resp, "disabled")
        self.assertContains(resp, "still needs your signature")

    def test_continue_becomes_a_link_once_everything_is_signed(self):
        self.client.force_login(self.user)
        self.client.post("/consent/accept/", {"doc_type": "cgu", "next": "/dashboard/"})
        resp = self.client.get("/consent/accept/?next=/dashboard/&signed=1")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'href="/dashboard/"')
        self.assertNotContains(resp, "still needs your signature")

    def test_nothing_to_sign_and_no_signature_just_made_leaves_the_screen(self):
        """Otherwise the URL is a dead end for anyone who lands on it."""
        self.client.force_login(self.user)
        Acceptance.record(self.user, "cgu", 1)
        resp = self.client.get("/consent/accept/?next=/inventory/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/inventory/")


class OpenRedirectTests(TestCase):
    """The acceptance screen is seen by every user after a terms update, so an
    unvalidated `next` is a first-rate phishing vector.

    The POST now returns to this screen rather than following `next`, so the
    hostile value has three places to leak from: the round-trip URL, the hidden
    input, and the Continue link. All three are checked."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("bob", password="pw")
        make_doc(doc_type="cgu", version=1)
        self.client.force_login(self.user)

    def _sign(self, next_value):
        return self.client.post(
            "/consent/accept/", {"doc_type": "cgu", "next": next_value}
        )

    def test_absolute_external_url_is_dropped_from_the_round_trip(self):
        resp = self._sign("https://evil.example/login")
        self.assertNotIn("evil.example", resp.url)

    def test_protocol_relative_url_is_dropped(self):
        resp = self._sign("//evil.example/login")
        self.assertNotIn("evil.example", resp.url)

    def test_javascript_scheme_is_dropped(self):
        resp = self._sign("javascript:alert(1)")
        self.assertNotIn("javascript", resp.url)

    def test_internal_path_is_kept(self):
        resp = self._sign("/inventory/")
        self.assertIn("next=%2Finventory%2F", resp.url)

    def test_hostile_next_never_reaches_the_hidden_input(self):
        resp = self.client.get("/consent/accept/?next=https://evil.example/login")
        self.assertNotContains(resp, "evil.example")

    def test_hostile_next_never_becomes_the_continue_link(self):
        Acceptance.record(self.user, "cgu", 1)
        resp = self.client.get(
            "/consent/accept/?signed=1&next=https://evil.example/login"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "evil.example")

    def test_the_leave_redirect_also_validates_next(self):
        Acceptance.record(self.user, "cgu", 1)
        resp = self.client.get("/consent/accept/?next=https://evil.example/login")
        self.assertEqual(resp.url, "/")


class RenderedCommentTests(TestCase):
    """No template comment may reach the browser.

    Django's short comment form spans ONE line only; written across several it is
    emitted verbatim. That shipped three times — on the signup page, on the
    layout bridge, and on the public legal documents, where visitors read
    paragraphs of developer prose in the middle of the terms. Structural checks
    all passed, because none of them looked at what the page actually says.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("bob", password="pw")

    def assertNoTemplateComment(self, resp, where):
        body = resp.content.decode("utf-8", "replace")
        for marker in ("{#", "#}", "{% comment", "endcomment %}"):
            self.assertNotIn(
                marker, body,
                f"{where}: {marker!r} reached the browser — a multi-line "
                f"short comment is rendered as text, use {{% comment %}}",
            )

    def test_document_page_is_clean(self):
        make_doc(doc_type="cgu", language="fr")
        self.assertNoTemplateComment(self.client.get("/consent/cgu/"), "/consent/cgu/")

    def test_document_page_is_clean_on_a_language_fallback(self):
        """_language_notice.html is where the worst offender lived."""
        make_doc(doc_type="cgu", language="fr")
        with self.settings(LANGUAGE_CODE="ja"):
            resp = self.client.get("/consent/cgu/")
        self.assertNoTemplateComment(resp, "/consent/cgu/ (fallback)")

    def test_acceptance_screen_is_clean(self):
        make_doc(doc_type="cgu", version=1)
        self.client.force_login(self.user)
        self.assertNoTemplateComment(
            self.client.get("/consent/accept/"), "/consent/accept/"
        )

    def test_my_consents_is_clean(self):
        make_doc(doc_type="cgu", version=1)
        self.client.force_login(self.user)
        self.assertNoTemplateComment(
            self.client.get("/consent/my-consents/"), "/consent/my-consents/"
        )


def exploding_resolver(user):
    raise RuntimeError("boom")


def resolver_org_a(user):
    """Test resolver: everyone called *_a belongs to org A."""
    return {"org:A"} if user.username.endswith("_a") else {"org:B"}


@override_settings(CONSENT_TRAIL_AUDIENCE_RESOLVER="tests.test_consent_trail.resolver_org_a")
class AudienceTests(TestCase):
    """Targeting a subset of users without the package knowing what an org is."""

    def setUp(self):
        cache.clear()
        self.alice = User.objects.create_user("alice_a", password="x")
        self.bob = User.objects.create_user("bob_b", password="x")

    def test_untargeted_document_applies_to_everyone(self):
        make_doc(doc_type="cgu", version=1)
        self.assertEqual(Acceptance.pending_for(self.alice), {"cgu": 1})
        self.assertEqual(Acceptance.pending_for(self.bob), {"cgu": 1})

    def test_targeted_document_only_applies_to_its_audience(self):
        make_doc(doc_type="cgv", version=1, audience="org:A")
        self.assertEqual(Acceptance.pending_for(self.alice), {"cgv": 1})
        self.assertEqual(Acceptance.pending_for(self.bob), {})

    def test_publishing_for_one_org_does_not_unpublish_another(self):
        a = make_doc(doc_type="cgu", version=1, audience="org:A")
        b = make_doc(doc_type="cgu", version=1, audience="org:B")
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertTrue(a.is_current)
        self.assertTrue(b.is_current, "org B's version must survive org A's publication")

    def test_a_broken_resolver_never_locks_users_out(self):
        make_doc(doc_type="cgu", version=1, audience="org:A")
        with override_settings(
            CONSENT_TRAIL_AUDIENCE_RESOLVER="tests.test_consent_trail.exploding_resolver"
        ):
            self.assertEqual(
                Acceptance.pending_for(self.alice), {},
                "a resolver raising must degrade to 'no tags', never trap the user",
            )


class MyConsentsViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("bob", password="pw")
        make_doc(doc_type="cgu", version=1)
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/consent/my-consents/").status_code, 302)

    def test_shows_not_accepted_yet(self):
        resp = self.client.get("/consent/my-consents/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "not accepted yet")

    def test_shows_the_acceptance_timestamp(self):
        Acceptance.record(self.user, "cgu", 1)
        resp = self.client.get("/consent/my-consents/")
        self.assertNotContains(resp, "not accepted yet")
        self.assertContains(resp, "datetime=")

    def test_superseded_acceptances_stay_visible(self):
        """The proof belongs to the user even once the version moved on."""
        Acceptance.record(self.user, "cgu", 1)
        cache.clear()
        make_doc(doc_type="cgu", version=2)
        resp = self.client.get("/consent/my-consents/")
        self.assertContains(resp, "superseded")


class PendingAdminViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.su = User.objects.create_superuser("root", "root@example.com", "pw")
        self.bob = User.objects.create_user("bob", password="x")
        make_doc(doc_type="cgu", version=1)
        self.client.force_login(self.su)

    def test_lists_users_who_have_not_accepted(self):
        resp = self.client.get("/admin/consent_trail/acceptance/pending/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "bob")

    def test_user_disappears_once_they_accept(self):
        Acceptance.record(self.bob, "cgu", 1)
        resp = self.client.get("/admin/consent_trail/acceptance/pending/")
        self.assertNotContains(resp, ">bob<")


class TemplateTagTests(TestCase):
    """A footer must not link documents that do not exist yet."""

    def setUp(self):
        cache.clear()

    def _render(self):
        from django.template import Context, Template
        from django.test import RequestFactory

        t = Template("{% load consent_trail %}{% legal_documents as docs %}"
                     "{% for slug, title in docs %}{{ slug }},{% endfor %}")
        req = RequestFactory().get("/")
        req.user = AnonymousUser()
        return t.render(Context({"request": req}))

    def test_lists_only_published_documents(self):
        make_doc(doc_type="cgu", language="fr")
        out = self._render()
        self.assertIn("cgu", out)
        self.assertNotIn("cgv", out)
        self.assertNotIn("privacy", out)

    def test_empty_when_nothing_published(self):
        self.assertEqual(self._render(), "")
