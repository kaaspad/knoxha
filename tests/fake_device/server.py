#!/usr/bin/env python3
"""
Fake Knox Chameleon64i Device Server

Simulates a Knox device for testing without hardware.
Supports various failure modes to test error handling.

Usage:
    python3 server.py --port 8899 --mode normal

Modes:
    - normal: Standard responses
    - slow: Delayed responses (tests timeout handling)
    - drop: Randomly drops responses (tests retry logic)
    - partial: Sends incomplete responses (tests framing)
    - hang: Stops responding after N commands (tests watchdog)
"""

import argparse
import asyncio
import logging
import random
import time

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)


class FakeKnoxDevice:
    """Fake Knox device for testing."""

    def __init__(self, mode: str = "normal", hang_after: int = 0):
        self.mode = mode
        self.hang_after = hang_after
        self._command_count = 0

        # Zone state storage
        self._zones = {}
        for z in range(1, 65):
            self._zones[z] = {
                "input": 1,
                "volume": z % 64,  # 0-63
                "muted": False,
            }

    def process_command(self, command: str) -> str:
        """Process a command and return response."""
        self._command_count += 1
        command = command.strip()
        _LOGGER.info(f"[CMD #{self._command_count}] {command}")

        # Hang mode: stop responding after N commands
        if self.mode == "hang" and self.hang_after > 0:
            if self._command_count > self.hang_after:
                _LOGGER.warning("HANG MODE: Not responding")
                return ""  # No response - will cause timeout

        # Slow mode: add delay
        if self.mode == "slow":
            delay = random.uniform(1.0, 4.0)
            _LOGGER.info(f"SLOW MODE: Delaying {delay:.1f}s")
            time.sleep(delay)

        # Drop mode: randomly don't respond
        if self.mode == "drop":
            if random.random() < 0.2:  # 20% drop rate
                _LOGGER.warning("DROP MODE: Dropping response")
                return ""

        # Parse command
        try:
            # Set mute: $Mxx0 or $Mxx1
            if command.startswith("$M"):
                zone = int(command[2:4])
                mute = command[4] == "1"
                self._zones[zone]["muted"] = mute
                return "DONE\r\n"

            # Set volume: $Vxxvv
            if command.startswith("$V"):
                zone = int(command[2:4])
                volume = int(command[4:6])
                self._zones[zone]["volume"] = volume
                return "DONE\r\n"

            # Get VTB: $Dxx
            if command.startswith("$D"):
                zone = int(command[2:4])
                state = self._zones.get(zone, {"volume": 32, "muted": False})
                v = state["volume"]
                m = 1 if state["muted"] else 0
                response = f"V:{v}  M:{m}  L:0  BL:00 BR:00 B: 0 T: 0\r\n"

                # Partial mode: truncate response
                if self.mode == "partial":
                    if random.random() < 0.1:
                        _LOGGER.warning("PARTIAL MODE: Truncating response")
                        response = response[:len(response)//2]

                return response

            # Set input: BxxII
            if command.startswith("B"):
                zone = int(command[1:3])
                input_id = int(command[3:5])
                self._zones[zone]["input"] = input_id
                return "DONE\r\n"

            # Get crosspoint: D0136 (returns all zones 1-36)
            if command.startswith("D01"):
                lines = []
                for z in range(1, 37):
                    state = self._zones.get(z, {"input": 1})
                    inp = state["input"]
                    lines.append(f"OUTPUT   {z:2d}   VIDEO   {inp:2d}   AUDIO   {inp:2d}")
                return "\r\n".join(lines) + "\r\nDONE\r\n"

            # Firmware version: I
            if command == "I":
                return "Knox Chameleon64i v1.0 (FAKE)\r\nDONE\r\n"

            _LOGGER.warning(f"Unknown command: {command}")
            return "ERROR\r\n"

        except Exception as e:
            _LOGGER.error(f"Error processing command: {e}")
            return "ERROR\r\n"


class FakeKnoxServer:
    """TCP server for fake Knox device."""

    def __init__(self, host: str, port: int, device: FakeKnoxDevice):
        self.host = host
        self.port = port
        self.device = device

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a client connection."""
        addr = writer.get_extra_info("peername")
        _LOGGER.info(f"Client connected: {addr}")

        # Send init bytes (like HF2211A)
        writer.write(b"\xff\xfe")
        await writer.drain()

        try:
            while True:
                # Read command until \r
                data = await asyncio.wait_for(
                    reader.readuntil(b"\r"),
                    timeout=30.0
                )
                command = data.decode("utf-8", errors="ignore").strip()

                if not command:
                    continue

                # Process command
                response = self.device.process_command(command)

                if response:
                    writer.write(response.encode("utf-8"))
                    await writer.drain()
                else:
                    # No response - simulate timeout
                    await asyncio.sleep(10)  # Make client timeout

        except asyncio.TimeoutError:
            _LOGGER.info(f"Client timeout: {addr}")
        except asyncio.IncompleteReadError:
            _LOGGER.info(f"Client disconnected: {addr}")
        except Exception as e:
            _LOGGER.error(f"Client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            _LOGGER.info(f"Client connection closed: {addr}")

    async def start(self):
        """Start the server."""
        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )

        addr = server.sockets[0].getsockname()
        _LOGGER.info(f"Fake Knox server listening on {addr}")
        _LOGGER.info(f"Mode: {self.device.mode}")

        async with server:
            await server.serve_forever()


async def main():
    parser = argparse.ArgumentParser(description="Fake Knox Device Server")
    parser.add_argument("--host", default="127.0.0.1", help="Listen address")
    parser.add_argument("--port", type=int, default=8899, help="Listen port")
    parser.add_argument("--mode", choices=["normal", "slow", "drop", "partial", "hang"],
                        default="normal", help="Failure mode")
    parser.add_argument("--hang-after", type=int, default=0,
                        help="Commands before hang (only for hang mode)")

    args = parser.parse_args()

    device = FakeKnoxDevice(mode=args.mode, hang_after=args.hang_after)
    server = FakeKnoxServer(args.host, args.port, device)

    try:
        await server.start()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    asyncio.run(main())
