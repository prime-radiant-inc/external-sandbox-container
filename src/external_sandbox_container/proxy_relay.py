"""Bounded socket streams over the existing agent pipe (stdlib, also used in guest).

The host endpoint has exactly one configured destination. The peer can never supply
an address. One acknowledged chunk per direction bounds each stream's buffering.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib

CHUNK_SIZE = 32768
MAX_STREAMS = 32
OPEN_TIMEOUT = 10
DRAIN_TIMEOUT = 120


class ProxyRelay:
    def __init__(self, send, *, address=None):
        self.send = send
        self.address = address  # None on the guest; fixed host proxy address otherwise.
        self.streams = {}
        self.tasks = set()
        self.last_id = 0
        self.closed = False

    def _track(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def accept(self, reader, writer):
        """Synchronous accept callback: never create unbounded connection tasks."""
        if self.closed or self.address is not None or len(self.tasks) >= MAX_STREAMS:
            writer.close()
            return
        self.last_id += 1
        stream = _Stream(self, self.last_id, reader, writer)
        self.streams[stream.id] = stream
        stream.task = self._track(stream.run())

    def feed(self, frame):
        """Dispatch without awaiting a socket, so RPC/process events remain live.

        Invalid frames are fatal to the private transport; callers close the relay
        and fail the agent connection. Frames for already closed IDs are ignored
        because both directions can close concurrently.
        """
        if self.closed:
            return
        action, ident = frame.get("action"), frame.get("streamId")
        allowed = {"event", "action", "streamId"}
        if action == "data":
            allowed |= {"seq", "data"}
        elif action == "ack":
            allowed.add("seq")
        if set(frame) != allowed or frame.get("event") != "proxy":
            raise ValueError("Invalid proxy frame fields")
        if type(ident) is not int or not 1 <= ident <= 2**53 - 1:
            raise ValueError("Invalid proxy stream ID")
        if action not in ("open", "opened", "data", "ack", "eof", "close"):
            raise ValueError("Invalid proxy frame action")
        if action == "open":
            if self.address is None or ident <= self.last_id or len(self.tasks) >= MAX_STREAMS:
                raise ValueError("Invalid or excessive proxy stream open")
            self.last_id = ident
            stream = _Stream(self, ident)
            self.streams[ident] = stream
            stream.task = self._track(stream.run())
            return
        if ident > self.last_id:
            raise ValueError("Proxy frame refers to an unopened stream")
        stream = self.streams.get(ident)
        if stream is None:
            return
        if action == "close":
            stream.remote_closed = True
            self.streams.pop(ident, None)
            if stream.writer is not None:
                stream.writer.close()
            stream.task.cancel()
        elif action == "opened":
            if self.address is not None or stream.opened.done():
                raise ValueError("Unexpected proxy open acknowledgement")
            stream.opened.set_result(None)
        elif action == "ack":
            seq = frame["seq"]
            if type(seq) is not int or stream.ack is None or stream.ack.done() or seq != stream.sent:
                raise ValueError("Unexpected proxy data acknowledgement")
            stream.ack.set_result(None)
        else:
            if not stream.opened.done() or stream.received_eof:
                raise ValueError("Proxy data received before open or after EOF")
            if action == "data":
                seq, encoded = frame["seq"], frame["data"]
                if type(seq) is not int or seq != stream.received + 1 or stream.receiving:
                    raise ValueError("Proxy data exceeds flow control window")
                if not isinstance(encoded, str) or len(encoded) > 4 * ((CHUNK_SIZE + 2) // 3):
                    raise ValueError("Oversized proxy data")
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError) as exc:
                    raise ValueError("Invalid proxy data encoding") from exc
                if not 1 <= len(data) <= CHUNK_SIZE:
                    raise ValueError("Invalid proxy chunk size")
                stream.received = seq
                stream.receiving = True
                stream.incoming.put_nowait((seq, data))
            else:
                stream.received_eof = True
                stream.incoming.put_nowait(None)

    async def close(self):
        self.closed = True
        for stream in self.streams.values():
            if stream.writer is not None:
                stream.writer.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        self.streams.clear()


class _Stream:
    def __init__(self, relay, ident, reader=None, writer=None):
        self.relay, self.id = relay, ident
        self.reader, self.writer = reader, writer
        self.opened = asyncio.get_running_loop().create_future()
        self.ack = None
        self.sent = self.received = 0
        self.receiving = self.received_eof = self.remote_closed = False
        self.incoming = asyncio.Queue(maxsize=2)
        self.task = None

    async def emit(self, action, **fields):
        await self.relay.send({"event": "proxy", "action": action, "streamId": self.id, **fields})

    async def upload(self):
        while data := await self.reader.read(CHUNK_SIZE):
            self.sent += 1
            self.ack = asyncio.get_running_loop().create_future()
            await self.emit("data", seq=self.sent, data=base64.b64encode(data).decode("ascii"))
            await asyncio.wait_for(self.ack, DRAIN_TIMEOUT)
            self.ack = None
        await self.emit("eof")

    async def download(self):
        while True:
            entry = await self.incoming.get()
            if entry is None:
                if self.writer.can_write_eof():
                    self.writer.write_eof()
                    await asyncio.wait_for(self.writer.drain(), DRAIN_TIMEOUT)
                return
            seq, data = entry
            self.writer.write(data)
            await asyncio.wait_for(self.writer.drain(), DRAIN_TIMEOUT)
            # Clear before sending the ACK: the next frame may arrive immediately.
            self.receiving = False
            await self.emit("ack", seq=seq)

    async def run(self):
        pumps = []
        try:
            if self.relay.address is None:
                await self.emit("open")
                await asyncio.wait_for(self.opened, OPEN_TIMEOUT)
            else:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(*self.relay.address, limit=CHUNK_SIZE), OPEN_TIMEOUT)
                self.opened.set_result(None)
                await self.emit("opened")
            self.writer.transport.set_write_buffer_limits(high=CHUNK_SIZE, low=CHUNK_SIZE // 2)
            pumps = [asyncio.create_task(self.upload()), asyncio.create_task(self.download())]
            await asyncio.gather(*pumps)
        except (Exception, asyncio.CancelledError):
            # Socket failures close this stream. They never create a direct route.
            pass
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            if self.writer is not None:
                self.writer.close()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(self.writer.wait_closed(), 2)
            self.relay.streams.pop(self.id, None)
            if not self.remote_closed and not self.relay.closed:
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(self.emit("close"), 2)
