"""Small serializers used only for OpenAPI documentation."""

from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    detail = serializers.CharField()


class AccessTokenSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Short-lived JWT access token.")


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    errors = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
        help_text="Validation errors keyed by field name.",
    )
