from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts.forms import StyledAuthenticationForm, StyledPasswordResetForm, StyledSetPasswordForm

admin.site.site_header = "PetroSmart Platform Administration"
admin.site.site_title = "PetroSmart Platform"
admin.site.index_title = "Tenants, subscriptions and users"

auth_patterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            authentication_form=StyledAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(form_class=StyledPasswordResetForm),
        name="password_reset",
    ),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(form_class=StyledSetPasswordForm),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]

urlpatterns = [
    path(settings.PLATFORM_ADMIN_PATH, admin.site.urls),
    path("accounts/", include(auth_patterns)),
    path("subscription/", include("tenants.urls")),
    path("setup/", include("station.urls")),
    path("users/", include("accounts.urls")),
    path("sales/", include("sales.urls")),
    path("stock/", include("stock.urls")),
    path("purchases/", include("purchases.urls")),
    path("finance/", include("finance.urls")),
    path("reports/", include("reports.urls")),
    path("outlet/", include("operations.urls")),
    path("", include("core.urls")),
]
