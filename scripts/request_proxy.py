#!/usr/bin/env python3
"""Tiny request proxy for the recommendations site.

POST /request  {tmdbId, mediaType}  ->  create the request in Seerr and auto-approve it.

The Seerr API key is held here server-side (env), never exposed to the browser. This service is
reachable ONLY through the auth-gated nginx (it is not published to the host), so the same basic-auth
login that protects the site also protects requesting. Pure stdlib — runs in a plain python image.
"""
import concurrent.futures
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEERR = os.environ.get("SEERR_BASE", "http://host.docker.internal:5055").rstrip("/")
KEY = os.environ.get("SEERR_API_KEY", "")
PORT = int(os.environ.get("PORT", "8090"))


def seerr(method, path, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        SEERR + path, data=data, method=method,
        headers={"X-Api-Key": KEY, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        ep = self.path.rstrip("/").split("/")[-1]   # "request" | "status"
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": "bad json: %s" % e})
        if not KEY:
            return self._send(500, {"error": "seerr key not configured"})
        if ep == "status":
            return self._status(payload)
        if ep == "request":
            return self._request(payload)
        return self._send(404, {"error": "not found"})

    def _request(self, payload):
        try:
            tmdb = int(payload["tmdbId"])
            mtype = "tv" if payload.get("mediaType") == "tv" else "movie"
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": "bad request: %s" % e})
        body = {"mediaType": mtype, "mediaId": tmdb}
        if mtype == "tv":
            body["seasons"] = "all"
        try:
            _, resp = seerr("POST", "/api/v1/request", body)
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("message", "")
            except Exception:  # noqa: BLE001
                msg = str(e)
            # 409 usually means already requested/available — treat as a soft success
            return self._send(200 if e.code in (409,) else e.code,
                              {"ok": e.code in (409,), "status": "already_exists", "error": msg})
        except Exception as e:  # noqa: BLE001
            return self._send(502, {"error": str(e)})
        rid = (resp or {}).get("id")
        rstatus = (resp or {}).get("status")  # 1 pending, 2 approved
        approved = rstatus == 2
        if rid and rstatus == 1:  # auto-approve if it landed pending
            try:
                seerr("POST", "/api/v1/request/%d/approve" % rid)
                approved = True
            except Exception:  # noqa: BLE001
                pass
        return self._send(200, {"ok": True, "requestId": rid, "approved": approved})

    def _status(self, payload):
        """Batch live availability for the cards: [{tmdbId, mediaType}] -> {"movie-123": statusCode}."""
        items = (payload.get("items") or [])[:200]

        def one(it):
            try:
                tmdb = int(it["tmdbId"])
                mt = "tv" if it.get("mediaType") == "tv" else "movie"
            except Exception:  # noqa: BLE001
                return None
            try:
                _, d = seerr("GET", "/api/v1/%s/%d" % (mt, tmdb), timeout=12)
                code = (d.get("mediaInfo") or {}).get("status") or 0
            except Exception:  # noqa: BLE001
                code = 0
            return ("%s-%d" % (mt, tmdb), code)

        out = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for r in ex.map(one, items):
                if r:
                    out[r[0]] = r[1]
        return self._send(200, out)

    def log_message(self, *a):  # quiet
        pass


if __name__ == "__main__":
    print("request-proxy on :%d -> %s (key %s)" % (PORT, SEERR, "set" if KEY else "MISSING"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
