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
        "distance_km": 944.0, "fuel_l": 273.8, "co2_kg": 739.2, "cost_usd": 268.28,
    }
    assert impact.shared.model_dump() == {
        "distance_km": 483.0, "fuel_l": 140.1, "co2_kg": 378.2, "cost_usd": 137.27,
    }
    assert impact.net_saved.model_dump() == {
        "distance_km": 461.0, "fuel_l": 133.7, "co2_kg": 361.0, "cost_usd": 131.02,
    }
    assert impact.reduction_pct == 48.8
    assert impact.recommended
    assert impact.assumptions_version == "v1"


def test_formula_trace(assumptions):
    trace = {s.label: s for s in calculate_impact(944.0, 483.0, assumptions).formula_trace}
    assert trace["Baseline fuel"].formula == "944.0 km × 29 L/100 km ÷ 100"
    assert trace["Baseline fuel"].value == 273.8
    assert trace["Net CO₂ avoided"].value == 361.0
    assert trace["Reduction"].unit == "%"


def test_negative_saving_allowed(assumptions):
    impact = calculate_impact(100.0, 150.0, assumptions)
    assert impact.net_saved.distance_km == -50.0
    assert impact.net_saved.fuel_l == -14.5
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
