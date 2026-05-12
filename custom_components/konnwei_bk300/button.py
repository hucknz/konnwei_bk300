"""Button platform for Konnwei BK300."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN, MANUFACTURER, MODEL
from .coordinator import BK300Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BK300 buttons."""
    coordinator: BK300Coordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]

    async_add_entities([
        BK300RefreshButton(coordinator, address),
    ])


class BK300RefreshButton(CoordinatorEntity[BK300Coordinator], ButtonEntity):
    """Button to poll the BK300 immediately."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_now"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BK300Coordinator, address: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_refresh_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"BK300 ({address})",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_press(self) -> None:
        """Trigger an immediate poll."""
        await self.coordinator.async_request_refresh()