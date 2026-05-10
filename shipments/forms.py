from django import forms
from django.contrib.auth.hashers import make_password
from .models import AppUser, Department
from shipments.models import Shipment
from django.contrib.auth.models import Group

class AppUserForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'border rounded px-2 py-1 w-full',
            'placeholder': 'Enter password'
        }),
        required=True
    )

    class Meta:
        model = AppUser
        fields = ['username', 'password', 'first_name', 'last_name', 'email', 'department', 'zone']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'border rounded px-2 py-1 w-full'}),
            'first_name': forms.TextInput(attrs={'class': 'border rounded px-2 py-1 w-full'}),
            'last_name': forms.TextInput(attrs={'class': 'border rounded px-2 py-1 w-full'}),
            'email': forms.EmailInput(attrs={'class': 'border rounded px-2 py-1 w-full'}),
            'department': forms.Select(attrs={'class': 'border rounded px-2 py-1 w-full'}),
            'zone': forms.TextInput(attrs={
                'class': 'border rounded px-2 py-1 w-full',
                'placeholder': 'Only for Operations'
            }),
        }

    def save(self, commit=True):
        user = super().save(commit=False)

        # Hash password
        raw_password = self.cleaned_data.get('password')
        if raw_password:
            user.set_password(raw_password)

        # Clear zone if not Operations
        if user.department and user.department.name != 'Operations':
            user.zone = None

        if commit:
            user.save()

        return user
    
class ShipmentForm(forms.ModelForm):
    class Meta:
        model = Shipment
        fields = [
            "tracking_number", "master_airwaybill", "no_of_pkg", "weight",
            "shipper_company", "shipper_name", "shipper_address", "shipper_country",
            "recipient_name", "recipient_company", "recipient_address", "recipient_country",
            "recipient_phone", "customs_value", "customs_currency", "commodity",
            "category", "department", "assigned_agent", "status"
        ]
        widgets = {
            "assigned_agent": forms.Select(attrs={'class': 'border rounded px-2 py-1 w-full'}),
            "department": forms.Select(attrs={'class': 'border rounded px-2 py-1 w-full'}),
        }