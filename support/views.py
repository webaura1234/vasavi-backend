"""Public support-related endpoints."""

from __future__ import annotations

from rest_framework.views import APIView

from permissions import IsPublic
from support.serializers import ContactInquirySerializer
from utils.responses import success_response


class ContactInquiryCreateView(APIView):
    """Accept contact form submissions from the public website."""

    permission_classes = [IsPublic]

    def post(self, request):
        serializer = ContactInquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry = serializer.save()
        return success_response(
            {
                "id": str(inquiry.pk),
                "message": "Thank you. We will respond to your message shortly.",
            },
            status=201,
        )
