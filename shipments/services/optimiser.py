import googlemaps
import numpy as np
import json
from django.contrib.auth.decorators import permission_required,login_required
from django.shortcuts import render, redirect , get_object_or_404
from django.contrib import messages
from ..models import Shipment, Driver_info
import googlemaps
import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from django.conf import settings
from datetime import datetime,date,timedelta

WAREHOUSE_OPS = (settings.WAREHOUSE_LAT, settings.WAREHOUSE_LON)


# ----------------------------
# GOOGLE MATRIX (TIME)
# ----------------------------
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


# # ----------------------------
# # MAIN VRP OPTIMIZER
# # ----------------------------

# def depot_distance(coord):
#     depot_lat, depot_lon = WAREHOUSE_OPS
#     lat, lon = coord
#     return (lat - depot_lat) ** 2 + (lon - depot_lon) ** 2

# def euclidean_distance(a, b):
#     return (
#         (a[0] - b[0]) ** 2 +
#         (a[1] - b[1]) ** 2
#     )


# def reorder_route_nearest_neighbor(depot, shipments):

#     remaining = shipments[:]
#     ordered = []

#     current = depot

#     while remaining:

#         next_stop = min(
#             remaining,
#             key=lambda s: euclidean_distance(
#                 current,
#                 (s.latitude, s.longitude)
#             )
#         )

#         ordered.append(next_stop)

#         current = (
#             next_stop.latitude,
#             next_stop.longitude
#         )

#         remaining.remove(next_stop)

#     return ordered

# def optimize(shipments, drivers, driver_time_limits, driver_capacity):

#     gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_KEY)

#     shipment_list = [
#         s for s in shipments if s.latitude and s.longitude
#     ]

#     if not shipment_list or not drivers:
#         return {}
#     shipment_list.sort(key=lambda s: depot_distance((s.latitude, s.longitude)))

#     # ----------------------------
#     # NODES (DEPOT + STOPS)
#     # ----------------------------
#     coords = [WAREHOUSE_OPS] + [
#         (s.latitude, s.longitude) for s in shipment_list
#     ]

#     n = len(coords)
#     num_vehicles = len(drivers)
#     depot = 0

#     # ----------------------------
#     # MATRIX
#     # ----------------------------
#     time_matrix = build_time_matrix(gmaps, coords)

#     # ----------------------------
#     # OR-TOOLS MODEL
#     # ----------------------------
#     manager = pywrapcp.RoutingIndexManager(
#         n,
#         num_vehicles,
#         depot
#     )

#     routing = pywrapcp.RoutingModel(manager)

#     # ----------------------------
#     # COST FUNCTION
#     # ----------------------------
#     def time_callback(from_index, to_index):
#         from_node = manager.IndexToNode(from_index)
#         to_node = manager.IndexToNode(to_index)
#         return time_matrix[from_node][to_node]

#     transit_callback_index = routing.RegisterTransitCallback(time_callback)
#     routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

#     # ----------------------------
#     # CAPACITY (MAX STOPS)
#     # ----------------------------
#     def demand_callback(from_index):
#         node = manager.IndexToNode(from_index)
#         return 0 if node == 0 else 1

#     demand_index = routing.RegisterUnaryTransitCallback(demand_callback)

#     routing.AddDimensionWithVehicleCapacity(
#         demand_index,
#         0,
#         driver_capacity,
#         True,
#         "Capacity"
#     )

#     # ----------------------------
#     # TIME WINDOWS (SHIFT LIMITS)
#     # ----------------------------
#     def time_callback_dim(from_index, to_index):
#         from_node = manager.IndexToNode(from_index)
#         to_node = manager.IndexToNode(to_index)
#         return time_matrix[from_node][to_node]

#     time_index = routing.RegisterTransitCallback(time_callback_dim)

#     routing.AddDimension(
#         time_index,
#         30 * 60,  # waiting slack (30 min)
#         max(driver_time_limits),
#         False,
#         "Time"
#     )

#     time_dimension = routing.GetDimensionOrDie("Time")

#     # depot time window
#     for v in range(num_vehicles):
#         start = routing.Start(v)
#         time_dimension.CumulVar(start).SetRange(0, max(driver_time_limits))

