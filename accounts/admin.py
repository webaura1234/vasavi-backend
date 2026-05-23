from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AdminBranch, OTPLog, ProfileConfirmation, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("phone",)
    list_display = ("phone", "name", "email", "role", "is_active", "is_staff", "date_joined")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("phone", "name", "email")
    readonly_fields = ("date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Personal", {"fields": ("name", "email")}),
        ("Role", {"fields": ("role", "is_first_login")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        ("Soft delete", {"fields": ("is_deleted", "deleted_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(OTPLog)
class OTPLogAdmin(admin.ModelAdmin):
    list_display = ("phone", "purpose", "is_verified", "attempts", "expires_at", "created_at")
    list_filter = ("purpose", "is_verified")
    search_fields = ("phone",)
    readonly_fields = (
        "phone",
        "hashed_otp",
        "purpose",
        "is_verified",
        "attempts",
        "locked_until",
        "expires_at",
        "created_at",
        "updated_at",
    )


@admin.register(ProfileConfirmation)
class ProfileConfirmationAdmin(admin.ModelAdmin):
    list_display = ("user", "is_confirmed", "confirmed_at", "created_at")
    list_filter = ("is_confirmed",)
    raw_id_fields = ("user",)


@admin.register(AdminBranch)
class AdminBranchAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "assigned_by", "assigned_at")
    raw_id_fields = ("user", "branch", "assigned_by")
