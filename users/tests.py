from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APIClient

from subscriptions.models import Subscription, Tier
from users.tokens import make_email_verification_token

User = get_user_model()

PASSWORD = "S0me-Str0ng-Pass"
NEW_PASSWORD = "An0ther-Str0ng-Pass"
REGISTER_URL = "/api/v1/auth/register/"
LOGIN_URL = "/api/v1/auth/login/"
VERIFY_URL = "/api/v1/auth/verify-email/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"


class AuthTestCase(TestCase):
    def setUp(self):
        cache.clear()  # DRF throttles use the cache
        mail.outbox.clear()
        self.client = APIClient()

    def register(self, username="alice", email="alice@example.com", password=PASSWORD):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                REGISTER_URL,
                {"username": username, "email": email, "password": password},
                format="json",
            )

    def verify(self, user, token=None):
        return self.client.post(
            VERIFY_URL,
            {"token": token or make_email_verification_token(user)},
            format="json",
        )

    def login(self, username="alice", password=PASSWORD):
        return self.client.post(
            LOGIN_URL, {"username": username, "password": password}, format="json"
        )

    def create_verified_user(self, **kwargs):
        self.register(**kwargs)
        user = User.objects.get(username=kwargs.get("username", "alice"))
        self.verify(user)
        return user


class RegistrationTests(AuthTestCase):
    def test_register_creates_unverified_basic_user(self):
        response = self.register(email="Alice@Example.com")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username="alice")
        self.assertEqual(user.email, "alice@example.com")  # normalised
        self.assertFalse(user.is_email_verified)
        self.assertIsNone(user.email_verified_at)
        self.assertEqual(user.tier, Tier.BASIC)
        self.assertTrue(
            Subscription.objects.filter(user=user, plan__tier=Tier.BASIC).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("verify-email?token=", mail.outbox[0].body)
        self.assertNotIn("password", response.json())

    def test_register_rejects_duplicate_email_case_insensitively(self):
        self.register()
        response = self.register(username="bob", email="ALICE@example.com")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.json()["errors"])

    def test_register_rejects_duplicate_email_of_soft_deleted_user(self):
        user = User.objects.create_user(
            username="gone", email="gone@example.com", password=PASSWORD
        )
        user.soft_delete()

        response = self.register(username="new", email="gone@example.com")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_rejects_weak_password(self):
        response = self.register(password="12345678")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.json()["errors"])

    def test_register_email_is_sent_only_after_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.client.post(
                REGISTER_URL,
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    "password": PASSWORD,
                },
                format="json",
            )
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 0)


