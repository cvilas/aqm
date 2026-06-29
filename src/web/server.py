"""
aiohttp web server.

Serves:
  GET /           → index.html dashboard
  GET /ws         → WebSocket: pushes JSON frames every second
  GET /history    → JSON: last MAX_HISTORY readings

Each JSON frame has:
  {
    "ts":          ISO-8601 timestamp,
    "co2":         int | null,
    "pm1_0":       float | null,
    "pm2_5":       float | null,
    "pm4_0":       float | null,
    "pm10_0":      float | null,
    "humidity":    float | null,
    "temperature": float | null,
    "voc_index":   float | null,
    "nox_index":   float | null,
    "ups":         { "bus_voltage_v", "current_ma", "percent" } | null,
  }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from typing import Any, Deque, Optional, Set

from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)

MAX_HISTORY = 3600  # 1 hour at 1 reading/second

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class AQMWebServer:
    def __init__(self) -> None:
        self._app = web.Application()
        self._history: Deque[dict] = deque(maxlen=MAX_HISTORY)
        self._clients: Set[web.WebSocketResponse] = set()
        self._setup_routes()

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def _setup_routes(self) -> None:
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_get("/history", self._handle_history)

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------
    async def _handle_index(self, request: web.Request) -> web.Response:
        index_path = os.path.join(_STATIC_DIR, "index.html")
        with open(index_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        return web.Response(content_type="text/html", text=content)

    async def _handle_history(self, request: web.Request) -> web.Response:
        return web.Response(
            content_type="application/json",
            text=json.dumps(list(self._history)),
        )

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("WebSocket client connected (total: %d)", len(self._clients))

        # Send history backlog on connect so the chart populates immediately
        if self._history:
            await ws.send_str(json.dumps({"type": "history", "data": list(self._history)}))

        try:
            async for msg in ws:
                if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)
            logger.info("WebSocket client disconnected (total: %d)", len(self._clients))

        return ws

    # ------------------------------------------------------------------
    # Public: push a new frame to all connected clients
    # ------------------------------------------------------------------
    async def push(self, frame: dict) -> None:
        self._history.append(frame)
        if not self._clients:
            return
        text = json.dumps({"type": "reading", "data": frame})
        dead: list[web.WebSocketResponse] = []
        for ws in self._clients:
            try:
                await ws.send_str(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------
    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        logger.info("Web server started on http://%s:%d", host, port)

    async def stop(self) -> None:
        await self._runner.cleanup()
