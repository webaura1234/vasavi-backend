"""Staff portal room inventory management."""

from __future__ import annotations

from accounts.branch_scope import filter_staff_room_queryset, staff_branch_id
from bookings.models import Booking
from permissions import IsAdminOrAbove
from properties.models import Room, RoomImage
from properties.serializers import RoomAvailabilitySerializer, RoomSearchSerializer
from properties.staff_serializers import (
    RoomImageSerializer,
    StaffRoomCreateSerializer,
    StaffRoomSerializer,
    StaffRoomUpdateSerializer,
)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView
from utils.responses import error_response, paginated_response, success_response

MAX_ROOM_IMAGES = 8
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _room_queryset_for_staff(user, branch_id_param: str | None = None):
    qs = (
        Room.objects.filter(is_deleted=False)
        .select_related("branch", "room_type")
        .prefetch_related("images")
    )
    return filter_staff_room_queryset(qs, user, branch_id_param)


def _get_room_for_staff(user, pk):
    try:
        room = _room_queryset_for_staff(user).get(pk=pk)
    except Room.DoesNotExist:
        return None
    return room


class StaffRoomListCreateView(APIView):
    """List and create rooms (branch-scoped for hotel admins)."""

    permission_classes = [IsAdminOrAbove]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        branch_id = request.query_params.get("branch_id")
        qs = _room_queryset_for_staff(request.user, branch_id)
        return paginated_response(
            qs.order_by("room_number"),
            request,
            StaffRoomSerializer,
        )

    def post(self, request):
        serializer = StaffRoomCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        room = serializer.save()
        room = _room_queryset_for_staff(request.user).get(pk=room.pk)
        return success_response(
            StaffRoomSerializer(room, context={"request": request}).data,
            status=201,
        )


class StaffRoomDetailView(APIView):
    """Retrieve or update a single room."""

    permission_classes = [IsAdminOrAbove]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request, pk):
        room = _get_room_for_staff(request.user, pk)
        if not room:
            return error_response("NOT_FOUND", "Room not found.", status=404)
        return success_response(
            StaffRoomSerializer(room, context={"request": request}).data
        )

    def patch(self, request, pk):
        room = _get_room_for_staff(request.user, pk)
        if not room:
            return error_response("NOT_FOUND", "Room not found.", status=404)
        serializer = StaffRoomUpdateSerializer(
            data=request.data,
            context={"room": room, "request": request},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        room = serializer.update(room, serializer.validated_data)
        room = _room_queryset_for_staff(request.user).get(pk=room.pk)
        return success_response(
            StaffRoomSerializer(room, context={"request": request}).data
        )


class StaffRoomOperationalStatusView(APIView):
    """Set staff operational status: available, blocked, or maintenance."""

    permission_classes = [IsAdminOrAbove]
    parser_classes = [JSONParser]

    def patch(self, request, pk):
        room = _get_room_for_staff(request.user, pk)
        if not room:
            return error_response("NOT_FOUND", "Room not found.", status=404)

        from properties.staff_serializers import StaffRoomOperationalStatusSerializer

        serializer = StaffRoomOperationalStatusSerializer(
            data=request.data,
            context={"room": room},
        )
        serializer.is_valid(raise_exception=True)
        room = serializer.save()
        room = _room_queryset_for_staff(request.user).get(pk=room.pk)
        return success_response(
            StaffRoomSerializer(room, context={"request": request}).data
        )


class StaffRoomImageUploadView(APIView):
    """Upload a photo for a room."""

    permission_classes = [IsAdminOrAbove]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        room = _get_room_for_staff(request.user, pk)
        if not room:
            return error_response("NOT_FOUND", "Room not found.", status=404)

        if room.images.count() >= MAX_ROOM_IMAGES:
            return error_response(
                "VALIDATION_ERROR",
                f"Maximum {MAX_ROOM_IMAGES} images per room.",
                status=400,
            )

        upload = request.FILES.get("image")
        if not upload:
            return error_response(
                "VALIDATION_ERROR",
                "Image file is required.",
                status=400,
            )
        if upload.content_type not in ALLOWED_IMAGE_TYPES:
            return error_response(
                "VALIDATION_ERROR",
                "Only JPEG, PNG, or WebP images are allowed.",
                status=400,
            )
        if upload.size > MAX_IMAGE_BYTES:
            return error_response(
                "VALIDATION_ERROR",
                "Image must be 5 MB or smaller.",
                status=400,
            )

        is_primary = request.data.get("is_primary") in (True, "true", "1", 1)
        if is_primary:
            room.images.update(is_primary=False)

        image = RoomImage.objects.create(
            room=room,
            image=upload,
            caption=(request.data.get("caption") or "")[:200],
            is_primary=is_primary or not room.images.exists(),
            sort_order=room.images.count(),
        )
        return success_response(
            RoomImageSerializer(image, context={"request": request}).data,
            status=201,
        )


class StaffRoomImageDeleteView(APIView):
    permission_classes = [IsAdminOrAbove]

    def delete(self, request, pk, image_id):
        room = _get_room_for_staff(request.user, pk)
        if not room:
            return error_response("NOT_FOUND", "Room not found.", status=404)
        try:
            image = room.images.get(pk=image_id)
        except RoomImage.DoesNotExist:
            return error_response("NOT_FOUND", "Image not found.", status=404)
        image.image.delete(save=False)
        image.delete()
        return success_response(message="Image removed.")


class StaffRoomSearchView(APIView):
    """Availability search for staff manual bookings."""

    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        serializer = RoomSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        scoped_branch = staff_branch_id(request.user)
        if scoped_branch:
            if data.get("branch_id") and str(data["branch_id"]) != str(scoped_branch):
                return error_response(
                    "PERMISSION_DENIED",
                    "You can only search rooms at your assigned branch.",
                    status=403,
                )
            data = {**data, "branch_id": scoped_branch}

        qs = Room.objects.filter(
            is_deleted=False,
            is_active=True,
            operational_status="available",
            capacity__gte=data["guests"],
        ).select_related("branch", "room_type")

        if data.get("branch_id"):
            qs = qs.filter(branch_id=data["branch_id"])

        if not data.get("donor_exclusive", False):
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
            unavailable_reason = (
                None if is_available else "Already booked for these dates."
            )
            payload = RoomAvailabilitySerializer(room).data
            payload["is_available"] = is_available
            payload["unavailable_reason"] = unavailable_reason
            results.append(payload)

        return success_response(results)
