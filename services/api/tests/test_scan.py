import json
import shutil
from pathlib import Path

from app.matching.scan import DEMO_DIR, clear_scan_cache, get_opportunity, scan_opportunities
from app.schemas import ReasonCode


def test_demo_scan_finds_one_match_and_rejects_two():
    scan = scan_opportunities()
    # trip-a-outbound has no spare capacity, so only the return leg is paired.
    assert scan.candidates_considered == 3

    assert [o.shipment_id for o in scan.opportunities] == ["ship-b"]
    match = scan.opportunities[0]
    assert match.trip_id == "trip-a-return"
    assert match.baseline.distance_km == 944.0
    assert match.shared.distance_km == 483.0
    assert match.impact.net_saved.co2_kg == 323.6
    assert match.impact.recommended

    rejected = {o.shipment_id: o.reason_codes for o in scan.rejected}
    assert rejected == {
        "ship-b-reefer": [ReasonCode.CARGO_TEMP_UNSUPPORTED],
        "ship-b-late": [ReasonCode.TIME_WINDOW_CONFLICT],
    }
    assert all(o.impact is None for o in scan.rejected)


def test_get_opportunity_returns_feasible_and_rejected():
    assert get_opportunity("opp-trip-a-return-ship-b").feasible
    rejected = get_opportunity("opp-trip-a-return-ship-b-late")
    assert rejected.reason_codes == [ReasonCode.TIME_WINDOW_CONFLICT]
    assert get_opportunity("opp-nope") is None


def test_results_are_copies():
    scan_opportunities().opportunities[0].reason_codes.append(ReasonCode.HAZMAT_UNSUPPORTED)
    assert get_opportunity("opp-trip-a-return-ship-b").reason_codes == []


def test_clear_scan_cache_picks_up_fixture_changes(tmp_path: Path):
    for name in ("trips.json", "shipments.json", "vehicles.json", "assumptions.json", "routes.geojson"):
        shutil.copy(DEMO_DIR / name, tmp_path / name)
    assert len(scan_opportunities(tmp_path).opportunities) == 1

    shipments = json.loads((tmp_path / "shipments.json").read_text(encoding="utf-8"))
    for s in shipments:
        if s["id"] == "ship-b":
            s["weight_kg"] = 4500.1  # just over the truck's spare capacity
    (tmp_path / "shipments.json").write_text(json.dumps(shipments), encoding="utf-8")

    assert len(scan_opportunities(tmp_path).opportunities) == 1  # still cached
    clear_scan_cache()
    rescanned = scan_opportunities(tmp_path)
    assert rescanned.opportunities == []
    assert ReasonCode.CAPACITY_WEIGHT_EXCEEDED in next(
        o.reason_codes for o in rescanned.rejected if o.shipment_id == "ship-b"
    )
