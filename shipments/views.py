import csv,io
from django.shortcuts import render, redirect , get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import permission_required,login_required
from .models import Shipment,AppUser, Department, Driver_info,ShipmentHistory
from datetime import datetime,date,time,timedelta
from .forms import AppUserForm
from django.contrib.auth.models import Group
from shipments.forms import ShipmentForm
from django.db.models import Count
from .services.geocoding import geocode
import json
from .services.optimiser import optimize
from django.conf import settings
from django.http import JsonResponse
from django.core.serializers.json import DjangoJSONEncoder

def dashboard(request):
    user = request.user
    is_manager = user.groups.filter(name__iexact="Manager").exists()
    is_admin = user.is_superuser
    if is_admin:
        shipments = Shipment.objects.all()
    elif is_manager:
        shipments = Shipment.objects.filter(department=user.department)
    else:
        shipments = Shipment.objects.filter(assigned_agent=user)

    status_counts = shipments.values('status').annotate(count=Count('id'))
    status_labels = [item['status'] for item in status_counts]
    status_data = [item['count'] for item in status_counts]

    if is_manager or is_admin:
        dept_counts = shipments.values('department__name').annotate(count=Count('id'))
        dept_labels = [item['department__name'] if item['department__name'] else "Unassigned" for item in dept_counts]
        dept_data = [item['count'] for item in dept_counts]
    else:
        dept_labels, dept_data = [], []
    total = shipments.count()

    return render(request, "shipments/dashboard.html", {
        'total': total,
        'status_labels': status_labels,
        'status_data': status_data,
        'dept_labels': dept_labels,
        'dept_data': dept_data,
        'is_manager': is_manager,
        'is_admin': is_admin,
    })
# -------------------------------------------User Listing ------------------------------------------------------------------------------

def users_list(request):
    departments = Department.objects.all()
    users = AppUser.objects.all().order_by('department', 'first_name')

    if request.method == 'POST':
        form = AppUserForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('users_list')
    else:
        form = AppUserForm()

    operations_dept = Department.objects.filter(name__iexact="Operations").first()
    operations_dept_id = operations_dept.id if operations_dept else None

    return render(request, 'shipments/users.html', {
        'users': users,
        'departments': departments,
        'form': form,
        'operations_dept_id': operations_dept_id
    })

def add_department(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Department.objects.get_or_create(name=name)
    return redirect('users_list')


# -------------------------------------------CRUD FOR USERS------------------------------------------------------------------------------
#--------------CREATE USER

def create_user(request):
    form = AppUserForm(request.POST or None)
    departments = Department.objects.all()
    groups = Group.objects.all()

    operations_dept = Department.objects.filter(name__iexact="Operations").first()
    operations_dept_id = operations_dept.id if operations_dept else None

from django.contrib.auth.models import Group
from django.contrib.auth.hashers import make_password

def create_user(request):
    form = AppUserForm(request.POST or None)
    departments = Department.objects.all()
    groups = Group.objects.all()

    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)  
        messages.success(request, f"User {user.first_name} {user.last_name} was successfully created.")

        raw_password = form.cleaned_data.get('password')
        if raw_password:
            user.set_password(raw_password)

        user.save() 


        group_id = request.POST.get('group')
        if group_id:
            group = Group.objects.get(id=group_id)
            user.groups.add(group)

        return redirect('users_list')

    return render(request, 'shipments/user_creation.html', {
        'form': form,
        'departments': departments,
        'groups': groups,
    })

#----------------------EDIT USER-------------------------

