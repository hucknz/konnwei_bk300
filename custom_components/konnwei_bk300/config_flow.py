"""Config flow for Konnwei BK300."""
from __future__ import annotations

import logging
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
    """Return True if this discovery looks like a BK300."""
    if SERVICE_UUID in [str(u).lower() for u in service_info.service_uuids]:
        return True
    if MANUFACTURER_ID in service_info.manufacturer_data:
        return True
    return False


def _get_all_ble_devices(hass) -> dict[str, BluetoothServiceInfoBleak]:
    """
    Get all BLE devices visible to HA using every available API.

    async_discovered_service_info only returns devices matched to an integration.
    We also walk every active scanner's device cache to find unmatched devices.
    """
    seen: dict[str, BluetoothServiceInfoBleak] = {}

    # Method 1: devices already matched to integrations (connectable + non-connectable)
    for info in async_discovered_service_info(hass, connectable=False):
        seen[info.address] = info

    # Method 2: walk every active scanner's raw advertisement cache
    try:
        for scanner in bluetooth.async_current_scanners(hass):
            try:
                # discovered_devices_and_advertisement_data is a dict of
                # {address: (BLEDevice, AdvertisementData)}
                raw = getattr(
                    scanner, "discovered_devices_and_advertisement_data", {}
                )
                for address, (ble_device, adv_data) in raw.items():
                    if address not in seen:
                        # Build a minimal BluetoothServiceInfoBleak-compatible object
                        seen[address] = BluetoothServiceInfoBleak(
                            name=adv_data.local_name or ble_device.name or "",
                            address=address,
                            rssi=adv_data.rssi or -100,
                            manufacturer_data=adv_data.manufacturer_data or {},
                            service_data=adv_data.service_data or {},
                            service_uuids=adv_data.service_uuids or [],
                            source=getattr(scanner, "source", ""),
                            device=ble_device,
                            advertisement=adv_data,
                            connectable=True,
                            time=0,
                            tx_power=adv_data.tx_power,
                        )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Error reading scanner %s: %s", scanner, err)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Error iterating scanners: %s", err)

    return seen


class BK300ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for Konnwei BK300."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle auto-discovery via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not _is_bk300(discovery_info):
            return self.async_abort(reason="not_supported")

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
        """Handle manual setup — shows dropdown of all visible BLE devices."""
        errors: dict[str, str] = {}
        current_addresses = self._async_current_ids()

        # Gather all visible devices from all scanner sources
        all_infos = _get_all_ble_devices(self.hass)

        all_devices: dict[str, str] = {}
        bk300_devices: dict[str, str] = {}

        for address, info in all_infos.items():
            if address in current_addresses:
                continue
            name = info.name or "Unknown"
            # Strip null bytes (BK300 pads its name with \x00)
            name = name.replace("\x00", "").strip() or "Unknown"
            label = f"{name} ({address})"
            all_devices[address] = label
            if _is_bk300(info):
                bk300_devices[address] = label

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
