from django.urls import path

from .views import (
    DiamondFeatureView,
    MySubscriptionView,
    PlanListView,
    PlatinumFeatureView,
)

app_name = "subscriptions"

urlpatterns = [
    path("plans/", PlanListView.as_view(), name="plans"),
    path("me/", MySubscriptionView.as_view(), name="my_subscription"),
    path("demo/platinum/", PlatinumFeatureView.as_view(), name="demo_platinum"),
    path("demo/diamond/", DiamondFeatureView.as_view(), name="demo_diamond"),
]