def edit_user(request, user_id):
    user = get_object_or_404(AppUser, id=user_id)
    form = AppUserForm(request.POST or None, instance=user)
    departments = Department.objects.all()
    groups = Group.objects.all()
    current_group = user.groups.first()

    if request.method == "POST":

        if form.is_valid():
            user = form.save(commit=False)

            raw_password = form.cleaned_data.get('password')
            if raw_password:
                user.set_password(raw_password)

            user.save()

            group_id = request.POST.get('group')
            user.groups.clear()

            if group_id:
                group = Group.objects.get(id=group_id)
                user.groups.add(group)

            messages.success(request, "User updated successfully.")
            return redirect('users_list')

        else:
            messages.error(request, "Unable to update user. Please check the form for errors.")

    return render(request, 'shipments/user_creation.html', {
        'form': form,
        'departments': departments,
        'groups': groups,
        'editing': True,
        'current_group': current_group,
        'user_id': user.id,
    })

#---------------DELETE USER
def delete_user(request, user_id):
    user = get_object_or_404(AppUser, id=user_id)

    if request.method == "POST":
        user.delete()
        messages.success(request, f"User {user.first_name} {user.last_name} was successfully deleted.")
        return redirect('users_list')

    # Optional: show confirmation page
    return render(request, 'shipments/user_delete_confirm.html', {
        'user': user
    })
# -------------------------------------------uploading of shipments------------------------------------------------------------------------------

from django.shortcuts import render, redirect
from django.contrib import messages
from shipments.models import Shipment, Department
from django.contrib.auth.models import Group
import csv


def clean_address(address):
    return " ".join(address.split()).strip()

def upload(request):
    if request.method == 'POST':
        file = request.FILES.get('file')

        if not file:
            messages.error(request, "No file selected")
            return redirect('upload')

        if not file.name.endswith('.csv'):
            messages.error(request, "Please upload a CSV file")
            return redirect('upload')


        decoded_file = file.read().decode('utf-8').splitlines()
        reader = csv.DictReader(decoded_file)  # Assumes CSV has headers


        clearance_dept = Department.objects.filter(name__iexact="Clearance").first()

        created_count = 0
        skipped_count = 0

        for row in reader:
            
            tracking_number = str(row.get('Tracking No', '')).strip()
            address = clean_address(row.get("Recipient Address", ""))
            lat, lon = geocode(row["Recipient Address"])

            print("ADDRESS:", row["Recipient Address"])
            print("lat/Lon:", lat, lon)

            if Shipment.objects.filter(tracking_number=tracking_number).exists():
                skipped_count += 1
                continue
            if not lat or not lon:
                lat, lon = -20.1609, 57.5012  # Mauritius center fallback
                status = "NEEDS_GEOLOCATION"
            else:
                status = row.get('Status', 'Uploaded')


            dept_name = row.get('Assigned Dept', '').strip()
            if dept_name:
                department = Department.objects.filter(name__iexact=dept_name).first()
                if not department:
                    department = clearance_dept
            else:
                department = clearance_dept


            Shipment.objects.create(
                tracking_number=tracking_number,
                master_airwaybill=row.get('Master Airwaybill', ''),
                no_of_pkg=row.get('No of Pkg', 0) or 0,
                weight=row.get('Weight', 0) or 0,
                shipper_company=row.get('Shipper Company', ''),
                shipper_name=row.get('Shipper Name', ''),
                shipper_address=row.get('Shipper Address', ''),
                shipper_country=row.get('Shipper Country', ''),
                recipient_name=row.get('Recipient Name', ''),
                recipient_company=row.get('Recipient Company', ''),
                recipient_address=row.get('Recipient Address', ''),
                recipient_country=row.get('Recipient Country', ''),
                recipient_phone=row.get('Recipient Phone', ''),
                customs_value=row.get('Customs Value', 0) or 0,
                customs_currency=row.get('Customs Currency', ''),
                commodity=row.get('Commodity', ''),
                category=row.get('Category', ''),
                department=department,
                status=row.get('Status', 'Uploaded'),
                latitude=lat,
                longitude=lon
            )
            created_count += 1

        messages.success(
            request,
            f"CSV processed: {created_count} shipments created, {skipped_count} skipped (duplicates)."
        )

        return redirect('upload')

    return render(request, 'shipments/upload.html')

