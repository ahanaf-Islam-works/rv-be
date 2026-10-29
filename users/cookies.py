from django.conf import settings

_EPOCH = "Thu, 01 Jan 1970 00:00:00 GMT"


def set_refresh_cookie(response, refresh_token: str) -> None:
    """Store the refresh token in an HttpOnly cookie.

    JavaScript can never read it, and the restricted path means it is not sent
    to the rest of the API on every request.
    """
    response.set_cookie(
        key=settings.AUTH_COOKIE_REFRESH,
        value=refresh_token,
        max_age=settings.AUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )


def delete_refresh_cookie(response) -> None:
    """Expire the cookie with the same attributes used to set it.

    Attributes must match the original cookie (name/path/domain); ``Secure`` is
    repeated because browsers reject ``SameSite=None`` cookies without it.
    """
    response.set_cookie(
        key=settings.AUTH_COOKIE_REFRESH,
        value="",
        max_age=0,
        expires=_EPOCH,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )
