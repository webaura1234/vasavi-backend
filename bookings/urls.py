"""Booking URL routes."""

from django.conf import settings
from django.urls import path

from bookings.views import (
    BookingCancelView,
    BookingCashPaymentView,
    BookingDetailView,
    BookingExtendStayView,
    BookingGuestConfirmView,
    BookingListCreateView,
    BookingPaymentOrderView,
    BookingRefundRequestView,
    BookingStatusLogView,
    BookingStatusUpdateView,
)

app_name = "bookings"

urlpatterns = [
    # -----------------------------------------------------------------------
    # Booking CRUD
    # -----------------------------------------------------------------------
    path("", BookingListCreateView.as_view(), name="booking-list"),
    path("<uuid:pk>/", BookingDetailView.as_view(), name="booking-detail"),

    # -----------------------------------------------------------------------
    # Status transitions
    # -----------------------------------------------------------------------
    path("<uuid:pk>/status/", BookingStatusUpdateView.as_view(), name="booking-status"),
    path("<uuid:pk>/extend/", BookingExtendStayView.as_view(), name="booking-extend"),
    path("<uuid:pk>/cancel/", BookingCancelView.as_view(), name="booking-cancel"),
    path("<uuid:pk>/confirm/", BookingGuestConfirmView.as_view(), name="booking-guest-confirm"),

    # -----------------------------------------------------------------------
    # Payment (cash-only for now; Razorpay dormant behind RAZORPAY_ENABLED)
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # Refund request (guest-initiated)
    # -----------------------------------------------------------------------
    path(
        "<uuid:pk>/refund-request/",
        BookingRefundRequestView.as_view(),
        name="booking-refund-request",
    ),

    # -----------------------------------------------------------------------
    # Audit log
    # -----------------------------------------------------------------------
    path("<uuid:pk>/logs/", BookingStatusLogView.as_view(), name="booking-logs"),
]

# Razorpay webhook — only registered when Razorpay is enabled.
if getattr(settings, "RAZORPAY_ENABLED", False):
    from bookings.services.razorpay import razorpay_webhook  # noqa: PLC0415

    urlpatterns += [
        path("webhooks/razorpay/", razorpay_webhook, name="razorpay-webhook"),
    ]
