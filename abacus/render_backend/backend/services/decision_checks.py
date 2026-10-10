"""Pre-decision safety checks for refrigerated delivery plans.

Rule-based constraints are authoritative. External provider checks are reported with
explicit configured/unavailable states; a missing API key is never presented as a live check.
"""
from datetime import datetime, timezone
from typing import Any

import httpx

from config import GOOGLE_MAPS_API_KEY, OPENWEATHER_API_KEY, ROAD_RESTRICTIONS_API_URL
from services.routing import travel_km


def _minutes(value: str | None, default: int) -> int:
    try:
        hour, minute = str(value).split(":", 1)
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return default


def _available_driver(drivers: list[dict], vehicle_id: str, assigned_driver_id: str | None = None) -> bool:
    return any(
        d.get("status", "Available") == "Available"
        and (not d.get("vehicle_id") or d.get("vehicle_id") == vehicle_id)
        and (not assigned_driver_id or d.get("id") == assigned_driver_id)
        for d in drivers
    )


def external_condition_checks(data: dict[str, list[dict]]) -> dict[str, Any]:
    orders = [o for o in data.get("orders", []) if o.get("status", "Pending") == "Pending"]
    inventory = {p.get("id"): p for p in data.get("inventory", [])}
    depots = {d.get("id"): d for d in data.get("depots", [])}
    signals: list[dict[str, Any]] = []
    warnings: list[str] = []
    results: dict[str, Any] = {"checked_at": datetime.now(timezone.utc).isoformat(), "signals": signals}

    # Live traffic estimates are optional and require Google Maps Distance Matrix API access.
    if GOOGLE_MAPS_API_KEY and orders:
        traffic_checked = 0
        traffic_failed = 0
        for order in orders[:3]:
            product = inventory.get(order.get("product_id"))
            depot = depots.get(product.get("depot_id")) if product else None
            if not depot:
                continue
            try:
                response = httpx.get(
                    "https://maps.googleapis.com/maps/api/distancematrix/json",
                    params={
                        "origins": f'{depot["lat"]},{depot["lng"]}',
                        "destinations": f'{order["lat"]},{order["lng"]}',
                        "departure_time": "now",
                        "key": GOOGLE_MAPS_API_KEY,
                    },
                    timeout=2.0,
                )
                response.raise_for_status()
                body = response.json()
                element = body.get("rows", [{}])[0].get("elements", [{}])[0]
                if body.get("status") == "OK" and element.get("status") == "OK":
                    traffic_checked += 1
                    traffic_duration = element.get("duration_in_traffic")
                    duration = traffic_duration or element.get("duration") or {}
                    signals.append({"order_id": order.get("id"), "type": "traffic", "status": "checked", "duration_seconds": duration.get("value"), "duration_source": "live_traffic" if traffic_duration else "typical_road_time", "label": ("Traffic estimate: " if traffic_duration else "Typical road-time estimate: ") + duration.get("text", "duration returned")})
                else:
                    traffic_failed += 1
                    signals.append({"order_id": order.get("id"), "type": "traffic", "status": "unavailable", "label": "Provider did not return a route"})
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                traffic_failed += 1
        traffic_partial = bool(traffic_failed or traffic_checked < len(orders))
        results["traffic"] = {"status": "partial" if traffic_checked and traffic_partial else "checked" if traffic_checked and not traffic_failed else "unavailable", "checked_routes": traffic_checked, "routes_to_review": max(0, len(orders) - traffic_checked), "message": f"Google Maps returned traffic estimates for {traffic_checked} of {len(orders)} pending orders." if traffic_checked else "Google Maps is configured, but a live traffic response was not available."}
        if traffic_partial:
            warnings.append("Live traffic was not checked successfully for every pending order; review unverified routes before dispatch.")
    else:
        results["traffic"] = {"status": "not_configured", "message": "Using road-time estimates only. Configure GOOGLE_MAPS_API_KEY for live traffic."}
        warnings.append("Live traffic is not configured; the route-time estimate may not reflect congestion.")

    # Current destination weather; limit calls to protect quota and API latency.
    if OPENWEATHER_API_KEY and orders:
        weather_checked = 0
        severe_weather = []
        weather_failed = 0
        for order in orders[:3]:
            try:
                response = httpx.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"lat": order["lat"], "lon": order["lng"], "appid": OPENWEATHER_API_KEY, "units": "metric"},
                    timeout=2.0,
                )
                response.raise_for_status()
                body = response.json()
                group = (body.get("weather") or [{}])[0]
                main = str(group.get("main", "Unknown"))
                temp = (body.get("main") or {}).get("temp")
                wind = (body.get("wind") or {}).get("speed", 0)
                severe = main.lower() in {"thunderstorm", "tornado"} or float(wind or 0) >= 15
                weather_checked += 1
                item = {"order_id": order.get("id"), "type": "weather", "status": "warning" if severe else "checked", "label": main, "ambient_c": temp}
                signals.append(item)
                if severe:
                    severe_weather.append(order.get("id"))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                weather_failed += 1
        weather_partial = bool(weather_failed or weather_checked < len(orders))
        results["weather"] = {"status": "warning" if severe_weather else "partial" if weather_checked and weather_partial else "checked" if weather_checked and not weather_failed else "unavailable", "checked_routes": weather_checked, "routes_to_review": max(0, len(orders) - weather_checked), "severe_weather_orders": severe_weather, "message": "Severe weather should be reviewed by dispatch." if severe_weather else f"Destination weather checked for {weather_checked} of {len(orders)} pending orders." if weather_checked else "Weather provider returned no usable readings."}
        if severe_weather:
            warnings.append("Potential severe weather at one or more destinations; require a dispatcher's review.")
        if weather_partial:
            warnings.append("Weather was not checked successfully for every pending order.")
    else:
        results["weather"] = {"status": "not_configured", "message": "Configure OPENWEATHER_API_KEY to check destination weather."}
        warnings.append("Destination weather is not configured; ambient conditions have not been verified.")

    # There is no universal road-closure API. If configured, this endpoint must return
    # JSON {"blocked": true|false, "reason": "..."}; otherwise request manual confirmation.
    if ROAD_RESTRICTIONS_API_URL and orders:
        checked, blocked = 0, []
        for order in orders[:3]:
            product = inventory.get(order.get("product_id"))
            depot = depots.get(product.get("depot_id")) if product else None
            if not depot:
                continue
            try:
                response = httpx.get(ROAD_RESTRICTIONS_API_URL, params={"origin_lat": depot["lat"], "origin_lng": depot["lng"], "destination_lat": order["lat"], "destination_lng": order["lng"]}, timeout=2.0)
                response.raise_for_status()
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("blocked"), bool):
                    checked += 1
                    if body["blocked"]:
                        blocked.append({"order_id": order.get("id"), "reason": body.get("reason", "Route reported as restricted")})
                    signals.append({"order_id": order.get("id"), "type": "road_restriction", "status": "blocked" if body["blocked"] else "clear", "label": body.get("reason", "Road restrictions checked")})
            except (httpx.HTTPError, ValueError, KeyError):
                pass
        restrictions_partial = checked < len(orders)
        results["road_restrictions"] = {"status": "blocked" if blocked else "partial" if checked and restrictions_partial else "checked" if checked and not restrictions_partial else "unavailable", "checked_routes": checked, "routes_to_review": max(0, len(orders) - checked), "blocked_routes": blocked, "message": "One or more routes are reported blocked." if blocked else f"Road restrictions checked for {checked} of {len(orders)} pending orders." if checked else "Restrictions provider did not return usable results."}
        if blocked:
            warnings.append("One or more routes are blocked by the configured road-restrictions provider.")
        if restrictions_partial:
            warnings.append("Road restrictions were not checked successfully for every pending order; manual clearance is required for unverified routes.")
        if not checked:
            warnings.append("Road restrictions could not be verified; check official road notices before dispatch.")
    else:
        results["road_restrictions"] = {"status": "manual_review", "message": "No road-closure provider is configured. Dispatch must verify road restrictions before release."}
        warnings.append("Road restrictions are not connected to a provider; manual route clearance is required.")

    return {**results, "warnings": warnings}


