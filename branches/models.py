"""
Owns the Branch model — physical Vasavi properties (guest houses,
convention centres, etc.) across different cities.
"""
from __future__ import annotations

from django.db import models

from core.models import SoftDeleteModel


class Branch(SoftDeleteModel):
    """
    A physical Vasavi branch location.

    Each branch represents a guest house, convention centre, or other
    bookable property managed by Vasavi Clubs International in a
    specific city.  Branches are the top-level organisational unit to
    which admin users are assigned and under which properties/rooms
    are catalogued.
    """

    name = models.CharField(
        max_length=200,
        help_text="Display name of the branch (e.g. 'Vasavi Guest House').",
    )
    city = models.CharField(
        max_length=100,
        db_index=True,
        help_text="City where the branch is located.",
    )
    address = models.TextField(
        help_text="Full postal address of the branch.",
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="Contact phone number for the branch.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive branches are hidden from public listings.",
    )

    class Meta:
        verbose_name = "branch"
        verbose_name_plural = "branches"
        ordering = ["city", "name"]

    def __str__(self) -> str:
        return f"{self.name}, {self.city}"
