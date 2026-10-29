import pytest
from rest_framework.test import APIClient
from traffic_control.models import Junction, VehicleEvent

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def junction(db):
    return Junction.objects.create(id="A", name="Test Junction")

@pytest.mark.django_db
def test_duplicate_event_ignored(api_client, junction):
    """Sending the same event_id twice must not create duplicate records."""
    payload = {
        "event_id": "evt-dup-1",
        "junction_id": "A",
        "direction": "NORTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_type": "TRUCK",
        "sequence_no": 1,
        "timestamp": "2026-10-27T10:00:00Z"
    }
    res1 = api_client.post('/api/v1/events/', payload, format='json')
    res2 = api_client.post('/api/v1/events/', payload, format='json')
    
    assert res1.status_code == 201
    assert res2.status_code == 200
    assert res2.data['message'] == "Duplicate event ignored"
    assert VehicleEvent.objects.count() == 1

@pytest.mark.django_db
def test_invalid_vehicle_type_rejected(api_client, junction):
    """Unknown vehicle types must be rejected with a 400 error."""
    payload = {
        "event_id": "evt-inv-1",
        "junction_id": "A",
        "direction": "NORTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_type": "AIRPLANE",  # Invalid
        "sequence_no": 1,
        "timestamp": "2026-10-27T10:00:00Z"
    }
    res = api_client.post('/api/v1/events/', payload, format='json')
    assert res.status_code == 400

@pytest.mark.django_db
def test_unknown_junction_rejected(api_client):
    """Requests to unknown junctions must fail."""
    payload = {
        "event_id": "evt-jx-1",
        "junction_id": "ZZZ",
        "direction": "NORTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_type": "TRUCK",
        "sequence_no": 1,
        "timestamp": "2026-10-27T10:00:00Z"
    }
    res = api_client.post('/api/v1/events/', payload, format='json')
    assert res.status_code == 400