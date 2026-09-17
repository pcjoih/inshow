"""The inshow integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import CannotConnect, InshowApi, InvalidAuth

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.CLIMATE]

type InshowConfigEntry = ConfigEntry[InshowApi]
DOMAIN = "inshow"
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: InshowConfigEntry) -> bool:
    """Set up config entry."""
    api = InshowApi(hass, entry.data["E-mail"], entry.data["password"])

    try:
        await api.initialize()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed("Invalid Inshow credentials") from err
    except CannotConnect as err:
        raise ConfigEntryNotReady("Cannot connect to Inshow API") from err

    if not await api.get_data():
        raise ConfigEntryNotReady("Failed to retrieve data from API")

    entry.runtime_data = api

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: InshowConfigEntry) -> bool:
    """Unload a config entry."""
    entry.runtime_data.shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
