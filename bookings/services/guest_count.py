"""Resolve adults + children into a single guest_count for bookings."""

from __future__ import annotations

from rest_framework import serializers


def resolve_guest_count(
    attrs: dict,
    *,
    default: int = 1,
) -> int:
    """
    Normalize guest_count from optional adults/children fields.

    If adults is provided, guest_count = adults + children (children defaults to 0).
    Otherwise guest_count from attrs (or default) is used.
    """
    adults = attrs.get("adults")
    children = attrs.get("children")
    if children is None:
        children = 0

    if adults is not None:
        if adults < 1:
            raise serializers.ValidationError(
                {"adults": "At least one adult is required."}
            )
        if children < 0:
            raise serializers.ValidationError(
                {"children": "Children count cannot be negative."}
            )
        guest_count = adults + children
        if guest_count < 1:
            raise serializers.ValidationError(
                {"guest_count": "Total guests must be at least 1."}
            )
        attrs["guest_count"] = guest_count
        return guest_count

    guest_count = attrs.get("guest_count", default)
    if guest_count is None:
        guest_count = default
    if guest_count < 1:
        raise serializers.ValidationError(
            {"guest_count": "Total guests must be at least 1."}
        )
    attrs["guest_count"] = guest_count
    return guest_count
