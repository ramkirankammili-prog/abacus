from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from auth import get_db
from config import FRONTEND_ORIGINS, SUPABASE_CONFIGURED, integration_status
from database import COLLECTIONS, SupabaseDB
from schemas.models import DepotIn, InventoryIn, OrderIn, VehicleIn, DriverIn
from services.ai_service import explain
from services.analytics import build_analytics
from services.optimizer import optimize
from services.shelf_life import shelf_life_risk
from services.decision_checks import evaluate_decision

app = FastAPI(
    title="FrostRoute AI API",
    version="2.0.0",
    description="Multi-depot perishable food routing and cold-chain risk API backed by Supabase.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Collections that can be listed directly. "alerts" is excluded on purpose: /api/alerts also
# adds computed shelf-life and temperature alerts.
LISTABLE = set(COLLECTIONS) - {"alerts"}


def require_manager(db: SupabaseDB) -> None:
    if getattr(db, "role", "manager") != "manager":
        raise HTTPException(403, "Manager access is required for this operation. Open the Driver workspace for driver tasks.")


def _validate_inventory_capacity(db: SupabaseDB, payload: InventoryIn, item_id: str | None = None) -> None:
    depots = db.get_collection("depots")
    depot = next((d for d in depots if d.get("id") == payload.depot_id), None)
    if not depot:
        raise HTTPException(400, "Choose an existing depot before saving this inventory item.")
    current = db.get_collection("inventory")
    used = sum(float(row.get("quantity") or 0) for row in current if row.get("depot_id") == payload.depot_id and row.get("id") != item_id)
    capacity = float(depot.get("storage_capacity") or 1000)
    if used + float(payload.quantity) > capacity:
        raise HTTPException(409, f"Warehouse capacity exceeded at {depot.get('name', depot['id'])}: {used:g} already stored + {payload.quantity:g} requested exceeds {capacity:g} capacity.")
    if payload.min_temp > payload.max_temp:
        raise HTTPException(400, "Minimum storage temperature cannot be greater than maximum temperature.")


def _validate_order_links(db: SupabaseDB, payload: OrderIn, item_id: str | None = None) -> None:
    inventory = db.get_collection("inventory")
    product = next((p for p in inventory if p.get("id") == payload.product_id), None)
    if not product:
        raise HTTPException(400, "Select a product that already exists in Inventory. Product ID is a required foreign-key link.")
    current_order = next((o for o in db.get_collection("orders") if o.get("id") == item_id), None) if item_id else None
    product_or_quantity_changed = (not current_order or current_order.get("product_id") != payload.product_id
                                   or float(current_order.get("quantity") or 0) != float(payload.quantity))
    if product_or_quantity_changed and float(product.get("quantity") or 0) < float(payload.quantity):
        raise HTTPException(409, f"Insufficient stock: {product.get('name', payload.product_id)} has {product.get('quantity', 0)} {product.get('unit', 'units')} available.")
    if payload.assigned_driver_id:
        drivers = db.get_collection("drivers")
        if not any(d.get("id") == payload.assigned_driver_id for d in drivers):
            raise HTTPException(400, "Choose an existing driver or leave Driver unassigned.")
    if payload.assigned_vehicle_id:
        vehicles = db.get_collection("vehicles")
        if not any(v.get("id") == payload.assigned_vehicle_id for v in vehicles):
            raise HTTPException(400, "Choose an existing vehicle or leave Vehicle unassigned.")


def _overview(d: dict) -> dict:
    today = datetime.now().date().isoformat()
    expiring = sum(1 for p in d["inventory"] if (p.get("expiry_date") or "9999") <= today)
    pending = sum(1 for o in d["orders"] if o.get("status") == "Pending")
    runs = d["optimization_runs"]
    return {
        "depots": len(d["depots"]),
        "orders": len(d["orders"]),
        "pending_orders": pending,
        "vehicles": len(d["vehicles"]),
        "available_vehicles": sum(1 for v in d["vehicles"] if v.get("status") == "Available"),
        "drivers": len(d.get("drivers", [])),
        "available_drivers": sum(1 for dr in d.get("drivers", []) if dr.get("status") == "Available"),
        "expiring_products": expiring,
        "latest_run": runs[-1] if runs else None,
        "recent_runs": runs[-5:],
    }


def _computed_alerts(d: dict) -> list[dict]:
    result = list(d["alerts"])
    for p in d["inventory"]:
        risk = shelf_life_risk(p)
        if risk["level"] in ("High", "Critical"):
            result.append({"id": f'EXP-{p["id"]}', "type": "Shelf-life risk", "severity": risk["level"], "entity": p["name"], "reason": risk["reason"], "status": "Open"})
    for t in d["temperature_readings"]:
        if t.get("temperature") is not None and t.get("min_temp") is not None and t.get("max_temp") is not None:
            if not (float(t["min_temp"]) <= float(t["temperature"]) <= float(t["max_temp"])):
                result.append({"id": f'TEMP-{t["id"]}', "type": "Temperature excursion", "severity": "High", "entity": t.get("product") or t["product_id"], "reason": "Recorded temperature is outside configured range.", "status": "Open"})
    return result


# --------------------------------------------------------------------------- public
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": "FrostRoute AI",
        "supabase_configured": SUPABASE_CONFIGURED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- read (auth required)
@app.get("/api/snapshot")
def snapshot(db: SupabaseDB = Depends(get_db)):
    """Manager workspace snapshot, read live from Supabase in one call."""
    require_manager(db)
    raw = db.load_data()
    d = {**raw, "alerts": _computed_alerts(raw)}
    return {
        "data": d,
        "overview": _overview(raw),
        "analytics": build_analytics(raw),
        "integrations": integration_status(),
        "user": {"id": db.user.get("id"), "email": db.user.get("email")},  # type: ignore[attr-defined]
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/overview")
def overview(db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    return _overview(db.load_data())


@app.get("/api/alerts")
def alerts(db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    return _computed_alerts(db.load_data())


@app.get("/api/{collection}")
def list_collection(collection: str, db: SupabaseDB = Depends(get_db)):
    if collection not in LISTABLE:
        raise HTTPException(404, "Collection not found")
    require_manager(db)
    return db.get_collection(collection)


# --------------------------------------------------------------------------- create / update / delete
def _create(db: SupabaseDB, collection: str, payload):
    require_manager(db)
    if collection == "inventory": _validate_inventory_capacity(db, payload)
    if collection == "orders": _validate_order_links(db, payload)
    row = payload.model_dump()
    if collection == "drivers" and not row.get("user_id"): row["user_id"] = None
    if collection == "orders":
        if not row.get("assigned_driver_id"): row["assigned_driver_id"] = None
        if not row.get("assigned_vehicle_id"): row["assigned_vehicle_id"] = None
    row["id"] = f'{collection[:1].upper()}-{uuid4().hex[:7].upper()}'
    if not row.get("created_at"):
        row.pop("created_at", None)  # let Postgres default it
    created = db.insert(collection, row)
    return created[0] if created else row


def _update(db: SupabaseDB, collection: str, item_id: str, payload):
    require_manager(db)
    if collection == "inventory": _validate_inventory_capacity(db, payload, item_id)
    if collection == "orders": _validate_order_links(db, payload, item_id)
    values = payload.model_dump()
    if collection == "drivers" and not values.get("user_id"): values["user_id"] = None
    if collection == "orders":
        if not values.get("assigned_driver_id"): values["assigned_driver_id"] = None
        if not values.get("assigned_vehicle_id"): values["assigned_vehicle_id"] = None
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
    if not values.get("created_at"):
        values.pop("created_at", None)
    updated = db.update(collection, item_id, values)
    if not updated:
        raise HTTPException(404, f"{collection[:-1].title()} not found")
    return updated


def _delete(db: SupabaseDB, collection: str, item_id: str):
    require_manager(db)
    if collection == "depots":
        if any(row.get("depot_id") == item_id for row in db.get_collection("inventory")):
            raise HTTPException(409, "Cannot delete this depot because inventory items depend on it. Move those items to another depot first.")
    if collection == "inventory":
        if any(row.get("product_id") == item_id for row in db.get_collection("orders")):
            raise HTTPException(409, "Cannot delete this product because existing orders reference it. Edit or remove those linked orders first.")
    if collection == "vehicles":
        if any(row.get("vehicle_id") == item_id for row in db.get_collection("drivers")) or any(row.get("assigned_vehicle_id") == item_id for row in db.get_collection("orders")):
            raise HTTPException(409, "Cannot delete this vehicle while a driver or order is assigned to it. Reassign them first.")
    if collection == "drivers":
        if any(row.get("assigned_driver_id") == item_id for row in db.get_collection("orders")):
            raise HTTPException(409, "Cannot delete this driver while orders are assigned. Reassign those orders first.")
    if not db.delete(collection, item_id):
        raise HTTPException(404, f"{collection[:-1].title()} not found")
    return {"deleted": True, "id": item_id}


@app.post("/api/depots")
def create_depot(payload: DepotIn, db: SupabaseDB = Depends(get_db)): return _create(db, "depots", payload)
@app.put("/api/depots/{item_id}")
def update_depot(item_id: str, payload: DepotIn, db: SupabaseDB = Depends(get_db)): return _update(db, "depots", item_id, payload)
@app.delete("/api/depots/{item_id}")
def delete_depot(item_id: str, db: SupabaseDB = Depends(get_db)): return _delete(db, "depots", item_id)

@app.post("/api/inventory")
def create_inventory(payload: InventoryIn, db: SupabaseDB = Depends(get_db)): return _create(db, "inventory", payload)
@app.put("/api/inventory/{item_id}")
def update_inventory(item_id: str, payload: InventoryIn, db: SupabaseDB = Depends(get_db)): return _update(db, "inventory", item_id, payload)
@app.delete("/api/inventory/{item_id}")
def delete_inventory(item_id: str, db: SupabaseDB = Depends(get_db)): return _delete(db, "inventory", item_id)

@app.post("/api/orders")
def create_order(payload: OrderIn, db: SupabaseDB = Depends(get_db)): return _create(db, "orders", payload)
@app.put("/api/orders/{item_id}")
def update_order(item_id: str, payload: OrderIn, db: SupabaseDB = Depends(get_db)): return _update(db, "orders", item_id, payload)
@app.delete("/api/orders/{item_id}")
def delete_order(item_id: str, db: SupabaseDB = Depends(get_db)): return _delete(db, "orders", item_id)

@app.post("/api/vehicles")
def create_vehicle(payload: VehicleIn, db: SupabaseDB = Depends(get_db)): return _create(db, "vehicles", payload)
@app.put("/api/vehicles/{item_id}")
def update_vehicle(item_id: str, payload: VehicleIn, db: SupabaseDB = Depends(get_db)): return _update(db, "vehicles", item_id, payload)
@app.delete("/api/vehicles/{item_id}")
def delete_vehicle(item_id: str, db: SupabaseDB = Depends(get_db)): return _delete(db, "vehicles", item_id)

@app.post("/api/drivers")
def create_driver(payload: DriverIn, db: SupabaseDB = Depends(get_db)): return _create(db, "drivers", payload)
@app.put("/api/drivers/{item_id}")
def update_driver(item_id: str, payload: DriverIn, db: SupabaseDB = Depends(get_db)): return _update(db, "drivers", item_id, payload)
@app.delete("/api/drivers/{item_id}")
def delete_driver(item_id: str, db: SupabaseDB = Depends(get_db)): return _delete(db, "drivers", item_id)


# --------------------------------------------------------------------------- optimization
@app.post("/api/decisions/check")
def decision_check(db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    return evaluate_decision(db.load_data())


@app.post("/api/optimization/run")
def run_optimization(db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    d = db.load_data()
    decision_report = evaluate_decision(d)
    blocked_ids = {str(x.get("order_id")) for x in decision_report.get("blockers", []) if x.get("order_id") not in (None, "*")}
    # Unsafe orders are excluded, but independent feasible orders can still be optimized.
    optimizer_data = {**d, "orders": [o for o in d.get("orders", []) if str(o.get("id")) not in blocked_ids]}
    result = optimize(optimizer_data)
    result["decision_report"] = decision_report
    # Route assignments must be reflected in Supabase so drivers see their own order queue.
    for route in result.get("routes", []):
        driver = route.get("driver") or {}
        vehicle = route.get("vehicle") or {}
        for stop in route.get("stops", []):
            order_id = stop.get("order_id")
            if order_id and driver.get("id") and vehicle.get("id"):
                db.update("orders", str(order_id), {
                    "assigned_driver_id": driver["id"],
                    "assigned_vehicle_id": vehicle["id"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
    for blocker in decision_report.get("blockers", []):
        if blocker.get("order_id") not in (None, "*"):
            oid = str(blocker["order_id"])
            if oid not in result.setdefault("unserved_orders", []): result["unserved_orders"].append(oid)
            result.setdefault("reasons", []).append({"order_id": oid, "reason": f'Pre-decision check ({blocker.get("category")}): {blocker.get("message")}'} )
    # The run summary describes all pending orders, including those removed during preflight.
    result["unserved_orders"] = list(dict.fromkeys(result.get("unserved_orders", [])))
    assigned_order_ids = {str(stop.get("order_id")) for route in result.get("routes", []) for stop in route.get("stops", []) if stop.get("order_id")}
    result.setdefault("summary", {})["orders"] = len([o for o in d.get("orders", []) if o.get("status", "Pending") == "Pending"])
    result["summary"]["assigned"] = len(assigned_order_ids)
    result["summary"]["unserved"] = len(result["unserved_orders"])
    if result.get("routes") and (decision_report.get("blockers") or decision_report.get("warnings")):
        result["status"] = "FEASIBLE_WITH_WARNINGS"
        result["message"] = (result.get("message", "Routes generated.") + " Some orders or external conditions require review; see pre-decision report.").strip()
    elif not result.get("routes") and decision_report.get("blockers"):
        result["status"] = "NO_FEASIBLE_SOLUTION"
        result["message"] = "Pre-decision checks blocked dispatch. Review the listed resource, budget, inventory, temperature, or road restriction issues."
    run = {
        "id": f'RUN-{uuid4().hex[:8].upper()}',
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": result.get("status"),
        "engine": result.get("engine"),
        "message": result.get("message"),
        "summary": result.get("summary") or {},
        "routes": result.get("routes") or [],
        "unserved_orders": result.get("unserved_orders") or [],
        "reasons": result.get("reasons") or [],
        "decision_report": decision_report,
    }
    db.insert("optimization_runs", run)
    return run


@app.get("/api/optimization/history")
def history(db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    return list(reversed(db.get_collection("optimization_runs")))


@app.get("/api/optimization/{run_id}")
def get_run(run_id: str, db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    for run in db.get_collection("optimization_runs"):
        if run["id"] == run_id:
            return run
    raise HTTPException(404, "Optimization run not found")


@app.post("/api/ai/explain")
async def ai_explain(payload: dict, db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    return await explain(payload)


# --------------------------------------------------------------------------- monitoring
@app.get("/api/monitoring/temperatures")
def temperatures(db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    return db.get_collection("temperature_readings")


@app.post("/api/monitoring/temperatures")
def add_temperature(payload: dict, db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    if any(k not in payload for k in ("product_id", "temperature")):
        raise HTTPException(400, "product_id and temperature are required")
    allowed = {"product_id", "product", "location", "temperature", "min_temp", "max_temp", "mode"}
    row = {k: v for k, v in payload.items() if k in allowed}
    row.update({"id": f"T-{uuid4().hex[:7]}", "timestamp": datetime.now(timezone.utc).isoformat()})
    row.setdefault("mode", "CONNECTED_INPUT")
    created = db.insert("temperature_readings", row)
    return created[0] if created else row


# --------------------------------------------------------------------------- driver workspace
@app.get("/api/driver/dashboard")
def driver_dashboard(db: SupabaseDB = Depends(get_db)):
    if getattr(db, "role", "manager") != "driver":
        raise HTTPException(403, "This workspace is for driver accounts.")
    user_id = str(getattr(db, "user", {}).get("id", ""))
    driver = db.get_driver_for_user(user_id)
    if not driver:
        raise HTTPException(404, "Your login is not linked to a driver record yet. Ask your manager to link your Supabase user ID on the Drivers page.")
    orders = db.get_orders_for_driver(str(driver["id"]))
    return {"driver": driver, "orders": orders, "fetched_at": datetime.now(timezone.utc).isoformat()}


@app.post("/api/driver/orders/{order_id}/status")
def update_driver_order_status(order_id: str, payload: dict, db: SupabaseDB = Depends(get_db)):
    if getattr(db, "role", "manager") != "driver":
        raise HTTPException(403, "This action is for driver accounts.")
    user_id = str(getattr(db, "user", {}).get("id", ""))
    driver = db.get_driver_for_user(user_id)
    if not driver:
        raise HTTPException(404, "Your login is not linked to a driver record yet.")
    order = next((o for o in db.get_orders_for_driver(str(driver["id"])) if o.get("id") == order_id), None)
    if not order:
        raise HTTPException(404, "This order is not assigned to your driver account.")
    status = str(payload.get("status", ""))
    allowed = {"Picked up", "In transit", "Delivered", "Issue"}
    if status not in allowed:
        raise HTTPException(400, "Choose a valid delivery status.")
    values = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status == "Issue":
        values["driver_note"] = str(payload.get("note", "Delivery issue reported by driver"))[:1000]
    elif order.get("status") == "Issue":
        values["driver_note"] = ""
    updated = db.update("orders", order_id, values)
    if not updated:
        # Some PostgREST versions return no representation if the SQL migration is stale.
        updated = {**order, **values}
    return {"order": updated, "message": "Delivery status updated."}


# --------------------------------------------------------------------------- scenarios / sample data
@app.post("/api/scenarios/simulate")
def simulate(payload: dict, db: SupabaseDB = Depends(get_db)):
    require_manager(db)
    d = db.load_data()
    scenario = payload.get("scenario", "vehicle_unavailable")
    changed = {k: [dict(x) for x in v] for k, v in d.items()}
    if scenario == "vehicle_unavailable":
        target = payload.get("vehicle_id")
        vehicle = next((v for v in changed["vehicles"] if v["id"] == target), None)
        if not vehicle and changed["vehicles"]:
            vehicle = changed["vehicles"][0]
        if vehicle:
            vehicle["status"] = "Unavailable"
    elif scenario == "urgent_order":
        if changed["orders"]:
            changed["orders"][0]["priority"] = "Urgent"
            changed["orders"][0]["window_end"] = "10:00"
    result = optimize(changed)
    return {
        "scenario": scenario,
        "baseline": {"orders": len(d["orders"]), "vehicles": len(d["vehicles"])},
        "simulated_result": result,
        "note": "Simulation only; the records stored in Supabase were not changed.",
    }


@app.post("/api/data/sample")
def load_sample_data(db: SupabaseDB = Depends(get_db)):
    """Replace the contents of the Supabase tables with the sample dataset."""
    require_manager(db)
    counts = db.replace_with_sample_data()
    return {"loaded": True, "counts": counts, "message": "Sample data loaded into Supabase."}
