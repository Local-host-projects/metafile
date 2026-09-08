"""
Timer artifact. {"timers": [{"id","label","duration_seconds","status",
"started_at","accumulated_seconds"}]}

status: "idle" | "running" | "paused" | "done"
Remaining time is never stored directly -- it's computed on every read
from started_at + accumulated_seconds, same reasoning as the spreadsheet
formulas: derive, don't cache, so it can't drift out of sync.
"""
import time
import uuid


def get_state(content: dict) -> dict:
    timers = content.get("timers", [])
    out = []
    for t in timers:
        out.append({**t, "remaining_seconds": _remaining(t)})
    return {"timers": out}


def _remaining(t: dict) -> float:
    duration = t.get("duration_seconds", 0)
    acc = t.get("accumulated_seconds", 0)
    if t.get("status") == "running" and t.get("started_at"):
        acc += time.time() - t["started_at"]
    return max(0.0, duration - acc)


def apply_patch(content: dict, op: str, path, value) -> dict:
    content.setdefault("timers", [])
    if op == "append":
        v = value if isinstance(value, dict) else {"label": value}
        timer = {
            "id": uuid.uuid4().hex[:10],
            "label": v.get("label", "Timer"),
            "duration_seconds": float(v.get("duration_seconds", 300)),
            "status": "idle",
            "started_at": None,
            "accumulated_seconds": 0.0,
        }
        content["timers"].append(timer)
    elif op == "set":
        # value.action: start | pause | reset | relabel
        for t in content["timers"]:
            if t["id"] == path:
                action = (value or {}).get("action") if isinstance(value, dict) else value
                if action == "start" and t["status"] != "running":
                    t["status"] = "running"
                    t["started_at"] = time.time()
                elif action == "pause" and t["status"] == "running":
                    t["accumulated_seconds"] += time.time() - t["started_at"]
                    t["started_at"] = None
                    t["status"] = "paused"
                elif action == "reset":
                    t["status"] = "idle"
                    t["started_at"] = None
                    t["accumulated_seconds"] = 0.0
                elif isinstance(value, dict) and "duration_seconds" in value:
                    t["duration_seconds"] = float(value["duration_seconds"])
                break
        else:
            raise ValueError(f"No timer with id {path}")
    elif op == "delete":
        content["timers"] = [t for t in content["timers"] if t["id"] != path]
    elif op == "bulk_set":
        content["timers"] = value.get("timers", [])
    else:
        raise ValueError(f"Unsupported op for timer artifact: {op}")
    return content
