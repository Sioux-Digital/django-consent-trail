"""Tests for the legal app.

Run with:  python tests/manage.py test tests
"""

from django.contrib.auth import get_user_model
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

    def test_new_version_makes_it_pending_again(self):
        make_doc(doc_type="cgu", version=1)
        Acceptance.record(self.user, "cgu", 1)
        cache.clear()
        make_doc(doc_type="cgu", version=2)
        self.assertEqual(Acceptance.pending_for(self.user), {"cgu": 2})

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

    def test_submitting_without_ticking_is_refused_server_side(self):
        """The HTML `required` attribute only stops a browser."""
        self.client.force_login(self.user)
        resp = self.client.post("/consent/accept/", {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Acceptance.objects.count(), 0)

    def test_ticking_records_the_proof_and_redirects(self):
        self.client.force_login(self.user)
        resp = self.client.post("/consent/accept/", {"accept": "1", "next": "/dashboard/"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/dashboard/")
        proof = Acceptance.objects.get(user=self.user, doc_type="cgu")
        self.assertEqual(proof.version, 1)
        self.assertIsNotNone(proof.accepted_at)


class OpenRedirectTests(TestCase):
    """The acceptance screen is seen by every user after a terms update, so an
    unvalidated `next` is a first-rate phishing vector."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("bob", password="pw")
        make_doc(doc_type="cgu", version=1)
        self.client.force_login(self.user)

    def test_absolute_external_url_is_refused(self):
        resp = self.client.post(
            "/consent/accept/", {"accept": "1", "next": "https://evil.example/login"}
        )
        self.assertEqual(resp.url, "/")

    def test_protocol_relative_url_is_refused(self):
        resp = self.client.post(
            "/consent/accept/", {"accept": "1", "next": "//evil.example/login"}
        )
        self.assertEqual(resp.url, "/")

    def test_javascript_scheme_is_refused(self):
        resp = self.client.post(
            "/consent/accept/", {"accept": "1", "next": "javascript:alert(1)"}
        )
        self.assertEqual(resp.url, "/")

    def test_internal_path_is_kept(self):
        resp = self.client.post(
            "/consent/accept/", {"accept": "1", "next": "/inventory/"}
        )
        self.assertEqual(resp.url, "/inventory/")

    def test_hostile_next_never_reaches_the_hidden_input(self):
        resp = self.client.get("/consent/accept/?next=https://evil.example/login")
        self.assertNotContains(resp, "evil.example")


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