# def shipment_list(request):
#     shipments = Shipment.objects.all().order_by('-created_at')  # newest first
#     context = {
#         'shipments': shipments
#     }
#     return render(request, 'shipments/shipment_list.html', context)



# -------------------------------------------Shipment List view------------------------------------------------------------------------------
@login_required
def shipment_list(request):
    user = request.user
    is_manager = user.groups.filter(name__iexact="Manager").exists()
    is_admin = user.is_superuser  

    can_optimize = (
    (user.department and user.department.name == "operations")
    or is_manager
    or is_admin
    )

    if request.method == "POST":
        shipment_id = request.POST.get("shipment_id")
        shipment = get_object_or_404(Shipment, id=shipment_id)

       # ------Checking if superuser----
        if not is_admin and not is_manager and shipment.assigned_agent != user:
            messages.error(request, "You cannot edit this shipment.")
            return redirect("shipment_list")

        # ------updating Department ----
        dept_id = request.POST.get("department")
        if dept_id:
            department = Department.objects.filter(id=dept_id).first()
            if department:
                shipment.department = department

        # ------updating status----
        status = request.POST.get("status")
        if status:
            shipment.status = status
            if status.lower() == "cleared":
                shipment.status = "Ready for Delivery"
                operations_dept = Department.objects.filter(name__iexact="Operations").first()
                if operations_dept:
                    shipment.department = operations_dept
                

        # ------Only Managers & Admins----
        if is_manager or is_admin:
            agent_id = request.POST.get("assigned_agent")
            if agent_id:
                shipment.assigned_agent_id = agent_id
            else:
                shipment.assigned_agent = None

        shipment.save()
        ShipmentHistory.objects.create(
            shipment=shipment,
            status=shipment.status,
            department=shipment.department,
            assigned_agent=shipment.assigned_agent,
            changed_by=request.user,
            note="Bulk update action"
        )
        messages.success(request, "Shipment updated successfully!")
        return redirect("shipment_list")

     # ------Get Filter---
    if is_admin:
        shipments = Shipment.objects.all()
    elif is_manager:
        shipments = Shipment.objects.filter(department=user.department)
    else:
        shipments = Shipment.objects.filter(assigned_agent=user)

    departments = Department.objects.all()
    users = AppUser.objects.all()
    statuses = ['Uploaded', 'In Progress', 'Cleared','Ready for Delivery','Assigned to Driver','Out for Delivery']

    return render(request, "shipments/shipment_list.html", {
        "shipments": shipments,
        "departments": departments,
        "users": users,
        "statuses": statuses,
        "is_manager": is_manager,
        "is_admin": is_admin,
        "can_optimize": can_optimize,
    })

# -------------------------------------------shipment details ------------------------------------------------------------------------------
def shipment_details(request, pk):
    shipment = get_object_or_404(Shipment, pk=pk)

    history = shipment.history.select_related(
        "department",
        "assigned_agent",
        "changed_by"
    ).order_by("-timestamp")
    return render(request, "shipments/shipment_details.html", {
        "shipment": shipment,
        "history": history
    })
# -------------------------------------------Login/logout of Users------------------------------------------------------------------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect('shipment_list')  

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome, {user.first_name}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password")

    return render(request, "shipments/login.html")
    

@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully")
    return redirect("login_view")


# -------------------------------------------SCHEDULE DRIVER ------------------------------------------------------------------------------

