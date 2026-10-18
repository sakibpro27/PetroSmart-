from django.urls import path

from . import views

app_name = "tenants"

urlpatterns = [
    path("", views.SubscriptionView.as_view(), name="subscription"),
    path("inactive/", views.SubscriptionInactiveView.as_view(), name="inactive"),
]
