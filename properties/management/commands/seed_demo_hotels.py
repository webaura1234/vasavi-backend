"""
Seed branches + rooms aligned with vasavi-main-site mock hotels (lib/data/hotels.ts).

Usage:
    python manage.py seed_demo_hotels
    python manage.py seed_demo_hotels --clear
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from branches.models import Branch
from properties.models import FunctionHall, Room, RoomType

# Mirrors vasavi-main-site HOTELS_RAW (mock id → property metadata)
DEMO_HOTELS = [
    {
        "mock_id": "1",
        "name": "Sri Vasavi Nityannadana Residency",
        "city": "Hyderabad",
        "address": "Abids, Hyderabad, Telangana 500001",
        "phone": "9999999001",
        "starting_price_rupees": 2500,
        "donor_room": True,
    },
    {
        "mock_id": "2",
        "name": "Sri Venkateswara Pilgrim Stay",
        "city": "Tirupati",
        "address": "Tirupati, Andhra Pradesh 517501",
        "phone": "9999999002",
        "starting_price_rupees": 1200,
        "donor_room": True,
    },
    {
        "mock_id": "3",
        "name": "Sri Vasavi Kanyaka Grand",
        "city": "Vijayawada",
        "address": "Benz Circle, Vijayawada, Andhra Pradesh 520010",
        "phone": "9999999003",
        "starting_price_rupees": 1800,
        "donor_room": True,
    },
    {
        "mock_id": "4",
        "name": "Vizag Ocean View Vasavi Retreat",
        "city": "Visakhapatnam",
        "address": "RK Beach Road, Visakhapatnam, Andhra Pradesh 530002",
        "phone": "9999999004",
        "starting_price_rupees": 2200,
        "donor_room": False,
    },
    {
        "mock_id": "5",
        "name": "Bengaluru Vasavi Royal Heritage",
        "city": "Bengaluru",
        "address": "Basavanagudi, Bengaluru, Karnataka 560004",
        "phone": "9999999005",
        "starting_price_rupees": 2800,
        "donor_room": True,
    },
]

ROOM_SPECS = [
    ("Standard", 2, 1.0),
    ("Deluxe", 2, 1.5),
    ("Suite", 4, 2.0),
]

# One function hall per demo branch (paise per day ≈ 3× base nightly rate × capacity factor)
HALL_BY_CITY = {
    "Hyderabad": ("Vasavi Grand Banquet Hall", 250, 75_000_00),
    "Tirupati": ("Pilgrim Community Hall", 180, 45_000_00),
    "Vijayawada": ("Kanyaka Convention Hall", 220, 60_000_00),
    "Visakhapatnam": ("Ocean View Function Hall", 200, 55_000_00),
    "Bengaluru": ("Royal Heritage Hall", 280, 85_000_00),
}


class Command(BaseCommand):
    help = "Seed demo branches/rooms for main-site mock hotel catalog"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Deactivate demo branches created by this command (by phone prefix 9999999).",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self._clear()
            return
        self._seed()

    def _clear(self) -> None:
        qs = Branch.objects.filter(phone__startswith="9999999")
        count = qs.count()
        for branch in qs:
            Room.objects.filter(branch=branch).update(is_active=False)
            branch.is_active = False
            branch.soft_delete()
        self.stdout.write(self.style.WARNING(f"Deactivated {count} demo branch(es)."))

    @transaction.atomic
    def _seed(self) -> None:
        for spec in DEMO_HOTELS:
            branch, created = Branch.objects.update_or_create(
                name=spec["name"],
                city=spec["city"],
                defaults={
                    "address": spec["address"],
                    "phone": spec["phone"],
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            if branch.is_deleted:
                branch.is_deleted = False
                branch.is_active = True
                branch.save(update_fields=["is_deleted", "is_active", "updated_at"])

            base_paise = spec["starting_price_rupees"] * 100
            for room_type_name, capacity, multiplier in ROOM_SPECS:
                room_type, _ = RoomType.objects.get_or_create(name=room_type_name)
                room_number = f"{room_type_name[0]}{branch.phone[-2:]}"
                Room.objects.update_or_create(
                    branch=branch,
                    room_number=room_number,
                    defaults={
                        "room_type": room_type,
                        "capacity": capacity,
                        "base_price_per_night": int(base_paise * multiplier),
                        "is_donor_exclusive": spec["donor_room"]
                        and room_type_name == "Suite",
                        "is_active": True,
                        "is_deleted": False,
                    },
                )

            hall_name, hall_capacity, hall_price = HALL_BY_CITY.get(
                spec["city"],
                (f"{spec['name']} Function Hall", 150, 40_000_00),
            )
            existing_hall = FunctionHall.objects.filter(
                branch=branch, is_deleted=False
            ).first()
            if existing_hall:
                existing_hall.name = hall_name
                existing_hall.capacity = hall_capacity
                existing_hall.base_price_per_day = hall_price
                existing_hall.is_active = True
                existing_hall.operational_status = "available"
                existing_hall.amenities = [
                    "AC",
                    "Stage",
                    "Sound system",
                    "Catering kitchen access",
                ]
                existing_hall.save()
                hall_action = "Updated hall"
            else:
                FunctionHall.objects.create(
                    branch=branch,
                    name=hall_name,
                    capacity=hall_capacity,
                    base_price_per_day=hall_price,
                    description="Demo function hall for events and gatherings.",
                    amenities=[
                        "AC",
                        "Stage",
                        "Sound system",
                        "Catering kitchen access",
                    ],
                    is_active=True,
                    operational_status="available",
                )
                hall_action = "Created hall"
            self.stdout.write(self.style.SUCCESS(f"  {hall_action}: {hall_name}"))

            action = "Created" if created else "Updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{action} branch mock_id={spec['mock_id']} -> {branch.id} ({branch.name})"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                "\nDemo catalog ready. Restart main-site search or run:\n"
                "  GET /api/rooms/search?hotel=1&checkIn=YYYY-MM-DD&checkOut=YYYY-MM-DD\n"
            )
        )
