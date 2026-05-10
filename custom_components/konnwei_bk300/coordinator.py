"""BLE coordinator for Konnwei BK300."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    INIT_SEQUENCE,
    NOTIFY_CHARACTERISTIC_UUID,
    STORAGE_KEY,
    VOLTAGE_POLL_CMD,
    WRITE_CHARACTERISTIC_UUID,
)
from .parser import BK300Reading, parse_notification

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
CONNECT_TIMEOUT = 20
WRITE_DELAY = 0.5  # seconds between init writes


class BK300Coordinator(DataUpdateCoordinator[BK300Reading]):
    """Manages polling and BLE connection for BK300."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        poll_interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Konnwei BK300 {address}",
            update_interval=timedelta(minutes=poll_interval_minutes),
        )
        self.address = address
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{address}")
        self._last_reading = BK300Reading()
        self._notification_event = asyncio.Event()
        self._pending_reading: BK300Reading | None = None

    async def async_setup(self) -> None:
        """Load persisted state."""
        stored = await self._store.async_load()
        if stored and "voltage" in stored:
            self._last_reading.voltage = stored["voltage"]
            _LOGGER.debug("Restored last voltage: %.2fV", stored["voltage"])

    async def _async_update_data(self) -> BK300Reading:
        """Poll the device for a fresh voltage reading."""
        try:
            reading = await self._poll_device()
        except BleakError as err:
            raise UpdateFailed(f"BLE error communicating with {self.address}: {err}") from err
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Timeout communicating with {self.address}") from err

        if reading and reading.voltage is not None:
            self._last_reading = reading
            await self._store.async_save({"voltage": reading.voltage})
            return reading

        # Return last known value if poll failed to get voltage
        if self._last_reading.voltage is not None:
            _LOGGER.warning(
                "Poll returned no voltage, using last known value: %.2fV",
                self._last_reading.voltage,
            )
            return self._last_reading

        raise UpdateFailed("No voltage data received and no cached value available")

    async def _poll_device(self) -> BK300Reading | None:
        """Connect, run init sequence, poll voltage, disconnect."""
        ble_device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if not ble_device:
            raise BleakError(f"Device {self.address} not found or not connectable")

        self._notification_event.clear()
        self._pending_reading = None

        async with BleakClient(ble_device, timeout=CONNECT_TIMEOUT) as client:
            _LOGGER.debug("Connected to BK300 %s", self.address)

            # Subscribe to FFF1 notifications
            await client.start_notify(
                NOTIFY_CHARACTERISTIC_UUID,
                self._on_notification,
            )

            # Run init sequence
            for cmd in INIT_SEQUENCE:
                await client.write_gatt_char(
                    WRITE_CHARACTERISTIC_UUID,
                    cmd,
                    response=False,
                )
                await asyncio.sleep(WRITE_DELAY)

            # Wait for voltage notification (up to 5 seconds)
            try:
                await asyncio.wait_for(self._notification_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout waiting for voltage notification from %s", self.address)

            await client.stop_notify(NOTIFY_CHARACTERISTIC_UUID)

        return self._pending_reading

    def _on_notification(
        self,
        characteristic: BleakGATTCharacteristic,
        data: bytearray,
    ) -> None:
        """Handle incoming FFF1 notification."""
        reading = parse_notification(bytes(data))
        if reading and reading.voltage is not None:
            self._pending_reading = reading
            self._notification_event.set()

    @property
    def last_known_voltage(self) -> float | None:
        """Return the last known voltage."""
        return self._last_reading.voltage
