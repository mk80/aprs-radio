import asyncio
import socket


class KissTCP:
    """
    Async KISS-over-TCP client for Dire Wolf (default port 8001).

    Reads are driven by asyncio's StreamReader, which uses epoll under the hood,
    so RX wakes the task the instant bytes arrive — no polling, no sleep floor.
    """

    def __init__(self, host='127.0.0.1', port=8001):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        sock = self.writer.get_extra_info('socket')
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception as e:
                print(f"Warning: Could not set TCP_NODELAY: {e}")
        print(f"Connected to Dire Wolf KISS at {self.host}:{self.port}")

    async def read(self, n=4096):
        """Block until at least one byte is available, then return up to n bytes."""
        return await self.reader.read(n)

    async def write_frame(self, kiss_frame):
        self.writer.write(kiss_frame)
        await self.writer.drain()

    async def close(self):
        if self.writer is not None:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            print(f"Disconnected from Dire Wolf KISS at {self.host}:{self.port}")
