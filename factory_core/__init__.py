# Load the Celery app when Django starts, so that @shared_task
# (and .delay / .apply_async) in the web process use OUR app
# (RabbitMQ broker) instead of the default localhost broker.
from .celery import app as celery_app

__all__ = ("celery_app",)