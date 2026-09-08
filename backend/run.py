"""
Dual-stack launcher.

Binds [::] with the IPv6-V6ONLY flag cleared so a single server answers
on IPv4 and IPv6 alike (fixes browsers that resolve `localhost` to ::1;
on hosts without IPv6 it falls back to plain 0.0.0.0).

Port resolution: $PORT env var (PaaS convention -- Railway sets this),
else argv[1], else 8000.
"""
import os
import socket
import sys

import uvicorn

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))


def make_socket():
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", PORT))
    except OSError:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", PORT))
    sock.listen(2048)
    return sock


if __name__ == "__main__":
    print(f"Metafile serving on http://localhost:{PORT} (dual-stack)")
    import asyncio
    config = uvicorn.Config("main:app", log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve(sockets=[make_socket()]))