@login_required
def driver_schedule_view(request):

    today = date.today()

    # 1. GET ALL DRIVERS
    drivers = AppUser.objects.filter(groups__name="Driver")

    # 2. AUTO CREATE SCHEDULE IF NOT EXISTS
    for d in drivers:
        Driver_info.objects.get_or_create(
            driver=d,
            date=today,
            defaults={
                "start_time": time(9, 0),
                "end_time": time(16, 0),
                "is_available": True,
                "max_stops": 25
            }
        )


    schedules = Driver_info.objects.filter(date=today)


    if request.method == "POST":

        schedule_id = request.POST.get("id")

        schedule = get_object_or_404(Driver_info, id=schedule_id)

        schedule.start_time = datetime.strptime(
            request.POST.get("start_time"), "%H:%M"
        ).time()

        schedule.end_time = datetime.strptime(
            request.POST.get("end_time"), "%H:%M"
        ).time()

        schedule.max_stops = int(request.POST.get("max_stops", 25))

        schedule.is_available = request.POST.get("is_available") == "on"

        schedule.save()

        return redirect("driver_schedule")

    return render(request, "shipments/schedules.html", {
        "schedules": schedules
    })
#  -------------------------------------------Routes Pages  ------------------------------------------------------------------------------
@login_required
def routes_page(request):

    drivers = AppUser.objects.filter(groups__name="Driver")

    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c"]

    routes_data = []

    for i, d in enumerate(drivers):

        shipments = Shipment.objects.filter(
            assigned_agent=d,
            latitude__isnull=False,
            longitude__isnull=False
        )

        routes_data.append({
            "driver_name": d.get_full_name() or d.username,
            "count": shipments.count(),
            "color": colors[i % len(colors)],

            "route": [
                {
                    "lat": s.latitude,
                    "lng": s.longitude,
                    "tracking_number": s.tracking_number,
                    "recipient_name": s.recipient_name,
                    "address": s.recipient_address,
                    "label": f"{s.tracking_number} - {s.recipient_name}"
                }
                for s in shipments
            ]
        })

    return render(request, "shipments/routes.html", {
        "routes_data_json": routes_data 
})
# -------------------------------------------Bulk Action ------------------------------------------------------------------------------

