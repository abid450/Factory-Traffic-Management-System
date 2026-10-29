import logging
import re
import sys
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import models
from .models import Junction, VehicleEvent
from traffic_control.core.state_manager import JunctionState
from traffic_control.core.queue_manager import QueueManager
from .tasks import (
    transition_to_yellow,
    decide_next_phase,
    start_green,
    emergency_timeout_check,
)

from django.db.models import Count
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

VALID_DIRECTIONS = [c[0] for c in VehicleEvent.DIRECTION_CHOICES]
VALID_EVENT_TYPES = [c[0] for c in VehicleEvent.EVENT_TYPE_CHOICES]
VALID_VEHICLE_TYPES = [c[0] for c in VehicleEvent.VEHICLE_TYPE_CHOICES]


# ==========================================
# 1. Frontend Dashboard View
# ==========================================
class DashboardView(APIView):

    def get(self, request):
        return render(request, 'dashboard.html')


# ==========================================
# 2. Sensor Event View (The API Endpoint)
# ==========================================
class SensorEventView(APIView):
    """
    Receives events from physical sensors.
    Handles deduplication, validation, and safe state updates.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        event_id = data.get('event_id')

        if not event_id:
            raise ValidationError({"error": "Missing event_id"})

        # 1. Deduplication Check
        if VehicleEvent.objects.filter(event_id=event_id).exists():
            return Response(
                {"message": "Duplicate event ignored"},
                status=status.HTTP_200_OK
            )

        # 2. Fetch Junction
        try:
            junction = Junction.objects.get(id=data.get('junction_id', 'A'))
        except Junction.DoesNotExist:
            raise ValidationError({"error": "Unknown junction"})

        # 3. Validate Fields
        direction = data.get('direction')
        event_type = data.get('event_type')
        vehicle_type = data.get('vehicle_type', 'EMPLOYEE_VEHICLE')

        if direction not in VALID_DIRECTIONS:
            raise ValidationError({"error": f"Invalid direction. Use one of {VALID_DIRECTIONS}"})
        if event_type not in VALID_EVENT_TYPES:
            raise ValidationError({"error": f"Invalid event_type. Use one of {VALID_EVENT_TYPES}"})
        if vehicle_type not in VALID_VEHICLE_TYPES:
            raise ValidationError({"error": f"Invalid vehicle_type. Use one of {VALID_VEHICLE_TYPES}"})

        # 4. Validate Timestamp
        raw_timestamp = data.get('timestamp')
        sensor_timestamp = parse_datetime(raw_timestamp) if raw_timestamp else timezone.now()
        if not sensor_timestamp:
            raise ValidationError({"error": "Invalid timestamp format"})

        state_mgr = JunctionState(junction.id)

        # 5. Concurrency Lock (Redis Distributed Lock)
        if not state_mgr.acquire_lock():
            return Response(
                {"error": "System is currently processing another event. Try again."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        try:
            # If anything below fails, the event row is rolled back,
            # so the sensor can safely retry with the same event_id.
            with transaction.atomic():
                # 6. Save Event (Persistence)
                event = VehicleEvent.objects.create(
                    event_id=event_id,
                    junction=junction,
                    direction=direction,
                    event_type=event_type,
                    vehicle_type=vehicle_type,
                    sequence_no=int(data.get('sequence_no', 0)),
                    sensor_timestamp=sensor_timestamp
                )

                # 7. Update Live Queue in Redis
                state = state_mgr.get_state() or {}
                queues = QueueManager.process_event(state, event)
                state_mgr.update_state(queues=queues)

                # 8. Handle Emergency Preemption
                chain_dispatched = False
                if event.vehicle_type == 'EMERGENCY' and event.event_type == 'VEHICLE_ARRIVED':
                    chain_dispatched = True
                    state_mgr.touch_cycle()
                    state_mgr.update_state(mode="EMERGENCY")

                    # Auto-revert after 5 mins if no clear event
                    emergency_timeout_check.apply_async((junction.id,), countdown=300)

                    current_phase = state.get("phase") or "ALL_RED"
                    if 'GREEN' in current_phase:
                        # phase is derived inside the task from the current state
                        transition_to_yellow.apply_async((junction.id,), countdown=1)
                    else:
                        decide_next_phase.apply_async((junction.id,), countdown=1)

                # 9. Self-healing: if nobody is driving the signal, start the cycle
                if (not chain_dispatched
                        and state_mgr.get_state().get("mode") != "MANUAL"
                        and not state_mgr.is_cycle_alive()):
                    state_mgr.touch_cycle()
                    decide_next_phase.apply_async((junction.id,), countdown=1)
                    logger.info("Signal cycle was idle - restarted for junction %s", junction.id)

            return Response({"status": "success"}, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.exception("Sensor event %s failed", event_id)
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        finally:
            # 10. Always Release Lock
            state_mgr.release_lock()


# ==========================================
# 3. Junction State View
# ==========================================
class JunctionStateView(APIView):
    """
    Returns current live state (Redis) for a specific junction.
    Used by the dashboard to poll updates every second.
    """
    def get(self, request, junction_id):
        state_mgr = JunctionState(junction_id)
        state = state_mgr.get_state()
        
        if not state:
            return Response(
                {"error": "Junction state not initialized"}, 
                status=status.HTTP_404_NOT_FOUND
            )
            
        # ---------------------------------------------------------
        # Build detailed_queues for the frontend icons
        # Currently, our state['queues'] looks like {"NORTH": 2, "EAST": 1}
        # We need to convert this to {"NORTH": {"TRUCK": 2}, ...}
        # ---------------------------------------------------------
        
        detailed_queues = {"NORTH": {}, "SOUTH": {}, "EAST": {}, "WEST": {}}
        
        # Fetch actual event data from DB to get vehicle types per direction
        # Get active (not cleared) vehicles for this junction
        active_vehicles = VehicleEvent.objects.filter(
            junction_id=junction_id,
            event_type='VEHICLE_ARRIVED'
        ).values('direction', 'vehicle_type').annotate(
            count=models.Count('id')
        )

        for v in active_vehicles:
            dir = v['direction']
            v_type = v['vehicle_type']
            if dir in detailed_queues:
                detailed_queues[dir][v_type] = v['count']

        if not any(detailed_queues.values()):
            for dir, count in state.get("queues", {}).items():
                if count > 0:
                    # Assume all are TRUCKS for fallback, so user sees something
                    detailed_queues[dir]["TRUCK"] = count

        state["detailed_queues"] = detailed_queues
        
        return Response(state, status=status.HTTP_200_OK)



# ==========================================
# 4. Manual Command View
# ==========================================
class ManualCommandView(APIView):
    """
    Handles admin manual commands (e.g., Manual Green).
    Enforces safe signal transitions.
    """
    def post(self, request, junction_id):
        state_mgr = JunctionState(junction_id)
        command = request.data.get('command')

        if not command:
            raise ValidationError({"error": "Command is required"})

        # Concurrency Lock
        if not state_mgr.acquire_lock():
            return Response(
                {"error": "System busy, try again"},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        try:
            if command == 'MANUAL_GREEN_REQUEST':
                direction = request.data.get('direction')
                if direction not in VALID_DIRECTIONS:
                    raise ValidationError({"error": "Invalid direction"})

                state_mgr.update_state(mode="MANUAL")
                current_phase = (state_mgr.get_state() or {}).get("phase") or "ALL_RED"
                phase = 'NS' if direction in ['NORTH', 'SOUTH'] else 'EW'

                # Safe Transition Logic
                if 'GREEN' in current_phase:
                    # Yellow -> All Red happens first; the chain is then
                    # re-started with a manual green for the requested direction.
                    transition_to_yellow.apply_async((junction_id,), countdown=1)
                    start_green.apply_async((junction_id, phase, "MANUAL_COMMAND"), countdown=9)
                else:
                    start_green.apply_async((junction_id, phase, "MANUAL_COMMAND"), countdown=2)

                return Response(
                    {"status": f"Transitioning to Manual Green for {direction}"},
                    status=status.HTTP_200_OK
                )

            elif command == 'RETURN_TO_AUTOMATIC':
                state_mgr.update_state(mode="AUTOMATIC")
                decide_next_phase.apply_async((junction_id,), countdown=1)
                return Response(
                    {"status": "Returned to Automatic Mode"},
                    status=status.HTTP_200_OK
                )

            return Response(
                {"error": f"Unknown command: {command}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        finally:
            state_mgr.release_lock()



# Traffic Analytics Endpoint  --------------------------------------------------------
class TrafficAnalyticsView(APIView):
    """
    Returns analytics of vehicle arrivals over the last hour for a specific junction.
    Useful for factory admins to see traffic patterns.
    """
    def get(self, request, junction_id):
        try:
            junction = Junction.objects.get(id=junction_id)
        except Junction.DoesNotExist:
            return Response({"error": "Unknown junction"}, status=404)

        last_hour = timezone.now() - timedelta(hours=1)
        
        # Query vehicle events from the last hour
        analytics_data = VehicleEvent.objects.filter(
            junction=junction,
            sensor_timestamp__gte=last_hour,
            event_type='VEHICLE_ARRIVED'
        ).values('direction', 'vehicle_type').annotate(count=Count('id'))

        # Convert to a more usable format for the frontend
        result = {}
        for item in analytics_data:
            direction = item['direction']
            v_type = item['vehicle_type']
            count = item['count']
            
            if direction not in result:
                result[direction] = {}
            result[direction][v_type] = count

        return Response({
            "junction_id": junction_id,
            "time_window": "last_1_hour",
            "analytics": result
        }, status=200)
    

# ==========================================
# 5. Celery Diagnostics (open in browser)
# ==========================================
def _mask(url):
    return re.sub(r"://[^@]*@", "://***@", url or "")


class CeleryHealthView(APIView):
    """
    GET /api/v1/health/celery/
    Shows whether the web process, broker and worker are wired correctly.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        # Must be checked BEFORE we import it ourselves below.
        loaded_at_startup = "factory_core.celery" in sys.modules

        from factory_core.celery import app

        report = {
            "celery_loaded_at_startup": loaded_at_startup,
            "broker_url": _mask(app.conf.broker_url),
        }
        try:
            insp = app.control.inspect(timeout=2)
            report["workers_ping"] = insp.ping() or "NO WORKER REPLIED"
            report["worker_queues"] = {
                w: [q["name"] for q in qs]
                for w, qs in (insp.active_queues() or {}).items()
            }
            report["registered_traffic_tasks"] = {
                w: sorted(t for t in ts if t.startswith("traffic_control."))
                for w, ts in (insp.registered() or {}).items()
            }
            report["scheduled_eta_tasks"] = {
                w: len(sc) for w, sc in (insp.scheduled() or {}).items()
            }
        except Exception as exc:
            report["error"] = repr(exc)

        return Response(report)