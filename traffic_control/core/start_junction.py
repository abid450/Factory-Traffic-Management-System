from django.core.management.base import BaseCommand

from traffic_control.models import Junction
from traffic_control.core.state_manager import JunctionState
from traffic_control.tasks import decide_next_phase


class Command(BaseCommand):
    help = "Create the junction, initialise its Redis state and start the signal cycle"

    def add_arguments(self, parser):
        parser.add_argument("--id", default="A")

    def handle(self, *args, **opts):
        jid = opts["id"]

        Junction.objects.get_or_create(id=jid, defaults={"name": f"Junction {jid}"})

        state_mgr = JunctionState(jid)
        state_mgr.update_state(phase="ALL_RED", mode="AUTOMATIC")

        result = decide_next_phase.delay(jid)
        self.stdout.write(self.style.SUCCESS(f"Junction {jid} started. Task id: {result.id}"))