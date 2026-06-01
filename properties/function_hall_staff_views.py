"""Staff portal function hall management."""

from __future__ import annotations

from django.db.models import Count

from accounts.branch_scope import filter_staff_function_hall_queryset, staff_branch_id
from bookings.services.availability import get_booked_resource_ids
from permissions import IsAdminOrAbove
from properties.function_hall_serializers import FunctionHallSearchSerializer
from properties.function_hall_staff_serializers import (
    FunctionHallImageStaffSerializer,
    StaffFunctionHallCreateSerializer,
    StaffFunctionHallDetailSerializer,
    StaffFunctionHallOperationalStatusSerializer,
    StaffFunctionHallUpdateSerializer,
    resolve_branch_for_hall_staff,
)
from properties.models import FunctionHall, FunctionHallImage
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView
from utils.responses import error_response, paginated_response, success_response

MAX_HALL_IMAGES = 8
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _hall_queryset_for_staff(user, branch_id_param: str | None = None):
    qs = (
        FunctionHall.objects.filter(is_deleted=False)
        .select_related("branch")
        .prefetch_related("images")
        .annotate(booking_count=Count("bookings"))
    )
    return filter_staff_function_hall_queryset(qs, user, branch_id_param)


def _get_hall_for_staff(user, pk, branch_id_param: str | None = None):
    try:
        return _hall_queryset_for_staff(user, branch_id_param).get(pk=pk)
    except FunctionHall.DoesNotExist:
        return None


class StaffFunctionHallListCreateView(APIView):
    permission_classes = [IsAdminOrAbove]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        branch_id = request.query_params.get("branch_id")
        qs = _hall_queryset_for_staff(request.user, branch_id)
        return paginated_response(
            qs.order_by("-created_at"),
            request,
            StaffFunctionHallDetailSerializer,
        )

    def post(self, request):
        branch_id = request.data.get("branch_id") or request.query_params.get("branch_id")
        branch = resolve_branch_for_hall_staff(request.user, branch_id)
        if branch is None:
            if request.user.role == "admin":
                return error_response(
                    "VALIDATION_ERROR",
                    "Your account is not assigned to a branch.",
                    status=400,
                )
            return error_response(
                "VALIDATION_ERROR",
                "branch_id is required for super admins.",
                status=400,
            )
        if request.user.role == "admin" and str(branch.id) != str(staff_branch_id(request.user)):
            return error_response(
                "PERMISSION_DENIED",
                "You can only create a hall at your assigned branch.",
                status=403,
            )

        serializer = StaffFunctionHallCreateSerializer(
            data=request.data,
            context={"branch": branch, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        hall = serializer.save()
        hall = _hall_queryset_for_staff(request.user).get(pk=hall.pk)
        return success_response(
            StaffFunctionHallDetailSerializer(hall, context={"request": request}).data,
            status=201,
        )


class StaffFunctionHallDetailUpdateView(APIView):
    permission_classes = [IsAdminOrAbove]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request, pk):
        hall = _get_hall_for_staff(request.user, pk)
        if not hall:
            return error_response("NOT_FOUND", "Function hall not found.", status=404)
        return success_response(
            StaffFunctionHallDetailSerializer(hall, context={"request": request}).data
        )

    def patch(self, request, pk):
        hall = _get_hall_for_staff(request.user, pk)
        if not hall:
            return error_response("NOT_FOUND", "Function hall not found.", status=404)
        serializer = StaffFunctionHallUpdateSerializer(
            data=request.data,
            context={"hall": hall, "request": request},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        hall = serializer.update(hall, serializer.validated_data)
        hall = _hall_queryset_for_staff(request.user).get(pk=hall.pk)
        return success_response(
            StaffFunctionHallDetailSerializer(hall, context={"request": request}).data
        )


class StaffFunctionHallOperationalStatusView(APIView):
    permission_classes = [IsAdminOrAbove]
    parser_classes = [JSONParser]

    def patch(self, request, pk):
        hall = _get_hall_for_staff(request.user, pk)
        if not hall:
            return error_response("NOT_FOUND", "Function hall not found.", status=404)
        serializer = StaffFunctionHallOperationalStatusSerializer(
            data=request.data,
            context={"hall": hall},
        )
        serializer.is_valid(raise_exception=True)
        hall = serializer.save()
        hall = _hall_queryset_for_staff(request.user).get(pk=hall.pk)
        return success_response(
            StaffFunctionHallDetailSerializer(hall, context={"request": request}).data
        )


class StaffFunctionHallImageUploadView(APIView):
    permission_classes = [IsAdminOrAbove]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        hall = _get_hall_for_staff(request.user, pk)
        if not hall:
            return error_response("NOT_FOUND", "Function hall not found.", status=404)

        if hall.images.count() >= MAX_HALL_IMAGES:
            return error_response(
                "VALIDATION_ERROR",
                f"Maximum {MAX_HALL_IMAGES} images per function hall.",
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
            hall.images.update(is_primary=False)

        image = FunctionHallImage.objects.create(
            function_hall=hall,
            image=upload,
            caption=(request.data.get("caption") or "")[:200],
            is_primary=is_primary or not hall.images.exists(),
            sort_order=hall.images.count(),
        )
        return success_response(
            FunctionHallImageStaffSerializer(image, context={"request": request}).data,
            status=201,
        )


class StaffFunctionHallImageDeleteView(APIView):
    permission_classes = [IsAdminOrAbove]

    def delete(self, request, pk, image_pk):
        hall = _get_hall_for_staff(request.user, pk)
        if not hall:
            return error_response("NOT_FOUND", "Function hall not found.", status=404)
        try:
            image = hall.images.get(pk=image_pk)
        except FunctionHallImage.DoesNotExist:
            return error_response("NOT_FOUND", "Image not found.", status=404)
        image.image.delete(save=False)
        image.delete()
        return success_response(message="Image removed.")


class StaffFunctionHallSearchView(APIView):
    permission_classes = [IsAdminOrAbove]

    def get(self, request):
        serializer = FunctionHallSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        scoped_branch = staff_branch_id(request.user)
        if scoped_branch:
            if str(data["branch_id"]) != str(scoped_branch):
                return error_response(
                    "PERMISSION_DENIED",
                    "You can only search halls at your assigned branch.",
                    status=403,
                )

        from branches.models import Branch

        try:
            branch = Branch.objects.get(pk=data["branch_id"], is_deleted=False)
        except Branch.DoesNotExist:
            return error_response("NOT_FOUND", "Branch not found.", status=404)

        qs = (
            FunctionHall.objects.filter(
                is_deleted=False,
                is_active=True,
                branch=branch,
                operational_status="available",
                capacity__gte=data.get("guests", 1),
            )
            .select_related("branch")
            .prefetch_related("images")
        )

        booked_hall_ids = get_booked_resource_ids(
            FunctionHall,
            branch,
            data["check_in_date"],
            data["check_out_date"],
        )

        from properties.function_hall_serializers import FunctionHallAvailabilitySerializer

        results = []
        for hall in qs:
            payload = FunctionHallAvailabilitySerializer(hall).data
            is_available = hall.pk not in booked_hall_ids
            payload["is_available"] = is_available
            payload["unavailable_reason"] = (
                None if is_available else "Already booked for these dates."
            )
            results.append(payload)

        return success_response(results)
