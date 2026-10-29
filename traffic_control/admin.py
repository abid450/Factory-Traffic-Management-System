from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Junction, VehicleEvent, TrafficSignalLog, VehicleQueue, SystemAlert

admin.site.register(Junction)
admin.site.register(VehicleEvent)
admin.site.register(TrafficSignalLog)
admin.site.register(VehicleQueue)
admin.site.register(SystemAlert)