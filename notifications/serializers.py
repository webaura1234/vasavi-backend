"""Serializers for in-app notifications."""

from __future__ import annotations

from rest_framework import serializers

from notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "id",
            "category",
            "type",
            "title",
            "message",
            "metadata",
            "related_entity_type",
            "related_entity_id",
            "read_at",
            "is_read",
            "created_at",
        )
        read_only_fields = fields

    def get_is_read(self, obj: Notification) -> bool:
        return obj.is_read
