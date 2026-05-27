"""User-facing booking operation messages (staff portal & API)."""

from __future__ import annotations

from bookings.models import Booking


def booking_status_label(status: str) -> str:
    labels = dict(Booking.Status.choices)
    return labels.get(status, status.replace("_", " ").title())


def cancel_not_allowed_message(current_status: str) -> str:
    label = booking_status_label(current_status)
    if current_status == Booking.Status.CHECKED_IN:
        return (
            "This guest is already checked in. Mark them as checked out first, "
            "or contact a super admin if the stay must be voided."
        )
    if current_status in (Booking.Status.CHECKED_OUT, Booking.Status.CANCELLED):
        return f"This booking is already {label.lower()} and cannot be cancelled again."
    if current_status == Booking.Status.NO_SHOW:
        return (
            "This booking was marked as a no-show. Use “Restore to confirmed” "
            "if the guest has arrived."
        )
    return (
        f"This booking is {label.lower()} right now. "
        "Cancellation is only available while it is pending or confirmed."
    )


def status_transition_not_allowed(from_status: str, to_status: str) -> str:
    from_label = booking_status_label(from_status)
    to_label = booking_status_label(to_status)
    return (
        f"You cannot move this booking from “{from_label}” to “{to_label}”. "
        f"Choose one of the actions listed for the current stage."
    )
