"""
Three simpler artifact types. Each exposes get_state(content) for reads
and apply_patch(content, op, path, value) for writes -- the same shape
main.py drives spreadsheet.py through too, so routing stays uniform.
"""
import time
import uuid


# ---------- HTML renderer ----------
# Stores raw HTML/CSS/JS. Rendered client-side inside a sandboxed
# iframe (sandbox="allow-scripts", no allow-same-origin) so a hostile
# metafile can't reach the parent page or read its own cookies/tokens.

def html_get_state(content: dict) -> dict:
    return {"html": content.get("html", "")}


def html_apply_patch(content: dict, op: str, path, value) -> dict:
    if op in ("set", "bulk_set"):
        content["html"] = value if isinstance(value, str) else value.get("html", "")
    else:
        raise ValueError(f"Unsupported op for html artifact: {op}")
    return content


# ---------- Canvas ----------
# Stores an ordered list of strokes; frontend replays them onto a
# <canvas>. Append is the common op (one new stroke at a time) so two
# agents drawing concurrently merge rather than overwrite.

def canvas_get_state(content: dict) -> dict:
    return {
        "width": content.get("width", 800),
        "height": content.get("height", 600),
        "strokes": content.get("strokes", []),
    }


def canvas_apply_patch(content: dict, op: str, path, value) -> dict:
    content.setdefault("strokes", [])
    if op == "append":
        stroke = value if isinstance(value, dict) else {"raw": value}
        stroke["id"] = uuid.uuid4().hex[:8]
        stroke["at"] = time.time()
        content["strokes"].append(stroke)
    elif op == "bulk_set":
        content["strokes"] = value.get("strokes", [])
        content["width"] = value.get("width", content.get("width", 800))
        content["height"] = value.get("height", content.get("height", 600))
    elif op == "delete":
        content["strokes"] = [s for s in content["strokes"] if s.get("id") != path]
    else:
        raise ValueError(f"Unsupported op for canvas artifact: {op}")
    return content


# ---------- Facts (the memory substrate) ----------
# {"facts": [{"id":..., "text":..., "tags":[...], "at":...}, ...]}
# This is the piece that plays the same role Mem0's fact store does --
# except portable, addressable, and multi-agent-signed.

def facts_get_state(content: dict) -> dict:
    return {"facts": content.get("facts", [])}


def facts_apply_patch(content: dict, op: str, path, value) -> dict:
    content.setdefault("facts", [])
    if op == "append":
        fact = {
            "id": uuid.uuid4().hex[:10],
            "text": value if isinstance(value, str) else value.get("text", ""),
            "tags": [] if isinstance(value, str) else value.get("tags", []),
            "at": time.time(),
        }
        content["facts"].append(fact)
    elif op == "set":
        # update an existing fact by id (path = fact id)
        for f in content["facts"]:
            if f["id"] == path:
                if isinstance(value, str):
                    f["text"] = value
                else:
                    f.update(value)
                f["at"] = time.time()
                break
        else:
            raise ValueError(f"No fact with id {path}")
    elif op == "delete":
        content["facts"] = [f for f in content["facts"] if f["id"] != path]
    elif op == "bulk_set":
        content["facts"] = value.get("facts", [])
    else:
        raise ValueError(f"Unsupported op for facts artifact: {op}")
    return content


from . import calendar as calendar_artifact
from . import timer as timer_artifact
from . import media as media_artifact

HANDLERS = {
    "html": (html_get_state, html_apply_patch),
    "canvas": (canvas_get_state, canvas_apply_patch),
    "facts": (facts_get_state, facts_apply_patch),
    "calendar": (calendar_artifact.get_state, calendar_artifact.apply_patch),
    "timer": (timer_artifact.get_state, timer_artifact.apply_patch),
    "media": (media_artifact.get_state, media_artifact.apply_patch),
}
