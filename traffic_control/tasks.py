import logging

from celery import shared_task
from .models import VehicleEvent
from traffic_control.core.state_manager import JunctionState
from traffic_control.core.queue_manager import QueueManager
from .models import TrafficSignalLog, SystemAlert, Junction
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def start_green(junction_id, phase, trigger="AUTO_SCHEDULE"):
    """
    Turn the signal GREEN for the selected phase (NS or EW).
    After 30 seconds, trigger the transition to YELLOW.
    """
    state_mgr = JunctionState(junction_id)
    state_mgr.touch_cycle()
    state_mgr.update_state(phase=f"{phase}_GREEN")
    logger.info("[%s] %s_GREEN (%s)", junction_id, phase, trigger)

    TrafficSignalLog.objects.create(
        junction_id=junction_id,
        phase=f"{phase}_GREEN",
        triggered_by=trigger,
    )

    # Schedule transition to YELLOW after 30 seconds
    transition_to_yellow.apply_async((junction_id, phase), countdown=30)


@shared_task
def transition_to_yellow(junction_id, phase=None):
    """
    Switch the active GREEN signal to YELLOW, then ALL_RED after 5 seconds.
    If phase is not given, it is derived from the current state.
    """
    state_mgr = JunctionState(junction_id)
    current = state_mgr.get_state().get("phase", "")

    if phase is None:
        if "GREEN" not in current:
            return                      # nothing to turn yellow
        phase = current.split("_")[0]   # NS_GREEN -> NS

    # Ignore stale timers (phase already changed by emergency/manual)
    if current != f"{phase}_GREEN":
        logger.info("[%s] stale yellow timer for %s ignored (now %s)", junction_id, phase, current)
        return

    state_mgr.touch_cycle()
    state_mgr.update_state(phase=f"{phase}_YELLOW")
    logger.info("[%s] %s_YELLOW", junction_id, phase)

    TrafficSignalLog.objects.create(
        junction_id=junction_id,
        phase=f"{phase}_YELLOW",
        triggered_by="AUTO_SCHEDULE",
    )

    transition_to_all_red.apply_async((junction_id,), countdown=5)


@shared_task
def transition_to_all_red(junction_id):
    """
    Set all directions to RED for a brief period (clearance phase).
    After 2 seconds, evaluate the next phase.
    """
    state_mgr = JunctionState(junction_id)
    state_mgr.touch_cycle()
    state_mgr.update_state(phase="ALL_RED")
    logger.info("[%s] ALL_RED", junction_id)

    TrafficSignalLog.objects.create(
        junction_id=junction_id,
        phase="ALL_RED",
        triggered_by="AUTO_SCHEDULE",
    )

    decide_next_phase.apply_async((junction_id,), countdown=2)


@shared_task
def decide_next_phase(junction_id):
    """
    Core decision engine.
    Checks manual mode and queue scores, then grants the next GREEN.
    """
    state_mgr = JunctionState(junction_id)
    state = state_mgr.get_state()

    # If in MANUAL mode, wait for admin command
    if state.get("mode") == "MANUAL":
        return

    state_mgr.touch_cycle()
    ns_score, ew_score = QueueManager.calculate_scores(state)
    logger.info("[%s] decide_next_phase NS=%s EW=%s", junction_id, ns_score, ew_score)

    # If both directions are empty, keep ALL_RED and check again later
    if ns_score == 0 and ew_score == 0:
        decide_next_phase.apply_async((junction_id,), countdown=5)
        return

    # Grant GREEN to the direction with the highest score
    if ns_score >= ew_score:
        start_green.delay(junction_id, 'NS')
    else:
        start_green.delay(junction_id, 'EW')


@shared_task
def emergency_timeout_check(junction_id):
    """
    Safety fallback for stuck emergency requests.
    If an emergency vehicle does not clear within 5 minutes,
    revert the junction to AUTOMATIC mode.
    """
    state_mgr = JunctionState(junction_id)
    state = state_mgr.get_state()

    if state.get("mode") == "EMERGENCY":
        state_mgr.update_state(mode="AUTOMATIC")

        SystemAlert.objects.create(
            junction_id=junction_id,
            severity="WARNING",
            message="Emergency Mode Timeout - Reverted to AUTOMATIC",
        )

        decide_next_phase.apply_async((junction_id,), countdown=1)



