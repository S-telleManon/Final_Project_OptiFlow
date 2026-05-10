from django.contrib import admin
from .models import AppUser, Department, Shipment

admin.site.register(AppUser)
admin.site.register(Department)
admin.site.register(Shipment)
