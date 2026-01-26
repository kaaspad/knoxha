#!/usr/bin/env python3
"""Check zone 25 current state."""

import sys
sys.path.insert(0, 'custom_components/knoxcham64i')

from chameleon_client.connection_blocking import ChameleonConnectionBlocking
import asyncio


async def test():
    conn = ChameleonConnectionBlocking(host="192.168.0.69", port=8899)

    # Get crosspoint data
    print("Sending D0136 command...")
    response = await conn.send_command("D0136")

    # Find zone 25
    for line in response.split('\n'):
        if 'OUTPUT   25 ' in line or 'OUTPUT  25 ' in line:
            print(f"Zone 25 line: {line}")
            parts = line.split()
            if len(parts) >= 6:
                print(f"  OUTPUT: {parts[1]}")
                print(f"  VIDEO: {parts[3]}")
                print(f"  AUDIO: {parts[5]}")


if __name__ == "__main__":
    asyncio.run(test())
