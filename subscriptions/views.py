from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.response import Response
from rest_framework.views import APIView

from config.schema import ErrorSerializer, MessageSerializer

from .models import BillingCycle, Plan, SubscriptionStatus, Tier
from .permissions import IsDiamond, IsPlatinumOrHigher
from .serializers import PlanSerializer, SubscriptionSerializer
from .services import get_live_subscription


@extend_schema_view(
    get=extend_schema(
        tags=["Subscriptions"],
        summary="List plan catalog",
        responses=PlanSerializer(many=True),
        description="Public pricing catalog, sorted by monthly price.",
    )
)
class PlanListView(APIView):
    """Public pricing catalog."""

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by("price_monthly", "tier")
        return Response(PlanSerializer(plans, many=True).data)


@extend_schema_view(
    get=extend_schema(
        tags=["Subscriptions"],
        summary="Current subscription",
        responses={200: SubscriptionSerializer, 401: ErrorSerializer},
        description=(
            "The caller's live subscription, limits included. The tier is read "
            "from the database, so it is fresh after a plan change."
        ),
    )
)
class MySubscriptionView(APIView):
    """The caller's live subscription. The tier here is always DB-fresh."""

    def get(self, request):
        sub = get_live_subscription(request.user)
        if sub:
            return Response(SubscriptionSerializer(sub).data)

        # Every registered user has a Basic row; this is only a safety net.
        plan = Plan.objects.filter(tier=Tier.BASIC).first()
        return Response(
            {
                "tier": Tier.BASIC,
                "plan": PlanSerializer(plan).data if plan else None,
                "limits": plan.limits if plan else {},
                "status": SubscriptionStatus.ACTIVE,
                "billing_cycle": BillingCycle.MONTHLY,
                "started_at": None,
                "current_period_start": None,
                "current_period_end": None,
                "cancel_at_period_end": False,
            }
        )


# --- Example gated endpoints -------------------------------------------------
@extend_schema_view(
    get=extend_schema(
        tags=["Subscriptions"],
        summary="Platinum+ demo feature",
        responses={200: MessageSerializer, 401: ErrorSerializer, 403: ErrorSerializer},
    )
)
class PlatinumFeatureView(APIView):
    permission_classes = [IsPlatinumOrHigher]

    def get(self, request):
        return Response({"detail": "Platinum+ feature unlocked."})


@extend_schema_view(
    get=extend_schema(
        tags=["Subscriptions"],
        summary="Diamond-only demo feature",
        responses={200: MessageSerializer, 401: ErrorSerializer, 403: ErrorSerializer},
    )
)
class DiamondFeatureView(APIView):
    permission_classes = [IsDiamond]

    def get(self, request):
        return Response({"detail": "Diamond-only feature unlocked."})
