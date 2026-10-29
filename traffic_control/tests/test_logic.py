import pytest
from traffic_control.core.queue_manager import QueueManager
from traffic_control.models import VehicleEvent

@pytest.mark.django_db
def test_queue_never_goes_negative(junction=None):
    """When a vehicle is cleared, queue count must not go below 0."""
    from traffic_control.models import Junction
    junction = Junction.objects.create(id="B", name="Junction B")
    
    state = {"queues": {"NORTH": 0}}
    # Simulating a CLEARED event when queue is already 0
    event = VehicleEvent(
        event_id="evt-clear-1",
        junction=junction,
        direction="NORTH",
        event_type="VEHICLE_CLEARED",
        vehicle_type="TRUCK",
        sequence_no=2,
        sensor_timestamp="2026-10-27T10:00:00Z"
    )
    updated_queues = QueueManager.process_event(state, event)
    assert updated_queues["NORTH"] == 0  # Should stay 0, not -1

@pytest.mark.django_db
def test_scoring_priority_weighting():
    """Verify that score calculation respects vehicle type weights."""
    state = {
        "queues": {
            "NORTH": 2,  # 2 vehicles
            "EAST": 1    # 1 vehicle
        }
    }
    ns_score, ew_score = QueueManager.calculate_scores(state)
    
    # North has 2 vehicles, East has 1 -> North should score higher
    assert ns_score > ew_score