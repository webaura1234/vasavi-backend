"""Notification API routes."""

from django.urls import path

from notifications.views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationRecentView,
    NotificationUnreadCountView,
)

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("recent/", NotificationRecentView.as_view(), name="notification-recent"),
    path("unread-count/", NotificationUnreadCountView.as_view(), name="notification-unread-count"),
    path("mark-all-read/", NotificationMarkAllReadView.as_view(), name="notification-mark-all-read"),
    path("<uuid:pk>/read/", NotificationMarkReadView.as_view(), name="notification-mark-read"),
]
