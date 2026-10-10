"""Supabase data layer.

Every request is executed with the signed-in user's access token (JWT) together with the
Supabase public (publishable) key that lives only in backend/.env. Row Level Security in
Supabase therefore applies to every query. There is no local JSON fallback: the frontend
always shows what is stored in Supabase.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from postgrest.exceptions import APIError
from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_PUBLIC_KEY, SUPABASE_CONFIGURED

# collection name -> (table name, column used for ordering)
COLLECTIONS: dict[str, tuple[str, str]] = {
    "depots": ("depots", "created_at"),
    "inventory": ("inventory", "created_at"),
    "orders": ("orders", "created_at"),
    "vehicles": ("vehicles", "created_at"),
    "drivers": ("drivers", "created_at"),
    "optimization_runs": ("optimization_runs", "created_at"),
    "temperature_readings": ("temperature_readings", "timestamp"),
    "alerts": ("alerts", "created_at"),
}

# Delete children before parents, insert parents before children.
_DELETE_ORDER = ["optimization_runs", "alerts", "temperature_readings", "orders", "drivers", "inventory", "vehicles", "depots"]


def _translate(exc: APIError) -> HTTPException:
    code = str(getattr(exc, "code", "") or "")
    message = getattr(exc, "message", None) or str(exc)
    if code in ("42P01", "PGRST205", "PGRST200"):
        return HTTPException(503, "Supabase tables were not found. Run database/schema.sql in the Supabase SQL editor first.")
    if code in ("42501", "401", "403") or "row-level security" in message.lower():
        return HTTPException(403, "Supabase denied this request (Row Level Security). Make sure you are signed in and database/schema.sql was applied.")
    if code == "23503":
        detail = (message or "").lower()
        if "orders_product_id_fkey" in detail:
            return HTTPException(409, "Select a product that exists in Inventory before saving this order.")
        if "orders_assigned_driver_id_fkey" in detail:
            return HTTPException(409, "Select an existing driver or leave Driver unassigned.")
        if "orders_assigned_vehicle_id_fkey" in detail:
            return HTTPException(409, "Select an existing vehicle or leave Vehicle unassigned.")
        return HTTPException(409, "This record is still used by another record. Change the linked order, driver, or inventory record first.")
    if code == "23505":
        return HTTPException(409, "A record with this id already exists.")
    if code.startswith("22") or code.startswith("23"):
        return HTTPException(400, f"Invalid data: {message}")
    return HTTPException(502, f"Supabase error: {message}")


class SupabaseDB:
    """A thin wrapper around the Supabase Python client bound to one signed-in user."""

    def __init__(self, access_token: str):
        if not SUPABASE_CONFIGURED:
            raise HTTPException(503, "Supabase is not configured on the server. Set SUPABASE_URL and SUPABASE_PUBLIC_KEY in backend/.env.")
        self._client: Client = create_client(SUPABASE_URL, SUPABASE_PUBLIC_KEY)
        # Run every query as the logged-in user so RLS policies apply.
        self._client.postgrest.auth(access_token)

    # ---- reads -------------------------------------------------------------
    def get_collection(self, name: str) -> list[dict[str, Any]]:
        table, order_col = COLLECTIONS[name]
        try:
            q = self._client.table(table).select("*").order(order_col)
            if order_col != "id":
                q = q.order("id")
            return q.execute().data or []
        except APIError as exc:
            raise _translate(exc)

    def load_data(self) -> dict[str, list[dict[str, Any]]]:
        # Query all tables in parallel so the dashboard refreshes quickly.
        names = list(COLLECTIONS)
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            return dict(zip(names, pool.map(self.get_collection, names)))

    # ---- writes ------------------------------------------------------------
    def insert(self, name: str, rows: dict | list[dict]) -> list[dict[str, Any]]:
        table, _ = COLLECTIONS[name]
        try:
            return self._client.table(table).insert(rows).select("*").execute().data or []
        except APIError as exc:
            raise _translate(exc)

    def update(self, name: str, item_id: str, values: dict) -> dict[str, Any] | None:
        table, _ = COLLECTIONS[name]
        try:
            data = self._client.table(table).update(values).eq("id", item_id).select("*").execute().data
        except APIError as exc:
            raise _translate(exc)
        return data[0] if data else None

    def delete(self, name: str, item_id: str) -> bool:
        table, _ = COLLECTIONS[name]
        try:
            data = self._client.table(table).delete().eq("id", item_id).select("id").execute().data
        except APIError as exc:
            raise _translate(exc)
        return bool(data)

    def get_app_role(self, user_id: str) -> str:
        """Read the caller's role; legacy users without a profile remain managers."""
        try:
            result = self._client.table("profiles").select("role").eq("id", user_id).maybe_single().execute()
            profile = result.data or {}
            return profile.get("role", "manager") if isinstance(profile, dict) else "manager"
        except Exception:
            # Keeps older deployments usable before the additive role migration is applied.
            return "manager"

    def get_driver_for_user(self, user_id: str) -> dict[str, Any] | None:
        try:
            result = self._client.table("drivers").select("*").eq("user_id", user_id).limit(1).execute()
            rows = result.data or []
            return rows[0] if rows else None
        except APIError as exc:
            raise _translate(exc)

    def get_orders_for_driver(self, driver_id: str) -> list[dict[str, Any]]:
        try:
            result = self._client.table("orders").select("*").eq("assigned_driver_id", driver_id).order("created_at").execute()
            return result.data or []
        except APIError as exc:
            raise _translate(exc)

    # ---- sample data -------------------------------------------------------
    def replace_with_sample_data(self) -> dict[str, int]:
        """Wipe the app tables and load the sample dataset into Supabase."""
        seed = sample_data()
        try:
            for name in _DELETE_ORDER:
                table, _ = COLLECTIONS[name]
                # PostgREST requires a filter on DELETE; "id is not null" matches every row.
                self._client.table(table).delete().not_.is_("id", "null").execute()
            for name in reversed(_DELETE_ORDER):
                rows = seed.get(name, [])
                if rows:
                    self.insert(name, rows)
        except APIError as exc:
            raise _translate(exc)
        return {k: len(v) for k, v in seed.items()}


