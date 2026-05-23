from django.contrib import admin

from .models import Room, RoomType


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = (
        "room_number",
        "branch",
        "room_type",
        "capacity",
        "base_price_per_night",
        "is_donor_exclusive",
        "is_active",
    )
    list_filter = ("branch", "room_type", "is_donor_exclusive", "is_active")
    search_fields = ("room_number", "branch__name")
    raw_id_fields = ("branch", "room_type")
