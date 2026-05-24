"""API exception envelope tests."""

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from utils.exceptions import _validation_message, custom_exception_handler


class ValidationErrorEnvelopeTests(TestCase):
    def test_field_errors_surface_in_message(self):
        exc = ValidationError({"status": ["Cannot check in before the scheduled date (2026-05-25)."]})
        response = custom_exception_handler(exc, {})
        self.assertIsNotNone(response)
        body = response.data
        self.assertEqual(
            body["error"]["message"],
            "Cannot check in before the scheduled date (2026-05-25).",
        )
        self.assertEqual(
            body["error"]["fields"]["status"],
            ["Cannot check in before the scheduled date (2026-05-25)."],
        )

    def test_multiple_messages_joined(self):
        joined = _validation_message(
            {
                "status": ["First issue."],
                "reason": ["Second issue."],
            }
        )
        self.assertEqual(joined, "First issue.; Second issue.")
