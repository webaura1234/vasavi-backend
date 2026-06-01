"""Property / room API views."""

from __future__ import annotations

from django.db.models import Q
from rest_framework import generics
from rest_framework.views import APIView

from bookings.models import Booking
from properties.models import Room, RoomType
from properties.serializers import (
    RoomAvailabilitySerializer,
    RoomSearchSerializer,
    RoomSerializer,
    RoomTypeSerializer,
    RoomWriteSerializer,
)
from permissions import IsPublic, IsSuperAdmin
from utils.responses import error_response, paginated_response, success_response


class RoomTypeListCreateView(generics.ListCreateAPIView):
    lookup_field = "pk"
    queryset = RoomType.objects.all().order_by("name")

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsSuperAdmin()]
        return [IsPublic()]

    def get_serializer_class(self):
        return RoomTypeSerializer

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, RoomTypeSerializer)

    def create(self, request, *args, **kwargs):
        serializer = RoomTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room_type = serializer.save()
        return success_response(RoomTypeSerializer(room_type).data, status=201)


class RoomListCreateView(generics.ListCreateAPIView):
    lookup_field = "pk"

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsSuperAdmin()]
        return [IsPublic()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return RoomWriteSerializer
        return RoomSerializer

    def get_queryset(self):
        qs = (
            Room.objects.filter(is_deleted=False, is_active=True)
            .select_related("branch", "room_type")
            .prefetch_related("images")
        )
        branch_id = self.request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs.order_by("branch__name", "room_number")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, RoomSerializer)

    def create(self, request, *args, **kwargs):
        serializer = RoomWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = serializer.save()
        room = (
            Room.objects.select_related("branch", "room_type")
            .prefetch_related("images")
            .get(pk=room.pk)
        )
        return success_response(
            RoomSerializer(room, context={"request": request}).data, status=201
        )


class RoomDetailView(generics.RetrieveUpdateDestroyAPIView):
    lookup_field = "pk"
    queryset = (
        Room.objects.filter(is_deleted=False)
        .select_related("branch", "room_type")
        .prefetch_related("images")
    )

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsPublic()]
        return [IsSuperAdmin()]

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return RoomWriteSerializer
        return RoomSerializer

    def retrieve(self, request, *args, **kwargs):
        return success_response(
            RoomSerializer(self.get_object(), context={"request": request}).data
        )

    def partial_update(self, request, *args, **kwargs):
        room = self.get_object()
        serializer = RoomWriteSerializer(room, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        room.refresh_from_db()
        return success_response(
            RoomSerializer(room, context={"request": request}).data
        )

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        room = self.get_object()
        room.is_active = False
        room.soft_delete()
        return success_response(message="Room deactivated.")


class RoomSearchView(APIView):
    permission_classes = [IsPublic]

    def get(self, request):
        serializer = RoomSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        qs = Room.objects.filter(
            is_deleted=False,
            is_active=True,
            operational_status="available",
            capacity__gte=data["guests"],
        ).select_related("branch", "room_type").prefetch_related("images")

        if data.get("branch_id"):
            qs = qs.filter(branch_id=data["branch_id"])

        user = request.user
        show_donor_exclusive = data.get("donor_exclusive", False)
        if not show_donor_exclusive:
            if user.is_authenticated and getattr(user, "role", None) == "donor":
                pass
            else:
                qs = qs.filter(is_donor_exclusive=False)
        elif not (user.is_authenticated and user.role == "donor"):
            qs = qs.filter(is_donor_exclusive=False)

        booked_room_ids = set(
            Booking.objects.filter(
                status__in=[
                    Booking.Status.PENDING,
                    Booking.Status.CONFIRMED,
                    Booking.Status.CHECKED_IN,
                ],
                check_in_date__lt=data["check_out"],
                check_out_date__gt=data["check_in"],
                is_deleted=False,
            ).values_list("room_id", flat=True)
        )

        results = []
        for room in qs:
            is_available = room.pk not in booked_room_ids
            unavailable_reason = None if is_available else "Already booked for these dates."
            serializer = RoomAvailabilitySerializer(
                room, context={"request": request}
            )
            payload = serializer.data
            payload["is_available"] = is_available
            payload["unavailable_reason"] = unavailable_reason
            results.append(payload)

        return success_response(results)