#     # ----------------------------
#     # SEARCH PARAMETERS
#     # ----------------------------
#     params = pywrapcp.DefaultRoutingSearchParameters()
#     params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
#     params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
#     params.time_limit.FromSeconds(30)

#     solution = routing.SolveWithParameters(params)

#     if not solution:
#         return {}

#     # ----------------------------
#     # BUILD RESULT
#     # ----------------------------
#     routes = {}

#     for v in range(num_vehicles):

#         index = routing.Start(v)
#         route_shipments = []

#         while not routing.IsEnd(index):

#             node = manager.IndexToNode(index)

#             if node != 0:
#                 route_shipments.append(shipment_list[node - 1])

#             index = solution.Value(routing.NextVar(index))
#         route_shipments = reorder_route_nearest_neighbor(
#             WAREHOUSE_OPS,
#             route_shipments
#         )
#         # build polyline
#         route_coords = [WAREHOUSE_OPS]
#         for s in route_shipments:
#             route_coords.append((s.latitude, s.longitude))
#         route_coords.append(WAREHOUSE_OPS)

#         poly = None
#         if len(route_coords) > 2:
#             poly = gmaps.directions(
#                 origin=route_coords[0],
#                 destination=route_coords[-1],
#                 waypoints=route_coords[1:-1],
#                 mode="driving"
#             )[0]["overview_polyline"]["points"]

#         routes[v] = {
#             "shipments": route_shipments,
#             "polyline": poly
#         }

#     return routes
from sklearn.cluster import KMeans
import numpy as np

def cluster_shipments(shipments, num_drivers):
    coords = np.array([
        [s.latitude, s.longitude] for s in shipments
    ])

    kmeans = KMeans(n_clusters=num_drivers, random_state=42, n_init=10)
    labels = kmeans.fit_predict(coords)

    clusters = {i: [] for i in range(num_drivers)}

    for shipment, label in zip(shipments, labels):
        clusters[label].append(shipment)

    return clusters

