"""Config flow for the OSControll integration."""
from __future__ import annotations

import logging

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import CannotConnect, InvalidAuth, OscontrollApi, SslError
from .const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CannotConnectError(HomeAssistantError):
    """Could not connect to the main server."""


class InvalidAuthError(HomeAssistantError):
    """The API token was rejected."""


class SslErrorConfig(HomeAssistantError):
    """SSL certificate verification failed."""


class OscontrollConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for OSControll."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_URL])
            self._abort_if_unique_id_configured()
            try:
                await self._validate(user_input)
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidAuthError:
                errors["base"] = "invalid_auth"
            except SslErrorConfig:
                errors["base"] = "ssl_error"
            except HomeAssistantError:
                _LOGGER.exception("Unexpected error validating OSControll config")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_URL],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=""): str,
                    vol.Required(CONF_TOKEN): str,
                    vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                }
            ),
            errors=errors,
        )

    async def _validate(self, data: dict) -> None:
        """Check that the URL and token work."""
        session = aiohttp.ClientSession()
        try:
            api = OscontrollApi(
                session,
                data[CONF_URL],
                data[CONF_TOKEN],
                data[CONF_VERIFY_SSL],
            )
            await api.get_agents()
        except CannotConnect as exc:
            raise CannotConnectError from exc
        except InvalidAuth as exc:
            raise InvalidAuthError from exc
        except SslError as exc:
            raise SslErrorConfig from exc
        finally:
            await session.close()
