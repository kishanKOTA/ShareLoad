# Calculation methodology

How ShareLoad estimates the distance, fuel, cost and CO₂ saved when one company's truck carries another company's shipment.

- Code: `services/api/app/routing/routes.py` (baseline vs shared distances) and `services/api/app/impact/engine.py` (fuel, CO₂, cost).
- Inputs: `data/demo/assumptions.json` (**version v2**) and the cached road routes in `data/demo/routes.geojson`.
- Tests: `services/api/tests/test_impact.py` and `test_routing.py` check the numbers below.

All figures are **estimates** from fictional sample data. The app labels CO₂ as "potential CO₂ avoided (estimate)".

## 1. System boundary

**Included**

- Truck movements of the two companies on the matched trip: the carrier's truck, and the truck the shipper would otherwise send.
- Diesel burned by those movements, its CO₂ from combustion only (tank-to-wheel), and its cost at the pump price.

**Not included**

- Upstream (well-to-tank) emissions of producing and delivering the fuel.
- Other greenhouse gases (CH₄, N₂O) and refrigerant leaks.
- Idling, loading and unloading, and any other trucks or trips.
- Driver time, tolls, handling, insurance and contract charges.

## 2. Baseline vs shared

We compare **total vehicle distance across both businesses** for the same day, the same shipment and the same assumptions.

| Scenario | What happens | Movements counted |
| --- | --- | --- |
| **Baseline** (without ShareLoad) | The carrier drives its trip and comes back empty. The shipper sends its own truck there and back. | Carrier outbound + carrier direct return + shipper's round trip |
| **Shared** (with ShareLoad) | The carrier's return trip picks up and drops off the shipper's load. The shipper's truck doesn't move. | Carrier outbound + carrier return via the pickup and drop-off |

- **Detour** = shared return leg − direct return leg. A match is rejected if the detour is longer than the max detour (30 km).
- The saving comes from the shipper's avoided round trip. The carrier's return leg is driven in both scenarios.

## 3. Formulas

| Quantity | Formula |
| --- | --- |
| Fuel (L) | distance (km) × fuel rate (L/100 km) ÷ 100 |
| CO₂ (kg) | fuel (L) × CO₂ factor (kg CO₂/L) |
| Cost ($) | fuel (L) × fuel price ($/L) |
| Net saved | baseline − shared (for distance, fuel, CO₂ and cost) |
| Reduction (%) | net distance ÷ baseline distance × 100 |

- The same fuel rate is used for loaded and empty running.
- Values are calculated unrounded and rounded only for display: km, L and kg to 0.1, $ to 0.01, % to 0.1. So a displayed net value can differ by 0.1 from subtracting the displayed baseline and shared values.
- The app's formula trace shows each input that is an earlier result (fuel, CO₂, cost, net distance) to 2 decimals, so the arithmetic visibly adds up, for example "245.44 L − 125.58 L = 119.9 L". Distances from the route data stay at 1 decimal.
- If the shared plan is longer than the baseline, net saved is negative. The app shows it in a neutral colour as "not recommended".

## 4. Assumptions and sources

From `data/demo/assumptions.json`, version **v2**. All sources were opened on **2026-11-20**.

