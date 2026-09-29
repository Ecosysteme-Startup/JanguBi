from django.urls import path

from apps.donations import apis

urlpatterns = [
    path("checkout/", apis.CheckoutApi.as_view(), name="checkout"),
    path("checkout/<uuid:donation_id>/", apis.CheckoutStatusApi.as_view(), name="checkout-status"),
    path("webhooks/<str:provider>/", apis.WebhookApi.as_view(), name="webhook"),
]
