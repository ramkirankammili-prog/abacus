import os
from dotenv import load_dotenv

load_dotenv()


def _clean_supabase_url(raw: str) -> str:
    """Accept either the project URL or REST URL and return the project URL."""
    url = (raw or "").strip().rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]
    return url


# These credentials stay server-side. The browser must never receive private API keys.
SUPABASE_URL = _clean_supabase_url(os.getenv("SUPABASE_URL", ""))
SUPABASE_PUBLIC_KEY = (os.getenv("SUPABASE_PUBLIC_KEY") or os.getenv("SUPABASE_KEY") or "").strip()
SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_PUBLIC_KEY)

FRONTEND_ORIGINS = [
    o.strip()
    for o in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

# Optional integrations; configure in backend/.env, never in VITE_* variables.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
ROAD_RESTRICTIONS_API_URL = os.getenv("ROAD_RESTRICTIONS_API_URL", "").strip()

# OSRM gives road distances / travel-time estimates. It is not live traffic data.
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
OSRM_ENABLED = os.getenv("OSRM_ENABLED", "true").lower() in ("1", "true", "yes")
OSRM_TIMEOUT = float(os.getenv("OSRM_TIMEOUT", "6"))


def integration_status() -> dict:
    """Expose setup state only, never the key values themselves."""
    return {
        "supabase": {"configured": SUPABASE_CONFIGURED, "purpose": "Authentication and operational data"},
        "gemini": {"configured": bool(GEMINI_API_KEY), "purpose": "Optional AI explanations"},
        "google_maps": {"configured": bool(GOOGLE_MAPS_API_KEY), "purpose": "Optional live traffic estimates"},
        "openweather": {"configured": bool(OPENWEATHER_API_KEY), "purpose": "Optional destination weather checks"},
        "road_restrictions": {"configured": bool(ROAD_RESTRICTIONS_API_URL), "purpose": "Optional configured road restriction provider"},
        "osrm": {"configured": OSRM_ENABLED, "purpose": "Road distance and estimated travel time; not live traffic"},
    }
