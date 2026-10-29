<div align="center">
  <h1>🏭 Factory Traffic Management System (FTMS)</h1>
  <p><strong>An Event-Driven Real-Time Traffic Control System for Internal Factory Roads</strong></p>
  
  ![Django](https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white)
  ![DRF](https://img.shields.io/badge/DRF-A30000?style=for-the-badge&logo=django&logoColor=white)
  ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)
  ![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)
  ![RabbitMQ](https://img.shields.io/badge/RabbitMQ-FF6600?style=for-the-badge&logo=rabbitmq&logoColor=white)
  ![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)
  ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
</div>

---

## 📖 Overview

The **Factory Traffic Management System (FTMS)** is a backend application designed to manage traffic signals and vehicle queues at factory junctions (e.g., Junction A). 

Instead of a simple CRUD application, this system is built as an **Event-Driven Control System**. It ingests high-frequency vehicle detection events, maintains real-time queues, controls traffic signals with strict safety invariants, and handles emergencies and manual overrides.

## 🏗 Architecture Overview

The system is designed as an **Event-Driven Microkernel** to ensure high throughput, safety, and reliability.

1. **API Layer (Django DRF):** Receives raw sensor events. Handles validation, deduplication (`event_id`), and immediately returns a `201 Created` response. It also uses a Redis Distributed Lock (`SETNX`) to prevent race conditions.
2. **State Layer (Redis):** Stores the live state (`phase`, `mode`, `queues`) for lightning-fast reads by the dashboard.
3. **Domain Logic Layer (Celery):** Processes signal transitions asynchronously without blocking the API.
4. **Persistence Layer (PostgreSQL):** Stores all events and an audit trail (`TrafficSignalLog`) for debugging and analytics.
5. **Background Monitors (Celery Beat):** Ensures the system is self-healing by checking sensor health and emergency timeouts.

```text
Sensors (HTTP POST) 
      │
      ▼
[ Django API ] ─── (Acquire Lock) ───► [ Redis (Live State & Lock) ]
      │                                         ▲
      │ (Publish Task)                          │ (Read State)
      ▼                                         │
[ RabbitMQ ]                                    │
      │                                         │
      ▼                                         │
[ Celery Worker ] ── (Update State/Log) ────────┘
      │
      ▼
[ Frontend Dashboard ] (Polls every 1 second)