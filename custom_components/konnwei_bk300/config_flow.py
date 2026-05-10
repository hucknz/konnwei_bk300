"""Config flow for Konnwei BK300."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ADDRESS,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MANUFACTURER_ID,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    SERVICE_UUID,
)

_LOGGER = logging.getLogger(__name__)


def _is_bk300(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if this discovery looks like a BK300.
    
    Checks for:
    - Proprietary service UUID (0000fff0)
    - Manufacturer ID 179 (Clarinox Technologies / Konnwei)
    """
    # Check service UUID
    if service_info.service_uuids:
        service_uuids_lower = [str(u).lower() for u in service_info.service_uuids]
        if SERVICE_UUID.lower() in service_uuids_lower:
            _LOGGER.debug(
                "BK300 detected by service UUID on %s", service_info.address
            )
            return True
    
    # Check manufacturer ID
    if service_info.manufacturer_data and MANUFACTURER_ID in service_info.manufacturer_data:
        _LOGGER.debug(
            "BK300 detected by manufacturer ID on %s", service_info.address
        )
        return True
    
    return False


def _get_all_ble_devices(hass) -> dict[str, BluetoothServiceInfoBleak]:
    """
    Get all BLE devices visible to HA using every available API.

    This implements the multi-layer discovery approach from the BM6 integration,
    which provides better device detection across various Bluetooth scanners.
    
    Discovery sources:
    1. Devices already matched to integrations (from async_discovered_service_info)
    2. Raw advertisement data from every active scanner's device cache
    """
    seen: dict[str, BluetoothServiceInfoBleak] = {}

    # Method 1: Get devices already matched to integrations
    # This includes both connectable and non-connectable devices
    for info in async_discovered_service_info(hass, connectable=False):
        seen[info.address] = info
        _LOGGER.debug("Found matched device: %s (%s)", info.address, info.name)

    # Method 2: Walk every active scanner's raw advertisement cache
    # This catches devices that haven't been matched to any integration yet
    try:
        active_scanners = bluetooth.async_current_scanners(hass)
        _LOGGER.debug("Found %d active Bluetooth scanners", len(active_scanners))
        
        for scanner in active_scanners:
            try:
                # Access the raw device cache from the scanner
                # discovered_devices_and_advertisement_data is dict[address, (BLEDevice, AdvertisementData)]
                raw_devices = getattr(
                    scanner, "discovered_devices_and_advertisement_data", {}
                )
                
                if not raw_devices:
                    _LOGGER.debug("Scanner %s has no cached devices", scanner.name)
                    continue
                
                _LOGGER.debug(
                    "Scanner %s has %d cached devices",
                    getattr(scanner, "name", "unknown"),
                    len(raw_devices),
                )
                
                for address, (ble_device, adv_data) in raw_devices.items():
                    if address in seen:
                        continue  # Already have this device
                    
                    # Build a BluetoothServiceInfoBleak from raw advertisement data
                    name = adv_data.local_name or ble_device.name or ""
                    # Clean up null byte padding from device names
                    name = name.replace("\x00", "").strip()
                    
                    try:
                        seen[address] = BluetoothServiceInfoBleak(
                            name=name,
                            address=address,
                            rssi=adv_data.rssi or -100,
                            manufacturer_data=adv_data.manufacturer_data or {},
                            service_data=adv_data.service_data or {},
                            service_uuids=adv_data.service_uuids or [],
                            source=getattr(scanner, "source", "unknown"),
                            device=ble_device,
                            advertisement=adv_data,
                            connectable=True,
                            time=0,
                            tx_power=adv_data.tx_power,
                        )
                        _LOGGER.debug(
                            "Added uncached device: %s (%s) from scanner %s",
                            address,
                            name,
                            getattr(scanner, "name", "unknown"),
                        )
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning(
                            "Error creating service info for %s: %s", address, err
                        )
                        
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Error reading scanner %s cache: %s",
                    getattr(scanner, "name", "unknown"),
                    err,
                )
                
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Error iterating Bluetooth scanners: %s", err)

    _LOGGER.info(
        "Device discovery complete: found %d total BLE devices", len(seen)
    )
    return seen


class BK300ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for Konnwei BK300."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        _LOGGER.debug("BK300ConfigFlow initialized")

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle auto-discovery via Bluetooth.
        
        This is called when Home Assistant discovers a device matching the
        Bluetooth configuration in manifest.json.
        """
        _LOGGER.info(
            "Bluetooth discovery triggered for device: %s (%s)",
            discovery_info.address,
            discovery_info.name,
        )
        
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not _is_bk300(discovery_info):
            _LOGGER.warning(
                "Device %s failed BK300 validation check, aborting discovery",
                discovery_info.address,
            )
            return self.async_abort(reason="not_supported")

        _LOGGER.info(
            "Device %s validated as BK300, proceeding with confirmation",
            discovery_info.address,
        )
        
        self._address = discovery_info.address
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "BK300",
            "address": discovery_info.address,
        }

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm auto-discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"BK300 ({self._address})",
                data={
                    CONF_ADDRESS: self._address,
                    CONF_POLL_INTERVAL: user_input.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                }
            ),
            description_placeholders={
                "address": self._address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup — shows dropdown of all visible BLE devices.
        
        This provides a fallback for devices that don't trigger automatic
        Bluetooth discovery, and helps diagnose why devices aren't being found.
        """
        errors: dict[str, str] = {}
        current_addresses = self._async_current_ids()

        # Gather all visible devices from all scanner sources
        _LOGGER.debug("Scanning for BLE devices...")
        all_infos = _get_all_ble_devices(self.hass)
        _LOGGER.info("Total BLE devices found: %d", len(all_infos))

        all_devices: dict[str, str] = {}
        bk300_devices: dict[str, str] = {}

        for address, info in all_infos.items():
            if address in current_addresses:
                _LOGGER.debug("Skipping already configured device: %s", address)
                continue
                
            name = info.name or "Unknown"
            # Strip null bytes (BK300 pads its name with \x00)
            name = name.replace("\x00", "").strip() or "Unknown"
            label = f"{name} ({address})"
            all_devices[address] = label
            
            # Check if this device looks like a BK300
            if _is_bk300(info):
                _LOGGER.info("Found BK300 device: %s", label)
                bk300_devices[address] = label
            else:
                _LOGGER.debug(
                    "Device %s is not a BK300 (service_uuids=%s, manufacturer=%s)",
                    address,
                    info.service_uuids,
                    list(info.manufacturer_data.keys()) if info.manufacturer_data else [],
                )

        _LOGGER.info(
            "Device scan results: %d BK300 devices, %d total devices",
            len(bk300_devices),
            len(all_devices),
        )

        # BK300 matches at top marked with ⭐, everything else below
        ordered: dict[str, str] = {}
        for addr, label in bk300_devices.items():
            ordered[addr] = f"⭐ {label}"
        for addr, label in all_devices.items():
            if addr not in ordered:
                ordered[addr] = label

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            name = all_devices.get(address, f"BK300 ({address})")
            _LOGGER.info("Creating config entry for device: %s", name)
            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_POLL_INTERVAL: user_input.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                },
            )

        if not ordered:
            _LOGGER.warning("No Bluetooth devices found during manual setup")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found"},
                description_placeholders={
                    "discovered_count": "0",
                    "total_count": "0",
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(ordered),
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "discovered_count": str(len(bk300_devices)),
                "total_count": str(len(ordered)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return BK300OptionsFlow(config_entry)


class BK300OptionsFlow(OptionsFlow):
    """Handle options for BK300."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_POLL_INTERVAL,
            self._config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=current_interval
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                }
            ),
        )
