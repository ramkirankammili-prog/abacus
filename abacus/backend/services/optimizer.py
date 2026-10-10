from datetime import datetime
from services.routing import travel_km, distance_matrix, OSRM_METHOD
from services.shelf_life import shelf_life_risk

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    ORTOOLS_AVAILABLE = True
except Exception:
    ORTOOLS_AVAILABLE = False

def _minutes(value: str, default: int = 8*60) -> int:
    try:
        h, m = value.split(":")
        return int(h)*60 + int(m)
    except Exception:
        return default

def optimize(data: dict) -> dict:
    depots = [d for d in data["depots"] if d.get("status", "Active") == "Active"]
    orders = [o for o in data["orders"] if o.get("status", "Pending") == "Pending"]
    vehicles = [v for v in data["vehicles"] if v.get("status", "Available") == "Available"]
    drivers = [d for d in data.get("drivers", []) if d.get("status", "Available") == "Available"]
    inventory = data["inventory"]
    if not depots or not orders or not vehicles or not drivers:
        missing = []
        if not depots: missing.append("an active depot")
        if not orders: missing.append("a pending order")
        if not vehicles: missing.append("an available vehicle")
        if not drivers: missing.append("an available driver")
        reason = "At least one " + ", ".join(missing) + " is required."
        return {"status":"NO_FEASIBLE_SOLUTION", "message":reason, "routes":[], "unserved_orders":[o["id"] for o in orders], "reasons":[{"order_id":o["id"],"reason":reason} for o in orders], "summary":{"orders":len(orders),"assigned":0,"unserved":len(orders),"distance_km":0,"estimated_cost":0}}
    products = {p["id"]:p for p in inventory}
    invalid = []
    for o in orders:
        p = products.get(o["product_id"])
        if not p:
            invalid.append((o, "Product not found"))
        elif float(p["quantity"]) < float(o["quantity"]):
            invalid.append((o, "Insufficient inventory"))
        elif shelf_life_risk(p)["remaining_days"] is not None and shelf_life_risk(p)["remaining_days"] < 0:
            invalid.append((o, "Product expired"))
    invalid_ids = {o["id"] for o, _ in invalid}
    feasible_orders = [o for o in orders if o["id"] not in invalid_ids]
    if not feasible_orders:
        return {"status":"NO_FEASIBLE_SOLUTION","message":"No orders passed inventory and expiry checks.","routes":[],"unserved_orders":[o["id"] for o in orders],"reasons":[{"order_id":o["id"],"reason":r} for o,r in invalid],"summary":{"orders":len(orders),"assigned":0,"unserved":len(orders),"distance_km":0,"estimated_cost":0}}
    # Assign each order to a compatible depot/vehicle before OR-Tools.
    assignments, pre_unserved = [], []
    planned_loads: dict[tuple[str, str], float] = {}
    for order in feasible_orders:
        p = products[order["product_id"]]
        candidates = []
        for d in depots:
            if d["id"] != p["depot_id"]:
                continue
            for v in vehicles:
                if order.get("assigned_vehicle_id") and v.get("id") != order.get("assigned_vehicle_id"):
                    continue
                temp_ok = (p.get("min_temp") is not None and v.get("refrigerated", False)
                           and float(v.get("min_temp", -99)) <= float(p.get("min_temp", 2))
                           and float(v.get("max_temp", 99)) >= float(p.get("max_temp", 8)))
                route_key = (str(d["id"]), str(v["id"]))
                requested_load = float(order.get("quantity") or 0)
                if not temp_ok or float(v["capacity"]) < requested_load:
                    continue
                # Reserve space while assigning orders, so a collection of individually-valid
                # orders cannot overfill the same vehicle route.
                if planned_loads.get(route_key, 0.0) + requested_load > float(v.get("capacity") or 0):
                    continue
                eligible_drivers = [dr for dr in drivers
                    if (not dr.get("vehicle_id") or dr.get("vehicle_id") == v.get("id"))
                    and (not order.get("assigned_driver_id") or dr.get("id") == order.get("assigned_driver_id"))]
                if not eligible_drivers:
                    continue
                km = travel_km(d, order)
                estimated_cost = km * float(v.get("cost_per_km", 18))
                if order.get("budget") is not None and estimated_cost > float(order["budget"]):
                    continue
                candidates.append((estimated_cost, d, v, km))
        if not candidates:
            if order.get("budget") is not None:
                reason = "No compatible refrigerated vehicle/driver meets the budget, capacity, and temperature requirements."
            else:
                reason = "No compatible active depot, available driver, and refrigerated vehicle satisfy capacity and temperature requirements."
            pre_unserved.append({"order_id":order["id"],"reason":reason})
        else:
            _, d, v, km = min(candidates, key=lambda x:x[0])
            route_key = (str(d["id"]), str(v["id"]))
            planned_loads[route_key] = planned_loads.get(route_key, 0.0) + float(order.get("quantity") or 0)
            assignments.append({"order":order,"depot":d,"vehicle":v,"km":km,"product":p})
    # Group by depot and vehicle, then reserve one suitable, currently unused driver per route.
    groups = {}
    for a in assignments:
        groups.setdefault((a["depot"]["id"], a["vehicle"]["id"]), []).append(a)
    routes, assigned_ids = [], set()
    methods_used = set()
    used_driver_ids = set()
    for (depot_id, vehicle_id), group in groups.items():
        depot, vehicle = group[0]["depot"], group[0]["vehicle"]
        requested_drivers = {a["order"].get("assigned_driver_id") for a in group if a["order"].get("assigned_driver_id")}
        if len(requested_drivers) > 1:
            pre_unserved.extend({"order_id":a["order"]["id"],"reason":"Orders grouped on one vehicle have conflicting assigned drivers; use one driver per route."} for a in group)
            continue
        requested_driver = next(iter(requested_drivers), None)
        driver = next((dr for dr in drivers if dr.get("id") not in used_driver_ids
            and (not dr.get("vehicle_id") or dr.get("vehicle_id") == vehicle_id)
            and (not requested_driver or dr.get("id") == requested_driver)), None)
        if not driver:
            pre_unserved.extend({"order_id":a["order"]["id"],"reason":"No unused available driver is compatible with this vehicle."} for a in group)
            continue
        used_driver_ids.add(driver.get("id"))
        if sum(float(a["order"].get("quantity") or 0) for a in group) > float(vehicle.get("capacity") or 0):
            pre_unserved.extend({"order_id":a["order"]["id"],"reason":"Combined order quantities exceed this vehicle's capacity."} for a in group)
            continue
        # Greedy nearest-neighbour is used only if OR-Tools is unavailable; status makes that explicit.
        nodes = [depot] + [g["order"] for g in group]
        n = len(nodes)
        # Road distances/times from OSRM (falls back to a labelled haversine estimate).
        km_m, min_m, distance_method = distance_matrix(nodes)
        methods_used.add(distance_method)
        dist = [[int(km_m[i][j] * 1000) for j in range(n)] for i in range(n)]
        order_sequence = list(range(1,n))
        solver_status = "GREEDY_FALLBACK"
        if ORTOOLS_AVAILABLE and len(group) >= 1:
            manager = pywrapcp.RoutingIndexManager(n, 1, 0)
            routing = pywrapcp.RoutingModel(manager)
            def distance_cb(from_index, to_index):
                return dist[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
            transit = routing.RegisterTransitCallback(distance_cb)
            routing.SetArcCostEvaluatorOfAllVehicles(transit)
            demands = [0] + [int(float(g["order"]["quantity"])) for g in group]
            def demand_cb(index):
                return demands[manager.IndexToNode(index)]
            demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
            routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [int(vehicle["capacity"])], True, "Capacity")
            # Time dimension: estimated travel minutes, with each customer's time window.
            def time_cb(from_index, to_index):
                i,j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
                return max(1, int(round(min_m[i][j])))
            time_idx = routing.RegisterTransitCallback(time_cb)
            routing.AddDimension(time_idx, 30, int(float(vehicle.get("max_route_hours",8))*60), False, "Time")
            time_dim = routing.GetDimensionOrDie("Time")
            for node, item in enumerate(group, start=1):
                idx = manager.NodeToIndex(node)
                start, end = _minutes(item["order"].get("window_start"), 8*60), _minutes(item["order"].get("window_end"), 17*60)
                time_dim.CumulVar(idx).SetRange(max(0,start-8*60), max(0,end-8*60))
            params = pywrapcp.DefaultRoutingSearchParameters()
            params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
            params.time_limit.seconds = 2
            solution = routing.SolveWithParameters(params)
            if solution:
                order_sequence = []
                idx = routing.Start(0)
                while not routing.IsEnd(idx):
                    node = manager.IndexToNode(idx)
                    if node:
                        order_sequence.append(node)
                    idx = solution.Value(routing.NextVar(idx))
                solver_status = "ORTOOLS_FEASIBLE"
            else:
                order_sequence = []
                solver_status = "ORTOOLS_NO_SOLUTION"
        if solver_status == "ORTOOLS_NO_SOLUTION":
            pre_unserved.extend({"order_id":g["order"]["id"],"reason":"OR-Tools could not find a feasible route under current constraints."} for g in group)
            continue
        route_stops, total_km, load, total_cost = [], 0.0, 0.0, 0.0
        prev, elapsed_min = 0, 0.0
        for seq, node in enumerate(order_sequence, start=1):
            item = group[node-1]
            order = item["order"]
            km = km_m[prev][node]
            elapsed_min += min_m[prev][node]
            total_km += km
            total_cost += km * float(vehicle.get("cost_per_km",18))
            load += float(order["quantity"])
            risk = shelf_life_risk(item["product"], elapsed_min/60)
            route_stops.append({"sequence":seq,"order_id":order["id"],"customer":order["customer"],"lat":order["lat"],"lng":order["lng"],"eta_minutes":int(round(elapsed_min)),"distance_from_previous_km":round(km,2),"quantity":order["quantity"],"risk":risk,"window":f'{order.get("window_start")}–{order.get("window_end")}'})
            assigned_ids.add(order["id"])
            prev = node
        if route_stops:
            routes.append({"id":f"R-{len(routes)+1:02d}","depot":depot,"vehicle":vehicle,"driver":driver,"stops":route_stops,"distance_km":round(total_km,2),"estimated_cost":round(total_cost,2),"load":load,"capacity":vehicle["capacity"],"solver_status":solver_status,"distance_method":distance_method})
    for o, reason in invalid:
        pre_unserved.append({"order_id":o["id"],"reason":reason})
    unserved = [o["id"] for o in orders if o["id"] not in assigned_ids]
    total_distance = round(sum(r["distance_km"] for r in routes),2)
    total_cost = round(sum(r["estimated_cost"] for r in routes),2)
    assigned = len(assigned_ids)
    return {"status":"FEASIBLE" if routes else "NO_FEASIBLE_SOLUTION","message":("No routes could be built." if not methods_used else "Routes use OSRM road distances and travel times." if methods_used == {OSRM_METHOD} else "Some or all distances are straight-line estimates because OSRM was unreachable; treat ETAs as approximate."),"routes":routes,"unserved_orders":unserved,"reasons":pre_unserved,"summary":{"orders":len(orders),"assigned":assigned,"unserved":len(unserved),"distance_km":total_distance,"estimated_cost":total_cost,"on_time_rate_estimate":None},"engine":"Google OR-Tools" if ORTOOLS_AVAILABLE else "Nearest compatible assignment fallback; install ortools for optimization"}
