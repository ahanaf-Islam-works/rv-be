"""
Consistent JSON error envelopes for the API.

Every error response has this shape::

    {"detail": "Human readable message.", "code": "machine_readable_code"}

Validation errors additionally carry the per-field messages::

    {
        "detail": "Validation failed.",
        "code": "invalid",
        "errors": {"email": ["Enter a valid email address."]}
    }

Clients should branch on ``code`` (stable) and display ``detail`` (may change or
be localized). Codes used by the auth flow are documented in ``auth-api.md``.
"""

from rest_framework import exceptions
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        # Unhandled exception: let Django/DRF produce a 500 and log it.
        return None

    if isinstance(exc, exceptions.ValidationError):
        errors = response.data
        if not isinstance(errors, dict):
            # Non-field errors raised as a string/list.
            errors = {
                "non_field_errors": errors if isinstance(errors, list) else [errors]
            }
        response.data = {
            "detail": "Validation failed.",
            "code": "invalid",
            "errors": errors,
        }
        return response

    code = None
    if hasattr(exc, "get_codes"):
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else None
    if not code:
        code = getattr(exc, "default_code", "error")

    if isinstance(response.data, dict):
        response.data.setdefault("detail", "Request failed.")
        response.data.setdefault("code", code)
    else:
        response.data = {"detail": response.data, "code": code}

    return response
