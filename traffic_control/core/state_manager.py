import redis
import json
from django.conf import settings

redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


class JunctionState:
    def __init__(self, junction_id):
        self.junction_id = junction_id
        self.state_key = f"junction:{junction_id}:state"
        self.lock_key = f"junction:{junction_id}:lock"
        self.cycle_key = f"junction:{junction_id}:cycle_alive"

    def get_state(self):
        state = redis_client.get(self.state_key)
        if not state:
            return {"phase": "ALL_RED", "mode": "AUTOMATIC", "queues": {}}
        return json.loads(state)

    def update_state(self, **kwargs):
        state = self.get_state()
        state.update(kwargs)
        redis_client.set(self.state_key, json.dumps(state))
        return state

    def acquire_lock(self, timeout=5):
        # Redis Distributed Lock for concurrency safety
        return redis_client.set(self.lock_key, "locked", nx=True, ex=timeout)

    def release_lock(self):
        redis_client.delete(self.lock_key)

    # ---- Signal-cycle heartbeat -------------------------------------
    # Every signal task refreshes this key. If it expires, nobody is
    # driving the signal, and the next sensor event restarts the cycle.
    def touch_cycle(self, ttl=90):
        redis_client.set(self.cycle_key, "1", ex=ttl)

    def is_cycle_alive(self):
        return bool(redis_client.exists(self.cycle_key))