class LoginTests(AuthTestCase):
    def test_login_blocked_until_email_verified(self):
        self.register()

        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "email_not_verified")
        self.assertNotIn(settings.AUTH_COOKIE_REFRESH, response.cookies)

    def test_wrong_password_does_not_reveal_verification_state(self):
        self.register()

        response = self.login(password="Wrong-Passw0rd!")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(response.json()["code"], "email_not_verified")

    def test_login_returns_access_in_body_and_refresh_in_httponly_cookie(self):
        self.create_verified_user()

        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("access", body)
        self.assertNotIn("refresh", body)
        cookie = response.cookies[settings.AUTH_COOKIE_REFRESH]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], settings.AUTH_COOKIE_PATH)
        self.assertEqual(cookie["samesite"], settings.AUTH_COOKIE_SAMESITE)

    def test_verify_email_is_idempotent(self):
        self.register()
        user = User.objects.get(username="alice")
        token = make_email_verification_token(user)

        self.assertEqual(self.verify(user, token).status_code, 200)
        first = User.objects.get(pk=user.pk).email_verified_at
        self.assertEqual(self.verify(user, token).status_code, 200)
        self.assertEqual(User.objects.get(pk=user.pk).email_verified_at, first)

    def test_email_change_invalidates_verification_link(self):
        self.register()
        user = User.objects.get(username="alice")
        token = make_email_verification_token(user)
        User.objects.filter(pk=user.pk).update(email="other@example.com")

        response = self.verify(user, token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "invalid")

    def test_resend_verification_is_enumeration_safe(self):
        response = self.client.post(
            "/api/v1/auth/resend-verification/",
            {"email": "nobody@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)


class TokenLifecycleTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.create_verified_user()
        self.login()
        self.assertIsNotNone(self.client.cookies.get(settings.AUTH_COOKIE_REFRESH))

    def test_me_requires_auth(self):
        self.client.cookies.clear()

        response = self.client.get(ME_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_db_backed_tier(self):
        login = self.login()

        response = self.client.get(
            ME_URL, HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tier"], Tier.BASIC)
        self.assertTrue(response.json()["email_verified"])

    def test_refresh_rotates_and_rejects_replay(self):
        old_refresh = self.client.cookies[settings.AUTH_COOKIE_REFRESH].value
        response = self.client.post(REFRESH_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.json())
        new_refresh = response.cookies[settings.AUTH_COOKIE_REFRESH].value
        self.assertNotEqual(old_refresh, new_refresh)

        # Replaying the old (already rotated) token must fail.
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = old_refresh
        replay = self.client.post(REFRESH_URL)

        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_without_cookie_fails(self):
        self.client.cookies.clear()

        response = self.client.post(REFRESH_URL)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "no_refresh_cookie")

    def test_logout_revokes_refresh_and_clears_cookie(self):
        stolen = self.client.cookies[settings.AUTH_COOKIE_REFRESH].value

        response = self.client.post(LOGOUT_URL)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.cookies[settings.AUTH_COOKIE_REFRESH]["max-age"], 0)

        # Even a copy of the cookie taken before logout is blacklisted.
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = stolen
        replay = self.client.post(REFRESH_URL)
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_soft_deleted_user_is_locked_out_immediately(self):
        login = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
        user = User.objects.get(username="alice")
        user.soft_delete()

        me = self.client.get(ME_URL)
        self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)

        refresh = self.client.post(REFRESH_URL)
        self.assertEqual(refresh.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(refresh.json()["code"], "user_inactive")

    def test_change_password_requires_old_password(self):
        login = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")

        response = self.client.post(
            "/api/v1/auth/change-password/",
            {"old_password": "nope", "new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_revokes_all_sessions(self):
        stolen = self.client.cookies[settings.AUTH_COOKIE_REFRESH].value
        login = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
        response = self.client.post(
            "/api/v1/auth/change-password/",
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = stolen
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 200)


class ApiDocsTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_swagger_ui_is_public(self):
        response = self.client.get("/api-docs/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "swagger-ui")

    def test_openapi_schema_is_public(self):
        response = self.client.get("/api/schema/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"].split(";")[0], "application/vnd.oai.openapi"
        )


class PasswordResetTests(AuthTestCase):
    def reset_link(self):
        body = mail.outbox[-1].body
        link = next(line for line in body.splitlines() if "/reset-password?" in line)
        query = parse_qs(urlparse(link).query)
        return query["uid"][0], query["token"][0]

    def test_reset_request_is_enumeration_safe(self):
        response = self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": "nobody@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_full_password_reset_flow_is_single_use(self):
        self.create_verified_user()
        self.login()
        mail.outbox.clear()
        self.client.post(
            "/api/v1/auth/password-reset/",
            {"email": "alice@example.com"},
            format="json",
        )
        self.assertEqual(len(mail.outbox), 1)
        uid, token = self.reset_link()

        response = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "new_password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        # Old sessions are revoked and the old password no longer works.
        self.client.cookies.clear()
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 200)

        # A reset token is single use.
        self.client.cookies.clear()
        reuse = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "new_password": "Y3t-An0ther-Str0ng"},
            format="json",
        )
        self.assertEqual(reuse.status_code, 400)

    def test_reset_token_is_bound_to_current_password_hash(self):
        user = self.create_verified_user()
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        user.set_password("Changed-Meanwhile-1")
        user.save(update_fields=["password"])

        response = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(default_token_generator.check_token(user, token))
