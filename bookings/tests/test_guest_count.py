import pytest
from rest_framework import serializers

from bookings.services.guest_count import resolve_guest_count


def test_resolve_from_adults_and_children():
    attrs = {"adults": 2, "children": 1}
    assert resolve_guest_count(attrs) == 3
    assert attrs["guest_count"] == 3


def test_resolve_guest_count_only():
    attrs = {"guest_count": 4}
    assert resolve_guest_count(attrs) == 4


def test_requires_at_least_one_adult():
    attrs = {"adults": 0, "children": 0}
    with pytest.raises(serializers.ValidationError) as exc:
        resolve_guest_count(attrs)
    assert "adults" in exc.value.detail
