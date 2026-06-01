"""Room and function hall multi-image API."""

import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image as PilImage
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AdminBranch, User
from branches.models import Branch
from properties.models import FunctionHall, Room, RoomImage, RoomType


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    PilImage.new("RGB", (4, 4), color="red").save(buf, format="JPEG")
    return buf.getvalue()


def _upload_file(name: str = "photo.jpg") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _jpeg_bytes(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="vasavi_room_media_"))
class RoomImageApiTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Image Branch",
            city="City",
            address="Addr",
            phone="9000000001",
        )
        self.room_type = RoomType.objects.create(name="Standard")
        self.room = Room.objects.create(
            branch=self.branch,
            room_type=self.room_type,
            room_number="101",
            capacity=2,
            base_price_per_night=250_000,
        )
        self.admin = User.objects.create_user(
            phone="9111111111",
            name="Admin",
            role="admin",
        )
        AdminBranch.objects.create(
            user=self.admin,
            branch=self.branch,
            assigned_by=self.admin,
        )
        self.client = APIClient()
        token = RefreshToken.for_user(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_staff_can_upload_multiple_room_images(self):
        for i in range(3):
            response = self.client.post(
                f"/api/v1/staff/rooms/{self.room.pk}/images/",
                {"image": _upload_file(f"r{i}.jpg"), "is_primary": i == 0},
                format="multipart",
            )
            self.assertEqual(response.status_code, 201, response.content)

        self.assertEqual(self.room.images.count(), 3)
        list_resp = self.client.get(
            f"/api/v1/properties/rooms/?branch_id={self.branch.pk}"
        )
        self.assertEqual(list_resp.status_code, 200)
        results = list_resp.json()["data"]["results"]
        room_row = next(r for r in results if r["id"] == str(self.room.pk))
        self.assertEqual(len(room_row["images"]), 3)
        urls = [img["url"] for img in room_row["images"]]
        self.assertTrue(
            all(
                u
                and (
                    u.startswith("http://")
                    or u.startswith("https://")
                    or "/media/" in u
                )
                for u in urls
            )
        )

    def test_staff_can_register_room_image_by_storage_path(self):
        path = "rooms/test-register.jpg"
        response = self.client.post(
            f"/api/v1/staff/rooms/{self.room.pk}/images/",
            {"storage_path": path, "is_primary": True},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        image = self.room.images.get()
        self.assertEqual(image.image.name, path)

    def test_staff_can_delete_room_image(self):
        image = RoomImage.objects.create(
            room=self.room,
            image=_upload_file(),
            is_primary=True,
        )
        response = self.client.delete(
            f"/api/v1/staff/rooms/{self.room.pk}/images/{image.pk}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RoomImage.objects.filter(pk=image.pk).exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="vasavi_hall_media_"))
class FunctionHallImageApiTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name="Hall Branch",
            city="City",
            address="Addr",
            phone="9000000002",
        )
        self.hall = FunctionHall.objects.create(
            branch=self.branch,
            name="Grand Hall",
            capacity=100,
            base_price_per_day=500_000,
        )
        self.admin = User.objects.create_user(
            phone="9222222222",
            name="Admin",
            role="admin",
        )
        AdminBranch.objects.create(
            user=self.admin,
            branch=self.branch,
            assigned_by=self.admin,
        )
        self.client = APIClient()
        token = RefreshToken.for_user(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_staff_can_upload_hall_images(self):
        response = self.client.post(
            f"/api/v1/staff/function-halls/{self.hall.pk}/images/",
            {"image": _upload_file()},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        public = self.client.get(
            f"/api/v1/properties/function-halls/?branch_id={self.branch.pk}"
        )
        self.assertEqual(public.status_code, 200)
        results = public.json()["data"]["results"]
        hall_row = results[0]
        self.assertEqual(len(hall_row["images"]), 1)
