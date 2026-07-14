"""
Owns the custom User model (phone-based auth), OTP verification,
profile confirmation, and admin–branch assignment.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from core.models import (
    AllObjectsManager,
    SoftDeleteManager,
    SoftDeleteModel,
    TimeStampedModel,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLE_CHOICES = [
    ("user", "User"),
    ("donor", "Donor"),
    ("admin", "Branch Admin"),
    ("super_admin", "Super Admin"),
]

_PHONE_REGEX = RegexValidator(
    regex=r"^\+?\d{10,15}$",
    message="Enter a valid phone number (10–15 digits, optional leading '+').",
)


# ---------------------------------------------------------------------------
# Custom User Manager
# ---------------------------------------------------------------------------

class UserManager(BaseUserManager):
    """
    Custom manager for :model:`accounts.User`.

    Extends Django's ``BaseUserManager`` and filters out soft-deleted
    rows by default (mirroring :class:`SoftDeleteManager` behaviour)
    so that ``User.objects`` never returns logically-deleted users.
    """

    def get_queryset(self):
        """Exclude soft-deleted users from default querysets."""
        return super().get_queryset().filter(is_deleted=False)

    # ---- factory helpers ---------------------------------------------------

    def create_user(
        self,
        phone: str,
        role: str = "user",
        password: str | None = None,
        **extra_fields,
    ):
        """
        Create and persist a regular user.

        Parameters
        ----------
        phone : str
            The user's phone number (used as the username field).
        role : str, optional
            One of the four system roles. Defaults to ``'user'``.
        password : str | None, optional
            Plain-text password. ``None`` for OTP-only authentication;
            a hashed password is stored when provided (required for
            ``createsuperuser``).
        **extra_fields
            Arbitrary keyword arguments forwarded to the model
            constructor (e.g. ``name``, ``email``).

        Returns
        -------
        User
            The newly-created user instance.

        Raises
        ------
        ValueError
            If *phone* is empty or missing.
        """
        if not phone:
            raise ValueError("A phone number is required to create a user.")

        # Normalise: strip whitespace
        phone = phone.strip()

        # Set privilege flags based on role
        extra_fields.setdefault(
            "is_staff", role in ("admin", "super_admin"),
        )
        extra_fields.setdefault(
            "is_superuser", role == "super_admin",
        )

        user = self.model(phone=phone, role=role, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        phone: str,
        password: str | None = None,
        **extra_fields,
    ):
        """
        Create and persist a superuser (``role='super_admin'``).

        Forces ``is_staff=True`` and ``is_superuser=True`` regardless
        of what is passed in *extra_fields*.
        """
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True

        return self.create_user(
            phone=phone,
            role="super_admin",
            password=password,
            **extra_fields,
        )


# ---------------------------------------------------------------------------
# User Model
# ---------------------------------------------------------------------------

class User(AbstractBaseUser, PermissionsMixin, SoftDeleteModel):
    """
    Custom user model with **phone-based authentication**.

    This model replaces Django's default ``auth.User``.  The phone
    number serves as the ``USERNAME_FIELD``; passwords are optional
    because the primary authentication flow relies on OTPs.

    Manager Layout
    ~~~~~~~~~~~~~~
    * ``objects`` — :class:`UserManager` (default; filters soft-deleted
      rows **and** exposes ``create_user`` / ``create_superuser``).
    * ``all_objects`` — :class:`AllObjectsManager` (includes soft-deleted
      rows, useful for admin audits).
    * ``active_objects`` — :class:`SoftDeleteManager` (identical filter
      to ``objects`` but without the ``BaseUserManager`` helpers; kept
      for consistency with other ``SoftDeleteModel`` subclasses).
    """

    # ---- fields ------------------------------------------------------------

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    phone = models.CharField(
        max_length=15,
        unique=True,
        db_index=True,
        validators=[_PHONE_REGEX],
        help_text="Primary identifier; 10–15 digits, optional leading '+'.",
    )
    name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Full display name of the user.",
    )
    email = models.EmailField(
        blank=True,
        null=True,
        help_text="Optional email address (not used for authentication).",
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="user",
        help_text="Determines UI capabilities and API permissions.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    is_staff = models.BooleanField(
        default=False,
        help_text="Designates whether the user can log into the admin site.",
    )
    is_first_login = models.BooleanField(
        default=True,
        help_text=(
            "True until the user confirms their profile after first "
            "OTP login."
        ),
    )

    date_joined = models.DateTimeField(
        default=timezone.now,
        help_text="Timestamp of account creation.",
    )

    # ---- managers ----------------------------------------------------------

    objects = UserManager()
    all_objects = AllObjectsManager()
    active_objects = SoftDeleteManager()

    # ---- auth config -------------------------------------------------------

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []  # phone is the username → already required

    # ---- properties --------------------------------------------------------

    @property
    def is_donor(self) -> bool:
        """Return ``True`` if the user has the *donor* role."""
        return self.role == "donor"

    @property
    def is_admin_staff(self) -> bool:
        """Return ``True`` for *admin* and *super_admin* roles."""
        return self.role in ("admin", "super_admin")

    # ---- meta & dunder -----------------------------------------------------

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ["-date_joined"]

    def __str__(self) -> str:
        return f"{self.phone} ({self.get_role_display()})"


# ---------------------------------------------------------------------------
# OTP Log
# ---------------------------------------------------------------------------

class OTPLog(TimeStampedModel):
    """
    Append-only log of every OTP issued by the system.

    OTPs are **never** stored in plain text.  The ``hashed_otp`` field
    holds a hash produced by ``django.contrib.auth.hashers.make_password``
    (Argon2 / PBKDF2) and is verified via ``check_password``.

    Security controls
    ~~~~~~~~~~~~~~~~~
    * Each OTP expires 10 minutes after creation (``expires_at``).
    * After 3 consecutive failed attempts the record is **locked** for
      10 minutes (``locked_until``).
    * A maximum of 5 unverified OTPs per phone per hour is enforced by
      :meth:`can_send`.

    .. note::
       This model intentionally does **not** use ``SoftDeleteModel`` —
       OTP records are immutable audit entries that must never be
       logically deleted.
    """

    phone = models.CharField(
        max_length=15,
        db_index=True,
        help_text="Phone number the OTP was sent to.",
    )
    hashed_otp = models.CharField(
        max_length=128,
        help_text="Argon2/PBKDF2 hashed OTP via make_password.",
    )
    purpose = models.CharField(
        max_length=20,
        choices=[("login", "Login"), ("registration", "Registration")],
        default="login",
        help_text="Reason the OTP was issued.",
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="Set to True once the OTP is successfully verified.",
    )
    attempts = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of consecutive failed verification attempts.",
    )
    locked_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="If set, the OTP cannot be verified until this time.",
    )
    expires_at = models.DateTimeField(
        help_text="Auto-set to created_at + 10 minutes on save.",
    )

    class Meta:
        verbose_name = "OTP log"
        verbose_name_plural = "OTP logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["phone", "created_at"],
                name="idx_otp_phone_created",
            ),
            # Covers OTPLog.can_send (phone + is_verified=False + created_at__gte)
            # and OTPLog.verify (phone + is_verified=False lookups).
            models.Index(
                fields=["phone", "is_verified", "created_at"],
                name="idx_otp_phone_verified_created",
            ),
        ]

    # ---- lifecycle ---------------------------------------------------------

    def save(self, *args, **kwargs):
        """Auto-populate ``expires_at`` on first insert (UUID pk is set before save)."""
        if self._state.adding and not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    # ---- class-level helpers -----------------------------------------------

    @classmethod
    def can_send(cls, phone: str) -> bool:
        """
        Rate-limit check: allow a maximum of **5 unverified OTPs per
        phone per hour**.

        Parameters
        ----------
        phone : str
            The phone number to check.

        Returns
        -------
        bool
            ``True`` if a new OTP may be sent; ``False`` otherwise.
        """
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_count = cls.objects.filter(
            phone=phone,
            created_at__gte=one_hour_ago,
            is_verified=False,
        ).count()
        return recent_count < 5

    @classmethod
    def verify(cls, phone: str, raw_otp: str) -> tuple[str, "OTPLog | None"]:
        """
        Attempt to verify the most recent pending OTP for *phone*.

        Parameters
        ----------
        phone : str
            The phone number whose OTP should be verified.
        raw_otp : str
            The plain-text OTP entered by the user.

        Returns
        -------
        tuple[str, OTPLog | None]
            A two-element tuple: the first element is one of
            ``'success'``, ``'invalid'``, ``'expired'``, or
            ``'locked'``; the second is the :class:`OTPLog` instance
            (or ``None`` when no matching record exists).
        """
        from django.db import transaction

        with transaction.atomic():
            log = (
                cls.objects.select_for_update()
                .filter(phone=phone, is_verified=False)
                .order_by("-created_at")
                .first()
            )

            if log is None:
                return "invalid", None

            now = timezone.now()

            # Locked-out after too many failed attempts
            if log.locked_until and now < log.locked_until:
                return "locked", log

            # OTP has expired
            if now > log.expires_at:
                return "expired", log

            # Verify the hash
            if not check_password(raw_otp, log.hashed_otp):
                log.attempts += 1
                if log.attempts >= 3:
                    log.locked_until = now + timedelta(minutes=10)
                log.save(update_fields=["attempts", "locked_until"])
                return "invalid", log

            # Success
            log.is_verified = True
            log.save(update_fields=["is_verified"])
            return "success", log


    # ---- dunder ------------------------------------------------------------

    def __str__(self) -> str:
        return f"OTP for {self.phone} at {self.created_at:%Y-%m-%d %H:%M}"


# ---------------------------------------------------------------------------
# Profile Confirmation
# ---------------------------------------------------------------------------

class ProfileConfirmation(TimeStampedModel):
    """
    Tracks whether a user has reviewed and confirmed their profile
    details after the very first OTP-based login.

    A companion to ``User.is_first_login`` — once the user submits the
    confirmation form the API sets ``is_confirmed=True`` and flips
    ``User.is_first_login`` to ``False``.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile_confirmation",
        help_text="The user whose profile confirmation this tracks.",
    )
    is_confirmed = models.BooleanField(
        default=False,
        help_text="True once the user has confirmed their profile.",
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of when the profile was confirmed.",
    )

    class Meta:
        verbose_name = "profile confirmation"
        verbose_name_plural = "profile confirmations"

    def __str__(self) -> str:
        return f"Profile confirmation for {self.user.phone}"


