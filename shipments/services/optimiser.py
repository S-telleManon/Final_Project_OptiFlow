import openrouteservice
from django.conf import settings
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from django.shortcuts import render, redirect , get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import permission_required,login_required
from ..models import Shipment,AppUser, Department, Driver_info
from datetime import datetime,date,time
from ..forms import AppUserForm
from django.contrib.auth.models import Group
from shipments.forms import ShipmentForm
from django.db.models import Count
import json
from django.core.serializers.json import DjangoJSONEncoder


delivery_duration = 7 

WAREHOUSE_OPS = (settings.WAREHOUSE_LON, settings.WAREHOUSE_LAT)


# def optimize(shipments, drivers):

#     client = openrouteservice.Client(key="eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjlhYmQ4NDVmYjA5MzQ3YTI4ZDMzOGFiOGQyYjM3YzU5IiwiaCI6Im11cm11cjY0In0=")

#     coords = [WAREHOUSE_OPS ]
#     shipment_list = []

#     for s in shipments:
#         coords.append((s.longitude, s.latitude))
#         shipment_list.append(s)

#     matrix = client.distance_matrix(
#         locations=coords,
#         profile="driving-car",
#         metrics=["duration"]
#     )["durations"]

#     manager = pywrapcp.RoutingIndexManager(len(matrix), len(drivers), 0)
#     routing = pywrapcp.RoutingModel(manager)

#     def cost(i, j):
#         a = manager.IndexToNode(i)
#         b = manager.IndexToNode(j)

#         time = matrix[a][b]

#         if a != 0:
#             time += delivery_duration * 60

#         return int(time)

#     cb = routing.RegisterTransitCallback(cost)
#     routing.SetArcCostEvaluatorOfAllVehicles(cb)

#     routing.AddDimension(
#         cb,
#         30 * 60,
#         8 * 60 * 60,
#         True,
#         "time"
#     )

#     params = pywrapcp.DefaultRoutingSearchParameters()
#     params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

#     solution = routing.SolveWithParameters(params)

#     routes = {}

#     for v in range(len(drivers)):
#         index = routing.Start(v)
#         route = []

#         while not routing.IsEnd(index):
#             node = manager.IndexToNode(index)

#             if node != 0:
#                 route.append(shipment_list[node - 1])

#             index = solution.Value(routing.NextVar(index))

#         routes[v] = route

#     return routes

def optimize(shipments, drivers):

    client = openrouteservice.Client(key="eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjlhYmQ4NDVmYjA5MzQ3YTI4ZDMzOGFiOGQyYjM3YzU5IiwiaCI6Im11cm11cjY0In0=")

    coords = [WAREHOUSE_OPS]  # (lon, lat)
    shipment_list = []


    for s in shipments:
        if s.latitude and s.longitude:
            coords.append((s.longitude, s.latitude))
            shipment_list.append(s)


    matrix = client.distance_matrix(
        locations=coords,
        profile="driving-car",
        metrics=["duration"]
    )["durations"]

 
    manager = pywrapcp.RoutingIndexManager(len(matrix), len(drivers), 0)
    routing = pywrapcp.RoutingModel(manager)

    delivery_duration = 7  # minutes per stop

    def cost(i, j):
        a = manager.IndexToNode(i)
        b = manager.IndexToNode(j)

        time = matrix[a][b]

        if time is None:
            time = 999999  # fallback penalty

        if a != 0:
            time += delivery_duration * 60

        return int(time)

    callback = routing.RegisterTransitCallback(cost)
    routing.SetArcCostEvaluatorOfAllVehicles(callback)

    routing.AddDimension(
        callback,
        30 * 60,      # waiting time
        8 * 60 * 60,  # max shift
        True,
        "time"
    )


    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC

    solution = routing.SolveWithParameters(params)

    if not solution:
        return {}


    routes = {}

    for v in range(len(drivers)):
        index = routing.Start(v)
        route = []

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)

            if node != 0 and node - 1 < len(shipment_list):
                route.append(shipment_list[node - 1])

            index = solution.Value(routing.NextVar(index))

        routes[v] = route

    return routes

# def run_optimizer(request):
#     shipments = Shipment.objects.all()
#     drivers = AppUser.objects.filter(groups__name="Driver")

#     routes = optimize(shipments, drivers)

#     return render(request, "shipments/routes.html", {"routes": routes})


def run_optimizer(request):

    shipments = Shipment.objects.filter(
        status__in=["Ready For Delivery", "Assigned to Driver"]
    )

    drivers = list(AppUser.objects.filter(
        groups__name="Driver",
        is_active=True
    ))

    if not shipments.exists():
        messages.warning(request, "No shipments available for processing.")
        return redirect("shipment_list")

    if not drivers:
        messages.warning(request, "No drivers available.")
        return redirect("shipment_list")

    routes = optimize(shipments, drivers)

    # ============================
    # ASSIGN DRIVERS + STATUS
    # ============================
    updated_shipments = []

    for driver_index, shipment_list in routes.items():

        driver = driver_index 

        if driver_index < 0 or driver_index >= len(drivers):
            continue

        driver = drivers[driver_index]

        for shipment in shipment_list:

            shipment.assigned_agent = driver
            shipment.status = "Assigned to Driver"   # ✅ REQUIRED CHANGE

            updated_shipments.append(shipment)

    # BULK SAVE (fast + clean)
    if updated_shipments:
        Shipment.objects.bulk_update(
            updated_shipments,
            ["assigned_agent", "status"]
        )

    # ============================
    # MAP DATA
    # ============================
    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c"]

    routes_data = []

    for driver_index, shipment_list in routes.items():

        if not isinstance(driver_index, int):
            continue

        if driver_index < 0 or driver_index >= len(drivers):
            continue

        driver = drivers[driver_index]

        routes_data.append({
            "driver_name": driver.get_full_name() or driver.username,
            "color": colors[driver_index % len(colors)],
            "count": len(shipment_list),
            "route": [
                {
                    "lat": s.latitude,
                    "lng": s.longitude,
                    "label": f"{s.tracking_number} - {s.recipient_name}"
                }
                for s in shipment_list
                if s.latitude and s.longitude
            ]
        })

    # ============================
    # SUCCESS MESSAGE
    # ============================
    messages.success(
        request,
        f"{len(updated_shipments)} shipment(s) assigned to drivers successfully."
    )

    return render(request, "shipments/routes.html", {
        "routes_data": routes_data,
        "drivers": drivers
    })