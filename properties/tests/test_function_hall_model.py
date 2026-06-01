"""FunctionHall model tests."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from branches.models import Branch
from properties.models import FunctionHall


class FunctionHallModelTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Test Branch",
            city="City",
            address="Addr",
        )
        self.other_branch = Branch.objects.create(
            name="Other Branch",
            city="City",
            address="Addr 2",
        )

    def test_create_hall_success(self):
        hall = FunctionHall.objects.create(
            branch=self.branch,
            name="Grand Hall",
            capacity=200,
            base_price_per_day=50_000_00,
        )
        self.assertEqual(str(hall), "Grand Hall — Test Branch")
        self.assertTrue(hall.is_available_for_booking)

    def test_second_hall_same_branch_raises(self):
        FunctionHall.objects.create(
            branch=self.branch,
            name="Hall One",
            capacity=100,
            base_price_per_day=10_000_00,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FunctionHall.objects.create(
                    branch=self.branch,
                    name="Hall Two",
                    capacity=50,
                    base_price_per_day=5_000_00,
                )

    def test_second_hall_after_soft_delete_succeeds(self):
        hall = FunctionHall.objects.create(
            branch=self.branch,
            name="Hall One",
            capacity=100,
            base_price_per_day=10_000_00,
        )
        hall.soft_delete()
        hall2 = FunctionHall.objects.create(
            branch=self.branch,
            name="Hall Two",
            capacity=80,
            base_price_per_day=8_000_00,
        )
        self.assertEqual(hall2.name, "Hall Two")

    def test_capacity_validator_min(self):
        hall = FunctionHall(
            branch=self.other_branch,
            name="Small",
            capacity=0,
            base_price_per_day=100,
        )
        with self.assertRaises(ValidationError):
            hall.full_clean()

    def test_str_representation(self):
        hall = FunctionHall.objects.create(
            branch=self.branch,
            name="Banquet",
            capacity=50,
            base_price_per_day=1_000_00,
        )
        self.assertEqual(str(hall), "Banquet — Test Branch")
