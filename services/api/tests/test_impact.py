import json
from pathlib import Path

import pytest

from app.impact import calculate_impact

DEMO = Path(__file__).resolve().parents[3] / "data" / "demo"


@pytest.fixture(scope="module")
def assumptions() -> dict:
    return json.loads((DEMO / "assumptions.json").read_text(encoding="utf-8"))


def test_demo_numbers_match_prd(assumptions):
    impact = calculate_impact(944.0, 483.0, assumptions)
    assert impact.baseline.model_dump() == {
        "distance_km": 944.0, "fuel_l": 245.4, "co2_kg": 662.7, "cost_usd": 385.34,
    }
    assert impact.shared.model_dump() == {
        "distance_km": 483.0, "fuel_l": 125.6, "co2_kg": 339.1, "cost_usd": 197.16,
    }
    assert impact.net_saved.model_dump() == {
        "distance_km": 461.0, "fuel_l": 119.9, "co2_kg": 323.6, "cost_usd": 188.18,
    }
    assert impact.reduction_pct == 48.8
    assert impact.recommended
    assert impact.assumptions_version == "v2"


def test_formula_trace(assumptions):
    trace = {s.label: s for s in calculate_impact(944.0, 483.0, assumptions).formula_trace}
    assert trace["Baseline fuel"].formula == "944.0 km × 26 L/100 km ÷ 100"
    assert trace["Baseline fuel"].value == 245.4
    assert trace["Net CO₂ avoided"].value == 323.6
    assert trace["Reduction"].unit == "%"


def test_negative_saving_allowed(assumptions):
    impact = calculate_impact(100.0, 150.0, assumptions)
    assert impact.net_saved.distance_km == -50.0
    assert impact.net_saved.fuel_l == -13.0
    assert impact.net_saved.co2_kg < 0
    assert impact.reduction_pct == -50.0
    assert not impact.recommended


def test_zero_baseline(assumptions):
    impact = calculate_impact(0.0, 0.0, assumptions)
    assert impact.reduction_pct == 0.0
    assert not impact.recommended


def test_negative_distance_rejected(assumptions):
    with pytest.raises(ValueError):
        calculate_impact(-1.0, 10.0, assumptions)
