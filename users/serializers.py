import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from subscriptions.services import assign_default_plan

from .exceptions import EmailNotVerified
from .tokens import (
    send_verification_email,
    user_from_email_verification_token,
    user_from_reset_credentials,
)

User = get_user_model()

logger = logging.getLogger("app.prod")


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        trim_whitespace=False,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
        )
        read_only_fields = ("id",)
        # Uniqueness is validated against all_objects (including soft-deleted
        # rows) because the DB unique constraints do too.
        extra_kwargs = {
            "username": {"validators": []},
            "email": {"validators": []},
        }

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Username is required.")
        if User.all_objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.all_objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        # Runs Django's AUTH_PASSWORD_VALIDATORS with user context (so the
        # similarity validator can compare against username/email).
        user = User(**{k: v for k, v in attrs.items() if k != "password"})
        try:
            validate_password(attrs["password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        try:
            user = User.objects.create_user(password=password, **validated_data)
        except IntegrityError as exc:
            # Covers a race where two requests pass validation simultaneously.
            raise serializers.ValidationError(
                "An account with these details already exists."
            ) from exc
        assign_default_plan(user)
        # Only send once the user row is committed.
        transaction.on_commit(lambda: send_verification_email(user))
        return user


class UserSerializer(serializers.ModelSerializer):
    tier = serializers.CharField(read_only=True)
    email_verified = serializers.BooleanField(
        source="is_email_verified", read_only=True
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "tier",
            "email_verified",
            "created_at",
        )
        read_only_fields = fields


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds small, non-sensitive claims. Never put secrets in a JWT."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.username
        token["tier"] = user.tier  # UI hint only; the server re-checks the DB
        return token

    def validate(self, attrs):
        # Credentials are checked first, so a wrong password never reveals
        # whether an account exists or is verified.
        data = super().validate(attrs)
        if not self.user.is_email_verified:
            logger.info("login blocked (unverified) user_id=%s", self.user.pk)
            raise EmailNotVerified()
        logger.info("login user_id=%s", self.user.pk)
        return data


class CookieTokenRefreshSerializer(TokenRefreshSerializer):
    """Reads the refresh token from the HttpOnly cookie, not the request body."""

    refresh = serializers.CharField(required=False, write_only=True)

    def validate(self, attrs):
        raw = self.context["request"].COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if not raw:
            raise InvalidToken(
                "No refresh token cookie found.", code="no_refresh_cookie"
            )

        # Verify signature/expiry/blacklist and make sure the account still
        # exists and is active before rotating (deleted users are rejected).
        try:
            token = RefreshToken(raw)
        except TokenError as exc:
            detail = exc.args[0] if exc.args else "Token is invalid or expired."
            raise InvalidToken(detail) from exc

        user_id = token.get(jwt_settings.USER_ID_CLAIM)
        try:
            user_is_active = User.objects.filter(pk=user_id, is_active=True).exists()
        except (DjangoValidationError, ValueError, TypeError):
            user_is_active = False
        if not user_is_active:
            raise InvalidToken("User not found or inactive.", code="user_inactive")

        attrs["refresh"] = raw
        return super().validate(attrs)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        trim_whitespace=False,
    )

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        try:
            validate_password(value, user=self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate(self, attrs):
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "Choose a password different from the old one."}
            )
        return attrs


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate(self, attrs):
        try:
            attrs["user"] = user_from_email_verification_token(attrs["token"])
        except ValueError as exc:
            raise serializers.ValidationError({"token": str(exc)}) from exc
        return attrs


class EmailOnlySerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        trim_whitespace=False,
    )

    def validate(self, attrs):
        try:
            user = user_from_reset_credentials(attrs["uid"], attrs["token"])
        except ValueError as exc:
            raise serializers.ValidationError({"token": str(exc)}) from exc
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"new_password": list(exc.messages)}
            ) from exc
        attrs["user"] = user
        return attrs
