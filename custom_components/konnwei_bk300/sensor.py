"""Sensor platform for Konnwei BK300."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN, MANUFACTURER, MODEL
from .coordinator import BK300Coordinator, BK300Data

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BK300 sensors."""
    coordinator: BK300Coordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]

    async_add_entities([
        BK300VoltageSensor(coordinator, entry, address),
    ])


class BK300VoltageSensor(CoordinatorEntity[BK300Coordinator], SensorEntity):
    """Battery voltage sensor for BK300."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 2
    _attr_has_entity_name = True
    _attr_name = "Battery Voltage"

    def __init__(
        self,
        coordinator: BK300Coordinator,
        entry: ConfigEntry,
        address: str,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{address}_voltage"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=f"BK300 ({address})",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def native_value(self) -> float | None:
        """Return current voltage, falling back to last known value."""
        if self.coordinator.data and self.coordinator.data.reading:
            if self.coordinator.data.reading.voltage is not None:
                return self.coordinator.data.reading.voltage
        
        # Fall back to persisted last known value
        return self.coordinator.last_known_voltage

    @property
    def available(self) -> bool:
        """Sensor is available if we have any value (including cached)."""
        return self.coordinator.last_known_voltage is not None

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        attrs: dict = {"mac_address": self._address}
        
        if self.coordinator.data and self.coordinator.data.reading:
            reading = self.coordinator.data.reading
            if reading.battery_percent is not None:
                attrs["battery_percent"] = reading.battery_percent
            if reading.charging is not None:
                attrs["charging"] = reading.charging
        
        return attrs

