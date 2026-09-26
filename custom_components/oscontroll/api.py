"""Async client for the OSControll main REST API."""
from __future__ import annotations

import logging

import aiohttp

from .const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class OscontrollError(Exception):
    """Base error for the OSControll API client."""


class CannotConnect(OscontrollError):
    """Connection to the main server failed."""


class InvalidAuth(OscontrollError):
    """The API token was rejected."""


class SslError(OscontrollError):
    """SSL certificate verification failed."""


class OscontrollApi:
    """Talks to the main server's REST API using the X-API-Key header."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str,
        verify_ssl: bool,
    ) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._token = token
        self._verify_ssl = verify_ssl

    async def _request(self, method: str, path: str) -> object:
        url = f"{self._url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                headers={"X-API-Key": self._token},
                ssl=self._verify_ssl,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 401:
                    raise InvalidAuth("bad api key")
                if resp.status >= 400:
                    text = await resp.text()
                    raise OscontrollError(f"HTTP {resp.status}: {text}")
                return await resp.json()
        except aiohttp.ClientConnectorCertificateError as exc:
            raise SslError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise CannotConnect(str(exc)) from exc

    async def get_agents(self) -> list[dict]:
        """GET /api/agents — all agents with their latest telemetry."""
        return await self._request("GET", "/api/agents")  # type: ignore[return-value]

    async def get_containers(self, agent: str) -> dict:
        """GET /api/agents/{name}/containers — {name: {"state": ...}}."""
        return await self._request("GET", f"/api/agents/{agent}/containers")  # type: ignore[return-value]

    async def action(self, agent: str, action: str) -> dict:
        """POST /api/agents/{name}/{wake|poweroff|reboot}."""
        return await self._request("POST", f"/api/agents/{agent}/{action}")  # type: ignore[return-value]

    async def container_action(self, agent: str, container: str, action: str) -> dict:
        """POST /api/agents/{name}/containers/{container}/{start|stop|restart}."""
        return await self._request(
            "POST", f"/api/agents/{agent}/containers/{container}/{action}"
        )  # type: ignore[return-value]