# Celery Beat Sheduling -------------------------------------------------------------------------------------------------------

@shared_task
def monitor_sensor_health():
    """
    Periodic task (runs every minute via Celery Beat).
    Detects junctions with stale heartbeats and logs alerts.
    """
    from .models import Junction, SystemAlert
    
    stale_threshold = timezone.now() - timedelta(minutes=5)
    
    for junction in Junction.objects.all():
        if junction.last_heartbeat and junction.last_heartbeat < stale_threshold:
            # Check if an unresolved alert already exists
            already_alerted = SystemAlert.objects.filter(
                junction=junction, 
                message__icontains="Sensor offline", 
                is_resolved=False
            ).exists()
            
            if not already_alerted:
                SystemAlert.objects.create(
                    junction=junction,
                    severity="CRITICAL",
                    message=f"Sensor offline at Junction {junction.id} for over 5 minutes"
                )


@shared_task
def emergency_stuck_monitor():
    """
    Periodic task (runs every 2 minutes).
    Detects emergency mode that has been active for too long.
    """
    from .models import SystemAlert
    
    junctions = Junction.objects.filter(mode="EMERGENCY")
    
    for junction in junctions:
        state_mgr = JunctionState(junction.id)
        state = state_mgr.get_state()
        phase = state.get("phase")
        
        if phase == "ALL_RED":
            # If stuck in EMERGENCY for too long
            state_mgr.update_state(mode="AUTOMATIC")
            SystemAlert.objects.create(
                junction=junction,
                severity="WARNING",
                message=f"Junction {junction.id} stuck in EMERGENCY mode for too long"
            )
            decide_next_phase.apply_async((junction.id,), countdown=1)



# cleanup_stale_events ------------------------------------------------------------
@shared_task
def cleanup_stale_events():
    """
    Periodic task to remove processed vehicle events older than 7 days.
    Keeps the database lean and fast.
    """
    cutoff_date = timezone.now() - timedelta(days=7)
    deleted_count, _ = VehicleEvent.objects.filter(
        event_type='VEHICLE_CLEARED', 
        sensor_timestamp__lt=cutoff_date
    ).delete()
    print(f"🧹 Cleaned up {deleted_count} stale vehicle events older than 7 days.")




# Auto Queue Reset on Shift Change    --------------------------------------------------------------------
@shared_task
def reset_all_queues():
    """
    Periodic task to reset all vehicle queues at shift changes.
    Simulates the real-world scenario where the factory floor is cleared between shifts.
    """
    from traffic_control.core.state_manager import JunctionState
    from .models import Junction
    
    for junction in Junction.objects.all():
        state_mgr = JunctionState(junction.id)
        # Reset queues to empty
        state_mgr.update_state(queues={})
        print(f"🔄 Reset queues for Junction {junction.id} (Shift Change).")




# High Traffic Alert -----------------------------------------------------------------
@shared_task
def check_traffic_congestion():
    """
    Periodic task to check for heavy traffic congestion.
    Raises an alert if queue count exceeds the threshold.
    """
    from traffic_control.core.state_manager import JunctionState
    from .models import Junction
    
    CONGESTION_THRESHOLD = 20
    
    for junction in Junction.objects.all():
        state_mgr = JunctionState(junction.id)
        state = state_mgr.get_state()
        queues = state.get("queues", {})
        
        for direction, count in queues.items():
            if count >= CONGESTION_THRESHOLD:
                # Avoid duplicate alerts for the same junction
                exists = SystemAlert.objects.filter(
                    junction=junction, 
                    message__icontains=f"Heavy traffic on {direction}", 
                    is_resolved=False
                ).exists()
                
                if not exists:
                    SystemAlert.objects.create(
                        junction=junction,
                        severity="WARNING",
                        message=f"Heavy traffic on {direction} ({count} vehicles). Please intervene."
                    )