from django.db import models

# Create your models here.
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator

class Junction(models.Model):
    MODE_CHOICES = [('AUTOMATIC', 'Automatic'), ('MANUAL', 'Manual'), ('EMERGENCY', 'Emergency'), ('DEGRADED', 'Degraded')]

    id = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=50, default="Main Junction")
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='AUTOMATIC')
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class VehicleEvent(models.Model):
    DIRECTION_CHOICES = [('NORTH', 'North'), ('SOUTH', 'South'), ('EAST', 'East'), ('WEST', 'West')]
    EVENT_TYPE_CHOICES = [('VEHICLE_ARRIVED', 'Vehicle Arrived'), ('VEHICLE_CLEARED', 'Vehicle Cleared')]
    VEHICLE_TYPE_CHOICES = [('EMERGENCY', 'Emergency'), ('TRUCK', 'Truck'), ('FORKLIFT', 'Forklift'), ('EMPLOYEE_VEHICLE', 'Employee')]
   
    event_id = models.CharField(max_length=50, unique=True, db_index=True)
    junction = models.ForeignKey(Junction, on_delete=models.CASCADE, related_name='events')
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPE_CHOICES)
    sequence_no = models.IntegerField()
    sensor_timestamp = models.DateTimeField()
    server_received_at = models.DateTimeField(auto_now_add=True)
    is_processed = models.BooleanField(default=False)
    error_message = models.TextField(null=True, blank=True)
    
    class Meta:
        ordering = ['-server_received_at']



class TrafficSignalLog(models.Model):
    PHASE_CHOICES = [('NS_GREEN', 'NS Green'), ('NS_YELLOW', 'NS Yellow'), ('EW_GREEN', 'EW Green'), ('EW_YELLOW', 'EW Yellow'), ('ALL_RED', 'All Red')]
    TRIGGER_CHOICES = [('AUTO_SCHEDULE', 'Auto'), ('EMERGENCY_PREEMPTION', 'Emergency'), ('MANUAL_COMMAND', 'Manual')]

    junction = models.ForeignKey(Junction, on_delete=models.CASCADE, related_name='signal_logs')
    phase = models.CharField(max_length=20, choices=PHASE_CHOICES)
    triggered_by = models.CharField(max_length=30, choices=TRIGGER_CHOICES)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)


class VehicleQueue(models.Model):
    junction = models.ForeignKey(Junction, on_delete=models.CASCADE, related_name='queues')
    direction = models.CharField(max_length=10)
    vehicle_type = models.CharField(max_length=20)
    count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    oldest_waiting_since = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('junction', 'direction', 'vehicle_type')


class SystemAlert(models.Model):
    SEVERITY_CHOICES = [('INFO', 'Info'), ('WARNING', 'Warning'), ('CRITICAL', 'Critical')]
    
    junction = models.ForeignKey(Junction, on_delete=models.CASCADE, null=True, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='WARNING')
    message = models.TextField()
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)