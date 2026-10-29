from datetime import datetime, timezone

class QueueManager:
    @staticmethod
    def process_event(state, event):
        queues = state.get("queues", {})
        direction = event.direction
        
        if event.event_type == 'VEHICLE_ARRIVED':
            queues[direction] = queues.get(direction, 0) + 1
        elif event.event_type == 'VEHICLE_CLEARED':
            queues[direction] = max(0, queues.get(direction, 0) - 1) # Never -1
            
        return queues

    @staticmethod
    def calculate_scores(state):
        queues = state.get("queues", {})
        ns_score = queues.get('NORTH', 0) + queues.get('SOUTH', 0)
        ew_score = queues.get('EAST', 0) + queues.get('WEST', 0)
        return ns_score, ew_score