"""
Waveshare UPS HAT (C) – INA219 battery monitor.

Ported directly from docs/ups/demo.py.

Key hardware facts (Waveshare UPS HAT C):
  - INA219 I²C address : 0x43  (not the default 0x40)
  - Shunt resistor      : 0.01 Ω
  - Range               : 16 V / 5 A, gain DIV_2_80 mV
  - CurrentLSB          : 0.1524 mA per bit
  - CalibrationRegister : 26868
  - PowerLSB            : 0.003048 W per bit
  - SoC mapping         : 3.0 V → 0 %,  4.2 V → 100 %
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    import smbus2
    _HAS_SMBUS = True
except ImportError:
    _HAS_SMBUS = False

INA219_ADDR = 0x43

# Register addresses
_REG_CONFIG      = 0x00
_REG_SHUNT_V     = 0x01
_REG_BUS_V       = 0x02
_REG_POWER       = 0x03
_REG_CURRENT     = 0x04
_REG_CALIBRATION = 0x05

# Calibration constants (from demo.py set_calibration_16V_5A)
_CAL_VALUE   = 26868
_CURRENT_LSB = 0.1524   # mA per bit
_POWER_LSB   = 0.003048  # W per bit

# Config: 16 V range | gain DIV_2_80mV | 12-bit 32-sample bus ADC |
#         12-bit 32-sample shunt ADC | shunt+bus continuous
_CONFIG = (
    (0x00 << 13) |  # BusVoltageRange.RANGE_16V
    (0x01 << 11) |  # Gain.DIV_2_80MV
    (0x0D << 7)  |  # ADCResolution.ADCRES_12BIT_32S (bus)
    (0x0D << 3)  |  # ADCResolution.ADCRES_12BIT_32S (shunt)
    0x07            # Mode.SANDBVOLT_CONTINUOUS
)


@dataclass
class UPSReading:
    bus_voltage_v:  float   # Battery terminal voltage (V)
    shunt_voltage_v: float  # Shunt voltage (V)
    current_ma:     float   # Charge/discharge current (mA)
    power_w:        float   # Instantaneous power (W)
    percent:        float   # Estimated SoC 0–100 %

    def to_dict(self) -> dict:
        return {
            "bus_voltage_v":   round(self.bus_voltage_v, 3),
            "shunt_voltage_v": round(self.shunt_voltage_v, 4),
            "current_ma":      round(self.current_ma, 1),
            "power_w":         round(self.power_w, 3),
            "percent":         round(self.percent, 1),
        }


class UPS:
    """Blocking driver for the INA219 on the Waveshare UPS HAT (C)."""

    def __init__(self, bus: int = 1) -> None:
        if not _HAS_SMBUS:
            raise RuntimeError("smbus2 is not installed")
        self._bus = smbus2.SMBus(bus)
        self._write(_REG_CALIBRATION, _CAL_VALUE)
        self._write(_REG_CONFIG, _CONFIG)

    # ------------------------------------------------------------------
    # Low-level register access (matches demo.py read/write exactly)
    # ------------------------------------------------------------------

    def _read(self, reg: int) -> int:
        data = self._bus.read_i2c_block_data(INA219_ADDR, reg, 2)
        return (data[0] << 8) | data[1]

    def _write(self, reg: int, value: int) -> None:
        self._bus.write_i2c_block_data(
            INA219_ADDR, reg,
            [(value >> 8) & 0xFF, value & 0xFF],
        )

    # ------------------------------------------------------------------
    # Measurement methods (mirroring demo.py getXxx methods)
    # ------------------------------------------------------------------

    def _get_shunt_voltage_mv(self) -> float:
        self._write(_REG_CALIBRATION, _CAL_VALUE)
        raw = self._read(_REG_SHUNT_V)
        if raw > 32767:
            raw -= 65535
        return raw * 0.01  # mV

    def _get_bus_voltage_v(self) -> float:
        self._write(_REG_CALIBRATION, _CAL_VALUE)
        self._read(_REG_BUS_V)                  # trigger conversion
        return (self._read(_REG_BUS_V) >> 3) * 0.004  # V

    def _get_current_ma(self) -> float:
        raw = self._read(_REG_CURRENT)
        if raw > 32767:
            raw -= 65535
        return raw * _CURRENT_LSB  # mA

    def _get_power_w(self) -> float:
        self._write(_REG_CALIBRATION, _CAL_VALUE)
        raw = self._read(_REG_POWER)
        if raw > 32767:
            raw -= 65535
        return raw * _POWER_LSB  # W

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self) -> UPSReading:
        bus_v    = self._get_bus_voltage_v()
        shunt_mv = self._get_shunt_voltage_mv()
        current  = self._get_current_ma()
        power    = self._get_power_w()

        # SoC: 3.0 V → 0 %, 4.2 V → 100 %  (from demo.py: (v-3)/1.2*100)
        percent = max(0.0, min(100.0, (bus_v - 3.0) / 1.2 * 100.0))

        return UPSReading(
            bus_voltage_v=bus_v,
            shunt_voltage_v=shunt_mv / 1000.0,
            current_ma=current,
            power_w=power,
            percent=percent,
        )

    def close(self) -> None:
        self._bus.close()
