"""
Smoke-test staff auth endpoints (/api/v1/staff/).

Usage:
    python manage.py test_staff_auth
"""

from __future__ import annotations

import uuid

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.test.utils import override_settings
from rest_framework.test import APIClient

from accounts.models import AdminBranch, OTPLog, ProfileConfirmation, User
from branches.models import Branch


PHONE_ADMIN = "9876543210"
PHONE_DONOR = "9876543211"
PHONE_UNKNOWN = "9876543299"
PHONE_SUPER = "9876543212"


def _cleanup_phone(phone: str) -> None:
    """Remove test users and related rows (respect PROTECT FKs)."""
    for user in User.all_objects.filter(phone=phone):
        AdminBranch.objects.filter(user=user).delete()
        AdminBranch.objects.filter(assigned_by=user).delete()
        ProfileConfirmation.objects.filter(user=user).delete()
        OTPLog.objects.filter(phone=phone).delete()
        user.delete()


def _ensure_super_admin(phone: str) -> User:
    _cleanup_phone(phone)
    user = User.objects.create_user(phone=phone, role="super_admin", name="Test Super")
    ProfileConfirmation.objects.get_or_create(
        user=user,
        defaults={"is_confirmed": True},
    )
    return user


def _ensure_branch_admin(phone: str, *, super_admin: User) -> User:
    _cleanup_phone(phone)
    branch = Branch.objects.filter(is_active=True, is_deleted=False).first()
    if not branch:
        branch = Branch.objects.create(
            name="Test Branch",
            city="Hyderabad",
            address="Test address",
            phone="9999999999",
        )
    user = User.objects.create_user(phone=phone, role="admin", name="Test Admin")
    ProfileConfirmation.objects.get_or_create(
        user=user,
        defaults={"is_confirmed": True},
    )
    AdminBranch.objects.create(
        user=user,
        branch=branch,
        assigned_by=super_admin,
    )
    return user


def _ensure_donor(phone: str) -> User:
    _cleanup_phone(phone)
    return User.objects.create_user(phone=phone, role="donor", name="Test Donor")


