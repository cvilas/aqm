"""
SEN66 air quality sensor driver via I2C.

Implements the Sensirion I2C protocol (2-byte commands, CRC-8 per word) and
exposes a simple async-friendly interface. All values are returned as floats
with NaN for unavailable readings, matching the behaviour documented in the
Sensirion datasheet and the reference C driver.

I2C address: 0x6B
CRC polynomial: 0x31, init: 0xFF
"""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from typing import Optional

try:
    import smbus2
    _HAS_SMBUS = True
except ImportError:
    _HAS_SMBUS = False

# ---------------------------------------------------------------------------
# I2C address
# ---------------------------------------------------------------------------
SEN66_ADDR = 0x6B

# ---------------------------------------------------------------------------
# Command IDs (16-bit, sent MSB first)
# ---------------------------------------------------------------------------
_CMD_START_MEASUREMENT      = 0x0021
_CMD_STOP_MEASUREMENT       = 0x0104
_CMD_GET_DATA_READY         = 0x0202
_CMD_READ_VALUES_INT        = 0x0300
_CMD_SET_AMBIENT_PRESSURE   = 0x6720
_CMD_DEVICE_RESET           = 0xD304

# ---------------------------------------------------------------------------
# CRC helpers (Sensirion CRC-8, poly=0x31, init=0xFF)
# ---------------------------------------------------------------------------
_CRC_POLY = 0x31
_CRC_INIT = 0xFF


def _crc8(data: bytes) -> int:
    crc = _CRC_INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ _CRC_POLY) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def _check_crc(data: bytes, expected: int) -> bool:
    return _crc8(data) == expected


def _parse_words(raw: bytes) -> list[int]:
    """Strip CRC bytes and return list of 16-bit raw words.

    Each word is 2 data bytes + 1 CRC byte; raises ValueError on bad CRC.
    """
    words: list[int] = []
    for i in range(0, len(raw), 3):
        msb, lsb, crc = raw[i], raw[i + 1], raw[i + 2]
        if not _check_crc(bytes([msb, lsb]), crc):
            raise ValueError(f"CRC error at word {i // 3}")
        words.append((msb << 8) | lsb)
    return words


def _uint16_to_signed(val: int) -> int:
    return val if val < 0x8000 else val - 0x10000


# ---------------------------------------------------------------------------
# Dataclass for a single reading
# ---------------------------------------------------------------------------
@dataclass
class AQReading:
    pm1_0:   float   # μg/m³
    pm2_5:   float   # μg/m³
    pm4_0:   float   # μg/m³
    pm10_0:  float   # μg/m³
    humidity:    float   # %RH
    temperature: float   # °C
    voc_index:   float   # dimensionless index
    nox_index:   float   # dimensionless index
    co2:         int     # ppm (0xFFFF → None)

    def to_dict(self) -> dict:
        def _fmt(v: float) -> Optional[float]:
            return None if math.isnan(v) else round(v, 2)

        return {
            "pm1_0":       _fmt(self.pm1_0),
            "pm2_5":       _fmt(self.pm2_5),
            "pm4_0":       _fmt(self.pm4_0),
            "pm10_0":      _fmt(self.pm10_0),
            "humidity":    _fmt(self.humidity),
            "temperature": _fmt(self.temperature),
            "voc_index":   _fmt(self.voc_index),
            "nox_index":   _fmt(self.nox_index),
            "co2":         None if self.co2 == 0xFFFF else self.co2,
        }


