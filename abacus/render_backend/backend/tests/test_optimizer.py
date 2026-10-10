from services.shelf_life import shelf_life_risk
from services.routing import haversine_km

def test_haversine_same_point():
    assert haversine_km(17.4, 78.4, 17.4, 78.4) == 0

def test_shelf_life_returns_score():
    p = {"expiry_date":"2099-01-01"}
    result = shelf_life_risk(p)
    assert 0 <= result["score"] <= 100
    assert result["level"] in {"Low","Medium","High","Critical","Unknown"}
