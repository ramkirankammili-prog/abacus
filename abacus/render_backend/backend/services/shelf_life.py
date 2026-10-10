from datetime import date

def shelf_life_risk(product: dict, travel_hours: float = 0, temp_excursion: bool = False) -> dict:
    try:
        days = (date.fromisoformat(product["expiry_date"]) - date.today()).days
    except Exception:
        days = None
    if days is None:
        score, level, reason = 35, "Unknown", "Expiry date could not be parsed."
    else:
        score = 10 if days > 7 else 35 if days > 3 else 65 if days >= 1 else 95
        if travel_hours > max(1, days * 24 - 4):
            score = max(score, 85)
        reason = f"{days} day(s) remaining before expiry."
        if days < 0:
            reason = f"Product expired {abs(days)} day(s) ago."
    if temp_excursion:
        score = min(100, score + 25)
        reason += " Temperature excursion recorded."
    level = "Critical" if score >= 80 else "High" if score >= 60 else "Medium" if score >= 35 else "Low"
    return {"score": min(100, score), "level": level, "reason": reason, "remaining_days": days}
