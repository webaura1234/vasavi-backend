"""Donor URL routes."""

from django.urls import path

from donors.views import (
    DonationListCreateView,
    DonationPurposeListCreateView,
    DonorDetailView,
    DonorListCreateView,
    DonorMeView,
    MembershipTierListCreateView,
    ExportDonorsExcelView,
)

app_name = "donors"

urlpatterns = [
    path("me/", DonorMeView.as_view(), name="donor-me"),
    path("export/", ExportDonorsExcelView.as_view(), name="donor-export"),
    path("", DonorListCreateView.as_view(), name="donor-list"),
    path("<uuid:pk>/", DonorDetailView.as_view(), name="donor-detail"),
    path("donations/", DonationListCreateView.as_view(), name="donation-list"),
    path("tiers/", MembershipTierListCreateView.as_view(), name="tier-list"),
    path("purposes/", DonationPurposeListCreateView.as_view(), name="purpose-list"),
]
