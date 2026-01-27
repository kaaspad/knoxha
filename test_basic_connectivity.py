#!/usr/bin/env python3
"""Basic connectivity test - single command to diagnose device responsiveness."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "knoxcham64i"))

from chameleon_client import ChameleonClient


async def test_single_command():
    """Test if device responds to a single command."""
    print("=" * 70)
    print("BASIC CONNECTIVITY TEST")
    print("Testing single command to device at 192.168.0.69:8899")
    print("=" * 70)

    client = ChameleonClient(host="192.168.0.69", port=8899, timeout=5.0, max_retries=3)

    try:
        print("\n1. Testing connection...")
        await client.connect()
        connected = await client.test_connection()

        if connected:
            print("   ✓ Connection successful")
        else:
            print("   ✗ Connection failed")
            return False

        print("\n2. Querying zone 1 state...")
        try:
            state = await client.get_zone_state(1)
            print(f"   ✓ Got state: input={state.input_id}, vol={state.volume}, mute={state.is_muted}")
            return True
        except Exception as e:
            print(f"   ✗ Query failed: {e}")
            return False

    except Exception as e:
        print(f"   ✗ Connection error: {e}")
        return False
    finally:
        await client.disconnect()


if __name__ == "__main__":
    success = asyncio.run(test_single_command())
    print("\n" + "=" * 70)
    if success:
        print("✓ Device is responsive - ready for full testing")
        sys.exit(0)
    else:
        print("✗ Device is not responding - check network/power")
        sys.exit(1)
