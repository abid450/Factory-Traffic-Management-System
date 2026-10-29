# conftest.py (প্রজেক্টের রুটে)
import pytest
from rest_framework.test import APIClient
from traffic_control.models import Junction

@pytest.fixture
def api_client():
    """Provides an unauthenticated DRF API client for testing."""
    return APIClient()

@pytest.fixture
def junction(db):
    """Creates a dummy junction for use in tests."""
    return Junction.objects.create(id="A", name="Test Junction")