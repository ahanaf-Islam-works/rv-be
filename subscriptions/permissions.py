from rest_framework.permissions import BasePermission

from .models import Tier, tier_rank
from .services import get_user_tier


def tier_required(min_tier: str):
    """Factory: ``permission_classes = [tier_required(Tier.PLATINUM)]``.

    The tier is always read from the database, never from the JWT claim, so an
    upgrade/downgrade takes effect on the next request instead of waiting for
    the access token to expire.
    """
    if min_tier not in Tier.values:
        raise ValueError(f"Unknown tier: {min_tier!r}")
    min_rank = tier_rank(min_tier)

    class _HasMinTier(BasePermission):
        message = f"This feature requires the {min_tier} plan or higher."
        code = "tier_required"

        def has_permission(self, request, view):
            user = getattr(request, "user", None)
            if not (user and user.is_authenticated):
                return False
            return tier_rank(get_user_tier(user)) >= min_rank

    _HasMinTier.__name__ = f"HasMinTier_{min_tier}"
    return _HasMinTier


IsPlatinumOrHigher = tier_required(Tier.PLATINUM)
IsDiamond = tier_required(Tier.DIAMOND)
