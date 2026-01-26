#!/usr/bin/env python3
"""Direct test of blocking connection."""

import sys
sys.path.insert(0, 'custom_components/knoxcham64i')

from chameleon_client.connection_blocking import ChameleonConnectionBlocking
import asyncio


async def test():
    conn = ChameleonConnectionBlocking(
        host="192.168.0.69",
        port=8899,
        timeout=5.0,  # HF2211A is very slow, needs longer timeout
    )

    try:
        print("Test 1: Sending $D25 command...")
        response = await conn.send_command("$D25")
        print(f"Response: {response[:200]}")
        print()

        print("Test 2: Sending D0136 command...")
        response = await conn.send_command("D0136")
        print(f"Response length: {len(response)} bytes")
        print(f"Full response:\n{response}")
        print(f"\nLast 200 chars: {response[-200:]}")
        print()

        print("Test 3: Sending $D25 again...")
        response = await conn.send_command("$D25")
        print(f"Response: {response[:200]}")
        print()

        print("✅ All tests passed!")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test())
