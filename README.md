# 🏭 Factory Traffic Management System (FTMS)

An **Event-Driven Real-Time Traffic Control System** designed for internal factory roads. This backend application manages vehicle flows, handles traffic signal state machines, and ensures strict safety invariants under high concurrency.

> Built for the **CSI Smart Tech Backend Developer Intern Assessment**.

---

## 📖 Table of Contents
1. [System Architecture](#system-architecture)
2. [Tech Stack](#tech-stack)
3. [Core Engineering Decisions](#core-engineering-decisions)
4. [Database Design](#database-design)
5. [API Endpoints & Postman Output](#api-endpoints--postman-output)
6. [Celery Tasks & Background Monitors](#celery-tasks--background-monitors)
7. [Concurrency & Safety Guarantees](#concurrency--safety-guarantees)
8. [Automated Testing (pytest)](#automated-testing-pytest)
9. [How to Run](#how-to-run)
10. [Screenshots](#screenshots)

---



## 🛠 Tech Stack

<div align="center">

| Layer | Technology | Purpose |
|:------|:-----------|:--------|
| **Framework** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/django/django-plain.svg" width="20" height="20" /> Django 4.2 + DRF | Core API & routing |
| **Database** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/postgresql/postgresql-original.svg" width="20" height="20" /> PostgreSQL | Persistent audit logs & event history |
| **Broker** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/rabbitmq/rabbitmq-original.svg" width="20" height="20" /> RabbitMQ | Message broker for Celery tasks |
| **Cache/State** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/redis/redis-original.svg" width="20" height="20" /> Redis | Live state, distributed locks, fast queue reads |
| **Async Worker** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/celery/celery-original.svg" width="20" height="20" /> Celery | Signal transitions, priority scoring |
| **Scheduler** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/celery/celery-original.svg" width="20" height="20" /> Celery Beat | Periodic health & emergency monitors |
| **Deployment** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/docker/docker-original.svg" width="20" height="20" /> Docker | Containerized environment |
| **Testing** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/pytest/pytest-original.svg" width="20" height="20" /> pytest | Automated test suite |
| **CI/CD** | <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/github/github-original.svg" width="20" height="20" /> GitHub Actions | Linting & testing pipeline |

</div>



🔑 Core Engineering Decisions
1. Separation of State and Persistence
We separate the live state (Redis) from the event logs (PostgreSQL). The dashboard reads from Redis every 1 second (fast, non-blocking). PostgreSQL is used for long-term audit logs (TrafficSignalLog) and analytics.

2. Asynchronous Processing (Non-Blocking API)
When a sensor event is received, the API does not wait for the signal to change. It saves the event and immediately returns 201 Created. The signal transition logic (30s Green, 5s Yellow, etc.) is offloaded to Celery, which uses countdown timers.

3. Distributed Locking (Redis SETNX)
If two sensor events arrive at the exact same millisecond, the system must not process them concurrently. We use a Redis SETNX lock (junction:<id>:lock) to serialize event processing. The second request gets a 429 Too Many Requests response.

4. Idempotency (Deduplication)
Sensors can send duplicate data. We use the event_id as a unique constraint in PostgreSQL. If a duplicate event_id arrives, it is silently ignored (returns 200 OK).

5. Self-Healing & Safety
Emergency Timeout: If an emergency vehicle enters but never sends a CLEARED event, Celery Beat automatically reverts the junction to AUTOMATIC mode after 5 minutes.

Sensor Health: Celery Beat checks the last_heartbeat of each junction. If a sensor hasn't reported in 5 minutes, a CRITICAL alert is generated.

🗄 Database Design
Junction: Represents a junction (e.g., Junction A). Tracks mode (AUTOMATIC, MANUAL, EMERGENCY), and last_heartbeat.

VehicleEvent: Logs every sensor event. Fields: event_id (unique), direction, event_type, vehicle_type, sensor_timestamp, server_received_at.

TrafficSignalLog: Audit trail of every signal change. Fields: phase (NS_GREEN, ALL_RED, etc.), triggered_by (AUTO, EMERGENCY, MANUAL), started_at.

SystemAlert: Stores system warnings (e.g., sensor offline, emergency timeout).

📡 API Endpoints & Postman Output
You can import postman_collection.json into Postman to test all endpoints.

1. Ingest Sensor Event
POST /api/v1/events/

Request:

{
    "event_id": "evt-1001",
    "junction_id": "A",
    "direction": "NORTH",
    "event_type": "VEHICLE_ARRIVED",
    "vehicle_type": "TRUCK",
    "sequence_no": 1,
    "timestamp": "2026-10-27T10:00:00Z"
}

Response (201 Created):

{ "status": "success" }

Duplicate Response (200 OK):

{ "message": "Duplicate event ignored" }

2. Get Live Junction State
GET /api/v1/junctions/A/state/

{
    "phase": "NS_GREEN",
    "mode": "AUTOMATIC",
    "queues": { "NORTH": 2, "EAST": 1 },
    "detailed_queues": {
        "NORTH": { "TRUCK": 2 },
        "EAST": { "EMERGENCY": 1 }
    }
}

3. Manual Command (Admin Override)
POST /api/v1/junctions/A/commands/

{
    "command": "MANUAL_GREEN_REQUEST",
    "direction": "WEST"
}

Response:

{ "status": "Transitioning to Manual Green for WEST" }

4. Traffic Analytics
GET /api/v1/junctions/A/analytics/

{
    "junction_id": "A",
    "time_window": "last_1_hour",
    "analytics": {
        "NORTH": { "TRUCK": 3, "FORKLIFT": 1 },
        "EAST": { "EMERGENCY": 1 }
    }
}

⚙️ Celery Tasks & Background Monitors

Core Signal Tasks (Routed to traffic_queue)
start_green: Turns the selected phase (NS or EW) GREEN. Schedules transition_to_yellow after 30 seconds.

transition_to_yellow: Changes GREEN to YELLOW. Schedules transition_to_all_red after 5 seconds.

transition_to_all_red: Turns all signals RED for safety clearance. Schedules decide_next_phase after 2 seconds.

decide_next_phase: The core engine. Reads queue scores from Redis. Grants GREEN to the direction with the highest score (Emergency > Truck > Forklift > Employee).

Background Monitors (Routed to default queue via Celery Beat)
monitor_sensor_health (Every 1 min): Checks junction last_heartbeat. Raises alert if stale.

emergency_stuck_monitor (Every 2 mins): Detects junctions stuck in EMERGENCY mode and reverts to AUTOMATIC.

check_traffic_congestion (Every 5 mins): Alerts if a queue exceeds 20 vehicles.

cleanup_stale_events (Daily at 2 AM): Removes processed events older than 7 days to keep the DB lean.

🔒 Concurrency & Safety Guarantees
No Green-Green Conflicts: The state machine strictly enforces GREEN -> YELLOW -> ALL_RED -> GREEN. Two conflicting phases can never be GREEN simultaneously.

Race Condition Prevention: The SensorEventView acquires a Redis lock. If another event is being processed, it returns 429 Too Many Requests.

Fail-Safe Defaults: If no vehicles are in any queue, the system defaults to ALL_RED (saving power and ensuring safety).


🧪 Automated Testing (pytest)

docker-compose exec web pytest

Tested Scenarios:

✅ test_duplicate_event_ignored: Validates event_id idempotency.

✅ test_invalid_vehicle_type_rejected: Rejects malformed data (HTTP 400).

✅ test_unknown_junction_rejected: Edge case handling.

✅ test_queue_never_goes_negative: Ensures queues don't drop below 0 on duplicate CLEARED events.

✅ test_scoring_priority_weighting: Confirms priority scoring logic.

Output: 5 passed in 2.34s

🚀 How to Run

1. Prerequisites
Docker & Docker Compose installed.

2. Setup
3. # Clone the repository
git clone <your-repo-link>
cd factory_traffic_management

# Create environment file
cp .env.example .env

# Build and start containers
docker-compose up --build -d
