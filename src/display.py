"""
Waveshare 2.13" e-ink display (B V4, 250×122) driver wrapper.

Renders a tabular summary of all AQ readings plus date/time and updates the
physical display. This module is designed to be called from a thread-pool
executor because the SPI/GPIO operations are blocking.

The display has two image planes:
  - Black/white (HBlackimage)
  - Red/yellow accent (HRYimage)

The table uses the black plane for text and borders; the header row uses the
red plane as a filled accent.
"""

from __future__ import annotations

import datetime
import importlib
import logging
import math
import os
import sys
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .sensor import AQReading

logger = logging.getLogger(__name__)

# Add the vendor library to sys.path so waveshare_epd can be imported.
_LIB_DIR = os.path.join(
    os.path.dirname(__file__), "..", "third_party", "display", "python", "lib"
)
_LIB_DIR = os.path.normpath(_LIB_DIR)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

# Font supplied with the Waveshare bundle
_FONT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "third_party", "display", "python", "pic", "Font.ttc"
)
_FONT_PATH = os.path.normpath(_FONT_PATH)

_EPD_WIDTH  = 250   # horizontal (landscape)
_EPD_HEIGHT = 122   # vertical (landscape)


def _load_epd():
    """Import the EPD driver lazily so the module can be imported on dev machines."""
    from waveshare_epd import epd2in13b_V4  # type: ignore[import]
    return epd2in13b_V4.EPD()


class EpaperDisplay:
    """Renders AQ readings onto the e-paper display."""

    def __init__(self) -> None:
        self._epd = None
        self._font_large = None
        self._font_small = None
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        try:
            from PIL import ImageFont
            self._epd = _load_epd()
            self._epd.init()
            self._epd.Clear()
            if os.path.exists(_FONT_PATH):
                self._font_large = ImageFont.truetype(_FONT_PATH, 14)
                self._font_small = ImageFont.truetype(_FONT_PATH, 11)
            else:
                self._font_large = ImageFont.load_default()
                self._font_small = ImageFont.load_default()
            self._initialized = True
        except Exception as exc:
            logger.error("e-paper init failed: %s", exc)
            raise

    def update(self, reading: "AQReading", ups_percent: Optional[float] = None) -> None:
        """Render the reading table and push it to the display."""
        self._ensure_init()
        from PIL import Image, ImageDraw

        now = datetime.datetime.now()

        # Landscape: width=250, height=122
        black_img = Image.new("1", (_EPD_WIDTH, _EPD_HEIGHT), 255)
        red_img   = Image.new("1", (_EPD_WIDTH, _EPD_HEIGHT), 255)
        draw_b = ImageDraw.Draw(black_img)
        draw_r = ImageDraw.Draw(red_img)

        # ------------------------------------------------------------------
        # Header bar (red accent)
        # ------------------------------------------------------------------
        draw_r.rectangle([0, 0, _EPD_WIDTH - 1, 14], fill=0)
        draw_b.text((4, 1), "AQM  " + now.strftime("%Y-%m-%d  %H:%M"), font=self._font_small, fill=1)
        if ups_percent is not None:
            batt_str = f"BAT {ups_percent:.0f}%"
            draw_b.text((_EPD_WIDTH - 52, 1), batt_str, font=self._font_small, fill=1)

        # ------------------------------------------------------------------
        # Table layout  (two columns of 4 rows each)
        # ------------------------------------------------------------------
        d = reading.to_dict()

        def _val(key: str, unit: str) -> str:
            v = d.get(key)
            if v is None:
                return "n/a"
            if isinstance(v, float):
                return f"{v:.1f}{unit}"
            return f"{v}{unit}"

        rows = [
            ("CO2",    _val("co2",         " ppm")),
            ("PM1.0",  _val("pm1_0",       " µg")),
            ("PM2.5",  _val("pm2_5",       " µg")),
            ("PM4.0",  _val("pm4_0",       " µg")),
            ("PM10",   _val("pm10_0",      " µg")),
            ("Temp",   _val("temperature", " °C")),
            ("Humid",  _val("humidity",    " %")),
            ("VOC",    _val("voc_index",   "")),
            ("NOx",    _val("nox_index",   "")),
        ]

        row_h = 11
        col_w = 125   # two equal columns
        y_start = 17

        for idx, (label, value) in enumerate(rows):
            col = idx % 2
            row = idx // 2
            x = col * col_w + 2
            y = y_start + row * row_h

            # Alternate-row shading using the red channel
            if row % 2 == 1:
                draw_r.rectangle([col * col_w, y - 1, (col + 1) * col_w - 1, y + row_h - 2], fill=0)
                draw_b.text((x, y), f"{label}: {value}", font=self._font_small, fill=1)
            else:
                draw_b.text((x, y), f"{label}: {value}", font=self._font_small, fill=0)

        # Column divider
        draw_b.line([col_w, 15, col_w, _EPD_HEIGHT - 1], fill=0)

        self._epd.display(
            self._epd.getbuffer(black_img),
            self._epd.getbuffer(red_img),
        )

    def sleep(self) -> None:
        if self._initialized and self._epd is not None:
            self._epd.sleep()

    def close(self) -> None:
        self.sleep()
