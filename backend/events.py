"""
In-process pub/sub bus for live sync (SSE).

Subscribers get a stdlib thread-safe queue; mutations (which run in
FastAPI's threadpool) publish from their threads; the SSE generators
drain the queues from the event loop. Single-worker only -- a multi-
worker deployment would need redis instead. Keys: ("mf", id) and
("sess", id).
"""
import queue
import threading


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs = {}  # key -> set(queue.Queue)

    def subscribe(self, key):
        q = queue.Queue(maxsize=256)
        with self._lock:
            self._subs.setdefault(key, set()).add(q)
        return q

    def unsubscribe(self, key, q):
        with self._lock:
            subs = self._subs.get(key)
            if subs is not None:
                subs.discard(q)
                if not subs:
                    self._subs.pop(key, None)

    def publish(self, key, event):
        with self._lock:
            subs = list(self._subs.get(key, ()))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow subscriber: drop; clients re-fetch on next event


bus = EventBus()
