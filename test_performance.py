#!/usr/bin/env python3
"""Test performance of optimized connection."""

import asyncio
import sys
import time
sys.path.insert(0, 'custom_components/knoxcham64i')

from chameleon_client import ChameleonClient


async def test():
    client = ChameleonClient(host="192.168.0.69", port=8899)

    try:
        print("\n" + "="*60)
        print("PERFORMANCE TEST")
        print("="*60)

        # Test 1: Get 3 zones sequentially
        start = time.time()
        for zone in [1, 2, 25]:
            state = await client.get_zone_state(zone)
            print(f"Zone {zone}: input={state.input_id}, vol={state.volume}, mute={state.is_muted}")
        elapsed = time.time() - start
        print(f"\n⏱️  Time to get 3 zones: {elapsed:.2f} seconds")

        # Test 2: Set input
        print("\n" + "-"*60)
        start = time.time()
        await client.set_input(25, 1)
        elapsed = time.time() - start
        print(f"⏱️  Time to set input: {elapsed:.2f} seconds")

        # Test 3: Set volume
        start = time.time()
        await client.set_volume(25, 20)
        elapsed = time.time() - start
        print(f"⏱️  Time to set volume: {elapsed:.2f} seconds")

        print("\n" + "="*60)
        print("Performance test complete!")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test())