# ---------------------------------------------------------------------------
# Sensor driver
# ---------------------------------------------------------------------------
class SEN66:
    """Blocking driver for SEN66 over I2C using smbus2.

    For the PoC this is called from a thread-pool executor so that it does not
    block the asyncio event loop.
    """

    def __init__(self, bus: int = 1) -> None:
        if not _HAS_SMBUS:
            raise RuntimeError("smbus2 is not installed")
        self._bus = smbus2.SMBus(bus)
        self._started = False

    # ------------------------------------------------------------------
    # Low-level I2C helpers
    # ------------------------------------------------------------------

    def _write_cmd(self, cmd: int) -> None:
        data = [(cmd >> 8) & 0xFF, cmd & 0xFF]
        msg = smbus2.i2c_msg.write(SEN66_ADDR, data)
        self._bus.i2c_rdwr(msg)

    def _read_bytes(self, n_bytes: int) -> bytes:
        msg = smbus2.i2c_msg.read(SEN66_ADDR, n_bytes)
        self._bus.i2c_rdwr(msg)
        return bytes(msg)

    def _cmd_and_read(self, cmd: int, n_words: int, delay_ms: int = 20) -> list[int]:
        """Send command, wait delay_ms, then read n_words (each word has CRC)."""
        self._write_cmd(cmd)
        time.sleep(delay_ms / 1000.0)
        raw = self._read_bytes(n_words * 3)
        return _parse_words(raw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._write_cmd(_CMD_DEVICE_RESET)
        time.sleep(1.2)
        self._started = False

    def start_measurement(self) -> None:
        self._write_cmd(_CMD_START_MEASUREMENT)
        time.sleep(1.1)
        self._started = True

    def stop_measurement(self) -> None:
        self._write_cmd(_CMD_STOP_MEASUREMENT)
        time.sleep(0.05)
        self._started = False

    def set_ambient_pressure(self, pressure_hpa: int) -> None:
        """Feed the current ambient pressure (hPa) into the CO₂ compensation.

        Valid range: 700–1200 hPa (datasheet §4.8.36).
        Call this whenever a fresh barometric reading is available;
        the sensor applies the correction to subsequent CO₂ readings.
        """
        pressure_hpa = max(700, min(1200, int(pressure_hpa)))
        # Command word (2 bytes) + uint16 value (2 bytes) + CRC (1 byte) = 5 bytes
        cmd_hi = (_CMD_SET_AMBIENT_PRESSURE >> 8) & 0xFF
        cmd_lo = _CMD_SET_AMBIENT_PRESSURE & 0xFF
        val_hi = (pressure_hpa >> 8) & 0xFF
        val_lo = pressure_hpa & 0xFF
        crc = _crc8(bytes([val_hi, val_lo]))
        msg = smbus2.i2c_msg.write(SEN66_ADDR, [cmd_hi, cmd_lo, val_hi, val_lo, crc])
        self._bus.i2c_rdwr(msg)
        time.sleep(0.02)  # 20 ms per datasheet

    def is_data_ready(self) -> bool:
        words = self._cmd_and_read(_CMD_GET_DATA_READY, n_words=1, delay_ms=20)
        # word[0]: upper byte padding, lower byte is ready flag
        return bool(words[0] & 0x01)

    def read(self) -> AQReading:
        """Read measured values. The sensor must be in measurement mode."""
        # Response: 9 words × (2 data bytes + 1 CRC) = 27 bytes
        words = self._cmd_and_read(_CMD_READ_VALUES_INT, n_words=9, delay_ms=20)

        pm1_0_raw   = words[0]
        pm2_5_raw   = words[1]
        pm4_0_raw   = words[2]
        pm10_0_raw  = words[3]
        hum_raw     = _uint16_to_signed(words[4])
        temp_raw    = _uint16_to_signed(words[5])
        voc_raw     = _uint16_to_signed(words[6])
        nox_raw     = _uint16_to_signed(words[7])
        co2_raw     = words[8]

        def _u16_to_float(v: int) -> float:
            return math.nan if v == 0xFFFF else v / 10.0

        def _s16_to_float(v: int) -> float:
            return math.nan if v == 0x7FFF else v / 10.0

        return AQReading(
            pm1_0=_u16_to_float(pm1_0_raw),
            pm2_5=_u16_to_float(pm2_5_raw),
            pm4_0=_u16_to_float(pm4_0_raw),
            pm10_0=_u16_to_float(pm10_0_raw),
            humidity=math.nan if hum_raw == 0x7FFF else hum_raw / 100.0,
            temperature=math.nan if temp_raw == 0x7FFF else temp_raw / 200.0,
            voc_index=_s16_to_float(voc_raw),
            nox_index=_s16_to_float(nox_raw),
            co2=co2_raw,
        )

    def close(self) -> None:
        try:
            if self._started:
                self.stop_measurement()
        finally:
            self._bus.close()
