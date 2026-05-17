from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import Group

class Shipment(models.Model):
    tracking_number = models.CharField(max_length=50, unique=True)
    master_airwaybill = models.CharField(max_length=50)
    no_of_pkg = models.IntegerField()  # number of packages
    weight = models.DecimalField(max_digits=10, decimal_places=2)  # e.g., 99999999.99 kg
    shipper_company = models.CharField(max_length=100)
    shipper_name = models.CharField(max_length=100)
    shipper_address = models.TextField()
    shipper_country = models.CharField(max_length=50)
    recipient_name = models.CharField(max_length=200)
    recipient_company = models.CharField(max_length=200)
    recipient_address = models.TextField()
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    recipient_country = models.CharField(max_length=50)
    recipient_phone = models.CharField(max_length=20)  
    customs_value = models.DecimalField(max_digits=12, decimal_places=2)  
    customs_currency = models.CharField(max_length=20)
    commodity = models.CharField(max_length=200)
    category = models.CharField(max_length=20)
    department = models.ForeignKey(
        'Department',
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
        default=None  # we will set default in form
    )
    assigned_agent = models.ForeignKey(
        'AppUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_shipments"
    )
    
    delivery_sequence = models.IntegerField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='Uploaded')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tracking_number} - {self.recipient_name} ({self.department})"
    
class Department(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class AppUser(AbstractUser):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(unique=True)

    username = models.CharField(max_length=50, unique=True)
    # password = models.CharField(max_length=128)  # hashed password

    department = models.ForeignKey(
        'Department',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    zone = models.CharField(max_length=50, null=True, blank=True)  # Only for Operations

    must_change_password = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        # Hash password if not already hashed
        if not self.password.startswith('pbkdf2_'):
            self.password = make_password(self.password)
        # Zone only for Operations
        if self.department and self.department.name != 'Operations':
            self.zone = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.username})"

class Driver_info(models.Model):

    driver = models.ForeignKey("AppUser", on_delete=models.CASCADE)

    date = models.DateField()

    start_time = models.TimeField()
    end_time = models.TimeField()

    is_available = models.BooleanField(default=True)

    max_stops = models.IntegerField(default=25)


class ShipmentHistory(models.Model):

    shipment = models.ForeignKey(
        "Shipment",
        on_delete=models.CASCADE,
        related_name="history"
    )

    status = models.CharField(max_length=50)
    department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    assigned_agent = models.ForeignKey(
        "AppUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    changed_by = models.ForeignKey(
        "AppUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shipment_changes"
    )

    timestamp = models.DateTimeField(auto_now_add=True)

    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.shipment.tracking_number} - {self.status}"