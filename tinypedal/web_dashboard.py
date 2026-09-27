#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Web dashboard: show live telemetry on phone or tablet (browser), disabled by default

    GET /?code=<access code>          dashboard page
    GET /api/telemetry                live data (JSON), requires "X-Access-Code" header

Listens on 127.0.0.1 only, unless LAN access is enabled. Access code is always required,
and repeated wrong codes from same address are blocked for a while.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import app_signal
from .const_file import ConfigType
from .setting import cfg

logger = logging.getLogger(__name__)

MAX_FAILURES = 10
LOCKOUT_SECONDS = 60
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O, 1/I


def generate_access_code(length: int = 8) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def local_addresses() -> list[str]:
    """LAN IPv4 addresses of this computer"""
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = str(info[4][0])
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    try:  # address of default route (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(addresses)


def _safe(func, default=0.0):
    try:
        return func()
    except Exception:  # API not ready, missing data
        return default


def _quad(func) -> list[float]:
    """Four wheel values, zeros if unavailable"""
    values = _safe(func, ())
    try:
        return [round(float(value), 1) for value in values[:4]] or [0.0] * 4
    except (TypeError, ValueError):
        return [0.0] * 4


def telemetry_snapshot() -> dict:
    """Current telemetry for dashboard"""
    from .api_control import api
    from .module_info import minfo

    read = api.read
    if read is None:
        return {"active": False}
    fuel = minfo.fuel
    delta = minfo.delta
    return {
        "active": bool(_safe(read.state.active, False)),
        "speed": round(_safe(read.vehicle.speed) * 3.6, 1),
        "gear": _safe(read.engine.gear, 0),
        "rpm": round(_safe(read.engine.rpm)),
        "rpm_max": round(_safe(read.engine.rpm_max)),
        "throttle": round(_safe(read.inputs.throttle), 3),
        "brake": round(_safe(read.inputs.brake), 3),
        "position": _safe(read.vehicle.place, 0),
        "vehicles": _safe(read.vehicle.total_vehicles, 0),
        "lap": _safe(read.lap.number, 0),
        "delta_best": round(delta.deltaBest, 3),
        "lap_current": round(delta.lapTimeCurrent, 3),
        "lap_last": round(delta.lapTimeLast, 3),
        "lap_best": round(delta.lapTimeBest, 3),
        "fuel": round(fuel.amountCurrent, 2),
        "fuel_laps": round(fuel.estimatedLaps, 1),
        "fuel_per_lap": round(fuel.estimatedConsumption, 3),
        "tyre_temp": _quad(read.tyre.surface_temperature_avg),
        "brake_temp": _quad(read.brake.temperature),
        "track_temp": round(_safe(read.session.track_temperature), 1),
        "time_remaining": round(_safe(read.session.remaining)),
        "track": _safe(read.session.track_name, ""),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    """Dashboard request handler"""

    server_version = "TinyPedal"
    access_code = ""
    failures: dict[str, list[float]] = {}  # address: [count, blocked until]
    lock = threading.Lock()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/telemetry":
            if self.authorized(self.headers.get("X-Access-Code", "")):
                try:
                    body = json.dumps(telemetry_snapshot()).encode("utf-8")
                except Exception:  # never drop connection on data error
                    logger.debug("WEB DASHBOARD: snapshot error", exc_info=True)
                    body = b'{"active": false}'
                self.send_body(200, body, "application/json")
            return
        if url.path in ("/", "/index.html"):
            code = parse_qs(url.query).get("code", [""])[0]
            if self.authorized(code, html=True):
                self.send_body(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        self.send_body(404, b"not found", "text/plain")

    def authorized(self, code: str, html: bool = False) -> bool:
        """Check access code, block address after repeated failures"""
        address = self.client_address[0]
        now = time.monotonic()
        with self.lock:
            count, until = self.failures.get(address, [0, 0.0])
            if until > now:
                self.send_body(429, b"too many attempts, try again later", "text/plain")
                return False
            if code and hmac.compare_digest(code.encode("utf-8"), self.access_code.encode("utf-8")):
                self.failures.pop(address, None)
                return True
            count += 1
            self.failures[address] = [count, now + LOCKOUT_SECONDS if count >= MAX_FAILURES else 0.0]
        if html:
            self.send_body(401, LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self.send_body(401, b'{"error": "invalid access code"}', "application/json")
        return False

    def send_body(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.debug("WEB DASHBOARD: %s", format % args)


class WebDashboard:
    """Web dashboard server control"""

    __slots__ = ("_server", "_thread")

    def __init__(self):
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @staticmethod
    def access_code() -> str:
        """Access code, generated and saved on first use"""
        setting = cfg.user.config["web_dashboard"]
        code = str(setting["access_code"]).strip()
        if len(code) < 6:
            code = generate_access_code()
            setting["access_code"] = code
            cfg.save(config_type=ConfigType.CONFIG)
        return code

    @staticmethod
    def host() -> str:
        return "0.0.0.0" if cfg.user.config["web_dashboard"]["enable_lan_access"] else "127.0.0.1"

    @staticmethod
    def port() -> int:
        return int(cfg.user.config["web_dashboard"]["web_dashboard_port"])

    def urls(self) -> list[str]:
        """Dashboard addresses with access code"""
        code = self.access_code()
        hosts = local_addresses() if cfg.user.config["web_dashboard"]["enable_lan_access"] else []
        return [f"http://{host}:{self.port()}/?code={code}" for host in ("127.0.0.1", *hosts)]

    def enable(self):
        """Start server if enabled in setting"""
        if not cfg.user.config["web_dashboard"]["enable_web_dashboard"] or self.running:
            return
        DashboardHandler.access_code = self.access_code()
        DashboardHandler.failures = {}
        host, port = self.host(), self.port()
        try:
            self._server = ThreadingHTTPServer((host, port), DashboardHandler)
        except OSError as error:
            logger.error("WEB DASHBOARD: unable to listen on %s:%s (%s)", host, port, error)
            app_signal.error.emit(f"Web dashboard: port {port} unavailable ({error.strerror}).")
            return
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="Web dashboard")
        self._thread.start()
        logger.info("ENABLED: web dashboard on http://%s:%s", host, port)

    def disable(self):
        """Stop server"""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        logger.info("DISABLED: web dashboard")


webdashboard = WebDashboard()

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TinyPedal</title>
<style>body{background:#0e1116;color:#e9ecf1;font-family:system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}form{display:flex;gap:8px}
input,button{font-size:20px;padding:10px;border-radius:8px;border:1px solid #373e4c;background:#1b1f27;color:#e9ecf1}
</style></head><body><form method="get" action="/"><input name="code" placeholder="Access code" autofocus
autocomplete="off"><button>OK</button></form></body></html>"""

DASHBOARD_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0e1116"><title>TinyPedal Dashboard</title>
<style>
:root{--bg:#0e1116;--panel:#1b1f27;--line:#2a303c;--text:#e9ecf1;--muted:#9aa3b2;
--green:#34c759;--red:#ff4d4f;--blue:#38bdf8;--yellow:#ffd43b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
main{display:grid;gap:10px;padding:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.label{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.05em}
.value{font-size:34px;font-weight:700;line-height:1.2}.big{grid-column:span 2}
.huge{font-size:84px;text-align:center}.bar{height:12px;border-radius:6px;background:var(--line);overflow:hidden;margin-top:6px}
.bar>div{height:100%;width:0}.grid4{display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:22px}
#status{padding:6px 12px;color:var(--muted);font-size:13px}.pos{color:var(--green)}.neg{color:var(--red)}
</style></head><body>
<div id="status">Connecting…</div>
<main>
<div class="card big"><div class="label">Gear · Speed</div>
<div class="value huge"><span id="gear">N</span> <span id="speed" style="font-size:48px">0</span>
<span style="font-size:18px">km/h</span></div>
<div class="bar"><div id="rpmbar" style="background:var(--blue)"></div></div></div>
<div class="card"><div class="label">Delta best</div><div class="value" id="delta">+0.000</div></div>
<div class="card"><div class="label">Position</div><div class="value" id="position">-</div></div>
<div class="card"><div class="label">Current lap</div><div class="value" id="lapcur">-:--.---</div></div>
<div class="card"><div class="label">Last lap</div><div class="value" id="laplast">-:--.---</div></div>
<div class="card"><div class="label">Best lap</div><div class="value" id="lapbest">-:--.---</div></div>
<div class="card"><div class="label">Fuel · laps left</div><div class="value" id="fuel">0</div>
<div style="font-size:18px;color:var(--muted)" id="fuellaps">0.0</div></div>
<div class="card"><div class="label">Throttle · Brake</div>
<div class="bar"><div id="thr" style="background:var(--green)"></div></div>
<div class="bar"><div id="brk" style="background:var(--red)"></div></div></div>
<div class="card"><div class="label">Tyre °C</div><div class="grid4" id="tyres"></div></div>
<div class="card"><div class="label">Brake °C</div><div class="grid4" id="brakes"></div></div>
<div class="card"><div class="label">Time left</div><div class="value" id="remain">--:--</div></div>
</main>
<script>
const code=new URLSearchParams(location.search).get("code")||"";
const $=id=>document.getElementById(id);
const lap=t=>{if(!(t>0))return"-:--.---";const m=Math.floor(t/60);return m+":"+(t-m*60).toFixed(3).padStart(6,"0")};
const hms=t=>{if(!(t>0))return"--:--";t=Math.floor(t);const h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=t%60;
return(h?h+":"+String(m).padStart(2,"0"):m)+":"+String(s).padStart(2,"0")};
const quad=v=>v.map(x=>"<div>"+Math.round(x)+"</div>").join("");
async function tick(){
try{const r=await fetch("/api/telemetry",{headers:{"X-Access-Code":code},cache:"no-store"});
if(r.status===401){$("status").textContent="Invalid access code";return setTimeout(tick,3000)}
if(!r.ok)throw new Error(r.status);const d=await r.json();
$("status").textContent=d.active?(d.track||"On track"):"Waiting for session…";
$("gear").textContent=d.gear>0?d.gear:(d.gear<0?"R":"N");$("speed").textContent=Math.round(d.speed||0);
$("rpmbar").style.width=(d.rpm_max>0?Math.min(d.rpm/d.rpm_max,1)*100:0)+"%";
const dl=d.delta_best||0;$("delta").textContent=(dl>=0?"+":"")+dl.toFixed(3);
$("delta").className="value "+(dl>0?"neg":"pos");
$("position").textContent=d.position?d.position+"/"+d.vehicles:"-";
$("lapcur").textContent=lap(d.lap_current);$("laplast").textContent=lap(d.lap_last);$("lapbest").textContent=lap(d.lap_best);
$("fuel").textContent=(d.fuel||0).toFixed(1);$("fuellaps").textContent=(d.fuel_laps||0).toFixed(1)+" laps";
$("thr").style.width=(d.throttle*100)+"%";$("brk").style.width=(d.brake*100)+"%";
$("tyres").innerHTML=quad(d.tyre_temp||[]);$("brakes").innerHTML=quad(d.brake_temp||[]);
$("remain").textContent=hms(d.time_remaining);setTimeout(tick,150)}
catch(e){$("status").textContent="Connection lost, retrying…";setTimeout(tick,2000)}}
tick();
</script></body></html>"""