def evaluate_decision(data: dict[str, list[dict]]) -> dict[str, Any]:
    """Run deterministic checks before the route solver is allowed to make a plan."""
    depots = [d for d in data.get("depots", []) if d.get("status", "Active") == "Active"]
    all_depots = {d.get("id"): d for d in data.get("depots", [])}
    inventory = {p.get("id"): p for p in data.get("inventory", [])}
    vehicles = [v for v in data.get("vehicles", []) if v.get("status", "Available") == "Available"]
    drivers = [d for d in data.get("drivers", []) if d.get("status", "Available") == "Available"]
    orders = [o for o in data.get("orders", []) if o.get("status", "Pending") == "Pending"]
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    checks: list[dict[str, str]] = []

    def block(order_id: str, category: str, message: str):
        blockers.append({"order_id": order_id, "category": category, "message": message})

    def warn(order_id: str, category: str, message: str):
        warnings.append({"order_id": order_id, "category": category, "message": message})

    checks.append({"category": "resources", "status": "passed" if depots and vehicles and drivers else "blocked", "message": f"{len(depots)} active depots, {len(vehicles)} available vehicles, {len(drivers)} available drivers."})
    if orders and not depots:
        for o in orders: block(o["id"], "resources", "No active depot is available.")
    if orders and not vehicles:
        for o in orders: block(o["id"], "resources", "No available vehicle is ready for dispatch.")
    if orders and not drivers:
        for o in orders: block(o["id"], "resources", "No available driver is registered. Add/activate a driver before optimizing routes.")

    # Warehouse occupancy comes from current inventory quantities at each depot.
    occupancy: dict[str, float] = {}
    for p in data.get("inventory", []):
        depot_id = p.get("depot_id")
        occupancy[depot_id] = occupancy.get(depot_id, 0.0) + float(p.get("quantity") or 0)
    full_depots = set()
    for depot in depots:
        capacity = float(depot.get("storage_capacity") or 1000)
        used = occupancy.get(depot.get("id"), 0.0)
        if used > capacity:
            full_depots.add(depot.get("id"))
            warn("*", "warehouse", f'{depot.get("name", depot.get("id"))} exceeds configured warehouse capacity ({used:g}/{capacity:g}).')

    # Latest temperature measurement per product.
    latest_readings: dict[str, dict] = {}
    for reading in data.get("temperature_readings", []):
        product_id = reading.get("product_id")
        if not product_id: continue
        previous = latest_readings.get(product_id)
        if previous is None or str(reading.get("timestamp", "")) > str(previous.get("timestamp", "")):
            latest_readings[product_id] = reading

    for order in orders:
        oid = str(order.get("id", "?"))
        product = inventory.get(order.get("product_id"))
        if not product:
            block(oid, "inventory", "Select an existing inventory product before saving or dispatching this order.")
            continue
        if float(product.get("quantity") or 0) < float(order.get("quantity") or 0):
            block(oid, "inventory", f'Insufficient stock: {product.get("name", product["id"])} has {product.get("quantity", 0)} {product.get("unit", "units")} available.')
        if str(product.get("expiry_date", "9999")) < datetime.now().date().isoformat():
            block(oid, "temperature_shelf_life", "Product is expired; do not dispatch it.")
        depot = all_depots.get(product.get("depot_id"))
        if not depot or depot.get("status", "Active") != "Active":
            block(oid, "resources", "The product's depot is missing or inactive.")
        elif depot.get("id") in full_depots:
            block(oid, "warehouse", "The product's depot exceeds its configured storage capacity; correct warehouse stock/capacity first.")

        reading = latest_readings.get(product.get("id"))
        if reading and reading.get("temperature") is not None:
            temp = float(reading["temperature"])
            low = float(product.get("min_temp", reading.get("min_temp", 2)))
            high = float(product.get("max_temp", reading.get("max_temp", 8)))
            if temp < low or temp > high:
                block(oid, "temperature_shelf_life", f"Latest product temperature ({temp:g}°C) is outside its allowed {low:g}–{high:g}°C range.")

        driver_id = order.get("assigned_driver_id")
        vehicle_id = order.get("assigned_vehicle_id")
        candidate_vehicles = [v for v in vehicles if (not vehicle_id or v.get("id") == vehicle_id) and float(v.get("capacity") or 0) >= float(order.get("quantity") or 0)]
        compatible = []
        for v in candidate_vehicles:
            temp_ok = bool(v.get("refrigerated")) and float(v.get("min_temp", -99)) <= float(product.get("min_temp", 2)) and float(v.get("max_temp", 99)) >= float(product.get("max_temp", 8))
            if temp_ok and _available_driver(drivers, str(v.get("id")), driver_id):
                compatible.append(v)
        if not compatible:
            block(oid, "resources", "No available driver and refrigerated vehicle satisfy the vehicle capacity, product temperature range, and assignment constraints.")
        else:
            checks.append({"category": "temperature_capacity", "status": "passed", "message": f"Order {oid}: compatible refrigerated vehicle and driver available."})
            if depot:
                estimate = min(travel_km(depot, order) * float(v.get("cost_per_km", 18)) for v in compatible)
                budget = order.get("budget")
                if budget is not None and estimate > float(budget):
                    block(oid, "budget", f"Minimum estimated direct-route cost ({estimate:.2f}) exceeds the order budget ({float(budget):.2f}).")
                elif budget is not None:
                    checks.append({"category": "budget", "status": "passed", "message": f"Order {oid}: rough estimated cost {estimate:.2f} is within budget {float(budget):.2f}."})
                travel_minutes = travel_km(depot, order) / 30 * 60
                start = _minutes(order.get("window_start"), 8 * 60)
                end = _minutes(order.get("window_end"), 17 * 60)
                if start + travel_minutes > end:
                    warn(oid, "deadline", "Rough travel-time estimate may miss this delivery window; the route solver must confirm feasibility.")

    external = external_condition_checks(data)
    for item in external.get("warnings", []):
        warn("*", "external_conditions", item)
    # Compare provider traffic duration with the order's configured delivery-window width.
    # This is a conservative advisory check; the route solver still evaluates the complete route.
    order_index = {str(o.get("id")): o for o in orders}
    for signal in external.get("signals", []):
        if signal.get("type") != "traffic" or signal.get("duration_seconds") is None:
            continue
        order = order_index.get(str(signal.get("order_id")))
        if not order:
            continue
        window_minutes = max(0, _minutes(order.get("window_end"), 17 * 60) - _minutes(order.get("window_start"), 8 * 60))
        travel_minutes = float(signal["duration_seconds"]) / 60
        if window_minutes and travel_minutes > window_minutes:
            warn(str(order.get("id")), "deadline", f"{signal.get('label', 'Traffic route time')} is longer than the configured delivery window ({window_minutes} min); dispatch review is required.")

    # Merge provider-specific signals into the report, but never claim unavailable data passed.
    for service in ("traffic", "weather", "road_restrictions"):
        status = external.get(service, {}).get("status", "unknown")
        message = external.get(service, {}).get("message", "")
        checks.append({"category": service, "status": "warning" if status not in ("checked", "clear") else "passed", "message": message})
    if any(x.get("type") == "road_restriction" and x.get("status") == "blocked" for x in external.get("signals", [])):
        for signal in external["signals"]:
            if signal.get("type") == "road_restriction" and signal.get("status") == "blocked":
                block(str(signal.get("order_id", "*")), "road_restrictions", signal.get("label", "Route is restricted."))

    # Keep a useful, concise check-list even when there are no pending orders.
    checks.insert(0, {"category": "orders", "status": "passed" if orders else "warning", "message": f"{len(orders)} pending orders to evaluate." if orders else "There are no pending orders to optimize."})
    status = "BLOCKED" if blockers else "READY_WITH_WARNINGS" if warnings else "READY"
    return {
        "status": status,
        "can_proceed": not blockers and bool(orders),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "external_conditions": external,
        "summary": {"orders_checked": len(orders), "blockers": len(blockers), "warnings": len(warnings)},
        "decision_note": "Hard safety and feasibility checks must pass before a route plan is released. Unavailable external data is shown as a warning and requires manual review.",
    }