def optimize(shipments, drivers, driver_time_limits, driver_capacity):

    gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_KEY)

    shipment_list = [
        s for s in shipments if s.latitude and s.longitude
    ]

    if not shipment_list or not drivers:
        return {}

    clusters = cluster_shipments(shipment_list, len(drivers))

    routes = {}

    for v, driver in enumerate(drivers):

        cluster_shipments_list = clusters[v]

        if not cluster_shipments_list:
            continue

        coords = [WAREHOUSE_OPS] + [
            (s.latitude, s.longitude) for s in cluster_shipments_list
        ]

        time_matrix = build_time_matrix(gmaps, coords)

        manager = pywrapcp.RoutingIndexManager(len(coords), 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def time_cb(from_index, to_index):
            return time_matrix[
                manager.IndexToNode(from_index)
            ][manager.IndexToNode(to_index)]

        transit_index = routing.RegisterTransitCallback(time_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

        routing.AddDimension(
            transit_index,
            30 * 60,
            driver_time_limits[v],
            False,
            "Time"
        )

        # capacity
        def demand_cb(from_index):
            return 0 if manager.IndexToNode(from_index) == 0 else 1

        demand_index = routing.RegisterUnaryTransitCallback(demand_cb)

        routing.AddDimensionWithVehicleCapacity(
            demand_index,
            0,
            [driver_capacity[v]],
            True,
            "Capacity"
        )

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.FromSeconds(10)

        solution = routing.SolveWithParameters(params)

        if not solution:
            continue

        # build route in solver order ONLY
        index = routing.Start(0)
        route_shipments = []

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:
                route_shipments.append(cluster_shipments_list[node - 1])
            index = solution.Value(routing.NextVar(index))

        # IMPORTANT: NO nearest neighbor reorder

        route_coords = [WAREHOUSE_OPS] + [
            (s.latitude, s.longitude) for s in route_shipments
        ] + [WAREHOUSE_OPS]

        poly = gmaps.directions(
            origin=route_coords[0],
            destination=route_coords[-1],
            waypoints=route_coords[1:-1],
            mode="driving"
        )[0]["overview_polyline"]["points"]

        routes[v] = {
            "shipments": route_shipments,
            "polyline": poly
        }

    return routes




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

#DRIVER SCHEDULES NOW INCLUDES THE STATUS OF ACTIVE USER ONLY 
    driver_infos = Driver_info.objects.filter(
        date=date.today(),
        is_available=True,
        driver__is_active=True,
        driver__groups__name="Driver"
    ).select_related("driver")

    if not driver_infos.exists():
        messages.warning(request, "No drivers available today.")
        return redirect("shipment_list")

    drivers = [info.driver for info in driver_infos]

#CLACULATING THE DRIVER LIMITS
    today = date.today()

    # driver_limits = []

    # for info in driver_infos:

    #     start_dt = datetime.combine(today, info.start_time)
    #     end_dt = datetime.combine(today, info.end_time)

    #     if end_dt < start_dt:
    #         end_dt += timedelta(days=1)

    #     shift_seconds = int((end_dt - start_dt).total_seconds())
    #     driver_limits.append(
    #     int((end_dt - start_dt).total_seconds())
    # )
    driver_time_limits = []
    driver_capacity = []

    for info in driver_infos:

        # SHIFT TIME (seconds)
        start_dt = datetime.combine(today, info.start_time)
        end_dt = datetime.combine(today, info.end_time)

        if end_dt < start_dt:
            end_dt += timedelta(days=1)

        driver_time_limits.append(
            int((end_dt - start_dt).total_seconds())
        )

        # MAX STOPS (CAPACITY)
        driver_capacity.append(info.max_stops)

#RUNNING THE OPTIMISER WITH ALL THE INFORMATION - DRIVERS AND DRIVERS LIMITS 
    routes = optimize(
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

        for shipment in shipment_list:
            shipment.assigned_agent = driver
            shipment.status = "Assigned to Driver"
            updated_shipments.append(shipment)

    if updated_shipments:
        Shipment.objects.bulk_update(
            updated_shipments,
            ["assigned_agent", "status"]
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

        shipment_list = route_data.get("shipments", [])
        duration = route_data.get("duration", 0)

        routes_data.append({

            # DRIVER INFO
            "driver_name": driver.get_full_name() or driver.username,
            "driver_id": driver.id,

            # SCHEDULE
            "start_time": schedule.start_time.strftime("%H:%M"),
            "end_time": schedule.end_time.strftime("%H:%M"),
            "departure_time": schedule.start_time.strftime("%H:%M"),

            # ROUTE INFO
            "max_stops": schedule.max_stops,
            "duration_minutes": round(duration / 60, 1),
            "count": len(shipment_list),

            # MAP COLOR
            "color": colors[driver_index % len(colors)],
            "polyline": route_data.get("polyline"),
            # DELIVERY STOPS
            "route": [
                {
                    # STOP ORDER
                    "sequence": idx + 1,

                    # LOCATION
                    "lat": s.latitude,
                    "lng": s.longitude,

                    # DELIVERY INFO
                    "tracking_number": s.tracking_number,
                    "recipient": s.recipient_name,
                    "address": s.address,

                    # ETA ESTIMATION
                    "eta": (
                        datetime.combine(date.today(), schedule.start_time)
                        + timedelta(minutes=(idx * 15))
                    ).strftime("%H:%M"),

                    # LABEL
                    "label":
                        f"{s.tracking_number} - "
                        f"{s.recipient_name}",

                    # COLOR
                    "color":
                        colors[driver_index % len(colors)],
                }

                for idx, s in enumerate(shipment_list)

                if s.latitude and s.longitude
            ]
        })
    routes_data_json = json.dumps(routes_data, cls=DjangoJSONEncoder)
    messages.success(
        request,
        f"{len(updated_shipments)} shipment(s) assigned across {len(routes_data)} driver(s)."
    )
    print("POLYLINE SAMPLE:", routes_data[0].get("polyline"))
    return render(
        request,
        "shipments/routes.html",
        {
            "routes_data": routes_data,
            "routes_data_json": routes_data_json,
            "drivers": drivers,
        }
    )