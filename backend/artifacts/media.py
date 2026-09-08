"""
Media artifact. {"items": [{"id","kind","mime","data_base64","caption","at"}]}
kind: "image" | "audio" | "video"

Binary data is base64-encoded inside the same content blob everything
else uses -- no separate object storage in this pass, which is why the
byte cap matters more here than anywhere else: base64 inflates raw
bytes by ~33%, so a 5MB free cap holds roughly 3.7MB of actual media.
"""
import time
import uuid

ALLOWED_KINDS = {"image", "audio", "video"}


def get_state(content: dict) -> dict:
    # strip the (large) base64 payload from the list view; fetch by id for the real bytes
    items = content.get("items", [])
    return {"items": [
        {k: v for k, v in item.items() if k != "data_base64"} | {"has_data": bool(item.get("data_base64"))}
        for item in items
    ]}


def get_item(content: dict, item_id: str):
    for item in content.get("items", []):
        if item["id"] == item_id:
            return item
    return None


def apply_patch(content: dict, op: str, path, value) -> dict:
    content.setdefault("items", [])
    if op == "append":
        if not isinstance(value, dict):
            raise ValueError("Media append needs {kind, mime, data_base64, caption?}")
        kind = value.get("kind")
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"kind must be one of {sorted(ALLOWED_KINDS)}")
        if not value.get("data_base64"):
            raise ValueError("data_base64 is required")
        item = {
            "id": uuid.uuid4().hex[:10],
            "kind": kind,
            "mime": value.get("mime", "application/octet-stream"),
            "data_base64": value["data_base64"],
            "caption": value.get("caption", ""),
            "at": time.time(),
        }
        content["items"].append(item)
    elif op == "set":
        for item in content["items"]:
            if item["id"] == path:
                if isinstance(value, dict):
                    item.update({k: v for k, v in value.items() if k in ("caption", "mime")})
                break
        else:
            raise ValueError(f"No media item with id {path}")
    elif op == "delete":
        content["items"] = [i for i in content["items"] if i["id"] != path]
    elif op == "bulk_set":
        content["items"] = value.get("items", [])
    else:
        raise ValueError(f"Unsupported op for media artifact: {op}")
    return content
