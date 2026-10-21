from django.urls import path

from . import views

urlpatterns = [
    path("buy/", views.pricing, name="pricing"),
    path("buy/order/", views.create_order, name="billing_order"),
    path("buy/verify/", views.verify, name="billing_verify"),
    path("buy/demo/", views.demo_pay, name="billing_demo"),
    path("buy/webhook/", views.webhook, name="billing_webhook"),
]
