"""In-app notification API for authenticated users."""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.serializers import NotificationSerializer
from utils.responses import error_response, paginated_response, success_response


def _user_notifications(user):
    return Notification.objects.filter(recipient=user)


def _apply_filters(qs, request):
    status = request.query_params.get("status", "all")
    if status == "read":
        qs = qs.filter(read_at__isnull=False)
    elif status == "unread":
        qs = qs.filter(read_at__isnull=True)

    category = request.query_params.get("category", "").strip()
    if category:
        categories = [c.strip() for c in category.split(",") if c.strip()]
        if categories:
            qs = qs.filter(category__in=categories)

    search = request.query_params.get("search", "").strip()
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(message__icontains=search))

    return qs.order_by("-created_at")


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _apply_filters(_user_notifications(request.user), request)
        return paginated_response(qs, request, NotificationSerializer)


class NotificationRecentView(APIView):
    """Latest notifications for the header dropdown (unread first, then newest)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 5)), 20)
        qs = (
            _user_notifications(request.user)
            .order_by("read_at", "-created_at")[:limit]
        )
        serializer = NotificationSerializer(qs, many=True)
        return success_response(serializer.data)


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = _user_notifications(request.user).filter(read_at__isnull=True).count()
        return success_response({"count": count})


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            notification = _user_notifications(request.user).get(pk=pk)
        except Notification.DoesNotExist:
            return error_response("NOT_FOUND", "Notification not found.", status=404)

        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at", "updated_at"])

        return success_response(NotificationSerializer(notification).data)


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = (
            _user_notifications(request.user)
            .filter(read_at__isnull=True)
            .update(read_at=timezone.now())
        )
        return success_response({"updated": updated})
