"""End-to-end integration test: real main + real agent over mTLS on localhost.

Uses the self-signed cert from conftest.py and a Python stub hostcmd so no
docker/systemd is required. Exercises the full loop:

  * mTLS handshake (agent -> main) and name+token auth,
  * telemetry streaming,
  * health / containers.list / container action (whitelist + reject),
  * poweroff,
  * the web API (list, containers, actions) with API-token auth,
  * that /ws is only reachable on the mTLS mgmt port (not the web port),
  * that the mgmt port rejects a client without a certificate.
"""

from __future__ import annotations

import asyncio
import os
import socket
import ssl

import pytest
from aiohttp import ClientSession, web

from common import protocol as P
from common import tlsutil
from common import wol as wol_mod
from main.main import (
    AgentInfo,
    Config as MainConfig,
    Main,
    create_mgmt_app,
    create_web_app,
)
from agent.agent import Agent, Config as AgentConfig


STUB_HOSTCMD = r'''
import json, sys
cmd = sys.argv[1]
if cmd == "health":
    print(json.dumps({"uptime_seconds": 123.0}))
elif cmd in ("poweroff", "reboot"):
    print(json.dumps({"ok": True}))
elif cmd == "containers.list":
    print(json.dumps({"nginx": {"state": "running"}, "postgres": {"state": "exited"}}))
elif cmd == "containers.action":
    print(json.dumps({"ok": True, "container": sys.argv[2], "action": sys.argv[3]}))
elif cmd == "telemetry":
    print(json.dumps({"cpu_temp_c": 45.0,
                      "ram": {"total_mb": 8192, "used_mb": 2048, "percent": 25.0},
                      "swap": {"total_mb": 0, "used_mb": 0, "percent": 0.0},
                      "amd_smi": None}))
else:
    sys.stderr.write("unknown " + cmd)
    sys.exit(2)
'''


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _wait_until(cond, timeout: float = 10.0, step: float = 0.05) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if cond():
            return True
        await asyncio.sleep(step)
    return cond()


async def test_integration(cert_dir, tmp_path):
    stub = tmp_path / "hostcmd_stub.py"
    stub.write_text(STUB_HOSTCMD, encoding="utf-8")

    web_port = _free_port()
    mgmt_port = _free_port()
    agent_token = "it-agent-token"
    api_token = "it-api-token"

    main_cfg = MainConfig(
        web_port=web_port,
        mgmt_port=mgmt_port,
        cert_dir=cert_dir,
        agent_token=agent_token,
        api_token=api_token,
        audit_log=str(tmp_path / "audit.jsonl"),
        web_root=os.path.join(os.path.dirname(__file__), "..", "main", "web"),
        agents=[AgentInfo(name="alpha", mac="AA:BB:CC:DD:EE:FF", ip="127.0.0.1")],
    )
    main = Main(main_cfg)
    web_app = create_web_app(main)
    mgmt_app = create_mgmt_app(main)
    web_ctx = tlsutil.load_web_context(main_cfg.cert, main_cfg.key)
    mgmt_ctx = tlsutil.load_server_context(main_cfg.ca, main_cfg.cert, main_cfg.key)

    web_runner = web.AppRunner(web_app)
    await web_runner.setup()
    await web.TCPSite(web_runner, "127.0.0.1", web_port, ssl_context=web_ctx).start()
    mgmt_runner = web.AppRunner(mgmt_app)
    await mgmt_runner.setup()
    await web.TCPSite(mgmt_runner, "127.0.0.1", mgmt_port, ssl_context=mgmt_ctx).start()

    agent_cfg = AgentConfig(
        main_host="127.0.0.1",
        main_port=mgmt_port,
        name="alpha",
        token=agent_token,
        cert_dir=cert_dir,
        containers=["nginx", "postgres"],
        interval=0.2,
        hostcmd=str(stub),
    )
    agent = Agent(agent_cfg)
    agent_task = asyncio.create_task(agent.run())

    try:
        # 1) agent connects and is marked online
        assert await _wait_until(lambda: main.agents["alpha"].online), "agent did not connect"

        # 2) telemetry arrives
        assert await _wait_until(lambda: bool(main.agents["alpha"].telemetry)), "no telemetry"
        tel = main.agents["alpha"].telemetry
        assert tel["cpu_temp_c"] == 45.0
        assert tel["ram"]["percent"] == 25.0

        # 3) forward a health check straight through main
        health = await main.forward(main.agents["alpha"], P.ACTION_HEALTH)
        assert health["ok"] and health["payload"]["uptime_seconds"] == 123.0

        async with ClientSession() as s:
            base = f"https://127.0.0.1:{web_port}"
            key = {"X-API-Key": api_token}

            # 4) web API: list agents (valid token)
            r = await s.get(f"{base}/api/agents", headers=key, ssl=False)
            assert r.status == 200
            data = await r.json()
            assert data[0]["name"] == "alpha" and data[0]["online"] is True

            # 5) web API: missing/bad token -> 401
            r = await s.get(f"{base}/api/agents", ssl=False)
            assert r.status == 401
            r = await s.get(f"{base}/api/agents", headers={"X-API-Key": "wrong"}, ssl=False)
            assert r.status == 401

            # 6) containers list via API
            r = await s.get(f"{base}/api/agents/alpha/containers", headers=key, ssl=False)
            assert r.status == 200
            assert (await r.json())["nginx"]["state"] == "running"

            # 7) whitelisted container action -> ok
            r = await s.post(f"{base}/api/agents/alpha/containers/nginx/start",
                             headers=key, ssl=False)
            assert r.status == 200 and (await r.json())["ok"] is True

            # 8) non-whitelisted container -> agent rejects
            r = await s.post(f"{base}/api/agents/alpha/containers/evil/start",
                             headers=key, ssl=False)
            assert r.status == 200
            body = await r.json()
            assert body["ok"] is False and "whitelist" in body["error"]

            # 9) poweroff via API (stub returns ok; nothing actually powers off)
            r = await s.post(f"{base}/api/agents/alpha/poweroff", headers=key, ssl=False)
            assert r.status == 200 and (await r.json())["ok"] is True

            # 9b) wake via API (WoL send is stubbed so the test stays offline-safe)
            _orig_send = wol_mod.send_wol
            wol_mod.send_wol = lambda mac, ip=None, port=9: "255.255.255.255,127.0.0.1"
            try:
                r = await s.post(f"{base}/api/agents/alpha/wake", headers=key, ssl=False)
                assert r.status == 200
                body = await r.json()
                assert body["ok"] is True
            finally:
                wol_mod.send_wol = _orig_send

            # 10) /ws is NOT exposed on the web port (mgmt endpoint is isolated)
            r = await s.get(f"{base}/ws", ssl=False)
            assert r.status == 404

            # 10b) "/" serves the SPA entry point (no API token needed)
            r = await s.get(f"{base}/", ssl=False)
            assert r.status == 200
            assert "<html" in (await r.text()).lower()

        # 11) the mgmt port requires a client certificate (mTLS)
        plain = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        plain.check_hostname = False
        plain.verify_mode = ssl.CERT_NONE
        with pytest.raises(Exception):  # noqa: B017 - any TLS failure is expected
            async with ClientSession() as s:
                async with s.ws_connect(f"wss://127.0.0.1:{mgmt_port}/ws", ssl=plain):
                    pass
    finally:
        agent.request_stop()
        agent_task.cancel()
        try:
            await agent_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        await web_runner.cleanup()
        await mgmt_runner.cleanup()
