import services.routing as routing
from database import sample_data
from services.analytics import build_analytics
from services.optimizer import optimize


def test_orders_by_priority_counts_live_rows():
    data = sample_data()
    result = build_analytics(data)["orders_by_priority"]
    assert sum(x["total"] for x in result) == len(data["orders"])


def test_distance_matrix_falls_back_to_haversine(monkeypatch):
    monkeypatch.setattr(routing, "OSRM_ENABLED", False)
    d = sample_data()
    km, minutes, method = routing.distance_matrix(d["depots"][:1] + d["orders"][:2])
    assert method == routing.HAVERSINE_METHOD
    assert km[0][0] == 0 and km[0][1] > 0 and minutes[0][1] > 0


def test_optimizer_serves_sample_orders(monkeypatch):
    monkeypatch.setattr(routing, "OSRM_ENABLED", False)
    result = optimize(sample_data())
    assert result["summary"]["assigned"] > 0
