import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import CannotConnect, InshowApi, InvalidAuth
from .const import DOMAIN  # DOMAIN은 통합의 도메인 이름

_LOGGER = logging.getLogger(__name__)

# 사용자에게 입력받을 필드 정의
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("E-mail"): str,
        vol.Required("password"): str,
    }
)


class InshowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Inshow IOT integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step where the user inputs their data."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api = InshowApi(self.hass, user_input["E-mail"], user_input["password"])
            try:
                await api.login()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during Inshow login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input["E-mail"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Inshow IOT", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