| Assumption | Value | How it was derived | Source |
| --- | --- | --- | --- |
| Fuel rate | **26 L/100 km** | US box trucks averaged **9.05 mpg** on-road in 2021; 235.2 ÷ 9.05 = 26.0 L/100 km | U.S. DOE Vehicle Technologies Office, [Fact of the Week #1342](https://www.energy.gov/cmei/vehicles/articles/fotw-1342-may-13-2024-average-road-fuel-economy-mediumheavy-trucks-ranged-40) (May 13, 2024), [dataset](https://www.energy.gov/sites/default/files/2024-05/FOTW_1342_web.xlsx) "Average On-Road Fuel Economy by Truck Body Type, 2021" (row "Box truck"), based on the 2021 Vehicle Inventory and Use Survey (BTS / Census) |
| CO₂ factor | **2.70 kg CO₂/L** | Diesel fuel **10.21 kg CO₂ per gallon**; 10.21 ÷ 3.785 L/gal = 2.697 kg/L. Combustion only. | U.S. EPA, [GHG Emission Factors Hub 2025](https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf), Table 2 "Mobile Combustion CO2" (last modified 15 January 2025) |
| Fuel price | **$1.57/L** | US average on-highway diesel retail price **$5.937/gal** for the week of **Nov 16, 2026**; 5.937 ÷ 3.785 = $1.57/L | U.S. EIA, [Gasoline and Diesel Fuel Update](https://www.eia.gov/petroleum/gasdiesel/), "U.S. On-Highway Diesel Fuel Prices" (released Nov 17, 2026) |
| Max detour | **30 km** | Longest extra distance the carrier's truck may drive to pick up a shared load | **Product setting**, not a sourced value |

Unit conversions: 1 US gallon = 3.785 L, and mpg → L/100 km = 235.2 ÷ mpg.

**Change from v1:** v1 used 29 L/100 km (an unsourced "about 8 mpg"), 2.70 kg/L and $0.98/L ($3.70/gal), all marked "TODO: cite". The fuel rate and price changed in v2 to match the sources above. The CO₂ factor is unchanged.

## 5. Worked example (demo scenario)

**NorthStar Regional Freight** (Madison, WI) drives a box truck to a customer in Chicago's West Loop and back. **Lakeview Supply Co.** (Chicago) needs 1,200 kg / 8 m³ moved from its Chicago warehouse to a customer in Madison the same day.

Road distances (OSRM, cached 2026-11-18):

| Leg | km |
| --- | ---: |
| NorthStar outbound: Madison depot → West Loop | 236.4 |
| NorthStar direct return: West Loop → Madison depot | 240.5 |
| Lakeview round trip: warehouse → Madison customer → warehouse | 467.1 |
| NorthStar shared return: West Loop → Lakeview warehouse → Madison customer → Madison depot | 246.6 |

**Distances**

- Baseline = 236.4 + 240.5 + 467.1 = **944.0 km**
- Shared = 236.4 + 246.6 = **483.0 km**
- Detour = 246.6 − 240.5 = **6.1 km** (limit 30 km)

**Fuel, CO₂ and cost**

The engine carries unrounded fuel into the CO₂ and cost steps:

| Step | Baseline | Shared |
| --- | --- | --- |
| Fuel | 944.0 × 26 ÷ 100 = 245.44 → **245.4 L** | 483.0 × 26 ÷ 100 = 125.58 → **125.6 L** |
| CO₂ | 245.44 × 2.70 = 662.69 → **662.7 kg** | 125.58 × 2.70 = 339.07 → **339.1 kg** |
| Cost | 245.44 × $1.57 = **$385.34** | 125.58 × $1.57 = **$197.16** |

**Result**

| | Baseline | Shared | Saved |
| --- | ---: | ---: | ---: |
| Distance | 944.0 km | 483.0 km | **461.0 km (48.8%)** |
| Fuel | 245.4 L | 125.6 L | **119.9 L** |
| CO₂ (estimate) | 662.7 kg | 339.1 kg | **323.6 kg** |
| Fuel cost | $385.34 | $197.16 | **$188.18** |

Fuel saved is 119.9 L, not 245.4 − 125.6 = 119.8 L, because the engine subtracts unrounded values (245.44 − 125.58 = 119.86 L). See section 3.

The app's formula trace for this example:

| Step | Formula | Result |
| --- | --- | ---: |
| Baseline fuel | 944.0 km × 26 L/100 km ÷ 100 | 245.4 L |
| Baseline CO₂ | 245.44 L × 2.7 kg/L | 662.7 kg |
| Baseline cost | 245.44 L × $1.57/L | $385.34 |
| Shared fuel | 483.0 km × 26 L/100 km ÷ 100 | 125.6 L |
| Shared CO₂ | 125.58 L × 2.7 kg/L | 339.1 kg |
| Shared cost | 125.58 L × $1.57/L | $197.16 |
| Net distance saved | 944.0 km − 483.0 km | 461.0 km |
| Net fuel saved | 245.44 L − 125.58 L | 119.9 L |
| Net CO₂ avoided | 662.69 kg − 339.07 kg | 323.6 kg |
| Net cost saved | $385.34 − $197.16 | $188.18 |
| Reduction | 461.00 km ÷ 944.00 km × 100 | 48.8% |

## 6. Limitations

- **Sample data.** Two fictional companies, one truck and three candidate shipments.
- **One fuel rate.** 26 L/100 km is a national average across all US box trucks in 2021, of all fuel types and loads. A real truck's rate depends on its engine, load, speed and route. Loaded and empty running use the same rate.
- **Fuel type.** The CO₂ factor and the price are for diesel, while the fuel-economy average covers box trucks of all fuel types.
- **Price changes weekly.** The diesel price is one week's national retail average. Regional prices differ.
- **Combustion only.** CO₂ excludes upstream fuel production and other gases, so total life-cycle emissions are higher than shown.
- **Cached routes.** Distances are OSRM road routes cached on 2026-11-18. Traffic, closures and actual driver routes are not modelled.
- **Shipper's baseline.** We assume the shipper would otherwise send its own truck there and back. If it would have used a carrier that was already going that way, the real saving is smaller.
