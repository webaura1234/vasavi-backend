"""Donor API views."""

from __future__ import annotations

from django.db.models import Q, Sum
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from donors.models import Donation, DonationPurpose, DonorProfile, MembershipTier
from donors.serializers import (
    DonationCreateSerializer,
    DonationSerializer,
    DonationPurposeSerializer,
    DonorCreateSerializer,
    DonorListSerializer,
    DonorProfileSerializer,
    DonorUpdateSerializer,
    MembershipTierSerializer,
    PublicDonorSerializer,
)
from permissions import IsAdminOrAbove, IsDonorOrAbove, IsSuperAdmin
from utils.responses import error_response, paginated_response, success_response


class DonorMeView(APIView):
    permission_classes = [IsDonorOrAbove]

    def get(self, request):
        user = request.user
        if user.role != "donor":
            return error_response(
                "PERMISSION_DENIED",
                "Only donors may access this endpoint.",
                status=403,
            )
        try:
            profile = DonorProfile.objects.select_related(
                "user", "membership_tier", "for_place"
            ).get(user=user)
        except DonorProfile.DoesNotExist:
            return error_response("NOT_FOUND", "Donor profile not found.", status=404)
        return success_response(DonorProfileSerializer(profile).data)


class DonorListCreateView(generics.ListCreateAPIView):
    lookup_field = "pk"

    def get_permissions(self):
        return [IsSuperAdmin()]

    def get_queryset(self):
        qs = (
            DonorProfile.objects.filter(is_deleted=False)
            .select_related("user", "membership_tier", "for_place")
            .annotate(total_donated_paise=Sum("donations__amount"))
        )
        tier_id = self.request.query_params.get("tier_id")
        club_name = self.request.query_params.get("club_name")
        for_place_id = self.request.query_params.get("for_place_id")
        search = self.request.query_params.get("search")

        if tier_id:
            qs = qs.filter(membership_tier_id=tier_id)
        if club_name:
            qs = qs.filter(club_name__icontains=club_name)
        if for_place_id:
            qs = qs.filter(for_place_id=for_place_id)
        if search:
            qs = qs.filter(
                Q(user__name__icontains=search)
                | Q(user__phone__icontains=search)
                | Q(donor_id__icontains=search)
            )
        return qs.order_by("-user__date_joined")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, DonorListSerializer)

    def create(self, request, *args, **kwargs):
        serializer = DonorCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        profile = DonorProfile.objects.select_related(
            "user", "membership_tier", "for_place"
        ).get(pk=profile.pk)
        return success_response(
            DonorProfileSerializer(profile).data,
            status=201,
            message="Donor created.",
        )


class DonorDetailView(generics.RetrieveUpdateAPIView):
    lookup_field = "pk"
    permission_classes = [IsSuperAdmin]
    queryset = DonorProfile.objects.filter(is_deleted=False).select_related(
        "user", "membership_tier", "for_place"
    )

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return DonorUpdateSerializer
        return DonorProfileSerializer

    def retrieve(self, request, *args, **kwargs):
        return success_response(DonorProfileSerializer(self.get_object()).data)

    def partial_update(self, request, *args, **kwargs):
        profile = self.get_object()
        serializer = DonorUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        profile.refresh_from_db()
        return success_response(DonorProfileSerializer(profile).data)

    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)


class DonationListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        qs = Donation.objects.select_related(
            "donor__user",
            "purpose",
            "created_by",
        ).prefetch_related("receipt_numbers")
        donor_id = self.request.query_params.get("donor_id")
        if donor_id:
            qs = qs.filter(donor_id=donor_id)
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, DonationSerializer)

    def create(self, request, *args, **kwargs):
        serializer = DonationCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        donation = serializer.save()
        donation = self.get_queryset().get(pk=donation.pk)

        try:
            from notifications.services import notify_donation_received

            notify_donation_received(donation)
        except Exception:
            import logging

            logging.getLogger("vasavi.donors").exception(
                "Could not create donation notification for donation %s", donation.pk
            )

        return success_response(DonationSerializer(donation).data, status=201)


class MembershipTierListCreateView(generics.ListCreateAPIView):
    lookup_field = "pk"
    queryset = MembershipTier.objects.filter(is_active=True).order_by("name")
    serializer_class = MembershipTierSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsSuperAdmin()]
        return [IsAdminOrAbove()]

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, MembershipTierSerializer)

    def create(self, request, *args, **kwargs):
        serializer = MembershipTierSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tier = serializer.save()
        return success_response(MembershipTierSerializer(tier).data, status=201)


class DonationPurposeListCreateView(generics.ListCreateAPIView):
    lookup_field = "pk"
    queryset = DonationPurpose.objects.filter(is_active=True).order_by("name")
    serializer_class = DonationPurposeSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsSuperAdmin()]
        return [IsAdminOrAbove()]

    def list(self, request, *args, **kwargs):
        return paginated_response(self.get_queryset(), request, DonationPurposeSerializer)

    def create(self, request, *args, **kwargs):
        serializer = DonationPurposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purpose = serializer.save()
        return success_response(DonationPurposeSerializer(purpose).data, status=201)


from django.http import HttpResponse

class ExportDonorsExcelView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        import openpyxl
        from django.utils import timezone

        # Create workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Donors"

        # Headers
        headers = ["Donor ID", "Name", "Phone", "Email", "Club Name", "Tier", "Total Donated"]
        ws.append(headers)

        qs = DonorProfile.objects.filter(is_deleted=False).select_related(
            "user", "membership_tier"
        ).annotate(total_donated_paise=Sum("donations__amount")).order_by("-user__date_joined")

        for profile in qs:
            total_donated = (profile.total_donated_paise or 0) / 100.0
            ws.append([
                profile.donor_id or "",
                profile.user.name,
                profile.user.phone,
                profile.user.email or "",
                profile.club_name or "",
                profile.membership_tier.name if profile.membership_tier else "",
                total_donated,
            ])

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="donors_export_{timezone.now().strftime("%Y%m%d%H%M")}.xlsx"'
        wb.save(response)
        return response


class PublicDonorListView(generics.ListAPIView):
    """Public endpoint to list donors for the website."""
    permission_classes = [AllowAny]
    serializer_class = PublicDonorSerializer

    def get_queryset(self):
        qs = DonorProfile.objects.filter(is_deleted=False).select_related(
            "user", "membership_tier", "for_place"
        )
        tier_id = self.request.query_params.get("tier_id")
        club_name = self.request.query_params.get("club_name")
        search = self.request.query_params.get("search")

        if tier_id:
            qs = qs.filter(membership_tier_id=tier_id)
        if club_name:
            qs = qs.filter(club_name__icontains=club_name)
        if search:
            qs = qs.filter(
                Q(user__name__icontains=search)
                | Q(donor_id__icontains=search)
            )
        return qs.order_by("-user__date_joined")

    def list(self, request, *args, **kwargs):
        # We can reuse the standard paginated_response
        return paginated_response(self.get_queryset(), request, self.get_serializer_class())


