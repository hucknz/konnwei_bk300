"""Constants for Konnwei BK300 integration."""

DOMAIN = "konnwei_bk300"
MANUFACTURER = "Konnwei"
MODEL = "BK300"

# BLE UUIDs
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
NOTIFY_CHARACTERISTIC_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
WRITE_CHARACTERISTIC_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

# Device identification
DEVICE_NAME = "Battery Monitor"
MANUFACTURER_ID = 0x00B3  # Clarinox Technologies

# Init sequence — exact bytes captured from BKMonitor app via PacketLogger
# Format: 40 40 [len_le2] [cmd] [subcmd] [payload] [checksum_le2] 0D 0A
INIT_SEQUENCE = [
    # Step 1: Handshake
    bytes([0x40, 0x40, 0x0A, 0x00, 0x02, 0x03, 0xF9, 0xE9, 0x0D, 0x0A]),
    # Step 2: Config request
    bytes([0x40, 0x40, 0x0E, 0x00, 0x0B, 0x01, 0xD4, 0xA4, 0xFF, 0x69, 0x29, 0x25, 0x0D, 0x0A]),
    # Step 3: Status request
    bytes([0x40, 0x40, 0x0A, 0x00, 0x05, 0x02, 0x78, 0xB5, 0x0D, 0x0A]),
    # Step 4: Enable
    bytes([0x40, 0x40, 0x0A, 0x00, 0x01, 0x00, 0x0A, 0xF1, 0x0D, 0x0A]),
    # Step 5: Request voltage data (0B0B)
    bytes([0x40, 0x40, 0x0A, 0x00, 0x0B, 0x0B, 0xA9, 0xB2, 0x0D, 0x0A]),
]

# Voltage poll command — sent periodically to get fresh readings
VOLTAGE_POLL_CMD = bytes([0x40, 0x40, 0x0A, 0x00, 0x0B, 0x0B, 0xA9, 0xB2, 0x0D, 0x0A])

# Response packet parsing
PACKET_HEADER = bytes([0x24, 0x24])
CMD_VOLTAGE = 0x4B
SUBCMD_VOLTAGE = 0x0B

# Config keys
CONF_POLL_INTERVAL = "poll_interval"
CONF_ADDRESS = "address"

# Defaults
DEFAULT_POLL_INTERVAL = 10  # minutes
MIN_POLL_INTERVAL = 1       # minutes
MAX_POLL_INTERVAL = 60      # minutes

# Storage
STORAGE_KEY = "konnwei_bk300_last_voltage"
