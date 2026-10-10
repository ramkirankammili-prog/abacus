from math import radians, sin, cos, asin, sqrt

import httpx

from config import OSRM_URL, OSRM_ENABLED, OSRM_TIMEOUT

HAVERSINE_METHOD = "Haversine-based estimate × 1.3; not road distance"
OSRM_METHOD = "OSRM road network (driving distance and travel time)"
FALLBACK_SPEED_KMH = 30.0


def haversine_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    # Straight-line distance, used only as a clearly labelled fallback.
    dlat, dlng = radians(b_lat - a_lat), radians(b_lng - a_lng)
    x = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    return 6371 * 2 * asin(sqrt(max(0, min(1, x))))


def travel_km(a: dict, b: dict) -> float:
    return haversine_km(float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])) * 1.3


def _fallback_matrix(nodes: list[dict]) -> tuple[list[list[float]], list[list[float]]]:
    n = len(nodes)
    km = [[0.0 if i == j else travel_km(nodes[i], nodes[j]) for j in range(n)] for i in range(n)]
    minutes = [[km[i][j] / FALLBACK_SPEED_KMH * 60 for j in range(n)] for i in range(n)]
    return km, minutes


def _osrm_matrix(nodes: list[dict]) -> tuple[list[list[float]], list[list[float]]]:
    coords = ";".join(f'{float(p["lng"])},{float(p["lat"])}' for p in nodes)
    url = f"{OSRM_URL}/table/v1/driving/{coords}"
    r = httpx.get(url, params={"annotations": "distance,duration"}, timeout=OSRM_TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "Ok":
        raise ValueError(f"OSRM returned {body.get('code')}")
    meters, seconds = body["distances"], body["durations"]
    n = len(nodes)
    if any(meters[i][j] is None or seconds[i][j] is None for i in range(n) for j in range(n)):
        raise ValueError("OSRM could not route between some points")
    km = [[meters[i][j] / 1000 for j in range(n)] for i in range(n)]
    minutes = [[seconds[i][j] / 60 for j in range(n)] for i in range(n)]
    return km, minutes


def distance_matrix(nodes: list[dict]) -> tuple[list[list[float]], list[list[float]], str]:
    """Return (km matrix, minutes matrix, method label). Uses OSRM, falls back to haversine."""
    if OSRM_ENABLED and len(nodes) > 1:
        try:
            km, minutes = _osrm_matrix(nodes)
            return km, minutes, OSRM_METHOD
        except Exception:
            pass
    km, minutes = _fallback_matrix(nodes)
    return km, minutes, HAVERSINE_METHOD
