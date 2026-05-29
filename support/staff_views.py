"""Staff portal support ticket API."""

from __future__ import annotations

from rest_framework.views import APIView

from accounts.branch_scope import require_staff_branch_id, staff_branch_id
from permissions import IsAdminOrAbove
from support.models import SupportTicket
from support.serializers import (
    SupportTicketCreateSerializer,
    SupportTicketSerializer,
    SupportTicketStatusSerializer,
)
from utils.responses import error_response, success_response


def _ticket_queryset_for_user(user):
    qs = SupportTicket.objects.filter(is_deleted=False).select_related(
        "branch", "created_by"
    )
    if user.role == "admin":
        branch_id = require_staff_branch_id(user)
        if not branch_id:
            return qs.none()
        return qs.filter(branch_id=branch_id)
    return qs


class StaffSupportTicketListCreateView(APIView):
    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        tickets = _ticket_queryset_for_user(request.user).order_by("-created_at")[:200]
        data = [SupportTicketSerializer(t).data for t in tickets]
        return success_response(data)

    def post(self, request):
        body = SupportTicketCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        branch = body.validated_data.get("hotel_id")
        user = request.user

        if user.role == "admin":
            assigned = staff_branch_id(user)
            if branch and str(branch.pk) != str(assigned):
                return error_response(
                    "FORBIDDEN",
                    "You can only create tickets for your assigned branch.",
                    status=403,
                )
            if not branch:
                from branches.models import Branch

                branch = Branch.objects.filter(pk=assigned, is_deleted=False).first()

        ticket = SupportTicket.objects.create(
            branch=branch,
            created_by=user,
            subject=body.validated_data["subject"],
            description=body.validated_data.get("description", ""),
            guest_name=body.validated_data.get("guest_name", ""),
            category=body.validated_data.get("category", ""),
            booking_reference=body.validated_data.get("booking_reference", ""),
            priority=body.validated_data["priority"],
        )
        return success_response(SupportTicketSerializer(ticket).data, status=201)


class StaffSupportTicketStatusView(APIView):
    permission_classes = [IsAdminOrAbove]

    def patch(self, request, pk):
        try:
            ticket = _ticket_queryset_for_user(request.user).get(pk=pk)
        except SupportTicket.DoesNotExist:
            return error_response("NOT_FOUND", "Ticket not found.", status=404)

        body = SupportTicketStatusSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        ticket.status = body.validated_data["status"]
        ticket.save(update_fields=["status", "updated_at"])
        return success_response(SupportTicketSerializer(ticket).data)