# ---------------------------------------------------------------------------
# Admin ↔ Branch Assignment
# ---------------------------------------------------------------------------

class AdminBranch(TimeStampedModel):
    """
    Links a **branch-admin** user to exactly one :model:`branches.Branch`.

    Only users with ``role='admin'`` may be assigned, and only a
    ``super_admin`` may perform the assignment.  These constraints are
    enforced at the database level via ``limit_choices_to`` and at the
    application level via :meth:`clean`.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_branch",
        limit_choices_to={"role": "admin"},
        help_text="The branch-admin user being assigned.",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.CASCADE,
        related_name="branch_admins",
        help_text="The branch this admin is responsible for.",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="admin_assignments_made",
        limit_choices_to={"role": "super_admin"},
        help_text="The super-admin who made this assignment.",
    )
    assigned_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the assignment was created.",
    )

    class Meta:
        verbose_name = "admin branch assignment"
        verbose_name_plural = "admin branch assignments"

    def clean(self):
        """
        Application-level validation to guarantee role constraints.

        Raises
        ------
        ValidationError
            If the assigned user is not an *admin* or the assigner is
            not a *super_admin*.
        """
        super().clean()

        if self.user_id and self.user.role != "admin":
            raise ValidationError(
                {"user": "Only users with the 'admin' role can be "
                         "assigned to a branch."}
            )

        if self.assigned_at and not self._state.adding:
            # Prevent reassigning admin to a different branch without explicit deletion.
            try:
                old = AdminBranch.objects.get(pk=self.pk)
                if old.branch_id != self.branch_id:
                    raise ValidationError(
                        {"branch": "Cannot reassign admin to a different branch. "                                    "Delete this record and create a new one."}
                    )
            except AdminBranch.DoesNotExist:
                pass

    class Meta:
        verbose_name = "admin branch assignment"
        verbose_name_plural = "admin branch assignments"
        unique_together = [("user",)]  # one branch per admin
