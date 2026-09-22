"""Notifications — public facade.

Owns message content and templates (ARCHITECTURE.md §4). No other module imports it
today; the service is exported for the composition root and its own Kafka consumer.
"""
from app.modules.notifications.application.services import NotificationService

__all__ = ["NotificationService"]
