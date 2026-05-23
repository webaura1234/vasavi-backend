"""Booking URL routes."""

from django.urls import path

from bookings.views import (
    BookingCancelView,
    BookingCashPaymentView,
    BookingDetailView,
    BookingExtendStayView,
    BookingListCreateView,
    BookingPaymentOrderView,
    BookingStatusLogView,
    BookingStatusUpdateView,
    razorpay_webhook,
)

app_name = "bookings"

urlpatterns = [
    path("", BookingListCreateView.as_view(), name="booking-list"),
    path("<uuid:pk>/", BookingDetailView.as_view(), name="booking-detail"),
    path("<uuid:pk>/status/", BookingStatusUpdateView.as_view(), name="booking-status"),
    path("<uuid:pk>/extend/", BookingExtendStayView.as_view(), name="booking-extend"),
    path("<uuid:pk>/cancel/", BookingCancelView.as_view(), name="booking-cancel"),
    path(
        "<uuid:pk>/payment/order/",
        BookingPaymentOrderView.as_view(),
        name="booking-payment-order",
    ),
    path(
        "<uuid:pk>/payment/cash/",
        BookingCashPaymentView.as_view(),
        name="booking-payment-cash",
    ),
    path("<uuid:pk>/logs/", BookingStatusLogView.as_view(), name="booking-logs"),
    path("webhooks/razorpay/", razorpay_webhook, name="razorpay-webhook"),
]
