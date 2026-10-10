"""Verify a Supabase access token and bind database access to that user and role."""
import time
import httpx
from fastapi import Header, HTTPException
from config import SUPABASE_URL, SUPABASE_PUBLIC_KEY, SUPABASE_CONFIGURED
from database import SupabaseDB

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL_SECONDS = 60
_MAX_CACHE = 512


async def _verify(token: str) -> dict:
    now = time.time()
    hit = _CACHE.get(token)
    if hit and hit[0] > now:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"apikey": SUPABASE_PUBLIC_KEY, "Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        raise HTTPException(503, "Could not reach Supabase Auth. Check SUPABASE_URL and your internet connection.")
    if response.status_code != 200:
        raise HTTPException(401, "Your session has expired or is invalid. Please sign in again.")
    user = response.json()
    if len(_CACHE) >= _MAX_CACHE:
        _CACHE.clear()
    _CACHE[token] = (now + _TTL_SECONDS, user)
    return user


async def get_db(authorization: str | None = Header(default=None)) -> SupabaseDB:
    if not SUPABASE_CONFIGURED:
        raise HTTPException(503, "Supabase is not configured on the server. Set SUPABASE_URL and SUPABASE_PUBLIC_KEY in backend/.env.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required.")
    token = authorization.split(" ", 1)[1].strip()
    user = await _verify(token)
    db = SupabaseDB(token)
    db.user = user  # type: ignore[attr-defined]
    db.role = db.get_app_role(str(user.get("id", "")))  # type: ignore[attr-defined]
    return db
