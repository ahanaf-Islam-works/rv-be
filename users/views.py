import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from config.schema import AccessTokenSerializer, ErrorSerializer, MessageSerializer

from .cookies import delete_refresh_cookie, set_refresh_cookie
from .serializers import (
    ChangePasswordSerializer,
    CookieTokenRefreshSerializer,
    CustomTokenObtainPairSerializer,
    EmailOnlySerializer,
    PasswordResetConfirmSerializer,
    RegisterSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)
from .tokens import (
    revoke_all_refresh_tokens,
    send_password_reset_email,
    send_verification_email,
)

logger = logging.getLogger("app.prod")

User = get_user_model()


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Register a new account",
        description=(
            "Creates an unverified user and a free Basic subscription in one "
            "transaction, then emails a verification link. No tokens are issued "
            "until the email is verified."
        ),
    )
)
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "register"


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Log in",
        request=CustomTokenObtainPairSerializer,
        responses={
            200: AccessTokenSerializer,
            401: ErrorSerializer,
            403: ErrorSerializer,
            429: ErrorSerializer,
        },
        description=(
            "Returns a short-lived access token in the body and sets the "
            "rotating refresh token in an HttpOnly cookie. Unverified users get "
            "`403` with `code=email_not_verified`."
        ),
    )
)
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            # Move the refresh token into an HttpOnly cookie, never the body.
            refresh = response.data.pop("refresh", None)
            if refresh:
                set_refresh_cookie(response, refresh)
        elif response.status_code == status.HTTP_401_UNAUTHORIZED:
            logger.warning(
                "login failed ip=%s", request.META.get("REMOTE_ADDR", "unknown")
            )
        return response


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Refresh the access token",
        request=None,
        responses={
            200: AccessTokenSerializer,
            401: ErrorSerializer,
            429: ErrorSerializer,
        },
        description=(
            "Reads the refresh token from the HttpOnly cookie (no request body), "
            "blacklists it, and returns a new access token plus a rotated refresh "
            "cookie."
        ),
    )
)
class CookieTokenRefreshView(TokenRefreshView):
    serializer_class = CookieTokenRefreshSerializer
    throttle_scope = "refresh"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            refresh = response.data.pop("refresh", None)
            if refresh:
                set_refresh_cookie(response, refresh)  # rotated token
        return response


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Log out",
        request=None,
        responses={204: None},
        description=(
            "Blacklists the refresh token from the cookie and clears the cookie. "
            "Works without an access token, so it still succeeds after expiry."
        ),
    )
)
class LogoutView(APIView):
    """Works even if the access token already expired, so it needs no auth."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass  # already invalid: nothing to revoke
            logger.info("logout refresh token revoked")
        response = Response(status=status.HTTP_204_NO_CONTENT)
        delete_refresh_cookie(response)
        return response


@extend_schema_view(
    get=extend_schema(
        tags=["Auth"],
        summary="Current user",
        description="Profile plus the live plan tier read from the database.",
    )
)
class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Change password",
        request=ChangePasswordSerializer,
        responses={
            200: MessageSerializer,
            400: ErrorSerializer,
            401: ErrorSerializer,
        },
        description=(
            "Requires the old password. Revokes every outstanding refresh token "
            "for the user and clears the refresh cookie; the access token still "
            "expires on its own within 15 minutes."
        ),
    )
)
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        request.user.set_password(ser.validated_data["new_password"])
        request.user.save(update_fields=["password", "updated_at"])
        revoked = revoke_all_refresh_tokens(request.user)
        logger.info("password changed user_id=%s revoked=%s", request.user.pk, revoked)

        response = Response(
            {"detail": "Password updated. Please log in again."},
            status=status.HTTP_200_OK,
        )
        delete_refresh_cookie(response)
        return response


class _PublicEmailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "email"


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Verify email",
        request=VerifyEmailSerializer,
        responses={200: MessageSerializer, 400: ErrorSerializer, 429: ErrorSerializer},
        description="Consumes the signed token from the verification link.",
    )
)
class VerifyEmailView(_PublicEmailView):
    def post(self, request):
        ser = VerifyEmailSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.validated_data["user"]
        if not user.is_email_verified:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at", "updated_at"])
            logger.info("email verified user_id=%s", user.pk)
        return Response({"detail": "Email verified. You can now log in."})


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Resend verification email",
        request=EmailOnlySerializer,
        responses={200: MessageSerializer, 400: ErrorSerializer, 429: ErrorSerializer},
        description=(
            "Always returns the same response, whether or not the account "
            "exists (no user enumeration)."
        ),
    )
)
class ResendVerificationView(_PublicEmailView):
    def post(self, request):
        ser = EmailOnlySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=ser.validated_data["email"], is_active=True
        ).first()
        if user and not getattr(user, "email_verified_at", None):
            send_verification_email(user)
        # Identical response whether or not the account exists (no enumeration).
        return Response(
            {"detail": "If that account needs verification, an email has been sent."}
        )


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Request a password reset",
        request=EmailOnlySerializer,
        responses={200: MessageSerializer, 400: ErrorSerializer, 429: ErrorSerializer},
        description=(
            "Emails a single-use reset link (valid 1 hour). The response is "
            "identical for unknown addresses."
        ),
    )
)
class PasswordResetRequestView(_PublicEmailView):
    def post(self, request):
        ser = EmailOnlySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=ser.validated_data["email"], is_active=True
        ).first()
        if user:
            send_password_reset_email(user)
        return Response(
            {"detail": "If that email is registered, a reset link has been sent."}
        )


@extend_schema_view(
    post=extend_schema(
        tags=["Auth"],
        summary="Reset password with a link token",
        request=PasswordResetConfirmSerializer,
        responses={200: MessageSerializer, 400: ErrorSerializer, 429: ErrorSerializer},
        description=(
            "Sets the new password, marks the email verified, and revokes every "
            "refresh token for the user. The reset token is single-use."
        ),
    )
)
class PasswordResetConfirmView(_PublicEmailView):
    def post(self, request):
        ser = PasswordResetConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.validated_data["user"]
        user.set_password(ser.validated_data["new_password"])
        # A successful reset also proves ownership of the email address.
        if not user.is_email_verified:
            user.email_verified_at = timezone.now()
        user.save(update_fields=["password", "email_verified_at", "updated_at"])
        revoked = revoke_all_refresh_tokens(user)
        logger.info("password reset user_id=%s revoked=%s", user.pk, revoked)

        response = Response(
            {"detail": "Password reset. Please log in with your new password."},
            status=status.HTTP_200_OK,
        )
        delete_refresh_cookie(response)
        return response
