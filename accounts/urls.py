from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("invite/<str:code>/", views.signup, name="invite"),
    path("welcome/seen/", views.dev_notice_seen, name="dev_notice_seen"),
    path("profile/", views.profile_edit, name="profile"),
    path("profile/<int:user_id>/", views.profile_detail, name="profile_detail"),
]
