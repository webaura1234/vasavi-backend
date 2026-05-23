from django.contrib import admin

from .models import Donation, DonationPurpose, DonorProfile, MembershipTier, ReceiptNumber


@admin.register(MembershipTier)
class MembershipTierAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)


@admin.register(DonationPurpose)
class DonationPurposeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)


class ReceiptNumberInline(admin.TabularInline):
    model = ReceiptNumber
    extra = 1


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("donor", "amount", "purpose", "dispatch_date", "created_by", "created_at")
    list_filter = ("purpose", "dispatch_method")
    raw_id_fields = ("donor", "created_by")
    inlines = [ReceiptNumberInline]


@admin.register(DonorProfile)
class DonorProfileAdmin(admin.ModelAdmin):
    list_display = ("donor_id", "user", "membership_tier", "club_name", "for_place")
    search_fields = ("donor_id", "user__phone", "user__name", "club_name")
    raw_id_fields = ("user", "membership_tier", "for_place")


@admin.register(ReceiptNumber)
class ReceiptNumberAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "donation")
    search_fields = ("receipt_number",)
