"""Collector service.

Telemetry arrives two ways:
- UDP datagrams of JSON lines from the patched game server (fast path)
- POST /ingest with a JSON array (handy for tests and tools)

Security note: the UDP listener has no authentication, so it binds to
127.0.0.1 by default. Only expose it on a trusted network.

Run:  uvicorn aegis_collector.app:create_app --factory --port 8000
"""

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .schema import Event, EventAdapter
from .store import EventStore

log = logging.getLogger("aegis.collector")

MAX_BATCH = 5000
UDP_RCVBUF = 8 * 1024 * 1024


class LiveHub:
    """Fans new events out to connected WebSocket clients."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, events: list[dict[str, Any]]) -> None:
        for q in list(self._subscribers):
            for ev in events:
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    break  # slow client: drop rather than stall ingestion


class Ingestor:
    def __init__(self, store: EventStore, hub: LiveHub) -> None:
        self.store = store
        self.hub = hub
        self.accepted = 0
        self.rejected = 0

    def ingest_lines(self, data: bytes) -> int:
        events = []
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(EventAdapter.validate_json(line))
            except ValidationError as exc:
                self.rejected += 1
                log.debug("rejected telemetry line: %s", exc.errors()[:1])
        self.commit(events)
        return len(events)

    def commit(self, events: list[Event]) -> None:
        if not events:
            return
        self.store.add_many(events)
        self.accepted += len(events)
        self.hub.publish([e.model_dump() for e in events])


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, ingestor: Ingestor) -> None:
        self.ingestor = ingestor

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            self.ingestor.ingest_lines(data)
        except Exception:  # never let one bad datagram kill the listener
            log.exception("failed to ingest datagram from %s", addr)


def create_app(
    db_path: str | None = None,
    udp_host: str | None = None,
    udp_port: int | None = None,
    enable_udp: bool = True,
) -> FastAPI:
    db_path = db_path or os.getenv("AEGIS_DB", "data/aegis.db")
    udp_host = udp_host or os.getenv("AEGIS_UDP_HOST", "127.0.0.1")
    udp_port = udp_port if udp_port is not None else int(os.getenv("AEGIS_UDP_PORT", "28800"))

    store = EventStore(db_path)
    hub = LiveHub()
    ingestor = Ingestor(store, hub)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        transport = None
        if enable_udp:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpProtocol(ingestor), local_addr=(udp_host, udp_port)
            )
            # The OS default receive buffer is small (64 KB on Windows); bursts
            # of telemetry overflow it and the kernel silently drops datagrams.
            sock = transport.get_extra_info("socket")
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_RCVBUF)
            log.info("telemetry UDP listening on %s:%d", udp_host, udp_port)
        try:
            yield
        finally:
            if transport:
                transport.close()
            store.close()

    app = FastAPI(title="Aegis AC collector", lifespan=lifespan)
    app.state.ingestor = ingestor

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "accepted": ingestor.accepted,
            "rejected": ingestor.rejected,
            "stored": store.count(),
        }

    @app.post("/ingest")
    async def ingest(events: list[Event]):
        if len(events) > MAX_BATCH:
            raise HTTPException(413, f"batch larger than {MAX_BATCH} events")
        ingestor.commit(events)
        return {"accepted": len(events)}

    @app.get("/events")
    def events(
        limit: int = Query(100, ge=1, le=5000),
        type: str | None = None,
        match_id: str | None = None,
        actor: int | None = None,
    ):
        return store.recent(limit=limit, type=type, match_id=match_id, actor=actor)

    @app.get("/matches")
    def matches():
        return store.matches()

    @app.get("/matches/{match_id}/players")
    def players(match_id: str):
        return store.players(match_id)

    @app.websocket("/ws/live")
    async def live(ws: WebSocket):
        await ws.accept()
        q = hub.subscribe()
        try:
            while True:
                await ws.send_json(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(q)

    return app