def bulk_action(request):

    if request.method == "POST":

        action = request.POST.get("action")
        selected_ids = request.POST.getlist("selected_shipments")

        new_dept = request.POST.get("bulk_department")
        new_status = request.POST.get("bulk_status")
        bulk_user = request.POST.get("bulk_user")

        print("ACTION:", action)
        print("IDS:", selected_ids)

        # ---------------- NO SELECTION ----------------
        if not selected_ids:
            messages.warning(request, "No shipments selected.")
            return redirect("shipment_list")

        qs = Shipment.objects.filter(id__in=selected_ids)

        # ================= REASSIGN =================
        if action == "reassign":

            update_data = {}

            # department
            if new_dept:
                update_data["department_id"] = new_dept
                update_data["assigned_agent"] = None

            # status
            if new_status:

                if new_status.lower() == "cleared":

                    update_data["status"] = "Ready for Delivery"

                    operations_dept = Department.objects.filter(
                        name__iexact="Operations"
                    ).first()

                    if operations_dept:
                        update_data["department_id"] = operations_dept.id
                    update_data["assigned_agent"] = None
                else:
                    update_data["status"] = new_status

            # user
            if bulk_user:
                update_data["assigned_agent_id"] = bulk_user

            if update_data:
                updated_count = qs.update(**update_data)

                messages.success(
                    request,
                    f"{updated_count} shipment(s) updated successfully."
                )
            else:
                messages.warning(
                    request,
                    "No changes selected."
                )

            return redirect("shipment_list")

        # ================= OPTIMIZE =================

        # elif action == "optimize":

        #     qs = qs.filter(status__iexact="Ready For Delivery")
        #     drivers = list(AppUser.objects.filter(
        #         groups__name="Driver",
        #         is_active=True
        #     ))

        #     if not qs.exists():
        #         messages.warning(request, "No eligible shipments for optimisation.")
        #         return redirect("shipment_list")

        #     routes = optimize(qs, drivers)

        elif action == "optimize":

    # =====================================================
    # GET SHIPMENTS
    # =====================================================
            qs = qs.filter(
                status__iexact="Ready For Delivery"
            )

            if not qs.exists():

                messages.warning(
                    request,
                    "No eligible shipments for optimisation."
                )

                return redirect("shipment_list")

            # =====================================================
            # GET AVAILABLE DRIVERS
            # =====================================================

            drivers = list(

                AppUser.objects.filter(
                    groups__name="Driver",
                    is_active=True
                )

            )

            if not drivers:

                messages.warning(
                    request,
                    "No drivers available."
                )

                return redirect("shipment_list")

            # =====================================================
            # GET DRIVER SCHEDULES
            # =====================================================

            today = date.today()

            driver_infos = Driver_info.objects.filter(
                date=today,
                driver__in=drivers,
                is_available=True
            ).select_related("driver")

            driver_map = {
                d.driver_id: d
                for d in driver_infos
            }

            # =====================================================
            # DRIVER LIMITS + CAPACITY
            # =====================================================

            driver_time_limits = []

            driver_capacity = []

            active_drivers = []

            for driver in drivers:

                info = driver_map.get(driver.id)

                # SKIP DRIVER WITHOUT SCHEDULE
                if not info:
                    continue

                # -----------------------------
                # SHIFT START/END
                # -----------------------------

                start_dt = datetime.combine(
                    today,
                    info.start_time
                )

                end_dt = datetime.combine(
                    today,
                    info.end_time
                )

                # NIGHT SHIFT SUPPORT
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)

                shift_seconds = int(
                    (end_dt - start_dt).total_seconds()
                )

                # -----------------------------
                # STORE DRIVER DATA
                # -----------------------------

                active_drivers.append(driver)

                driver_time_limits.append(
                    shift_seconds
                )

                driver_capacity.append(
                    info.max_stops or 999
                )

            # =====================================================
            # VALIDATION
            # =====================================================

            if not active_drivers:

                messages.warning(
                    request,
                    "No scheduled drivers available."
                )

                return redirect("shipment_list")

            # =====================================================
            # RUN GOOGLE OPTIMIZER
            # =====================================================

            MAX_OPTIMIZE = 9

            MAX_PER_RUN = 50

            qs = qs.order_by("id")[:MAX_PER_RUN]

            routes = optimize(
                qs,
                active_drivers,
                driver_time_limits,
                driver_capacity
            )

            # =====================================================
            # NO ROUTES
            # =====================================================

            if not routes:

                messages.warning(
                    request,
                    "No optimized routes generated."
                )

                return redirect("shipment_list")

            # =====================================================
            # ASSIGN SHIPMENTS
            # =====================================================

            updated_shipments = []

            history_logs =[]

            for driver_index, route_data in routes.items():

                # SAFETY CHECK
                if driver_index >= len(active_drivers):
                    continue

                driver = active_drivers[driver_index]

                shipment_list = route_data.get(
                    "shipments",
                    []
                )

                for shipment in shipment_list:

                    if not shipment:
                        continue

                    shipment.assigned_agent = driver

                    shipment.status = "Assigned to Driver"

                    updated_shipments.append(
                        shipment
                    )
                    history_logs.append(
                        ShipmentHistory(
                            shipment=shipment,
                            status=shipment.status,
                            department=shipment.department,
                            assigned_agent=driver,
                            changed_by=request.user,
                            note="Auto-optimized route assignment"
                        )
                )
            # =====================================================
            # BULK UPDATE
            # =====================================================

            if updated_shipments:

                Shipment.objects.bulk_update(
                    updated_shipments,
                    [
                        "assigned_agent",
                        "status"
                    ]
                )

            # =====================================================
            # SUCCESS MESSAGE
            # =====================================================

            total_routes = len(routes)

            total_shipments = len(updated_shipments)

            messages.success(

                request,

                f"{total_shipments} shipment(s) "
                f"optimized across "
                f"{total_routes} driver(s)."

            )

            # =====================================================
            # REDIRECT TO MAP
            # =====================================================

            return redirect("routes_diplay")