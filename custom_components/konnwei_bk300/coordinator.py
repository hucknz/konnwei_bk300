"""BLE coordinator for Konnwei BK300."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError

from homeassistant.components.bluetooth import async_scanner_devices_by_address
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from habluetooth import BluetoothScannerDevice

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


@dataclass
class BK300Data:
    """Data returned by the coordinator."""
    reading: BK300Reading | None = None


class BK300Coordinator(DataUpdateCoordinator[BK300Data]):
    """Manages polling and BLE connection for BK300.
    
    Follows the BM6 integration pattern for multi-scanner support
    and robust error handling.
    """

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
        self._notification_event: asyncio.Event | None = None
        self._pending_reading: BK300Reading | None = None

    async def async_setup(self) -> None:
        """Load persisted state."""
        stored = await self._store.async_load()
        if stored and "voltage" in stored:
            self._last_reading.voltage = stored["voltage"]
            if "battery_percent" in stored:
                self._last_reading.battery_percent = stored["battery_percent"]
            if "charging" in stored:
                self._last_reading.charging = stored["charging"]
            _LOGGER.debug(
                "Restored last reading: voltage=%.2fV percent=%s charging=%s",
                self._last_reading.voltage,
                self._last_reading.battery_percent,
                self._last_reading.charging,
            )

    async def _async_update_data(self) -> BK300Data:
        """Poll the device for a fresh voltage reading."""
        try:
            reading = await self._poll_device()
        except BleakError as err:
            _LOGGER.warning("BLE error communicating with %s: %s", self.address, err)
            raise UpdateFailed(f"BLE error: {err}") from err
        except asyncio.TimeoutError as err:
            _LOGGER.warning("Timeout communicating with %s", self.address)
            raise UpdateFailed("Timeout communicating with device") from err
        except Exception as err:
            _LOGGER.error("Unexpected error polling %s: %s", self.address, err)
            raise UpdateFailed(f"Unexpected error: {err}") from err

        if reading and reading.voltage is not None:
            self._last_reading = reading
            # Persist the reading
            await self._store.async_save({
                "voltage": reading.voltage,
                "battery_percent": reading.battery_percent,
                "charging": reading.charging,
            })
            _LOGGER.debug(
                "Updated reading: voltage=%.2fV percent=%s charging=%s",
                reading.voltage,
                reading.battery_percent,
                reading.charging,
            )
            return BK300Data(reading=reading)

        # Return last known value if poll failed to get voltage
        if self._last_reading.voltage is not None:
            _LOGGER.debug(
                "Poll returned no voltage, using cached: %.2fV",
                self._last_reading.voltage,
            )
            return BK300Data(reading=self._last_reading)

        raise UpdateFailed("No voltage data received and no cached value available")

    async def _poll_device(self) -> BK300Reading | None:
        """Connect, run init sequence, poll voltage, disconnect.
        
        Follows BM6 approach: tries multiple scanners in order of RSSI strength.
        """
        # Get all available scanner devices for this address
        scanner_devices = async_scanner_devices_by_address(
            self.hass, self.address, connectable=True
        )
        
        if not scanner_devices:
            raise BleakError(f"Device {self.address} not found by any scanner")

        # Sort by signal strength (RSSI) - higher is better
        scanner_devices.sort(
            key=lambda s: s.advertisement.rssi or -100,
            reverse=True
        )

        exceptions: list[Exception] = []

        for scanner_device in scanner_devices:
            try:
                scanner_name = scanner_device.scanner.name
                rssi = scanner_device.advertisement.rssi or -100
                _LOGGER.debug(
                    "Attempting to poll %s via scanner %s (RSSI: %d)",
                    self.address,
                    scanner_name,
                    rssi,
                )

                reading = await self._connect_and_poll(scanner_device)
                
                if reading and reading.voltage is not None:
                    _LOGGER.info(
                        "Successfully polled %s via scanner %s: %.2fV",
                        self.address,
                        scanner_name,
                        reading.voltage,
                    )
                    return reading

            except Exception as err:
                _LOGGER.debug(
                    "Failed to poll via scanner %s: %s",
                    scanner_device.scanner.name,
                    err,
                )
                exceptions.append(err)
                continue

        # All scanners failed
        if exceptions:
            raise BleakError(
                f"Failed to poll device {self.address} via any scanner: {exceptions[0]}"
            ) from exceptions[0]
        
        raise BleakError(f"No scanners available for device {self.address}")

    async def _connect_and_poll(
        self, scanner_device: BluetoothScannerDevice
    ) -> BK300Reading | None:
        """Connect to device via a specific scanner and poll for voltage."""
        self._notification_event = asyncio.Event()
        self._pending_reading = None

        try:
            async with BleakClient(
                scanner_device.ble_device,
                timeout=CONNECT_TIMEOUT,
            ) as client:
                _LOGGER.debug(
                    "Connected to BK300 %s via %s",
                    self.address,
                    scanner_device.scanner.name,
                )

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
                    await asyncio.wait_for(
                        self._notification_event.wait(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    _LOGGER.warning(
                        "Timeout waiting for notification from %s",
                        self.address,
                    )

                await client.stop_notify(NOTIFY_CHARACTERISTIC_UUID)

            return self._pending_reading

        except BleakError as err:
            _LOGGER.debug("BLE connection error: %s", err)
            raise
        except Exception as err:
            _LOGGER.debug("Unexpected error during poll: %s", err)
            raise

    def _on_notification(
        self,
        characteristic: BleakGATTCharacteristic,
        data: bytearray,
    ) -> None:
        """Handle incoming FFF1 notification."""
        reading = parse_notification(bytes(data))
        if reading and reading.voltage is not None:
            self._pending_reading = reading
            if self._notification_event:
                self._notification_event.set()

    @property
    def last_known_voltage(self) -> float | None:
        """Return the last known voltage."""
        return self._last_reading.voltage

