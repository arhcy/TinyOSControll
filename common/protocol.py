"""TinyOSControll wire protocol.

JSON messages over a WebSocket (mTLS). Only a fixed set of message types and
actions exist; there is no arbitrary command execution.

Message types
-------------
hello       agent -> main   {"type":"hello","agent":..,"token":..}
hello_ok    main  -> agent  {"type":"hello_ok"}
hello_err   main  -> agent  {"type":"hello_err","reason":..}
request     main  -> agent  {"type":"request","id":..,"action":..,"payload":{..}}
response    agent -> main   {"type":"response","id":..,"ok":bool,"payload":{..},"error":..}
telemetry   agent -> main   {"type":"telemetry","agent":..,"ts":..,"payload":{..}}
ping        either          {"type":"ping"}
pong        either          {"type":"pong"}
bye         either          {"type":"bye"}
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

# Message type names.
HELLO = "hello"
HELLO_OK = "hello_ok"
HELLO_ERR = "hello_err"
REQUEST = "request"
RESPONSE = "response"
TELEMETRY = "telemetry"
PING = "ping"
PONG = "pong"
BYE = "bye"

ALL_TYPES = frozenset(
    {HELLO, HELLO_OK, HELLO_ERR, REQUEST, RESPONSE, TELEMETRY, PING, PONG, BYE}
)

# Fixed set of control actions (main -> agent). No arbitrary commands.
ACTION_HEALTH = "health"
ACTION_POWEROFF = "poweroff"
ACTION_REBOOT = "reboot"
ACTION_CONTAINERS_LIST = "containers.list"
ACTION_CONTAINERS_ACTION = "containers.action"

ALL_ACTIONS = frozenset(
    {
        ACTION_HEALTH,
        ACTION_POWEROFF,
        ACTION_REBOOT,
        ACTION_CONTAINERS_LIST,
        ACTION_CONTAINERS_ACTION,
    }
)

# container sub-actions
CONTAINER_START = "start"
CONTAINER_STOP = "stop"
CONTAINER_RESTART = "restart"
ALL_CONTAINER_ACTIONS = frozenset({CONTAINER_START, CONTAINER_STOP, CONTAINER_RESTART})


class ProtocolError(ValueError):
    """Raised when a message is malformed or not allowed."""


def new_id() -> str:
    return uuid.uuid4().hex


def encode(msg: Dict[str, Any]) -> str:
    """Serialize a message dict to a JSON line (no trailing newline)."""
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a dict")
    if "type" not in msg:
        raise ProtocolError("message missing 'type'")
    return json.dumps(msg, separators=(",", ":"), ensure_ascii=False)


def decode(text: str) -> Dict[str, Any]:
    """Parse and validate a JSON message line.

    Raises ProtocolError on bad JSON or an unknown/missing type.
    """
    try:
        msg = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError("message must be a JSON object")
    mtype = msg.get("type")
    if mtype not in ALL_TYPES:
        raise ProtocolError(f"unknown message type: {mtype!r}")
    return msg


# --- constructors ---------------------------------------------------------

def make_hello(agent: str, token: str) -> Dict[str, Any]:
    return {"type": HELLO, "agent": agent, "token": token}


def make_hello_ok() -> Dict[str, Any]:
    return {"type": HELLO_OK}


def make_hello_err(reason: str) -> Dict[str, Any]:
    return {"type": HELLO_ERR, "reason": reason}


def make_request(action: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if action not in ALL_ACTIONS:
        raise ProtocolError(f"unknown action: {action!r}")
    msg: Dict[str, Any] = {"type": REQUEST, "id": new_id(), "action": action}
    if payload is not None:
        msg["payload"] = payload
    return msg


def make_response(req_id: str, ok: bool, payload: Dict[str, Any] | None = None,
                  error: str | None = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"type": RESPONSE, "id": req_id, "ok": bool(ok)}
    if payload is not None:
        msg["payload"] = payload
    if error is not None:
        msg["error"] = error
    return msg


def make_telemetry(agent: str, ts: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": TELEMETRY, "agent": agent, "ts": ts, "payload": payload}


def make_ping() -> Dict[str, Any]:
    return {"type": PING}


def make_pong() -> Dict[str, Any]:
    return {"type": PONG}


def make_bye() -> Dict[str, Any]:
    return {"type": BYE}
