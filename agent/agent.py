"""TinyOSControll agent daemon.

A single long-running daemon that:
  * connects outbound to main over an mTLS WebSocket,
  * authenticates with its name + shared token,
  * executes a fixed set of host operations (via hostcmd.sh),
  * streams host telemetry to main once per second.

It never listens for inbound connections and never runs arbitrary commands:
all host work is delegated to hostcmd.sh, a fixed bash dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from aiohttp import ClientSession, WSMsgType

from common import protocol as P
from common import tlsutil

log = logging.getLogger("tinyos.agent")


@dataclass
class Config:
    main_host: str
    main_port: int
    name: str
    token: str
    cert_dir: str
    containers: list[str] = field(default_factory=list)
    interval: float = 1.0
    hostcmd: str = "/opt/tinyos/hostcmd.sh"
    ws_path: str = "/ws"

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
    containers = [c.strip() for c in os.environ.get("CONTAINERS", "").split(",") if c.strip()]
    return Config(
        main_host=os.environ["MAIN_HOST"],
        main_port=int(os.environ.get("MAIN_PORT", "9443")),
        name=os.environ["AGENT_NAME"],
        token=os.environ["AGENT_TOKEN"],
        cert_dir=os.environ.get("CERT_DIR", "/certs"),
        containers=containers,
        interval=float(os.environ.get("TELEMETRY_INTERVAL", "1.0")),
        hostcmd=os.environ.get("HOSTCMD", "/opt/tinyos/hostcmd.sh"),
    )


class Agent:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._stop = asyncio.Event()
        self._ws = None
        self._send_lock = asyncio.Lock()

    def request_stop(self) -> None:
        self._stop.set()

    async def _send(self, ws, msg: dict) -> None:
        # Serialize all outbound frames: the telemetry loop, request handlers
        # and pong replies share one WebSocket and aiohttp does not lock writes.
        async with self._send_lock:
            if not ws.closed:
                await ws.send_str(P.encode(msg))

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on any failure
                log.warning("connection problem: %s; retrying in %.0fs", exc, backoff)
                await self._sleep_or_stop(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _session(self) -> None:
        ctx = tlsutil.load_client_context(self.cfg.ca, self.cfg.cert, self.cfg.key)
        url = f"wss://{self.cfg.main_host}:{self.cfg.main_port}{self.cfg.ws_path}"
        log.info("connecting to %s", url)
        async with ClientSession() as session:
            async with session.ws_connect(url, ssl=ctx, heartbeat=20) as ws:
                self._ws = ws
                await self._handshake(ws)
                telemetry = asyncio.create_task(self._telemetry_loop(ws))
                try:
                    await self._serve(ws)
                finally:
                    telemetry.cancel()
                    try:
                        await telemetry
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass
                self._ws = None
                log.info("disconnected from main")

    async def _handshake(self, ws) -> None:
        await ws.send_str(P.encode(P.make_hello(self.cfg.name, self.cfg.token)))
        raw = await ws.receive()
        if raw.type != WSMsgType.TEXT:
            raise ConnectionError("expected hello_ok/hello_err")
        msg = P.decode(raw.data)
        if msg["type"] == P.HELLO_OK:
            log.info("authenticated as %s", self.cfg.name)
            return
        raise PermissionError(f"rejected by main: {msg.get('reason')}")

    async def _serve(self, ws) -> None:
        async for raw in ws:
            if raw.type == WSMsgType.TEXT:
                msg = P.decode(raw.data)
                t = msg["type"]
                if t == P.PING:
                    await self._send(ws, P.make_pong())
                elif t == P.REQUEST:
                    asyncio.create_task(self._handle_request(ws, msg))
                elif t == P.BYE:
                    return
            elif raw.type in (WSMsgType.CLOSE, WSMsgType.CLOSING,
                              WSMsgType.CLOSED, WSMsgType.ERROR):
                return

    async def _handle_request(self, ws, req: dict[str, Any]) -> None:
        rid = req["id"]
        action = req["action"]
        params = req.get("payload") or {}
        try:
            result = await self._execute(action, params)
            resp = P.make_response(rid, True, result)
        except Exception as exc:  # noqa: BLE001
            resp = P.make_response(rid, False, error=str(exc))
        await self._send(ws, resp)

    async def _execute(self, action: str, params: dict[str, Any]) -> Any:
        if action == P.ACTION_HEALTH:
            return await self._hostcmd("health")
        if action == P.ACTION_POWEROFF:
            await self._hostcmd("poweroff")
            return {"ok": True}
        if action == P.ACTION_REBOOT:
            await self._hostcmd("reboot")
            return {"ok": True}
        if action == P.ACTION_CONTAINERS_LIST:
            return await self._hostcmd("containers.list", ",".join(self.cfg.containers))
        if action == P.ACTION_CONTAINERS_ACTION:
            name = params.get("container")
            act = params.get("action")
            if name not in self.cfg.containers:
                raise PermissionError(f"container {name!r} not in whitelist")
            if act not in P.ALL_CONTAINER_ACTIONS:
                raise ValueError(f"invalid container action {act!r}")
            return await self._hostcmd("containers.action", name, act)
        raise ValueError(f"unknown action {action!r}")

    async def _hostcmd(self, cmd: str, *args: str) -> Any:
        exe = self.cfg.hostcmd
        argv = [exe, cmd, *args]
        if exe.endswith(".py"):  # allow a Python-based hostcmd (used by local tests)
            argv = [sys.executable, exe, cmd, *args]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"hostcmd {cmd!r} failed: {err.decode().strip()}")
        text = out.decode().strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def _telemetry_loop(self, ws) -> None:
        while not self._stop.is_set():
            try:
                data = await self._hostcmd("telemetry")
                ts = datetime.now(timezone.utc).isoformat()
                await self._send(ws, P.make_telemetry(self.cfg.name, ts, data))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("telemetry error: %s", exc)
            await self._sleep_or_stop(self.cfg.interval)


async def _amain() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    agent = Agent(cfg)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, agent.request_stop)
        except (NotImplementedError, RuntimeError):
            pass
    await agent.run()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
