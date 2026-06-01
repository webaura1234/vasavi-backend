"""Public function hall API views."""

from __future__ import annotations

from django.db.models import Q

from permissions import IsPublic, IsSuperAdmin
from properties.function_hall_serializers import (
    FunctionHallAvailabilitySerializer,
    FunctionHallSearchSerializer,
    FunctionHallSerializer,
    FunctionHallWriteSerializer,
)
from properties.models import FunctionHall
from rest_framework import generics
from rest_framework.views import APIView
from utils.responses import error_response, paginated_response, success_response


def _active_hall_queryset():
    return (
        FunctionHall.objects.filter(is_deleted=False, is_active=True)
        .select_related("branch")
        .prefetch_related("images")
    )


class FunctionHallListView(generics.ListAPIView):
    permission_classes = [IsPublic]
    serializer_class = FunctionHallSerializer

    def get_queryset(self):
        qs = _active_hall_queryset()
        branch_id = self.request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, FunctionHallSerializer)


class FunctionHallDetailView(generics.RetrieveAPIView):
    permission_classes = [IsPublic]
    lookup_field = "pk"
    serializer_class = FunctionHallSerializer

    def get_queryset(self):
        return (
            FunctionHall.objects.filter(is_deleted=False, is_active=True)
            .select_related("branch")
            .prefetch_related("images")
        )

    def retrieve(self, request, *args, **kwargs):
        return success_response(FunctionHallSerializer(self.get_object()).data)


class FunctionHallCreateView(generics.CreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = FunctionHallWriteSerializer

    def create(self, request, *args, **kwargs):
        serializer = FunctionHallWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hall = serializer.save()
        hall = (
            FunctionHall.objects.filter(pk=hall.pk)
            .select_related("branch")
            .prefetch_related("images")
            .get()
        )
        return success_response(FunctionHallSerializer(hall).data, status=201)


class FunctionHallUpdateView(generics.UpdateAPIView):
    permission_classes = [IsSuperAdmin]
    lookup_field = "pk"
    serializer_class = FunctionHallWriteSerializer
    http_method_names = ["patch", "options", "head"]

    def get_queryset(self):
        return FunctionHall.objects.filter(is_deleted=False).select_related("branch")

    def partial_update(self, request, *args, **kwargs):
        hall = self.get_object()
        serializer = FunctionHallWriteSerializer(hall, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        hall = serializer.save()
        hall = (
            FunctionHall.objects.filter(pk=hall.pk)
            .select_related("branch")
            .prefetch_related("images")
            .get()
        )
        return success_response(FunctionHallSerializer(hall).data)


class FunctionHallDeleteView(generics.DestroyAPIView):
    permission_classes = [IsSuperAdmin]
    lookup_field = "pk"

    def get_queryset(self):
        return FunctionHall.objects.filter(is_deleted=False)

    def destroy(self, request, *args, **kwargs):
        hall = self.get_object()
        hall.is_active = False
        hall.soft_delete()
        return success_response(message="Function hall deactivated.")


class FunctionHallSearchView(APIView):
    permission_classes = [IsPublic]

    def get(self, request):
        serializer = FunctionHallSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from bookings.services.availability import get_booked_resource_ids
        from branches.models import Branch

        try:
            branch = Branch.objects.get(pk=data["branch_id"], is_deleted=False)
        except Branch.DoesNotExist:
            return error_response("NOT_FOUND", "Branch not found.", status=404)

        qs = _active_hall_queryset().filter(
            branch=branch,
            operational_status="available",
            capacity__gte=data.get("guests", 1),
        )

        booked_hall_ids = get_booked_resource_ids(
            FunctionHall,
            branch,
            data["check_in_date"],
            data["check_out_date"],
        )

        results = []
        for hall in qs:
            payload = FunctionHallAvailabilitySerializer(hall).data
            payload["is_available"] = hall.pk not in booked_hall_ids
            results.append(payload)

        return success_response(results)
