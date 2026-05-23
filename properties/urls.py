"""Property URL routes."""

from django.urls import path

from properties.views import (
    RoomDetailView,
    RoomListCreateView,
    RoomSearchView,
    RoomTypeListCreateView,
)

app_name = "properties"

urlpatterns = [
    path("room-types/", RoomTypeListCreateView.as_view(), name="room-type-list"),
    path("rooms/", RoomListCreateView.as_view(), name="room-list"),
    path("rooms/search/", RoomSearchView.as_view(), name="room-search"),
    path("rooms/<uuid:pk>/", RoomDetailView.as_view(), name="room-detail"),
]
