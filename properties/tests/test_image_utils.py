"""Property image URL helpers."""

from django.test import SimpleTestCase, override_settings

from properties.image_utils import (
    normalize_property_image_path,
    supabase_public_url,
)


@override_settings(
    SUPABASE_URL="https://example.supabase.co",
    SUPABASE_STORAGE_BUCKET="images",
    MEDIA_ROOMS_DIR="rooms",
    MEDIA_FUNCTION_HALLS_DIR="function_halls",
)
class ImageUtilsTests(SimpleTestCase):
    def test_normalize_legacy_room_path(self):
        legacy = "properties.media_paths.room_image_upload_to/photo.png"
        self.assertEqual(normalize_property_image_path(legacy), "rooms/photo.png")

    def test_supabase_public_url_from_normalized_legacy(self):
        legacy = "properties.media_paths.room_image_upload_to/photo.png"
        url = supabase_public_url(legacy)
        self.assertEqual(
            url,
            "https://example.supabase.co/storage/v1/object/public/images/rooms/photo.png",
        )

    def test_supabase_public_url_for_hall(self):
        url = supabase_public_url("function_halls/abc.jpg")
        self.assertIn("/images/function_halls/abc.jpg", url or "")
