from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("login/", views.login_view, name="login"),
    path("verify/", views.verify_otp, name="verify_otp"),
    path("verify/email/", views.send_verify_email, name="send_verify_email"),
    path("verify/resend/", views.resend_otp, name="resend_otp"),
    path("logout/", views.logout_view, name="logout"),
    path("invite/<str:code>/", views.signup, name="invite"),
    path("welcome/seen/", views.dev_notice_seen, name="dev_notice_seen"),
    path("profile/", views.profile_edit, name="profile"),
    path("profile/<int:user_id>/", views.profile_detail, name="profile_detail"),
    path(
        "password-reset/",
        views.password_reset_request,
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),

]
