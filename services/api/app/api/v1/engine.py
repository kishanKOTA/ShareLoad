"""Platform adapter around Kishan's engines; never recomputes feasibility or impact."""
import fcntl
import hashlib
import shutil
from contextlib import contextmanager
from pathlib import Path

from app.agent.agent import AgentScanResult, CACHE_FILENAME
from app.api.v1.fixtures import load_fixtures


class EngineWorkspace:
    def __init__(self, source: Path, runtime: Path):
        self.source = source
        self.runtime = runtime
        self.data_dir = None

    @contextmanager
    def locked(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / "engine.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if self.data_dir is None:
                    self.prepare()
                yield self.data_dir
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def prepare(self):
        load_fixtures(self.source)
        files = sorted(p for p in self.source.iterdir()
                       if p.suffix in {".json", ".geojson"} and p.name != CACHE_FILENAME)
        signature = hashlib.sha256()
        for path in files:
            signature.update(path.name.encode())
            signature.update(path.read_bytes())
        target = self.runtime / signature.hexdigest()
        target.mkdir(parents=True, exist_ok=True)
        for path in files:
            if not (target / path.name).exists():
                shutil.copyfile(path, target / path.name)
        self.data_dir = target
        seed = self.source / CACHE_FILENAME
        if seed.exists() and not (target / CACHE_FILENAME).exists():
            shutil.copyfile(seed, target / CACHE_FILENAME)

    def reset_cache(self):
        # The source checkout remains read-only; restore the writable input copy.
        for source in self.source.iterdir():
            if source.suffix in {".json", ".geojson"} and source.name != CACHE_FILENAME:
                shutil.copyfile(source, self.data_dir / source.name)
        path = self.data_dir / CACHE_FILENAME
        path.unlink(missing_ok=True)
        if (self.source / CACHE_FILENAME).exists():
            shutil.copyfile(self.source / CACHE_FILENAME, path)


def parties_for(opportunity, data):
    trip = next(t for t in data.trips if t.id == opportunity.trip_id)
    shipment = next(s for s in data.shipments if s.id == opportunity.shipment_id)
    return [trip.org_id, shipment.org_id]


def scoped_scan(result: AgentScanResult, org_id: str, data) -> AgentScanResult:
    visible = [o for o in (*result.opportunities, *result.rejected)
               if org_id in parties_for(o, data)]
    pairs = {(o.trip_id, o.shipment_id) for o in visible}
    all_visible = len(visible) == len(result.opportunities) + len(result.rejected)
    calls = []
    for call in result.tool_calls:
        name, args = call.get("name"), call.get("args", {})
        if name == "list_candidates" and all_visible:
            calls.append({"name": name, "args": {}, "ok": bool(call.get("ok")),
                          "summary": call.get("summary", "") if call.get("ok") else "Tool call failed"})
        elif name in {"validate_candidate", "evaluate_routes", "calculate_impact"} and (
                args.get("trip_id"), args.get("shipment_id")) in pairs:
            calls.append({"name": name, "args": {"trip_id": args["trip_id"], "shipment_id": args["shipment_id"]},
                          "ok": bool(call.get("ok")),
                          "summary": call.get("summary", "") if call.get("ok") else "Tool call failed"})
    return AgentScanResult(**(result.model_dump() | {
        "opportunities": [o for o in visible if o.feasible],
        "rejected": [o for o in visible if not o.feasible],
        "candidates_considered": len(visible), "tool_calls": calls,
        # Never synthesize a new AI summary or expose a global one for a subset.
        "agent_summary": result.agent_summary if all_visible else "",
        "template_explanations": [i for i in result.template_explanations if i in {o.id for o in visible}],
        "fallback_reason": result.fallback_reason,
    }))
