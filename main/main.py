"""TinyOSControll main service.

One container that provides:
  * an HTTPS web UI + JSON API + SSE (port 8443, static API token auth),
  * an mTLS WebSocket management endpoint that agents connect to (port 9443),
  * Wake-on-LAN (sent from main, which is always up and holds the MAC list),
  * a JSON-lines audit log.

main holds no host access itself; every host operation is forwarded to the
target agent, which runs it through the fixed hostcmd.sh dispatcher.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import signal
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from aiohttp import web
from aiohttp import WSMsgType

from common import protocol as P
from common import tlsutil, wol

log = logging.getLogger("tinyos.main")


@dataclass
class AgentInfo:
    name: str
    mac: str
    ip: str = ""
    online: bool = False
    last_seen: float = 0.0
    telemetry: dict = field(default_factory=dict)
    ws: Optional["web.WebSocketResponse"] = None
    session: str = ""
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class Config:
    web_port: int
    mgmt_port: int
    cert_dir: str
    agent_token: str
    api_token: str
    audit_log: str
    web_root: str
    agents: list = field(default_factory=list)

    @property
    def ca(self) -> str:
        return os.path.join(self.cert_dir, "cert.crt")

    @property
    def cert(self) -> str:
        return os.path.join(self.cert_dir, "cert.crt")

    @property
    def key(self) -> str:
        return os.path.join(self.cert_dir, "cert.key")


def load_config() -> Config:
    count = int(os.environ.get("AGENTS_COUNT", "0"))
    agents: list[AgentInfo] = []
    for i in range(1, count + 1):
        name = os.environ.get(f"AGENT_{i}_NAME", "").strip()
        mac = os.environ.get(f"AGENT_{i}_MAC", "").strip()
        if not name or not mac:
            continue
        agents.append(AgentInfo(name=name, mac=mac,
                                ip=os.environ.get(f"AGENT_{i}_IP", "").strip()))
    return Config(
        web_port=int(os.environ.get("WEB_PORT", "8443")),
        mgmt_port=int(os.environ.get("MGMT_PORT", "9443")),
        cert_dir=os.environ.get("CERT_DIR", "/certs"),
        agent_token=os.environ.get("AGENT_TOKEN", ""),
        api_token=os.environ.get("API_TOKEN", ""),
        audit_log=os.environ.get("AUDIT_LOG", "/var/log/tinyos/audit.jsonl"),
        web_root=os.environ.get("WEB_ROOT", "/opt/tinyos/web"),
        agents=agents,
    )


class Main:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.agents: dict[str, AgentInfo] = {a.name: a for a in cfg.agents}
        self.sse_clients: set[web.StreamResponse] = set()
        self.pending: dict[str, asyncio.Future] = {}
        self._audit_lock = asyncio.Lock()

    # --- audit + broadcast -------------------------------------------------
    async def audit(self, event: str, **data: Any) -> None:
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": event, **data}
        try:
            async with self._audit_lock:
                os.makedirs(os.path.dirname(self.cfg.audit_log) or ".", exist_ok=True)
                with open(self.cfg.audit_log, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(line) + "\n")
        except OSError as exc:
            log.warning("audit write failed: %s", exc)

    async def broadcast(self, event: str, payload: dict) -> None:
        if not self.sse_clients:
            return
        msg = f"data: {json.dumps({'event': event, 'data': payload})}\n\n"
        dead = []
        for resp in list(self.sse_clients):
            try:
                await resp.write(msg.encode("utf-8"))
            except Exception:  # noqa: BLE001
                dead.append(resp)
        for resp in dead:
            self.sse_clients.discard(resp)

    async def _send(self, agent: AgentInfo, msg: dict) -> None:
        async with agent.send_lock:
            if agent.ws is not None and not agent.ws.closed:
                await agent.ws.send_str(P.encode(msg))

    async def forward(self, agent: AgentInfo, action: str,
                      payload: dict | None = None, timeout: float = 15.0) -> dict:
        if agent.ws is None or agent.ws.closed:
            raise web.HTTPServiceUnavailable(text="agent offline")
        req = P.make_request(action, payload)
        rid = req["id"]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            await self._send(agent, req)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self.pending.pop(rid, None)

    def _require_token(self, request: web.Request) -> None:
        # Header is preferred; the query param exists so the browser's
        # EventSource (which cannot set headers) can use the SSE stream.
        provided = request.headers.get("X-API-Key", "") or request.query.get("token", "")
        if not hmac.compare_digest(provided, self.cfg.api_token):
            raise web.HTTPUnauthorized(text="bad api key")

    def _agent(self, name: str) -> AgentInfo:
        agent = self.agents.get(name)
        if agent is None:
            raise web.HTTPNotFound(text="unknown agent")
        return agent

    # --- management WebSocket (mTLS) ---------------------------------------
    async def handle_mgmt_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        try:
            raw = await asyncio.wait_for(ws.receive(), timeout=10)
        except asyncio.TimeoutError:
            await ws.close()
            return ws
        if raw.type != WSMsgType.TEXT:
            await ws.close()
            return ws
        try:
            msg = P.decode(raw.data)
        except P.ProtocolError:
            await ws.close()
            return ws
        if msg["type"] != P.HELLO:
            await ws.send_str(P.encode(P.make_hello_err("expected hello")))
            await ws.close()
            return ws

        name = msg.get("agent")
        token = msg.get("token") or ""
        agent = self.agents.get(name)
        if agent is None or not hmac.compare_digest(token, self.cfg.agent_token):
            await ws.send_str(P.encode(P.make_hello_err("unauthorized")))
            await self.audit("agent_rejected", agent=name)
            await ws.close()
            return ws

        # replace any stale connection for this agent
        if agent.ws is not None and not agent.ws.closed:
            try:
                await agent.ws.close()
            except Exception:  # noqa: BLE001
                pass
        agent.ws = ws
        agent.online = True
        agent.last_seen = time.time()
        agent.session = uuid.uuid4().hex
        sess = agent.session
        await ws.send_str(P.encode(P.make_hello_ok()))
        await self.audit("agent_online", agent=name)
        await self.broadcast("status", {"agent": name, "online": True})

        try:
            async for raw in ws:
                if raw.type == WSMsgType.TEXT:
                    try:
                        m = P.decode(raw.data)
                    except P.ProtocolError:
                        continue
                    t = m["type"]
                    if t == P.TELEMETRY:
                        agent.telemetry = m.get("payload", {})
                        agent.last_seen = time.time()
                        await self.broadcast("telemetry",
                                             {"agent": name, "data": agent.telemetry})
                    elif t == P.RESPONSE:
                        fut = self.pending.get(m["id"])
                        if fut is not None and not fut.done():
                            fut.set_result(m)
                    elif t == P.PONG:
                        pass
                elif raw.type in (WSMsgType.CLOSE, WSMsgType.CLOSING,
                                  WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        finally:
            if agent.session == sess:
                agent.online = False
                agent.ws = None
                agent.telemetry = {}
                await self.audit("agent_offline", agent=name)
                await self.broadcast("status", {"agent": name, "online": False})
        return ws

    # --- web API -----------------------------------------------------------
    async def api_agents(self, request: web.Request) -> web.Response:
        self._require_token(request)
        out = []
        for a in self.agents.values():
            out.append({
                "name": a.name, "online": a.online, "mac": a.mac, "ip": a.ip,
                "last_seen": a.last_seen, "telemetry": a.telemetry,
            })
        return web.json_response(out)

    async def api_telemetry(self, request: web.Request) -> web.Response:
        self._require_token(request)
        agent = self._agent(request.match_info["name"])
        return web.json_response({"name": agent.name, "online": agent.online,
                                  "telemetry": agent.telemetry})

    async def _do_action(self, request: web.Request, action: str,
                         label: str, payload: dict | None = None) -> web.Response:
        self._require_token(request)
        agent = self._agent(request.match_info["name"])
        try:
            resp = await self.forward(agent, action, payload)
            ok = bool(resp.get("ok"))
            err = resp.get("error")
        except web.HTTPServiceUnavailable as exc:
            await self.audit(label, agent=agent.name, ok=False, error=str(exc))
            raise
        except Exception as exc:  # noqa: BLE001
            ok, err = False, str(exc)
        await self.audit(label, agent=agent.name, ok=ok, error=err)
        await self.broadcast("action", {"agent": agent.name, "action": label,
                                        "ok": ok, "error": err})
        return web.json_response({"ok": ok, "error": err})

    async def api_poweroff(self, request: web.Request) -> web.Response:
        return await self._do_action(request, P.ACTION_POWEROFF, "poweroff")

    async def api_reboot(self, request: web.Request) -> web.Response:
        return await self._do_action(request, P.ACTION_REBOOT, "reboot")

    async def api_container_action(self, request: web.Request) -> web.Response:
        self._require_token(request)
        mi = request.match_info
        action = mi["action"]
        if action not in P.ALL_CONTAINER_ACTIONS:
            raise web.HTTPBadRequest(text="invalid action")
        agent = self._agent(mi["name"])
        payload = {"container": mi["container"], "action": action}
        return await self._do_action(request, P.ACTION_CONTAINERS_ACTION,
                                     f"container.{action}", payload)

    async def api_containers(self, request: web.Request) -> web.Response:
        self._require_token(request)
        agent = self._agent(request.match_info["name"])
        try:
            resp = await self.forward(agent, P.ACTION_CONTAINERS_LIST)
        except web.HTTPServiceUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise web.HTTPBadGateway(text=str(exc))
        if not resp.get("ok"):
            raise web.HTTPBadGateway(text=resp.get("error") or "agent error")
        return web.json_response(resp.get("payload") or {})

    async def api_wake(self, request: web.Request) -> web.Response:
        self._require_token(request)
        agent = self._agent(request.match_info["name"])
        loop = asyncio.get_running_loop()
        dest = await loop.run_in_executor(
            None, wol.send_wol, agent.mac, agent.ip or None)
        await self.audit("wake", agent=agent.name, mac=agent.mac, dest=dest)
        await self.broadcast("action", {"agent": agent.name, "action": "wake",
                                        "ok": True, "dest": dest})
        return web.json_response({"ok": True, "dest": dest})

    async def api_stream(self, request: web.Request) -> web.StreamResponse:
        self._require_token(request)
        resp = web.StreamResponse()
        resp.headers["Content-Type"] = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)
        self.sse_clients.add(resp)
        try:
            await resp.write(b"retry: 2000\n\n")
            while True:
                await asyncio.sleep(15)
                await resp.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.sse_clients.discard(resp)
        return resp

    async def serve_index(self, request: web.Request) -> web.Response:
        # aiohttp's static handler 403s on a directory request, so serve the
        # SPA entry point explicitly for "/".
        return web.FileResponse(os.path.join(self.cfg.web_root, "index.html"))


def create_web_app(main: Main) -> web.Application:
    """UI + API + SSE. Served over TLS without a client certificate."""
    app = web.Application()
    app.router.add_get("/api/agents", main.api_agents)
    app.router.add_get("/api/agents/{name}/telemetry", main.api_telemetry)
    app.router.add_get("/api/agents/{name}/containers", main.api_containers)
    app.router.add_post("/api/agents/{name}/poweroff", main.api_poweroff)
    app.router.add_post("/api/agents/{name}/reboot", main.api_reboot)
    app.router.add_post("/api/agents/{name}/wake", main.api_wake)
    app.router.add_post(
        "/api/agents/{name}/containers/{container}/{action}",
        main.api_container_action)
    app.router.add_get("/api/stream", main.api_stream)
    # "/" must be registered before the static prefix so it wins for the root
    # (the static handler would otherwise 403 on the directory request).
    app.router.add_get("/", main.serve_index)
    app.router.add_static("/", main.cfg.web_root)
    return app


def create_mgmt_app(main: Main) -> web.Application:
    """Agent WebSocket endpoint. Served over mTLS (client cert required)."""
    app = web.Application()
    app.router.add_get("/ws", main.handle_mgmt_ws)
    return app


async def _run(cfg: Config) -> None:
    main = Main(cfg)
    web_app = create_web_app(main)
    mgmt_app = create_mgmt_app(main)
    web_ctx = tlsutil.load_web_context(cfg.cert, cfg.key)
    mgmt_ctx = tlsutil.load_server_context(cfg.ca, cfg.cert, cfg.key)
    web_runner = web.AppRunner(web_app)
    await web_runner.setup()
    web_site = web.TCPSite(web_runner, "0.0.0.0", cfg.web_port, ssl_context=web_ctx)
    mgmt_runner = web.AppRunner(mgmt_app)
    await mgmt_runner.setup()
    mgmt_site = web.TCPSite(mgmt_runner, "0.0.0.0", cfg.mgmt_port, ssl_context=mgmt_ctx)
    await web_site.start()
    await mgmt_site.start()
    log.info("main listening: web=%s mgmt=%s agents=%d",
             cfg.web_port, cfg.mgmt_port, len(cfg.agents))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    await stop.wait()
    await web_runner.cleanup()
    await mgmt_runner.cleanup()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    try:
        asyncio.run(_run(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
