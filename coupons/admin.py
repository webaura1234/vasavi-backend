from django.contrib import admin

from .models import Coupon, CouponBatch


class CouponInline(admin.TabularInline):
    model = Coupon
    extra = 0
    readonly_fields = ("serial_number", "coupon_type", "status", "created_at")
    can_delete = False
    show_change_link = True


@admin.register(CouponBatch)
class CouponBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "donation",
        "coupon_type",
        "serial_start",
        "serial_end",
        "count",
        "created_at",
    )
    list_filter = ("coupon_type",)
    raw_id_fields = ("donation",)
    inlines = [CouponInline]


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        "serial_number",
        "coupon_type",
        "status",
        "batch",
        "redeemed_by",
        "redeemed_on",
    )
    list_filter = ("status", "coupon_type")
    search_fields = ("serial_number",)
    raw_id_fields = (
        "batch",
        "redeemed_by",
        "redeemed_at_branch",
        "redeemed_at_booking",
    )
    filter_horizontal = ("assigned_donors",)
