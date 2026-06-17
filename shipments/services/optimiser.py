import googlemaps
import json
from django.contrib.auth.decorators import permission_required, login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from ..models import Shipment, Driver_info
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from django.conf import settings
from datetime import datetime, date, timedelta
from django.core.serializers.json import DjangoJSONEncoder

# FedEx Warehouse location - using the settings.py inserted lat/lon 
WAREHOUSE_OPS = (settings.WAREHOUSE_LAT, settings.WAREHOUSE_LON)


def build_time_matrix(gmaps, coords):
    size = len(coords)
    matrix = [[0] * size for _ in range(size)]
    CHUNK = 10

    for i in range(0, size, CHUNK):
        for j in range(0, size, CHUNK):

            result = gmaps.distance_matrix(
                origins=coords[i:i + CHUNK],
                destinations=coords[j:j + CHUNK],
                mode="driving"
            )

            for r_idx, row in enumerate(result["rows"]):
                for c_idx, element in enumerate(row["elements"]):

                    if element["status"] == "OK":
                        matrix[i + r_idx][j + c_idx] = element["duration"]["value"]
                    else:
                        matrix[i + r_idx][j + c_idx] = 999999

    return matrix


DROP_PENALTY = 10_000_000

def optimize(shipments, drivers, driver_time_limits, driver_capacity):

    gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_KEY)

    shipment_list = [
        s for s in shipments if s.latitude and s.longitude
    ]

    if not shipment_list or not drivers:
        return {}, []

    num_vehicles = len(drivers)
    depot = 0

    coords = [WAREHOUSE_OPS] + [
        (s.latitude, s.longitude) for s in shipment_list
    ]

    n = len(coords)

    time_matrix = build_time_matrix(gmaps, coords)

    manager = pywrapcp.RoutingIndexManager(
        n,
        num_vehicles,
        depot
    )

    routing = pywrapcp.RoutingModel(manager)


    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return time_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)


    def demand_callback(from_index):
        node = manager.IndexToNode(from_index)
        return 0 if node == 0 else 1

    demand_index = routing.RegisterUnaryTransitCallback(demand_callback)

    routing.AddDimensionWithVehicleCapacity(
        demand_index,
        0,
        driver_capacity,   # one max_stops value per driver, in driver order
        True,
        "Capacity"
    )


    routing.AddDimension(
        transit_callback_index,
        30 * 60,                   # waiting slack (30 min)
        max(driver_time_limits),   # generous upper bound; real cap set per-vehicle below
        False,
        "Time"
    )

    time_dimension = routing.GetDimensionOrDie("Time")


    for v in range(num_vehicles):
        end_index = routing.End(v)
        time_dimension.CumulVar(end_index).SetMax(driver_time_limits[v])
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(end_index))


    for node in range(1, n):
        index = manager.NodeToIndex(node)
        routing.AddDisjunction([index], DROP_PENALTY)


    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.LOCAL_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(30)

    solution = routing.SolveWithParameters(params)

    if not solution:
        return {}, []

    dropped_shipments = []
    for node in range(1, n):
        index = manager.NodeToIndex(node)
        if solution.Value(routing.NextVar(index)) == index:
            # a node that routes to itself was dropped by AddDisjunction
            dropped_shipments.append(shipment_list[node - 1])

    routes = {}

    for v in range(num_vehicles):

        index = routing.Start(v)
        route_shipments = []
        route_arrivals = []
        # while not routing.IsEnd(index):

        #     node = manager.IndexToNode(index)

        #     if node != 0:
        #         route_shipments.append(shipment_list[node - 1])

        #     index = solution.Value(routing.NextVar(index))
        while not routing.IsEnd(index):

            node = manager.IndexToNode(index)

            arrival_seconds = solution.Value(
                time_dimension.CumulVar(index)
            )

            if node != 0:

                shipment = shipment_list[node - 1]

                route_shipments.append(shipment)

                route_arrivals.append(arrival_seconds)

            index = solution.Value(routing.NextVar(index))

        if not route_shipments:
            continue

        end_index = routing.End(v)
        duration_seconds = solution.Value(time_dimension.CumulVar(end_index))

        route_coords = [WAREHOUSE_OPS]
        for s in route_shipments:
            route_coords.append((s.latitude, s.longitude))
        route_coords.append(WAREHOUSE_OPS)

        poly = None
        if len(route_coords) > 2:
            print(route_coords)
            poly = gmaps.directions(
                origin=route_coords[0],
                destination=route_coords[-1],
                waypoints=route_coords[1:-1],
                optimize_waypoints=False,
                mode="driving"
            )[0]["overview_polyline"]["points"]
        print("\nDriver", v)

        for i, s in enumerate(route_shipments, 1):
            print(
                i,
                s.tracking_number,
                s.recipient_address
            )
        routes[v] = {
            "shipments": route_shipments,
            "arrivals": route_arrivals,
            "polyline": poly,
            "duration": duration_seconds,
        }

    return routes, dropped_shipments


