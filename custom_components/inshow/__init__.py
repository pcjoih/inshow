"""The inshow integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import InshowApi

PLATFORMS: list[Platform] = [Platform.LIGHT]

type InshowConfigEntry = ConfigEntry[InshowApi]
DOMAIN = "inshow"
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: InshowConfigEntry) -> bool:
    """Set up config entry."""
    api = InshowApi(hass, entry.data["E-mail"], entry.data["password"])
    await api.initialize()

    if await api.get_data():
        entry.runtime_data = api
    else:
        _LOGGER.error("Failed to retrieve data from API")
        return False

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: InshowConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
