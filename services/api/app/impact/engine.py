"""Fuel, cost and CO2 for the baseline and shared scenarios (docs/PRD.md, "Impact methodology").

- Fuel (L)  = km × (L/100 km) ÷ 100
- CO2 (kg)  = fuel × kg CO2 per litre
- Cost (USD) = fuel × price per litre
- Net saved = baseline − shared (may be negative; shown as "not recommended")
- % reduction = net distance ÷ baseline distance × 100

One fuel rate covers loaded and empty running (stated simplification).
Values are computed unrounded and rounded only for output: km, L and kg to
0.1, USD to 0.01, percent to 0.1.
In the formula trace, an input that is an earlier result (fuel, CO2, cost,
net distance) is shown to 2 decimals so the arithmetic visibly adds up.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.schemas import FormulaStep, Impact, ScenarioMetrics


def _factor(assumptions: Mapping[str, Any], key: str) -> float:
    entry = assumptions[key]
    return float(entry["value"] if isinstance(entry, Mapping) else entry)


def _prior(x: float) -> str:
    """An earlier, unrounded result used as a formula input, shown to 2 decimals."""
    return f"{x:,.2f}"


def _metrics(km: float, fuel: float, co2: float, cost: float) -> ScenarioMetrics:
    return ScenarioMetrics(
        distance_km=round(km, 1), fuel_l=round(fuel, 1), co2_kg=round(co2, 1), cost_usd=round(cost, 2)
    )


def calculate_impact(baseline_km: float, shared_km: float, assumptions: Mapping[str, Any]) -> Impact:
    if baseline_km < 0 or shared_km < 0:
        raise ValueError("distances must not be negative")

    rate = _factor(assumptions, "fuel_l_per_100km")
    co2_per_l = _factor(assumptions, "co2_kg_per_l")
    price = _factor(assumptions, "fuel_price_usd_per_l")

    trace: list[FormulaStep] = []

    def scenario(label: str, km: float) -> tuple[float, float, float]:
        fuel = km * rate / 100
        co2 = fuel * co2_per_l
        cost = fuel * price
        trace.extend([
            FormulaStep(label=f"{label} fuel", formula=f"{km:,.1f} km × {rate:g} L/100 km ÷ 100",
                        value=round(fuel, 1), unit="L"),
            # Inputs that are earlier results are shown to 2 decimals (see _prior),
            # so the arithmetic visibly matches the rounded value.
            FormulaStep(label=f"{label} CO₂", formula=f"{_prior(fuel)} L × {co2_per_l:g} kg/L",
                        value=round(co2, 1), unit="kg"),
            FormulaStep(label=f"{label} cost", formula=f"{_prior(fuel)} L × ${price:g}/L",
                        value=round(cost, 2), unit="USD"),
        ])
        return fuel, co2, cost

    b_fuel, b_co2, b_cost = scenario("Baseline", baseline_km)
    s_fuel, s_co2, s_cost = scenario("Shared", shared_km)

    net_km = baseline_km - shared_km
    net_fuel, net_co2, net_cost = b_fuel - s_fuel, b_co2 - s_co2, b_cost - s_cost
    reduction_pct = net_km / baseline_km * 100 if baseline_km > 0 else 0.0

    trace.extend([
        FormulaStep(label="Net distance saved", formula=f"{baseline_km:,.1f} km − {shared_km:,.1f} km",
                    value=round(net_km, 1), unit="km"),
        FormulaStep(label="Net fuel saved", formula=f"{_prior(b_fuel)} L − {_prior(s_fuel)} L",
                    value=round(net_fuel, 1), unit="L"),
        FormulaStep(label="Net CO₂ avoided", formula=f"{_prior(b_co2)} kg − {_prior(s_co2)} kg",
                    value=round(net_co2, 1), unit="kg"),
        FormulaStep(label="Net cost saved", formula=f"${_prior(b_cost)} − ${_prior(s_cost)}",
                    value=round(net_cost, 2), unit="USD"),
        FormulaStep(label="Reduction", formula=f"{_prior(net_km)} km ÷ {_prior(baseline_km)} km × 100",
                    value=round(reduction_pct, 1), unit="%"),
    ])

    return Impact(
        baseline=_metrics(baseline_km, b_fuel, b_co2, b_cost),
        shared=_metrics(shared_km, s_fuel, s_co2, s_cost),
        net_saved=_metrics(net_km, net_fuel, net_co2, net_cost),
        reduction_pct=round(reduction_pct, 1),
        recommended=net_km > 0,
        formula_trace=trace,
        assumptions_version=str(assumptions.get("version", "unversioned")),
    )
