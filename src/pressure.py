"""
Ambient pressure from Open-Meteo (https://open-meteo.com).

Open-Meteo is free, open-source, requires no API key, and is GDPR-compliant.
It returns surface_pressure in hPa, which matches exactly what the SEN66
set_ambient_pressure command expects.

Fetch interval: every 15 minutes is more than sufficient — surface pressure
changes slowly and the SEN66 accepts values to the nearest hPa.

Usage:
    client = PressureClient(latitude=51.5, longitude=-0.1)
    hpa = await client.fetch()   # returns int, e.g. 1013

On network error the previous value is returned so the sensor keeps its last
good compensation rather than falling back to the default 1013 hPa.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=surface_pressure"
    "&forecast_days=1"
)

_DEFAULT_PRESSURE_HPA = 1013


class PressureClient:
    def __init__(self, latitude: float, longitude: float) -> None:
        self._lat = latitude
        self._lon = longitude
        self._last: int = _DEFAULT_PRESSURE_HPA

    async def fetch(self) -> int:
        """Return the latest surface pressure in hPa.

        Falls back to the previous value on any network or parse error.
        """
        import aiohttp

        url = _API_URL.format(lat=self._lat, lon=self._lon)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            hpa = int(round(data["current"]["surface_pressure"]))
            hpa = max(700, min(1200, hpa))
            self._last = hpa
            logger.info("Ambient pressure updated: %d hPa", hpa)
        except Exception as exc:
            logger.warning("Pressure fetch failed (%s) – keeping %d hPa", exc, self._last)

        return self._last
