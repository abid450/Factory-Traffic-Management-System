from django.urls import path
from . import views

app_name = 'traffic_control'

urlpatterns = [
    # Sensor Event Ingestion
    path('events/', views.SensorEventView.as_view(), name='sensor_event'),

    # Live Junction State
    path('junctions/<str:junction_id>/state/', views.JunctionStateView.as_view(), name='junction_state'),

    # Manual Control Commands
    path('junctions/<str:junction_id>/commands/', views.ManualCommandView.as_view(), name='junction_command'),

    path('junctions/<str:junction_id>/analytics/', views.TrafficAnalyticsView.as_view(), name='junction_analytics'),

    # Celery diagnostics (open in browser)
    path('health/celery/', views.CeleryHealthView.as_view(), name='celery_health'),
]