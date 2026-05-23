from django.contrib import admin

from .models import Booking, BookingStatusLog


class BookingStatusLogInline(admin.TabularInline):
    model = BookingStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "reason", "created_at")
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "booking_reference",
        "user",
        "branch",
        "room",
        "check_in_date",
        "check_out_date",
        "status",
        "payment_status",
        "final_amount",
    )
    list_filter = ("status", "payment_status", "branch")
    search_fields = ("booking_reference", "user__phone", "guest_name")
    raw_id_fields = ("user", "room", "branch")
    filter_horizontal = ("coupons_applied",)
    inlines = [BookingStatusLogInline]
    readonly_fields = ("booking_reference", "nights", "created_at", "updated_at")


@admin.register(BookingStatusLog)
class BookingStatusLogAdmin(admin.ModelAdmin):
    list_display = ("booking", "from_status", "to_status", "changed_by", "created_at")
    list_filter = ("to_status",)
    raw_id_fields = ("booking", "changed_by")