def sample_data() -> dict[str, list[dict[str, Any]]]:
    today = date.today()
    now = datetime.now(timezone.utc).isoformat()
    inventory = [
        {"id": "P-001", "name": "Fresh Milk", "category": "Dairy", "depot_id": "D-001", "quantity": 180, "unit": "crates", "expiry_date": (today + timedelta(days=2)).isoformat(), "min_temp": 2, "max_temp": 6, "priority": "High"},
        {"id": "P-002", "name": "Yogurt", "category": "Dairy", "depot_id": "D-002", "quantity": 120, "unit": "boxes", "expiry_date": (today + timedelta(days=4)).isoformat(), "min_temp": 2, "max_temp": 6, "priority": "Medium"},
        {"id": "P-003", "name": "Leafy Greens", "category": "Vegetables", "depot_id": "D-003", "quantity": 90, "unit": "crates", "expiry_date": (today + timedelta(days=1)).isoformat(), "min_temp": 1, "max_temp": 5, "priority": "High"},
        {"id": "P-004", "name": "Strawberries", "category": "Fruit", "depot_id": "D-001", "quantity": 75, "unit": "boxes", "expiry_date": (today + timedelta(days=3)).isoformat(), "min_temp": 1, "max_temp": 4, "priority": "High"},
        {"id": "P-005", "name": "Cheese", "category": "Dairy", "depot_id": "D-002", "quantity": 200, "unit": "boxes", "expiry_date": (today + timedelta(days=18)).isoformat(), "min_temp": 2, "max_temp": 8, "priority": "Low"},
    ]
    readings = []
    for i, p in enumerate(inventory):
        readings.append({
            "id": f"T-{i + 1}", "product_id": p["id"], "product": p["name"], "location": p["depot_id"],
            "temperature": round((p["min_temp"] + p["max_temp"]) / 2 + (2.8 if i == 2 else 0), 1),
            "min_temp": p["min_temp"], "max_temp": p["max_temp"], "timestamp": now, "mode": "SIMULATED",
        })
    return {
        "depots": [
            {"id": "D-001", "name": "North Fresh Hub", "address": "Hyderabad, Telangana", "lat": 17.4401, "lng": 78.3489, "operating_start": "06:00", "operating_end": "20:00", "storage_capacity": 1000, "status": "Active"},
            {"id": "D-002", "name": "Central Distribution Hub", "address": "Secunderabad, Telangana", "lat": 17.4399, "lng": 78.4983, "operating_start": "06:00", "operating_end": "21:00", "storage_capacity": 1000, "status": "Active"},
            {"id": "D-003", "name": "South Cold Store", "address": "LB Nagar, Hyderabad", "lat": 17.3457, "lng": 78.5522, "operating_start": "05:30", "operating_end": "20:00", "storage_capacity": 1000, "status": "Active"},
        ],
        "inventory": inventory,
        "orders": [
            {"id": "O-1001", "customer": "Green Basket Market", "address": "Madhapur, Hyderabad", "lat": 17.4483, "lng": 78.3915, "product_id": "P-001", "quantity": 20, "window_start": "08:00", "window_end": "12:00", "priority": "High", "status": "Pending"},
            {"id": "O-1002", "customer": "City Cafe", "address": "Banjara Hills, Hyderabad", "lat": 17.4126, "lng": 78.4482, "product_id": "P-002", "quantity": 15, "window_start": "09:00", "window_end": "13:00", "priority": "Medium", "status": "Pending"},
            {"id": "O-1003", "customer": "Fresh Mart", "address": "Kukatpally, Hyderabad", "lat": 17.4849, "lng": 78.4138, "product_id": "P-003", "quantity": 12, "window_start": "08:00", "window_end": "11:00", "priority": "High", "status": "Pending"},
            {"id": "O-1004", "customer": "Daily Needs", "address": "Gachibowli, Hyderabad", "lat": 17.4401, "lng": 78.3489, "product_id": "P-004", "quantity": 10, "window_start": "10:00", "window_end": "15:00", "priority": "Medium", "status": "Pending"},
            {"id": "O-1005", "customer": "Sunrise Bakery", "address": "Ameerpet, Hyderabad", "lat": 17.4375, "lng": 78.4483, "product_id": "P-005", "quantity": 18, "window_start": "09:00", "window_end": "14:00", "priority": "Low", "status": "Pending"},
            {"id": "O-1006", "customer": "Organic Corner", "address": "Kondapur, Hyderabad", "lat": 17.4604, "lng": 78.3568, "product_id": "P-003", "quantity": 16, "window_start": "08:00", "window_end": "12:00", "priority": "High", "status": "Pending"},
            {"id": "O-1007", "customer": "Healthy Foods", "address": "Dilsukhnagar, Hyderabad", "lat": 17.3688, "lng": 78.5247, "product_id": "P-001", "quantity": 25, "window_start": "10:00", "window_end": "16:00", "priority": "Medium", "status": "Pending"},
            {"id": "O-1008", "customer": "Market Square", "address": "Begumpet, Hyderabad", "lat": 17.4435, "lng": 78.4672, "product_id": "P-002", "quantity": 14, "window_start": "08:00", "window_end": "12:00", "priority": "High", "status": "Pending"},
        ],
        "vehicles": [
            {"id": "V-01", "name": "Chiller Van 01", "capacity": 70, "unit": "crates/boxes", "refrigerated": True, "min_temp": 1, "max_temp": 6, "lat": 17.4401, "lng": 78.3489, "cost_per_km": 18, "max_route_hours": 8, "status": "Available"},
            {"id": "V-02", "name": "Cold Truck 02", "capacity": 100, "unit": "crates/boxes", "refrigerated": True, "min_temp": 1, "max_temp": 8, "lat": 17.4399, "lng": 78.4983, "cost_per_km": 22, "max_route_hours": 9, "status": "Available"},
            {"id": "V-03", "name": "Fresh Van 03", "capacity": 55, "unit": "crates/boxes", "refrigerated": True, "min_temp": 2, "max_temp": 6, "lat": 17.3457, "lng": 78.5522, "cost_per_km": 16, "max_route_hours": 7, "status": "Available"},
            {"id": "V-04", "name": "Backup Van 04", "capacity": 35, "unit": "crates/boxes", "refrigerated": False, "min_temp": 10, "max_temp": 25, "lat": 17.4399, "lng": 78.4983, "cost_per_km": 12, "max_route_hours": 6, "status": "Available"},
        ],
        "drivers": [
            {"id": "DR-001", "user_id": None, "name": "Driver One", "phone": "", "license_number": "", "vehicle_id": "V-01", "status": "Available"},
            {"id": "DR-002", "user_id": None, "name": "Driver Two", "phone": "", "license_number": "", "vehicle_id": "V-02", "status": "Available"},
            {"id": "DR-003", "user_id": None, "name": "Driver Three", "phone": "", "license_number": "", "vehicle_id": "V-03", "status": "Available"},
            {"id": "DR-004", "user_id": None, "name": "Backup Driver", "phone": "", "license_number": "", "vehicle_id": "V-04", "status": "Available"},
        ],
        "optimization_runs": [],
        "temperature_readings": readings,
        "alerts": [],
    }
