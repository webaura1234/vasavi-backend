"""Property URL routes."""

from django.urls import path

from properties.views import (
    RoomDetailView,
    RoomListCreateView,
    RoomSearchView,
    RoomTypeListCreateView,
)
from properties.function_hall_views import (
    FunctionHallCreateView,
    FunctionHallDeleteView,
    FunctionHallDetailView,
    FunctionHallListView,
    FunctionHallSearchView,
    FunctionHallUpdateView,
)

app_name = "properties"

urlpatterns = [
    path("room-types/", RoomTypeListCreateView.as_view(), name="room-type-list"),
    path("rooms/", RoomListCreateView.as_view(), name="room-list"),
    path("rooms/search/", RoomSearchView.as_view(), name="room-search"),
    path("rooms/<uuid:pk>/", RoomDetailView.as_view(), name="room-detail"),
    path("function-halls/", FunctionHallListView.as_view(), name="function-hall-list"),
    path(
        "function-halls/search/",
        FunctionHallSearchView.as_view(),
        name="function-hall-search",
    ),
    path(
        "function-halls/create/",
        FunctionHallCreateView.as_view(),
        name="function-hall-create",
    ),
    path(
        "function-halls/<uuid:pk>/",
        FunctionHallDetailView.as_view(),
        name="function-hall-detail",
    ),
    path(
        "function-halls/<uuid:pk>/update/",
        FunctionHallUpdateView.as_view(),
        name="function-hall-update",
    ),
    path(
        "function-halls/<uuid:pk>/delete/",
        FunctionHallDeleteView.as_view(),
        name="function-hall-delete",
    ),
]
