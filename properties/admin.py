from django.contrib import admin

from .models import (
    FunctionHall,
    FunctionHallImage,
    Room,
    RoomImage,
    RoomType,
)


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


class RoomImageInline(admin.TabularInline):
    model = RoomImage
    extra = 0


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    inlines = [RoomImageInline]
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


class FunctionHallImageInline(admin.TabularInline):
    model = FunctionHallImage
    extra = 0


@admin.register(FunctionHall)
class FunctionHallAdmin(admin.ModelAdmin):
    inlines = [FunctionHallImageInline]
    list_display = (
        "name",
        "branch",
        "capacity",
        "base_price_per_day",
        "is_active",
        "operational_status",
    )
    list_filter = ("branch", "is_active", "operational_status")
    search_fields = ("name", "branch__name")
    raw_id_fields = ("branch",)
