# Konnwei BK300 Battery Monitor — Home Assistant Integration

A custom HACS integration for the Konnwei BK300 Bluetooth battery monitor.

## Features

- Auto-discovers nearby BK300 devices via Bluetooth
- Manual device selection by MAC address
- Configurable polling interval (default 10 minutes, range 1–60 minutes)
- Voltage sensor with persisted last-known value (survives HA restarts)
- Battery percentage and charging state as extra attributes
- A "Poll Now" button to refresh the device immediately

## Requirements

- Home Assistant 2023.9.0 or later
- A Bluetooth adapter or [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)
- Konnwei BK300 battery monitor

## Installation via HACS

1. In HACS, go to **Integrations → Custom Repositories**
2. Add `https://github.com/hucknz/konnwei_bk300` and select **Integration** as the category
3. Install **Konnwei BK300 Battery Monitor**
4. Restart Home Assistant

## Manual Installation

1. Copy the `custom_components/konnwei_bk300` folder to your HA `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Konnwei BK300**
3. If your device is nearby it will be auto-discovered — just confirm and set your poll interval
4. Or enter the MAC address manually (visible in nRF Connect or similar BLE scanner)

## Protocol Notes

This integration was reverse-engineered by capturing BLE traffic from the official BKMonitor app.

The BK300 uses a custom protocol over BLE service `FFF0`:
- **FFF1** — Notify (device sends data here)
- **FFF2** — Write Without Response (commands sent here)

On connect, a 5-step init sequence is sent to FFF2 using `4040` header packets, followed by a voltage poll command (`0B0B`). The device responds on FFF1 with a `2424` header packet containing voltage as a little-endian uint16 divided by 100.

## Sensors

| Sensor | Unit | Description |
|--------|------|-------------|
| Battery Voltage | V | Current battery voltage (e.g. 12.69V) |

Extra attributes on the voltage sensor:
- `mac_address` — BLE MAC of the device
- `battery_percent` — Battery percentage (if available)
- `charging` — Whether the battery is being charged (if available)

The integration also adds a "Poll Now" button on the device page to trigger an immediate refresh.

## Options

After setup, click **Configure** on the integration to change the poll interval.
