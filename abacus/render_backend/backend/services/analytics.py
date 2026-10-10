"""Operational analytics computed with Pandas/NumPy from the live Supabase rows."""
from datetime import date

import numpy as np
import pandas as pd

PRIORITIES = ["Urgent", "High", "Medium", "Low"]


def orders_by_priority(orders: list[dict]) -> list[dict]:
    """Pending vs completed order counts per priority (drives the dashboard chart)."""
    base = [{"priority": p, "pending": 0, "completed": 0, "total": 0} for p in PRIORITIES]
    if not orders:
        return base
    df = pd.DataFrame(orders)
    df["priority"] = df.get("priority", "Medium").fillna("Medium")
    df["status"] = df.get("status", "Pending").fillna("Pending")
    counts = df.groupby(["priority", "status"]).size().unstack(fill_value=0)
    out = []
    for p in PRIORITIES:
        pending = int(counts.loc[p].get("Pending", 0)) if p in counts.index else 0
        completed = int(counts.loc[p].get("Completed", 0)) if p in counts.index else 0
        total = int(counts.loc[p].sum()) if p in counts.index else 0
        out.append({"priority": p, "pending": pending, "completed": completed, "total": total})
    return out


def inventory_health(inventory: list[dict]) -> dict:
    """Stock totals and days-to-expiry statistics."""
    if not inventory:
        return {"items": 0, "total_quantity": 0, "expiring_within_3_days": 0, "avg_days_to_expiry": None}
    df = pd.DataFrame(inventory)
    df["quantity"] = pd.to_numeric(df.get("quantity"), errors="coerce").fillna(0)
    expiry = pd.to_datetime(df.get("expiry_date"), errors="coerce")
    days = (expiry - pd.Timestamp(date.today())).dt.days.to_numpy(dtype="float64")
    valid = days[~np.isnan(days)]
    return {
        "items": int(len(df)),
        "total_quantity": float(df["quantity"].sum()),
        "expiring_within_3_days": int((valid <= 3).sum()),
        "avg_days_to_expiry": round(float(valid.mean()), 1) if valid.size else None,
    }


def build_analytics(data: dict) -> dict:
    return {
        "orders_by_priority": orders_by_priority(data.get("orders", [])),
        "inventory_health": inventory_health(data.get("inventory", [])),
    }
