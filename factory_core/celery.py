# cooking/celery.py

import os
from celery import Celery
from celery.schedules import crontab
from kombu import Queue, Exchange


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'factory_core.settings')

app = Celery('factory_core')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    """Debug task to test Celery"""
    print(f'✅ Debug task executed! ID: {self.request.id}')
    return {'status': 'success', 'message': 'Celery is working with RabbitMQ!'}


# ============================================================
# TASK ROUTES (Explicitly defined per task)
# ============================================================
app.conf.task_routes = {
    # Route each specific task to the traffic_queue
    'traffic_control.tasks.start_green': {'queue': 'traffic_queue'},
    'traffic_control.tasks.transition_to_yellow': {'queue': 'traffic_queue'},
    'traffic_control.tasks.transition_to_all_red': {'queue': 'traffic_queue'},
    'traffic_control.tasks.decide_next_phase': {'queue': 'traffic_queue'},
    'traffic_control.tasks.emergency_timeout_check': {'queue': 'traffic_queue'},
}


# ============================================================
# TASK QUEUES (Kombu Definition)
# ============================================================
app.conf.task_queues = (
    Queue('default', Exchange('default'), routing_key='default'),
    Queue('traffic_queue', Exchange('traffic_queue', type='direct'), routing_key='traffic_queue'),
)


# ============================================================
#  CELERY BEAT SCHEDULE (Periodic Tasks)
# ============================================================
# These tasks run automatically at fixed intervals.
# Alternative to configuring via Django Admin.
app.conf.beat_schedule = {
    'monitor-sensor-health-every-minute': {
        'task': 'traffic_control.tasks.monitor_sensor_health',
        'schedule': 60.0,  # Every 60 seconds
    },
    'emergency-stuck-monitor-every-2-minutes': {
        'task': 'traffic_control.tasks.emergency_stuck_monitor',
        'schedule': 120.0,  # Every 2 minutes
    },

    'cleanup-stale-events-nightly': {
        'task': 'traffic_control.tasks.cleanup_stale_events',
        'schedule': crontab(hour=2, minute=0),
    },
    
    'reset-queues-shift-morning': {
        'task': 'traffic_control.tasks.reset_all_queues',
        'schedule': crontab(hour=8, minute=0),
    },
    'reset-queues-shift-evening': {
        'task': 'traffic_control.tasks.reset_all_queues',
        'schedule': crontab(hour=16, minute=0),
    },

    'check-traffic-congestion-5m': {
        'task': 'traffic_control.tasks.check_traffic_congestion',
        'schedule': 300.0,  # 5 minutes in seconds
    },
}


# ============================================================
# TASK SETTINGS
# ============================================================
app.conf.task_time_limit = 30 * 60
app.conf.task_soft_time_limit = 25 * 60
app.conf.task_max_retries = 3
app.conf.task_default_retry_delay = 60
app.conf.task_acks_late = True
app.conf.task_track_started = True
app.conf.task_send_sent_event = False