def run_optimizer(request):

    shipments = Shipment.objects.filter(
        status__in=[
            "Ready For Delivery",
            "Assigned to Driver"
        ]
    )

    if not shipments.exists():
        messages.warning(request, "No shipments available for processing.")
        return redirect("shipment_list")

#-------------------including available drivers---------------- 
    driver_infos = Driver_info.objects.filter(
        date=date.today(),
        is_available=True,
        driver__is_active=True,
        driver__groups__name="Driver"
    ).select_related("driver")

    if not driver_infos.exists():
        messages.warning(request, "No drivers available today.")
        return redirect("shipment_list")

    driver_infos = list(driver_infos)
    drivers = [info.driver for info in driver_infos]

    today = date.today()
    driver_time_limits = []
    driver_capacity = []

    for info in driver_infos:
        start_dt = datetime.combine(today, info.start_time)
        end_dt = datetime.combine(today, info.end_time)

        if end_dt < start_dt:
            end_dt += timedelta(days=1)

        driver_time_limits.append(
            int((end_dt - start_dt).total_seconds())
        )
        driver_capacity.append(info.max_stops)

# running the optimiser - now returns (routes, dropped_shipments)
    routes, dropped_shipments = optimize(
        shipments=shipments,
        drivers=drivers,
        driver_time_limits=driver_time_limits,
        driver_capacity=driver_capacity
    )

    if not routes:
        messages.warning(request, "No optimized routes could be generated.")
        return redirect("shipment_list")


    updated_shipments = []

    for driver_index, route_data in routes.items():

        if (
            not isinstance(driver_index, int)
            or driver_index < 0
            or driver_index >= len(drivers)
        ):
            continue

        driver = drivers[driver_index]

        shipment_list = route_data.get("shipments", [])

        for seq, shipment in enumerate(shipment_list, start=1):
            shipment.assigned_agent = driver
            shipment.status = "Assigned to Driver"
            shipment.delivery_sequence = seq
            updated_shipments.append(shipment)

    if updated_shipments:
        Shipment.objects.bulk_update(
            updated_shipments,
            ["assigned_agent", "status", "delivery_sequence"]
        )

    colors = [
        "#e74c3c",
        "#3498db",
        "#2ecc71",
        "#f39c12",
        "#9b59b6",
        "#1abc9c",
        "#34495e",
        "#d35400",
    ]

    routes_data = []

    for driver_index, route_data in routes.items():

        if (
            not isinstance(driver_index, int)
            or driver_index < 0
            or driver_index >= len(drivers)
        ):
            continue

        driver = drivers[driver_index]
        schedule = driver_infos[driver_index]

        shipment_list = sorted(
            route_data.get("shipments", []),
            key=lambda s: getattr(s, "delivery_sequence", 0)
        )
        arrivals = route_data.get("arrivals", [])
        duration = route_data.get("duration", 0)  # now actually populated by optimize()
        print("ARRIVALS:", arrivals)
        routes_data.append({

            # ---------------DRIVER INFO
            "driver_name": driver.get_full_name() or driver.username,
            "driver_id": driver.id,

            #----------------- SCHEDULE
            "start_time": schedule.start_time.strftime("%H:%M"),
            "end_time": schedule.end_time.strftime("%H:%M"),
            "departure_time": schedule.start_time.strftime("%H:%M"),

            # -----------------ROUTE INFO
            "max_stops": schedule.max_stops,
            "duration_minutes": round(duration / 60, 1),
            "count": len(shipment_list),

            # -----------------MAP COLOR
            "color": colors[driver_index % len(colors)],
            "polyline": route_data.get("polyline"),
            # --------------DELIVERY STOPS
            "route": [
                {
                    "sequence": idx + 1,
                    "lat": s.latitude,
                    "lng": s.longitude,
                    "tracking_number": s.tracking_number,
                    "recipient": s.recipient_name,
                    "address": s.recipient_address,
                    "eta": (
                        datetime.combine(date.today(), schedule.start_time)
                        + timedelta(seconds=arrivals[idx])
                    ).strftime("%H:%M")
                    if idx < len(arrivals) else "",
                    "label":
                        f"{s.tracking_number} - "
                        f"{s.recipient_name}",
                    "color":
                        colors[driver_index % len(colors)],
                }

                for idx, s in enumerate(shipment_list)

                if s.latitude and s.longitude
            ]
        })
    routes_data_json = json.dumps(routes_data, cls=DjangoJSONEncoder)

    success_msg = f"{len(updated_shipments)} shipment(s) assigned across {len(routes_data)} driver(s)."

    if dropped_shipments:
        success_msg += (
            f" {len(dropped_shipments)} shipment(s) could not be scheduled today "
            f"(over total capacity, or no driver shift could reach them): "
            + ", ".join(s.tracking_number for s in dropped_shipments)
        )
        messages.warning(request, success_msg)
    else:
        messages.success(request, success_msg)

    return render(
        request,
        "shipments/routes.html",
        {
            "routes_data": routes_data,
            "routes_data_json": routes_data_json,
            "drivers": drivers,
        }
    )