class Command(BaseCommand):
    help = "Run staff auth API smoke tests"

    def handle(self, *args, **options):
        with override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"]):
            failures = run_staff_auth_tests(self.stdout, self.style)
        if failures:
            self.stderr.write(self.style.ERROR(f"\n{failures} check(s) failed.\n"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nAll staff auth checks passed.\n"))


def run_staff_auth_tests(stdout, style) -> int:
    """Return number of failed checks."""
    super_admin = _ensure_super_admin(PHONE_SUPER)
    _ensure_branch_admin(PHONE_ADMIN, super_admin=super_admin)
    _ensure_donor(PHONE_DONOR)

    client = APIClient()
    failures = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal failures
        if condition:
            stdout.write(style.SUCCESS(f"  PASS  {name}"))
        else:
            failures += 1
            stdout.write(style.ERROR(f"  FAIL  {name} {detail}"))

    stdout.write("Staff OTP send\n")

    r = client.post("/api/v1/staff/otp/send/", {"phone": PHONE_DONOR}, format="json")
    check(
        "donor phone rejected on staff send",
        r.status_code == 400 and r.json().get("error", {}).get("code") == "ACCESS_DENIED",
        str(r.json()),
    )
    check(
        "no OTP log for rejected donor",
        not OTPLog.objects.filter(phone=PHONE_DONOR, is_verified=False).exists(),
        "",
    )

    r = client.post("/api/v1/staff/otp/send/", {"phone": PHONE_UNKNOWN}, format="json")
    check(
        "unregistered phone rejected",
        r.status_code == 400 and r.json().get("error", {}).get("code") == "PHONE_NOT_REGISTERED",
        str(r.json()),
    )

    r = client.post("/api/v1/staff/otp/send/", {"phone": PHONE_ADMIN}, format="json")
    body = r.json()
    check("admin staff send OK", r.status_code == 200 and body.get("data", {}).get("ok") is True, str(body))

    log = OTPLog.objects.filter(phone=PHONE_ADMIN, is_verified=False).order_by("-created_at").first()
    check("OTP log created for admin", log is not None, "")

    stdout.write("\nStaff OTP verify\n")

    if not log:
        stdout.write(style.ERROR("  SKIP  verify tests (no OTP log)\n"))
        failures += 1
    else:
        # Dev-only: read OTP from latest log by brute-forcing is not possible (hashed).
        # Create a fresh OTP with known hash for verify test.
        OTPLog.objects.filter(phone=PHONE_ADMIN, is_verified=False).delete()
        test_otp = "123456"
        OTPLog.objects.create(
            phone=PHONE_ADMIN,
            hashed_otp=make_password(test_otp),
            purpose="login",
        )

        r = client.post(
            "/api/v1/staff/otp/verify/",
            {"phone": PHONE_ADMIN, "otp": test_otp},
            format="json",
        )
        body = r.json()
        data = body.get("data", {})
        user_data = data.get("user", {})
        check("admin verify OK", r.status_code == 200 and data.get("access"), str(body))
        check(
            "admin has branch in response",
            user_data.get("role") == "admin" and user_data.get("branch") is not None,
            str(user_data.get("branch")),
        )
        staff_cookie = r.cookies.get("vasavi_staff_refresh")
        customer_cookie = r.cookies.get("vasavi_refresh")
        check(
            "staff refresh cookie set",
            staff_cookie is not None and bool(staff_cookie.value),
            f"cookies={list(r.cookies.keys())}",
        )
        check(
            "customer refresh cookie not set",
            customer_cookie is None or not customer_cookie.value,
            "",
        )

        access = data.get("access")
        staff_client = APIClient()
        staff_client.cookies["vasavi_staff_refresh"] = r.cookies["vasavi_staff_refresh"].value

        stdout.write("\nStaff token refresh\n")
        r = staff_client.post("/api/v1/staff/token/refresh/", format="json")
        check("token refresh OK", r.status_code == 200 and r.json().get("data", {}).get("access"), str(r.json()))

        stdout.write("\nStaff /me/\n")
        staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        r = staff_client.get("/api/v1/staff/me/")
        check("staff me OK", r.status_code == 200 and r.json().get("data", {}).get("permissions"), str(r.json()))

        stdout.write("\nBranch create blocked for donor JWT (IsSuperAdmin)\n")
        donor = User.objects.get(phone=PHONE_DONOR)
        from rest_framework_simplejwt.tokens import RefreshToken

        donor_access = str(RefreshToken.for_user(donor).access_token)
        donor_client = APIClient()
        donor_client.credentials(HTTP_AUTHORIZATION=f"Bearer {donor_access}")
        r = donor_client.post(
            "/api/v1/branches/",
            {
                "name": "Blocked Branch",
                "city": "Test",
                "address": "Test",
                "phone": "9888888888",
            },
            format="json",
        )
        check(
            "donor blocked on branch create",
            r.status_code == 403,
            str(r.json()),
        )

        stdout.write("\nCustomer OTP verify still works for admin phone\n")
        OTPLog.objects.filter(phone=PHONE_ADMIN, is_verified=False).delete()
        OTPLog.objects.create(phone=PHONE_ADMIN, hashed_otp=make_password(test_otp), purpose="login")
        cust = APIClient()
        r = cust.post(
            "/api/v1/accounts/otp/verify/",
            {"phone": PHONE_ADMIN, "otp": test_otp},
            format="json",
            HTTP_X_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        check(
            "customer verify OK for admin",
            r.status_code == 200 and r.json().get("data", {}).get("access"),
            str(r.json()),
        )
        cust_refresh = r.cookies.get("vasavi_refresh")
        cust_staff = r.cookies.get("vasavi_staff_refresh")
        check(
            "customer cookie on accounts flow",
            cust_refresh is not None
            and bool(cust_refresh.value)
            and (cust_staff is None or not cust_staff.value),
            "",
        )

        stdout.write("\nStaff logout\n")
        r = staff_client.post("/api/v1/staff/logout/", format="json")
        check("logout OK", r.status_code == 200 and r.json().get("data", {}).get("ok") is True, str(r.json()))

    return failures
