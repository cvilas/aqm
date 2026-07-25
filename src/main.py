"""
AQM main entry point.

Orchestrates three concurrent loops:
  1. Sensor loop    – reads SEN66 every second, broadcasts via WebSocket
  2. Pressure loop  – fetches ambient pressure from Open-Meteo every 15 min
                       and feeds it to the SEN66 for CO₂ compensation
  3. Web server     – serves the dashboard and WebSocket

Run with:
  python -m src.main
or (from the repo root):
  python src/main.py
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aqm")

# ---------------------------------------------------------------------------
# Optional hardware imports – fall back to simulated data on non-Pi hardware
# ---------------------------------------------------------------------------
try:
    from .sensor import SEN66, AQReading
    _HAS_SENSOR = True
except Exception as exc:
    logger.warning("SEN66 unavailable (%s) – using simulated data", exc)
    _HAS_SENSOR = False

try:
    from .ups import UPS
    _HAS_UPS = True
except Exception as exc:
    logger.warning("UPS unavailable (%s)", exc)
    _HAS_UPS = False

from .web.server import AQMWebServer
from .pressure import PressureClient

_PRESSURE_INTERVAL = 15 * 60  # seconds between Open-Meteo fetches

# ---------------------------------------------------------------------------
# Simulated sensor for dev/testing
# ---------------------------------------------------------------------------
import math
import random
import time as _time

_sim_t0 = _time.monotonic()


def _simulate_reading() -> dict:
    t = _time.monotonic() - _sim_t0
    return {
        "co2":         int(600 + 200 * math.sin(t / 120)),
        "pm1_0":       round(3 + 2 * abs(math.sin(t / 60)), 1),
        "pm2_5":       round(5 + 3 * abs(math.sin(t / 60)), 1),
        "pm4_0":       round(7 + 4 * abs(math.sin(t / 60)), 1),
        "pm10_0":      round(10 + 5 * abs(math.sin(t / 60)), 1),
        "humidity":    round(45 + 10 * math.sin(t / 300), 1),
        "temperature": round(22 + 2 * math.sin(t / 600), 1),
        "voc_index":   round(100 + 50 * abs(math.sin(t / 90)), 1),
        "nox_index":   round(20 + 10 * abs(math.sin(t / 90)), 1),
    }


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------
class AQMApp:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080,
                 latitude: Optional[float] = None,
                 longitude: Optional[float] = None) -> None:
        self._host = host
        self._port = port
        self._server = AQMWebServer()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aqm")
        self._sensor: Optional[object] = None
        self._ups: Optional[object] = None
        self._last_reading: Optional[dict] = None
        self._running = False
        self._ambient_hpa: int = 1013  # updated by _pressure_loop
        self._pressure_client: Optional[PressureClient] = (
            PressureClient(latitude, longitude)
            if latitude is not None and longitude is not None
            else None
        )

    # ------------------------------------------------------------------
    # Hardware init (in thread so constructor stays fast)
    # ------------------------------------------------------------------
    def _init_hardware(self) -> None:
        global _HAS_SENSOR, _HAS_UPS, _HAS_DISPLAY
        if _HAS_SENSOR:
            try:
                self._sensor = SEN66(bus=1)
                self._sensor.reset()
                self._sensor.start_measurement()
                logger.info("SEN66 started")
            except Exception as exc:
                logger.error("SEN66 init failed: %s", exc)
                _HAS_SENSOR = False

        if _HAS_UPS:
            try:
                self._ups = UPS(bus=1)
                logger.info("UPS INA219 ready")
            except Exception as exc:
                logger.error("UPS init failed: %s", exc)
                _HAS_UPS = False

    def _shutdown_hardware(self) -> None:
        if self._sensor is not None:
            try:
                self._sensor.close()
            except Exception:
                pass
        if self._ups is not None:
            try:
                self._ups.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Sensor polling (blocking – runs in executor)
    # ------------------------------------------------------------------
    def _poll_sensor(self) -> dict:
        if _HAS_SENSOR and self._sensor is not None:
            try:
                if self._sensor.is_data_ready():
                    reading = self._sensor.read()
                    data = reading.to_dict()
                else:
                    data = self._last_reading or {}
            except Exception as exc:
                logger.warning("Sensor read error: %s", exc)
                data = self._last_reading or {}
        else:
            data = _simulate_reading()

        ups_data = None
        if _HAS_UPS and self._ups is not None:
            try:
                ups_data = self._ups.read().to_dict()
            except Exception as exc:
                logger.warning("UPS read error: %s", exc)

        frame = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            **data,
            "ups": ups_data,
            "pressure_hpa": self._ambient_hpa,
            "pressure_lat": self._pressure_client._lat if self._pressure_client else None,
            "pressure_lon": self._pressure_client._lon if self._pressure_client else None,
        }
        return frame

    # ------------------------------------------------------------------
    # Async loops
    # ------------------------------------------------------------------
    async def _sensor_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            t0 = loop.time()
            try:
                frame = await loop.run_in_executor(self._executor, self._poll_sensor)
                self._last_reading = frame
                await self._server.push(frame)
            except Exception as exc:
                logger.error("Sensor loop error: %s", exc)

            # Maintain ~1 Hz cadence
            elapsed = loop.time() - t0
            await asyncio.sleep(max(0.0, 1.0 - elapsed))

    async def _pressure_loop(self) -> None:
        """Fetch ambient pressure from Open-Meteo and push it to the SEN66
        every _PRESSURE_INTERVAL seconds for CO₂ compensation."""
        if self._pressure_client is None:
            return
        while self._running:
            hpa = await self._pressure_client.fetch()
            self._ambient_hpa = hpa
            if _HAS_SENSOR and self._sensor is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    self._executor,
                    self._sensor.set_ambient_pressure,
                    hpa,
                )
            await asyncio.sleep(_PRESSURE_INTERVAL)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    async def run(self) -> None:
        self._running = True

        # Init hardware in thread so the event loop isn't blocked
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._init_hardware)

        await self._server.start(self._host, self._port)

        sensor_task   = asyncio.create_task(self._sensor_loop(),   name="sensor")
        pressure_task = asyncio.create_task(self._pressure_loop(), name="pressure")

        if self._pressure_client is not None:
            logger.info("Pressure compensation enabled (lat=%.4f, lon=%.4f)",
                        self._pressure_client._lat, self._pressure_client._lon)
        else:
            logger.info("Pressure compensation disabled – no --lat/--lon provided")

        logger.info("AQM running – open http://%s:%d in your browser", self._host, self._port)

        try:
            await asyncio.gather(sensor_task, pressure_task)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            sensor_task.cancel()
            pressure_task.cancel()
            await self._server.stop()
            await loop.run_in_executor(self._executor, self._shutdown_hardware)
            self._executor.shutdown(wait=False)
            logger.info("AQM stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Air Quality Monitor")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")
    parser.add_argument("--lat",  type=float, default=None,
                        help="Latitude for Open-Meteo pressure fetch (enables CO₂ compensation)")
    parser.add_argument("--lon",  type=float, default=None,
                        help="Longitude for Open-Meteo pressure fetch")
    args = parser.parse_args()

    if (args.lat is None) != (args.lon is None):
        parser.error("--lat and --lon must be provided together")

    app = AQMApp(host=args.host, port=args.port, latitude=args.lat,
                 longitude=args.lon)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal():
        logger.info("Shutdown requested")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        loop.run_until_complete(app.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
