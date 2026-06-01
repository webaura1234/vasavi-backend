from django.contrib import admin

from notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "category", "type", "read_at", "created_at")
    list_filter = ("category", "type", "read_at")
    search_fields = ("title", "message", "recipient__phone", "recipient__name")
    readonly_fields = ("created_at", "updated_at")
