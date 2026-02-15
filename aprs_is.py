import aprslib
import threading
import time
import queue
import socket

import asyncio
import logging

class AsyncIGate:
    def __init__(self, callsign, passcode, gateway_q, host="rotate.aprs2.net", port=14580):
        self.callsign = callsign
        self.passcode = passcode
        self.host = host
        self.port = port
        self.queue = gateway_q
        self.reader = None
        self.writer = None
        self.connected = False

    async def connect(self):
        while True:
            try:
                print(f"--- Connecting to APRS-IS ({self.host}:{self.port}) ---")
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                
                # TCP_NODELAY to disable Nagle's algorithm for lower latency
                sock = self.writer.get_extra_info('socket')
                if sock:
                    import socket
                    try:
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    except Exception as e:
                        print(f"Warning: Could not set TCP_NODELAY: {e}")

                # Login
                login_str = f"user {self.callsign} pass {self.passcode} vers AsyncAPRS 0.1\r\n"
                self.writer.write(login_str.encode('ascii'))
                await self.writer.drain()
                
                # Read login response
                response = await self.reader.read(1024)
                print(f"APRS-IS Login Response: {response.decode('ascii', errors='ignore').strip()}")
                
                self.connected = True
                return # Connected successfully

            except Exception as e:
                print(f"APRS-IS Connection Failed: {e}. Retrying in 5s...")
                self.connected = False
                await asyncio.sleep(5)

    async def send_loop(self):
        """
        Continuously consumes packets from the queue and sends them to APRS-IS.
        Maintains connection.
        """
        # Ensure initial connection
        await self.connect()

        while True:
            try:
                packet = await self.queue.get()
                if not self.connected:
                    await self.connect()
                
                if packet:
                    line = packet + "\r\n"
                    self.writer.write(line.encode('ascii'))
                    await self.writer.drain()
                    print(f"iGated >> {packet}")
                    
                self.queue.task_done()
                
            except Exception as e:
                print(f"Error in send_loop: {e}")
                self.connected = False
                # If we fail to send, we might lose that packet or we could try to re-queue it.
                # For now, simplest is to just reconnect and let the next packet go through.
                # Optional: await self.connect() here immediately?
                await asyncio.sleep(1) # Backoff slightly

    async def keepalive(self):
        """
        Optional: Send a keepalive comment if idle for a long time.
        APRS-IS usually terminates if no data for 20 mins.
        We are RX mostly, so we might need this if traffic is low.
        """
        while True:
            await asyncio.sleep(300) # 5 minutes
            if self.connected:
                try:
                    self.writer.write(f"# {self.callsign} keepalive\r\n".encode('ascii'))
                    await self.writer.drain()
                except Exception:
                    self.connected = False