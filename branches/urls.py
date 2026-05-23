"""Branch URL routes."""

from django.urls import path

from branches.views import AssignAdminToBranchView, BranchDetailView, BranchListCreateView

app_name = "branches"

urlpatterns = [
    path("", BranchListCreateView.as_view(), name="branch-list"),
    path("<uuid:pk>/", BranchDetailView.as_view(), name="branch-detail"),
    path(
        "<uuid:pk>/assign-admin/",
        AssignAdminToBranchView.as_view(),
        name="branch-assign-admin",
    ),
]
