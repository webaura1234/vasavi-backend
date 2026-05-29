from django.contrib import admin

from support.models import ContactInquiry, SupportTicket


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "branch", "status", "priority", "created_by", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("subject", "guest_name", "booking_reference")


@admin.register(ContactInquiry)
class ContactInquiryAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "branch", "inquiry_type", "created_at")
    search_fields = ("name", "email", "message")
