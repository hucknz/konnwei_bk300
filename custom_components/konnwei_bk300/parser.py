"""Parser for Konnwei BK300 BLE notifications."""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

PACKET_HEADER = bytes([0x24, 0x24])
CMD_VOLTAGE = 0x4B
SUBCMD_VOLTAGE = 0x0B


@dataclass
class BK300Reading:
    """A parsed reading from the BK300."""
    voltage: float | None = None
    battery_percent: int | None = None
    charging: bool | None = None


def parse_notification(data: bytes) -> BK300Reading | None:
    """
    Parse a FFF1 notification from the BK300.

    Two packet formats observed:

    1. Structured $$ packet:
       24 24 [len_le2] [cmd] [subcmd] [payload...] [checksum_le2] 0D 0A
       Voltage packet (cmd=0x4B, sub=0x0B):
         payload[0:2] = voltage as uint16 LE / 100
         payload[2]   = state code (0x02 = charging)
         payload[3]   = unknown flags

    2. Raw 2-byte voltage:
       [voltage_le2] — uint16 LE / 100
    """
    if not data:
        return None

    # Structured packet
    if len(data) >= 8 and data[:2] == PACKET_HEADER:
        cmd = data[4]
        sub = data[5]
        payload = data[6:-4]  # strip header(2)+len(2)+cmd(1)+sub(1) and checksum(2)+crlf(2)

        if cmd == CMD_VOLTAGE and sub == SUBCMD_VOLTAGE and len(payload) >= 2:
            raw_voltage = struct.unpack_from("<H", payload, 0)[0]
            voltage = raw_voltage / 100.0

            if not (6.0 <= voltage <= 20.0):
                _LOGGER.debug("Voltage out of range: %.2fV", voltage)
                return None

            reading = BK300Reading(voltage=voltage)

            if len(payload) >= 3:
                # Byte 2 is a state code, not a percentage
                # Observed: 0x02 = charging, others = not charging
                state_code = payload[2]
                reading.charging = state_code == 0x02

            # Battery percent meaning unconfirmed, omit for now
            reading.battery_percent = None

            _LOGGER.debug(
                "Parsed voltage=%.2fV pct=%s charging=%s",
                voltage, reading.battery_percent, reading.charging,
            )
            return reading

        _LOGGER.debug("Unhandled structured packet cmd=0x%02X sub=0x%02X", cmd, sub)
        return None

    # Raw 2-byte voltage fallback
    if len(data) == 2:
        raw = struct.unpack("<H", data)[0]
        voltage = raw / 100.0
        if 6.0 <= voltage <= 20.0:
            _LOGGER.debug("Raw voltage packet: %.2fV", voltage)
            return BK300Reading(voltage=voltage)

    return None
