from rest_framework.exceptions import APIException


class EmailNotVerified(APIException):
    """Credentials are valid, but the account still needs email verification.

    Returned with ``403`` (not ``401``) so clients do not mistake it for an
    expired/invalid access token and start a refresh loop.
    """

    status_code = 403
    default_detail = "Please verify your email before logging in."
    default_code = "email_not_verified"
