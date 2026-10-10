import httpx
from config import GEMINI_API_KEY, GEMINI_MODEL

async def explain(payload: dict) -> dict:
    if not GEMINI_API_KEY:
        summary = payload.get("summary", {})
        risks = payload.get("reasons", [])
        return {"mode":"local_fallback","explanation":f'The optimizer assigned {summary.get("assigned",0)} order(s), with {summary.get("unserved",0)} unserved. Estimated distance is {summary.get("distance_km",0)} km and estimated cost is {summary.get("estimated_cost",0)}. These are demo estimates, not verified road-distance costs. Review unserved-order reasons and high-risk products before dispatch.',"recommendations":["Verify stock and vehicle temperature compatibility for unserved orders.","Connect a road-routing provider before using travel-time estimates operationally.","Treat temperature readings as simulated unless a real sensor source is connected."]}
    prompt = ("Explain the following FrostRoute AI optimization results. Only use facts present in the JSON. "
              "Separate computed facts from suggestions. Mention limitations and never invent metrics. JSON:\n" + str(payload)[:12000])
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(url, json={"contents":[{"parts":[{"text":prompt}]}]})
            r.raise_for_status()
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return {"mode":"gemini","explanation":text,"recommendations":[]}
    except Exception as exc:
        return {"mode":"local_fallback","explanation":"Gemini is unavailable; showing a safe fallback. " + str(exc)[:180],"recommendations":["Check API key and model configuration.","Use the deterministic risk and optimization results as the source of truth."]}
