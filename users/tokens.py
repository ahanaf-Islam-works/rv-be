"""Signed email-verification tokens, password-reset links and token revocation."""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

User = get_user_model()

logger = logging.getLogger("app.prod")

EMAIL_VERIFY_SALT = "users.email-verify"


# ---------------------------------------------------------------------------
# Email verification: signed, time-limited and tied to the current email.
# ---------------------------------------------------------------------------
def make_email_verification_token(user) -> str:
    return signing.dumps(
        {"uid": str(user.pk), "email": user.email},
        salt=EMAIL_VERIFY_SALT,
    )


def user_from_email_verification_token(token: str):
    """Return the user or raise ``ValueError``.

    Changing the account email invalidates previously issued links because the
    address is part of the signed payload.
    """
    try:
        data = signing.loads(
            token,
            salt=EMAIL_VERIFY_SALT,
            max_age=settings.EMAIL_VERIFY_MAX_AGE,
        )
    except (signing.BadSignature, TypeError, ValueError) as exc:
        raise ValueError("Invalid or expired token.") from exc

    try:
        uid, email = data["uid"], data["email"]
        return User.objects.get(pk=uid, email=email)
    except (
        User.DoesNotExist,
        DjangoValidationError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError("Invalid or expired token.") from exc


def send_verification_email(user) -> None:
    query = urlencode({"token": make_email_verification_token(user)})
    link = f"{settings.FRONTEND_URL}/verify-email?{query}"
    _send(
        subject="Verify your email",
        message=(
            f"Hi {user.username},\n\n"
            f"Confirm your email address:\n{link}\n\n"
            "This link expires in 24 hours."
        ),
        recipient=user.email,
        event="verification",
        user=user,
    )


# ---------------------------------------------------------------------------
# Password reset: Django's generator is single-use and dies when the password
# (or last_login) changes.
# ---------------------------------------------------------------------------
def send_password_reset_email(user) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    query = urlencode({"uid": uid, "token": token})
    link = f"{settings.FRONTEND_URL}/reset-password?{query}"
    _send(
        subject="Reset your password",
        message=(
            f"Hi {user.username},\n\n"
            f"Reset your password:\n{link}\n\n"
            "If you didn't ask for this, ignore this email."
        ),
        recipient=user.email,
        event="password_reset",
        user=user,
    )


def user_from_reset_credentials(uidb64: str, token: str):
    """Resolve and validate a password-reset uid/token pair."""
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (
        User.DoesNotExist,
        ValueError,
        TypeError,
        OverflowError,
        DjangoValidationError,
    ) as exc:
        raise ValueError("Invalid reset link.") from exc
    if not user.is_active or not default_token_generator.check_token(user, token):
        raise ValueError("Invalid or expired reset link.")
    return user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def revoke_all_refresh_tokens(user) -> int:
    """Blacklist every outstanding refresh token for the user (all devices)."""
    already = set(
        BlacklistedToken.objects.filter(token__user=user).values_list(
            "token_id", flat=True
        )
    )
    to_blacklist = [
        BlacklistedToken(token_id=token_id)
        for token_id in OutstandingToken.objects.filter(user=user)
        .exclude(id__in=already)
        .values_list("id", flat=True)
    ]
    if to_blacklist:
        BlacklistedToken.objects.bulk_create(to_blacklist, ignore_conflicts=True)
    return len(to_blacklist)


def _send(*, subject: str, message: str, recipient: str, event: str, user) -> None:
    if not recipient:
        logger.warning("Cannot send %s email: user %s has no address", event, user.pk)
        return
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
        )
    except Exception:
        # Never leak account existence or provider errors to the client. In
        # production this should be a background job with retries.
        logger.exception("Failed to send %s email for user %s", event, user.pk)
