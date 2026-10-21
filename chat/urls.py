from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.dashboard, name="dashboard"),
    path("chat/conversations/", views.conversations_api, name="conversations_api"),
    path("notifications/", views.notifications_api, name="notifications_api"),
    path("notifications/seen/", views.notifications_seen, name="notifications_seen"),
    path("chat/request/send/<int:user_id>/", views.request_send, name="request_send"),
    path("chat/request/<int:request_id>/accept/", views.request_accept, name="request_accept"),
    path("chat/request/<int:request_id>/decline/", views.request_decline, name="request_decline"),
    path("chat/<int:conversation_id>/attach/", views.attach_api, name="attach_api"),
    path("chat/<int:conversation_id>/", views.dashboard, name="chat"),
    path("chat/<int:conversation_id>/messages/", views.messages_api, name="messages_api"),
]
