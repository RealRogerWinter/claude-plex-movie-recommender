#!/usr/bin/env python3
"""Preview the built site locally. fetch() needs http (not file://), so serve over a port.

    python3 scripts/serve.py --dir ~/recommendations/site --port 8000
then open http://localhost:8000/  (or tunnel the port if you're remote)."""
import argparse
import functools
import http.server
import os
import socketserver

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default=os.path.expanduser("~/recommendations/site"))
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--bind", default="0.0.0.0")
args = ap.parse_args()

os.chdir(args.dir)
http.server.SimpleHTTPRequestHandler.extensions_map.setdefault(".json", "application/json")
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=args.dir)
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer((args.bind, args.port), Handler) as httpd:
    print(f"Serving {args.dir} at http://{args.bind}:{args.port}/  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
