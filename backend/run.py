"""
Dual-stack launcher.

Opens an explicit IPv4 socket (0.0.0.0) AND an explicit IPv6 socket (::)
so the app answers on every stack — IPv4-only inspectors (like PaaS
route checkers) see a real listener in the IPv4 table, while IPv6
clients (::1, LAN v6) work too. If either family is unavailable the
other still serves.

Port resolution: $PORT env var (PaaS convention), else argv[1], else 8000.
"""
import os
import socket
import sys

import uvicorn

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))


def make_sockets():
    sockets = []
    try:
        v4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        v4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        v4.bind(("0.0.0.0", PORT))
        v4.listen(2048)
        sockets.append(v4)
        print(f"[run] listening IPv4 0.0.0.0:{PORT}")
    except OSError as e:
        print(f"[run] IPv4 bind failed: {e}")
    try:
        v6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            # Force v6-only so this never steals the IPv4 bind on Linux,
            # where the default is dual-stack.
            v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        except OSError:
            pass
        v6.bind(("::", PORT))
        v6.listen(2048)
        sockets.append(v6)
        print(f"[run] listening IPv6 [::]:{PORT}")
    except OSError as e:
        print(f"[run] IPv6 bind failed: {e}")
    if not sockets:
        raise SystemExit(f"[run] could not bind port {PORT}")
    return sockets


if __name__ == "__main__":
    print(f"Metafile serving on http://localhost:{PORT} (IPv4 + IPv6)")
    import asyncio
    config = uvicorn.Config("main:app", log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve(sockets=make_sockets()))
