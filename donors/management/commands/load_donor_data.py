"""
Load donor, donation, and coupon data from Excel into PostgreSQL.

Usage:
    python manage.py load_donor_data --file=data/Coupons_165__Ph_No_.xlsx --sheet=Sheet1
    python manage.py load_donor_data --file="Donors list TPTY -2026.xlsx" --sheet=Sheet1
    python manage.py load_donor_data --file="Donors list TPTY -2026.xlsx" --sheet=Sheet2
    python manage.py load_donor_data --file="KCGF Donor's 2023 & 2024.xlsx" --sheet=2023
    python manage.py load_donor_data --file="KCGF Donor's 2023 & 2024.xlsx" --sheet=2024
    python manage.py load_donor_data --file=data/Coupons_165__Ph_No_.xlsx --sheet=Sheet1 --dry-run
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.models import User
from branches.models import Branch
from coupons.models import Coupon, CouponBatch
from donors.models import Donation, DonationPurpose, DonorProfile, MembershipTier, ReceiptNumber

# Keys: (file_kind, sheet_name). file_kind is detected from the Excel filename.
SHEET_CONFIGS = {
    ("coupons", "Sheet1"): {
        "header_row": 2,
        "has_serial_ranges": True,
        "has_amount": True,
        "has_receipt": True,
        "has_dispatch": True,
        "has_sankalp_header_rows": False,
        "default_sankalp_type": "Hall Renovation",
        "column_map": {
            "sno": "SNo",
            "dist_code": "Dist Code",
            "club_name": "Club Name / Through",
            "donor_name": "Recd From / Through",
            "mobile": "Mobile No",
            "amount": "Amount",
            "receipt_no": "Rec.No.",
            "for_place": "For Place",
            "remarks": 8,
            "concession_count": ("Eligible", 0),
            "concession_serial": ("Sl.No.", 0),
            "free_count": ("Eligible", 1),
            "free_serial": ("Sl.No.", 1),
            "dispatch_ref": "Signature / Reference",
        },
    },
    ("tpty", "Sheet1"): {
        "header_row": 4,
        "has_serial_ranges": True,
        "has_amount": True,
        "has_receipt": True,
        "has_dispatch": True,
        "has_sankalp_header_rows": False,
        "default_sankalp_type": None,
        "column_map": {
            "sno": "SNo",
            "club_name": "Club Name",
            "dist_code": "Dist Code",
            "donor_name": "Recd From",
            "mobile": "Mobile No",
            "amount": "Amount",
            "receipt_no": "Rec No",
            "date": "Date",
            "concession_from": "Cons from",
            "concession_to": ("To", 0),
            "free_from": " Free From",
            "free_to": ("To", 1),
            "dispatch_date": "Dis Date",
            "dispatch_thru": "Dis thru",
            "sankalp_type": "Nature of Payment",
            "concession_serial": "Cons from",
            "concession_count": None,
            "free_serial": " Free From",
            "free_count": None,
        },
    },
    ("tpty", "Sheet2"): {
        "header_row": None,
        "has_serial_ranges": True,
        "has_amount": False,
        "has_receipt": False,
        "has_dispatch": True,
        "has_sankalp_header_rows": True,
        "default_sankalp_type": None,
        "column_map": {
            "sno": "SNo",
            "dist_code": "Dist Code",
            "club_name": "Club Name",
            "donor_name": "Recd From",
            "mobile": "Mobile No",
            "concession_from": "Concession From",
            "concession_to": ("To", 0),
            "free_from": " Free From",
            "free_to": ("To", 1),
            "dispatch_date": "Dispatched Date",
            "dispatch_thru": "Dispatched Thru",
            "concession_serial": "Concession From",
            "free_serial": " Free From",
        },
    },
    ("kcgf", "2023"): {
        "header_row": 3,
        "has_serial_ranges": False,
        "has_amount": False,
        "has_receipt": False,
        "has_dispatch": False,
        "has_sankalp_header_rows": False,
        "default_sankalp_type": "Vidya Sankalp 2023",
        "column_map": {
            "sno": "SNo",
            "dist_code": "Dist Code",
            "club_name": "Club Name",
            "donor_name": "Recd From",
            "mobile": "Mobile Number",
            "free_count": "Free",
            "concession_count": "Concession",
        },
    },
    ("kcgf", "2024"): {
        "header_row": None,
        "has_serial_ranges": True,
        "has_amount": True,
        "has_receipt": False,
        "has_dispatch": False,
        "has_sankalp_header_rows": True,
        "default_sankalp_type": None,
        "column_map": {
            "sno": "S.No.",
            "dist_code": "Dist ",
            "donor_name": "Name",
            "mobile": "Mobile No",
            "amount": "Amount",
            "free_count": "Free",
            "free_serial": ("Count", 0),
            "concession_count": "Concession",
            "concession_serial": ("Count", 1),
        },
    },
}

HEADER_ROW_MARKERS = frozenset({"sno", "s.no.", "s.no"})

TIER_ALIASES = {
    "gold": "Golden",
    "couple silver": "Couple Silver",
    "late silver": "Late Silver",
    "vanitha": "Vanitha",
    "diamond": "Diamond",
    "silver": "Silver",
    "golden": "Golden",
}

# Created via get_or_create before any row import (including --dry-run).
OTHERS_PURPOSE_NAME = "Others"

REQUIRED_DONATION_PURPOSES = [
    "Hall Renovation",
    "Vidya Sankalp 2023",
    "Building A/c. Tirupathi Donations",
    "KCGF Krupa Sankalp",
    OTHERS_PURPOSE_NAME,
]

REQUIRED_MEMBERSHIP_TIERS = [
    "Default",
    "Golden",
    "Silver",
    "Diamond",
    "Couple Silver",
    "Late Silver",
    "Vanitha",
    "Progressive",
]

# Normalized Excel / free-text → canonical DonationPurpose.name
PURPOSE_ALIASES = {
    "hall renovation": "Hall Renovation",
    "hall rennovation": "Hall Renovation",
    "contribution for hall renovation": "Hall Renovation",
    "contribution for hall rennovation": "Hall Renovation",
    "vidya sankalp 2023": "Vidya Sankalp 2023",
    "building a/c. tirupathi donations": "Building A/c. Tirupathi Donations",
    "kcgf krupa sankalp": "KCGF Krupa Sankalp",
}


def normalize_purpose_key(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ").strip().lower())
    text = text.replace("rennovation", "renovation")
    if "contribution for" in text:
        text = text.split("contribution for", 1)[-1].strip()
    return text


def collect_required_purpose_names() -> set[str]:
    names = set(REQUIRED_DONATION_PURPOSES)
    for cfg in SHEET_CONFIGS.values():
        default = cfg.get("default_sankalp_type")
        if default:
            names.add(default)
    return names


def ensure_lookup_tables(command) -> tuple[list[str], list[str]]:
    """get_or_create donation purposes and membership tiers needed for import."""
    created_purposes: list[str] = []
    created_tiers: list[str] = []

    for name in sorted(collect_required_purpose_names()):
        _purpose, created = DonationPurpose.objects.get_or_create(
            name=name,
            defaults={"is_active": True},
        )
        if created:
            created_purposes.append(name)

    for name in REQUIRED_MEMBERSHIP_TIERS:
        _tier, created = MembershipTier.objects.get_or_create(
            name=name,
            defaults={"is_active": True},
        )
        if created:
            created_tiers.append(name)

    if created_purposes:
        command.stdout.write(
            command.style.SUCCESS(
                "Created donation purposes: " + ", ".join(created_purposes)
            )
        )
    if created_tiers:
        command.stdout.write(
            command.style.SUCCESS(
                "Created membership tiers: " + ", ".join(created_tiers)
            )
        )
    return created_purposes, created_tiers


def build_purposes_by_name() -> dict[str, DonationPurpose]:
    purposes_by_name: dict[str, DonationPurpose] = {}
    for purpose in DonationPurpose.objects.filter(is_active=True):
        purposes_by_name[purpose.name.lower()] = purpose
        purposes_by_name[normalize_purpose_key(purpose.name)] = purpose
    for alias_key, canonical in PURPOSE_ALIASES.items():
        canonical_purpose = purposes_by_name.get(canonical.lower())
        if canonical_purpose is not None:
            purposes_by_name[alias_key] = canonical_purpose
    return purposes_by_name


def resolve_purpose(
    raw_value,
    purposes_by_name: dict[str, DonationPurpose],
    *,
    fallback: DonationPurpose | None = None,
) -> tuple[DonationPurpose | None, bool]:
    """Return (purpose, used_fallback). Unmatched values map to fallback (Others)."""
    if _is_blank(raw_value):
        return fallback, fallback is not None
    text = str(raw_value).strip()
    for key in (text.lower(), normalize_purpose_key(text)):
        purpose = purposes_by_name.get(key)
        if purpose is not None:
            return purpose, False
    canonical = PURPOSE_ALIASES.get(normalize_purpose_key(text))
    if canonical:
        purpose = purposes_by_name.get(canonical.lower())
        if purpose is not None:
            return purpose, False
    if fallback is not None:
        return fallback, True
    return None, False


def normalize_phone(value) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if text.startswith("+91"):
        text = text[3:].strip()
    digits_only = re.sub(r"\D", "", text)
    if len(digits_only) >= 10:
        return digits_only[-10:]
    match = re.search(r"(?:\+?91)?[6-9]\d{9}", text)
    if match:
        return re.sub(r"\D", "", match.group())[-10:]
    if digits_only:
        return digits_only
    return text or None


def clean_amount(value) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 10000
    try:
        if isinstance(value, str):
            text = value
        else:
            text = str(value)
        text = text.replace("Rs.", "").replace("rs.", "")
        text = text.replace(",", "").replace("/-", "").strip()
        if not text:
            return 10000
        rupees = int(float(text))
        paise = rupees * 100
        return paise if paise > 0 else 10000
    except (TypeError, ValueError):
        return 10000


def parse_serial_range(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return (None, None)
    text = str(value).strip()
    if not text or text.lower() in {"na", "n/a", "-", "none"}:
        return (None, None)
    match = re.search(r"(\d+)\s*[-to ]+\s*(\d+)", text, re.IGNORECASE)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    try:
        single = int(float(text))
        return (single, single)
    except (TypeError, ValueError):
        return (None, None)


def split_donor_name(raw_name):
    if raw_name is None or (isinstance(raw_name, float) and pd.isna(raw_name)):
        return (None, "Unknown")
    text = str(raw_name).strip()
    if not text:
        return (None, "Unknown")
    if "*" in text:
        left, right = text.split("*", 1)
        return (left.strip() or None, right.strip() or "Unknown")
    return (None, text)


def normalize_rank_prefix(prefix):
    if prefix is None:
        return None
    cleaned = str(prefix).lower().strip()
    prefixes = ("vn.", "vn", "prog.", "prog ", "vanitha ")
    changed = True
    while changed:
        changed = False
        for lead in prefixes:
            if cleaned.startswith(lead):
                cleaned = cleaned[len(lead) :].strip()
                changed = True
    cleaned = cleaned.strip()
    if cleaned in TIER_ALIASES:
        return TIER_ALIASES[cleaned]
    if cleaned:
        return cleaned.title()
    return None


def resolve_tier(normalized_prefix, tiers_by_name):
    if tiers_by_name is None or not tiers_by_name:
        raise CommandError("No MembershipTier rows exist. Seed them first.")
    if normalized_prefix:
        tier = tiers_by_name.get(normalized_prefix.lower())
        if tier is not None:
            return tier
    default_tier = tiers_by_name.get("default")
    if default_tier is not None:
        return default_tier
    return next(iter(tiers_by_name.values()))


def normalize_dist_code(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", "", str(value).upper())


def normalize_date(value):
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def normalize_dispatch_method(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "other"
    text = str(value).lower()
    if "courier" in text:
        return "courier"
    if "hand" in text:
        return "by_hand"
    return "other"


def extract_sankalp_type(df: pd.DataFrame) -> pd.DataFrame:
    """Tag data rows with sankalp_type; drop section titles and apply column headers."""
    chunks: list = []
    sankalps: list[str | None] = []
    current_sankalp: str | None = None
    columns: list[str] | None = None

    for idx in range(len(df)):
        row = df.iloc[idx]
        if _is_column_header_row(row):
            columns = [_norm_col(c) for c in row]
            continue
        if _is_sankalp_section_header(row):
            current_sankalp = str(row.iloc[0]).strip()
            continue
        if columns is None:
            continue
        chunks.append(row.tolist()[: len(columns)])
        sankalps.append(current_sankalp)

    if not chunks or columns is None:
        return pd.DataFrame()

    out = pd.DataFrame(chunks, columns=columns)
    out["sankalp_type"] = sankalps
    return out.reset_index(drop=True)


def _is_column_header_row(row) -> bool:
    col0 = row.iloc[0]
    if pd.isna(col0):
        return False
    marker = str(col0).strip().lower().rstrip(".")
    if marker in HEADER_ROW_MARKERS:
        return True
    if len(row) > 1:
        col1 = row.iloc[1]
        if isinstance(col1, str) and "dist" in col1.lower():
            return True
    return False


def _is_sankalp_section_header(row) -> bool:
    if _is_column_header_row(row):
        return False
    col0 = row.iloc[0]
    if pd.isna(col0):
        return False
    try:
        float(str(col0).strip().replace(",", ""))
        return False
    except (TypeError, ValueError):
        pass
    filled = sum(1 for val in row if not _is_blank(val))
    return filled <= 1


def _norm_col(name) -> str:
    return str(name).strip()


def _parse_count(value) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        count = int(float(value))
        return count if count > 0 else None
    except (TypeError, ValueError):
        return None


def read_row_field(row, df: pd.DataFrame, field_spec) -> object | None:
    if field_spec is None:
        return None
    if isinstance(field_spec, int):
        if field_spec < len(row):
            val = row.iloc[field_spec]
            return None if isinstance(val, float) and pd.isna(val) else val
        return None
    if isinstance(field_spec, tuple):
        col_name = field_spec[0]
        occurrence = field_spec[1] if len(field_spec) > 1 else 0
        indices = [i for i, c in enumerate(df.columns) if _norm_col(c) == _norm_col(col_name)]
        if not indices:
            return None
        idx = indices[min(occurrence, len(indices) - 1)]
        val = row.iloc[idx]
        return None if isinstance(val, float) and pd.isna(val) else val
    col_name = field_spec
    if col_name not in df.columns:
        matches = [c for c in df.columns if _norm_col(c) == _norm_col(col_name)]
        if not matches:
            return None
        val = row[matches[0]]
    else:
        val = row[col_name]
    return None if isinstance(val, float) and pd.isna(val) else val


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return not str(value).strip()


def _is_valid_sno(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def detect_file_kind(file_path: str) -> str:
    name = Path(file_path).name.lower()
    if "coupon" in name or "165" in name:
        return "coupons"
    if "tpty" in name or "donors list" in name:
        return "tpty"
    if "kcgf" in name or "2023" in name or "2024" in name:
        return "kcgf"
    raise CommandError(
        f"Cannot detect file type from filename '{Path(file_path).name}'. "
        "Expected Coupons, TPTY, or KCGF workbook."
    )


def load_dataframe(file_path: str, sheet_name: str, config: dict) -> pd.DataFrame:
    df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    if config.get("has_sankalp_header_rows"):
        return extract_sankalp_type(df)
    header_row = config["header_row"]
    df.columns = [_norm_col(c) for c in df.iloc[header_row]]
    return df.iloc[header_row + 1 :].reset_index(drop=True)


def get_or_create_user(phone, name, dry_run: bool = False):
    phone_text = normalize_phone(phone) or ""
    if not phone_text:
        phone_text = f"UNKNOWN-{uuid.uuid4().hex[:8]}"
        print(f"WARNING: missing phone for '{name}'; using placeholder {phone_text}")
    existing = User.objects.filter(phone=phone_text).first()
    if existing:
        return existing, False
    if dry_run:
        return None, True
    user = User.objects.create(
        phone=phone_text,
        name=name or "",
        role="donor",
        is_active=True,
        is_first_login=True,
    )
    user.set_unusable_password()
    user.save()
    return user, True


def get_or_create_donor_profile(
    user,
    dist_code,
    club_name,
    tier,
    branch,
    counter,
    year,
    dry_run: bool = False,
):
    if user is None:
        return None, True
    existing = DonorProfile.objects.filter(user=user).first()
    if existing:
        return existing, False
    if dry_run:
        return None, True
    donor_id = f"DH-{year}-{str(counter).zfill(4)}"
    profile = DonorProfile.objects.create(
        user=user,
        donor_id=donor_id,
        membership_tier=tier,
        district_code=dist_code,
        club_name=club_name,
        for_place=branch,
    )
    return profile, True


def _parse_range_from_columns(row, df, from_spec, to_spec):
    start_raw = read_row_field(row, df, from_spec) if from_spec else None
    end_raw = read_row_field(row, df, to_spec) if to_spec else None
    if start_raw is not None and end_raw is not None:
        try:
            start = int(float(start_raw))
            end = int(float(end_raw))
            if start > 0 and end >= start:
                return (start, end)
        except (TypeError, ValueError):
            pass
    if start_raw is not None:
        return parse_serial_range(start_raw)
    return (None, None)


def _create_batch(
    *,
    donation,
    coupon_type: str,
    serial_start: int,
    serial_end: int,
    dry_run: bool,
    stats: dict,
) -> int:
    count = serial_end - serial_start + 1
    stats["batches_created"] += 1
    if coupon_type == CouponBatch.CouponType.CONCESSION:
        stats["batches_concession"] += 1
    else:
        stats["batches_free"] += 1
    if stats["first_serial"] is None or serial_start < stats["first_serial"]:
        stats["first_serial"] = serial_start
    if stats["last_serial"] is None or serial_end > stats["last_serial"]:
        stats["last_serial"] = serial_end
    if dry_run:
        stats["coupons_created"] += count
        return serial_end
    CouponBatch.objects.create(
        donation=donation,
        coupon_type=coupon_type,
        serial_start=serial_start,
        serial_end=serial_end,
        count=count,
    )
    stats["coupons_created"] += count
    return serial_end


def _resolve_batch_count(
    batch_kind: str,
    row,
    df: pd.DataFrame,
    config: dict,
    cmap: dict,
) -> int | None:
    """How many coupons in this batch. Excel serials are used only to derive count."""
    count_key = f"{batch_kind}_count"
    from_key = f"{batch_kind}_from"
    to_key = f"{batch_kind}_to"
    serial_key = f"{batch_kind}_serial"

    count = _parse_count(read_row_field(row, df, cmap.get(count_key)))
    if count:
        return count

    if not config.get("has_serial_ranges"):
        return None

    file_start = file_end = None
    from_spec = cmap.get(from_key)
    to_spec = cmap.get(to_key)
    if from_spec is not None or to_spec is not None:
        file_start, file_end = _parse_range_from_columns(row, df, from_spec, to_spec)
    if file_start is None:
        serial_spec = cmap.get(serial_key)
        if serial_spec is not None:
            file_start, file_end = parse_serial_range(read_row_field(row, df, serial_spec))

    if file_start is not None and file_end is not None and file_end >= file_start:
        return file_end - file_start + 1
    return None


def process_coupon_batch(
    *,
    batch_kind: str,
    row,
    df,
    config: dict,
    serial_counter: int,
    donation,
    dry_run: bool,
    stats: dict,
) -> int:
    cmap = config["column_map"]

    coupon_type = (
        CouponBatch.CouponType.CONCESSION
        if batch_kind == "concession"
        else CouponBatch.CouponType.FREE
    )

    count = _resolve_batch_count(batch_kind, row, df, config, cmap)
    if not count:
        return serial_counter

    # Always assign from the running counter (>= 5000) — never reuse Excel serials.
    serial_start = serial_counter + 1
    serial_end = serial_counter + count

    if donation is None and not dry_run:
        return serial_end

    return _create_batch(
        donation=donation,
        coupon_type=coupon_type,
        serial_start=serial_start,
        serial_end=serial_end,
        dry_run=dry_run,
        stats=stats,
    )


class Command(BaseCommand):
    help = "Load donor, donation, and coupon data from an Excel workbook sheet."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Full path to the Excel file.")
        parser.add_argument("--sheet", required=True, help="Sheet name to load.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )
        parser.add_argument(
            "--skip-errors",
            action="store_true",
            help="Log per-row errors and continue instead of aborting the whole load.",
        )

    def handle(self, *args, **options):
        try:
            import pandas  # noqa: F401
        except ImportError as exc:
            raise CommandError("pandas is required: pip install pandas") from exc

        file_path = options["file"]
        sheet_name = options["sheet"]
        dry_run = options["dry_run"]
        skip_errors = options["skip_errors"]

        if not Path(file_path).exists():
            raise CommandError(f"File not found: {file_path}")

        file_kind = detect_file_kind(file_path)
        config_key = (file_kind, sheet_name)
        if config_key not in SHEET_CONFIGS:
            raise CommandError(
                f"No SHEET_CONFIGS entry for file kind '{file_kind}' and sheet '{sheet_name}'."
            )
        config = SHEET_CONFIGS[config_key]

        df = load_dataframe(file_path, sheet_name, config)
        cmap = config["column_map"]

        ensure_lookup_tables(self)
        tiers_by_name = {t.name.lower(): t for t in MembershipTier.objects.filter(is_active=True)}
        purposes_by_name = build_purposes_by_name()
        branches_lookup: dict[str, Branch] = {}
        for branch in Branch.objects.all():
            branches_lookup[branch.city.lower()] = branch
        for branch in Branch.objects.all():
            branches_lookup.setdefault(branch.name.lower(), branch)

        super_admin = User.objects.filter(role="super_admin").first()
        if super_admin is None:
            raise CommandError("No super_admin user found. Create one before running this command.")

        max_serial = Coupon.objects.aggregate(m=Max("serial_number"))["m"] or 0
        serial_counter = max(max_serial, 4999)

        year = timezone.now().year
        suffixes = []
        for profile in DonorProfile.all_objects.filter(donor_id__startswith=f"DH-{year}-"):
            match = re.match(rf"DH-{year}-(\d+)", profile.donor_id)
            if match:
                suffixes.append(int(match.group(1)))
        donor_id_counter = max(suffixes) + 1 if suffixes else 1

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            f"{prefix}File: {file_path}\n"
            f"{prefix}Sheet: {sheet_name} ({file_kind})\n"
            f"{prefix}Rows to process: {len(df)}\n"
            f"{prefix}Dry run: {'yes' if dry_run else 'no'}\n"
            f"{prefix}Next serial: {serial_counter + 1}\n"
            f"{prefix}Next donor_id suffix: {donor_id_counter:04d}"
        )

        stats = {
            "rows_processed": 0,
            "rows_skipped": 0,
            "users_created": 0,
            "users_would_create": 0,
            "users_reused": 0,
            "profiles_created": 0,
            "profiles_would_create": 0,
            "profiles_reused": 0,
            "donations_created": 0,
            "donations_would_create": 0,
            "receipts_created": 0,
            "batches_created": 0,
            "batches_concession": 0,
            "batches_free": 0,
            "coupons_created": 0,
            "rows_mapped_to_others": 0,
            "first_serial": None,
            "last_serial": None,
        }
        skip_log: list[tuple[int, str]] = []
        serial_counter_ref = [serial_counter]
        donor_id_counter_ref = [donor_id_counter]

        def run_all_rows():
            for row_idx, row in df.iterrows():
                _run_single_row(
                    row_idx=row_idx,
                    row=row,
                    df=df,
                    config=config,
                    cmap=cmap,
                    tiers_by_name=tiers_by_name,
                    purposes_by_name=purposes_by_name,
                    branches_lookup=branches_lookup,
                    super_admin=super_admin,
                    dry_run=dry_run,
                    stats=stats,
                    skip_log=skip_log,
                    serial_counter_ref=serial_counter_ref,
                    donor_id_counter_ref=donor_id_counter_ref,
                    year=year,
                    command=self,
                )

        if skip_errors:
            for row_idx, row in df.iterrows():
                try:
                    with transaction.atomic():
                        _run_single_row(
                            row_idx=row_idx,
                            row=row,
                            df=df,
                            config=config,
                            cmap=cmap,
                            tiers_by_name=tiers_by_name,
                            purposes_by_name=purposes_by_name,
                            branches_lookup=branches_lookup,
                            super_admin=super_admin,
                            dry_run=dry_run,
                            stats=stats,
                            skip_log=skip_log,
                            serial_counter_ref=serial_counter_ref,
                            donor_id_counter_ref=donor_id_counter_ref,
                            year=year,
                            command=self,
                        )
                except Exception as exc:
                    row_num = int(row_idx) + 1
                    stats["rows_skipped"] += 1
                    skip_log.append((row_num, str(exc)))
                    self.stdout.write(self.style.ERROR(f"Row {row_num}: {exc}"))
        elif dry_run:
            run_all_rows()
        else:
            with transaction.atomic():
                run_all_rows()

        self._print_summary(file_path, sheet_name, dry_run, stats, skip_log, skip_errors)

    def _print_summary(
        self,
        file_path: str,
        sheet_name: str,
        dry_run: bool,
        stats: dict,
        skip_log: list[tuple[int, str]],
        skip_errors: bool,
    ) -> None:
        first = stats["first_serial"]
        last = stats["last_serial"]
        if first is None or last is None:
            serial_range = "n/a"
        else:
            serial_range = f"{first} -> {last}"

        lines = [
            "========== LOAD SUMMARY ==========",
            f"File      : {file_path}",
            f"Sheet     : {sheet_name}",
            f"Dry run   : {'yes' if dry_run else 'no'}",
            "----------------------------------",
            f"Rows processed     : {stats['rows_processed']}",
            f"Rows skipped       : {stats['rows_skipped']} (errors or missing purpose)",
            f"Rows -> Others     : {stats['rows_mapped_to_others']}",
            (
                f"Users created      : {stats['users_would_create'] if dry_run else stats['users_created']}"
                + (" (planned)" if dry_run else "")
            ),
            f"Users reused       : {stats['users_reused']}",
            (
                f"Profiles created   : {stats['profiles_would_create'] if dry_run else stats['profiles_created']}"
                + (" (planned)" if dry_run else "")
            ),
            f"Profiles reused    : {stats['profiles_reused']}",
            (
                f"Donations created  : {stats['donations_would_create'] if dry_run else stats['donations_created']}"
                + (" (planned)" if dry_run else "")
            ),
            (
                f"Receipts created   : {stats['receipts_created']}"
                + (" (planned)" if dry_run and stats["receipts_created"] else "")
            ),
            (
                f"Batches created    : {stats['batches_created']} "
                f"(concession: {stats['batches_concession']}, free: {stats['batches_free']})"
            ),
            f"Coupons created    : {stats['coupons_created']}",
            f"Serial range used  : {serial_range}",
            "==================================",
        ]
        prefix = "[DRY RUN] " if dry_run else ""
        for line in lines:
            self.stdout.write(prefix + line)

        if skip_errors and skip_log:
            self.stdout.write(prefix + "Skipped row details:")
            for row_num, message in skip_log:
                self.stdout.write(prefix + f"  Row {row_num}: {message}")


def _run_single_row(
    *,
    row_idx,
    row,
    df,
    config,
    cmap,
    tiers_by_name,
    purposes_by_name,
    branches_lookup,
    super_admin,
    dry_run,
    stats,
    skip_log,
    serial_counter_ref,
    donor_id_counter_ref,
    year,
    command,
):
    """Process one data row; mutates serial_counter_ref and donor_id_counter_ref."""
    serial_counter = serial_counter_ref[0]
    donor_id_counter = donor_id_counter_ref[0]

    sno_val = read_row_field(row, df, cmap.get("sno"))
    if not _is_valid_sno(sno_val):
        return

    stats["rows_processed"] += 1
    row_num = int(row_idx) + 1

    raw_donor_name = read_row_field(row, df, cmap.get("donor_name"))
    rank_prefix, clean_name = split_donor_name(raw_donor_name)
    normalized_prefix = normalize_rank_prefix(rank_prefix)
    tier = resolve_tier(normalized_prefix, tiers_by_name)

    sankalp_raw = read_row_field(row, df, cmap.get("sankalp_type"))
    if _is_blank(sankalp_raw) and "sankalp_type" in row.index:
        val = row.get("sankalp_type")
        sankalp_raw = None if isinstance(val, float) and pd.isna(val) else val
    if _is_blank(sankalp_raw):
        sankalp_raw = config.get("default_sankalp_type")
    original_sankalp = "" if _is_blank(sankalp_raw) else str(sankalp_raw).strip()
    others_purpose = purposes_by_name.get(OTHERS_PURPOSE_NAME.lower())
    purpose, used_others = resolve_purpose(
        sankalp_raw,
        purposes_by_name,
        fallback=others_purpose,
    )
    if purpose is None:
        msg = f"Row {row_num}: no purpose and '{OTHERS_PURPOSE_NAME}' missing in DB — skipping."
        command.stdout.write(command.style.WARNING(msg))
        stats["rows_skipped"] += 1
        skip_log.append((row_num, msg))
        return
    if used_others and original_sankalp:
        stats["rows_mapped_to_others"] += 1
        command.stdout.write(
            command.style.WARNING(
                f"Row {row_num}: purpose '{original_sankalp}' -> {OTHERS_PURPOSE_NAME}"
            )
        )

    mobile_raw = read_row_field(row, df, cmap.get("mobile"))
    mobile = normalize_phone(mobile_raw)
    if not mobile:
        mobile = normalize_phone(raw_donor_name)

    for_place = read_row_field(row, df, cmap.get("for_place"))
    branch = None
    if not _is_blank(for_place):
        branch = branches_lookup.get(str(for_place).strip().lower())

    dist_code = normalize_dist_code(read_row_field(row, df, cmap.get("dist_code")))

    club_name_raw = read_row_field(row, df, cmap.get("club_name"))
    club_name = "Others" if _is_blank(club_name_raw) else str(club_name_raw).strip()

    user, user_created = get_or_create_user(mobile, clean_name, dry_run=dry_run)
    if user_created:
        if dry_run:
            stats["users_would_create"] += 1
        else:
            stats["users_created"] += 1
    else:
        stats["users_reused"] += 1

    profile, profile_created = get_or_create_donor_profile(
        user,
        dist_code,
        club_name,
        tier,
        branch,
        donor_id_counter,
        year,
        dry_run=dry_run,
    )
    if profile_created:
        if dry_run:
            stats["profiles_would_create"] += 1
        else:
            stats["profiles_created"] += 1
        donor_id_counter += 1
    else:
        stats["profiles_reused"] += 1

    amount_raw = read_row_field(row, df, cmap.get("amount"))
    if not config["has_amount"]:
        amount_raw = None
    amount_paise = clean_amount(amount_raw)

    dispatch_method = "other"
    dispatch_date = None
    raw_dispatch_thru = ""
    if config["has_dispatch"]:
        dispatch_ref = read_row_field(row, df, cmap.get("dispatch_ref"))
        dispatch_thru = read_row_field(row, df, cmap.get("dispatch_thru"))
        raw_dispatch_thru = "" if _is_blank(dispatch_thru) else str(dispatch_thru).strip()
        if _is_blank(raw_dispatch_thru) and not _is_blank(dispatch_ref):
            raw_dispatch_thru = str(dispatch_ref).strip()
        dispatch_method = normalize_dispatch_method(raw_dispatch_thru)
        dispatch_date = normalize_date(read_row_field(row, df, cmap.get("dispatch_date")))

    dispatch_notes = raw_dispatch_thru or ""
    if used_others and original_sankalp:
        sankalp_note = f"Sankalp: {original_sankalp}"
        dispatch_notes = (
            f"{sankalp_note}; {dispatch_notes}" if dispatch_notes else sankalp_note
        )

    donation = None
    if dry_run:
        stats["donations_would_create"] += 1
        if config["has_receipt"]:
            receipt_no = read_row_field(row, df, cmap.get("receipt_no"))
            if not _is_blank(receipt_no):
                stats["receipts_created"] += 1
    else:
        donation = Donation.objects.create(
            donor=profile,
            amount=amount_paise,
            purpose=purpose,
            dispatch_date=dispatch_date,
            dispatch_method=dispatch_method,
            dispatch_notes=dispatch_notes,
            created_by=super_admin,
        )
        stats["donations_created"] += 1

        if config["has_receipt"]:
            receipt_no = read_row_field(row, df, cmap.get("receipt_no"))
            if not _is_blank(receipt_no):
                ReceiptNumber.objects.create(
                    donation=donation,
                    receipt_number=str(receipt_no).strip(),
                )
                stats["receipts_created"] += 1

    serial_counter = process_coupon_batch(
        batch_kind="concession",
        row=row,
        df=df,
        config=config,
        serial_counter=serial_counter,
        donation=donation,
        dry_run=dry_run,
        stats=stats,
    )
    serial_counter = process_coupon_batch(
        batch_kind="free",
        row=row,
        df=df,
        config=config,
        serial_counter=serial_counter,
        donation=donation,
        dry_run=dry_run,
        stats=stats,
    )

    if donation is not None and dispatch_date is not None and not dry_run:
        Coupon.objects.filter(batch__donation=donation).update(status=Coupon.Status.DISPATCHED)

    serial_counter_ref[0] = serial_counter
    donor_id_counter_ref[0] = donor_id_counter
