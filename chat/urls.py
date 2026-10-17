from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.dashboard, name="dashboard"),
    path("chat/conversations/", views.conversations_api, name="conversations_api"),
    path("chat/<int:conversation_id>/", views.dashboard, name="chat"),
    path("chat/<int:conversation_id>/messages/", views.messages_api, name="messages_api"),
]
