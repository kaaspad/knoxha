#!/usr/bin/env python3
"""Test input switching on zone 25 so user can hear the change."""

import asyncio
import sys
sys.path.insert(0, 'custom_components/knoxcham64i')

from chameleon_client import ChameleonClient


async def test():
    client = ChameleonClient(host="192.168.0.69", port=8899)

    try:
        print("\n" + "="*60)
        print("ZONE 25 INPUT SWITCHING TEST")
        print("="*60)
        print("You should be in zone 25 (physically in that room) to hear changes.\n")

        await client.connect()

        # Get current state
        print("1. Getting current state of zone 25...")
        state = await client.get_zone_state(25)
        print(f"   Current input: {state.input_id}")
        print(f"   Current volume: {state.volume}")
        print(f"   Current mute: {state.is_muted}\n")

        original_input = state.input_id if state.input_id is not None else 1

        # Switch to input 1
        print("2. Switching to INPUT 1...")
        await client.set_input(25, 1)
        print("   ✅ Command sent")
        print("   >>> LISTEN: You should hear audio from INPUT 1")
        await asyncio.sleep(3)

        # Verify
        state = await client.get_zone_state(25)
        print(f"   Verified: Zone 25 is now on input {state.input_id}\n")

        # Switch to input 2
        print("3. Switching to INPUT 2...")
        await client.set_input(25, 2)
        print("   ✅ Command sent")
        print("   >>> LISTEN: You should hear audio from INPUT 2 (different source)")
        await asyncio.sleep(3)

        # Verify
        state = await client.get_zone_state(25)
        print(f"   Verified: Zone 25 is now on input {state.input_id}\n")

        # Switch back to input 1
        print("4. Switching back to INPUT 1...")
        await client.set_input(25, 1)
        print("   ✅ Command sent")
        print("   >>> LISTEN: You should hear INPUT 1 again")
        await asyncio.sleep(2)

        # Verify
        state = await client.get_zone_state(25)
        print(f"   Verified: Zone 25 is now on input {state.input_id}\n")

        # Restore original
        print(f"5. Restoring to original input {original_input}...")
        await client.set_input(25, original_input)
        state = await client.get_zone_state(25)
        print(f"   ✅ Restored to input {state.input_id}\n")

        print("="*60)
        print("TEST COMPLETE")
        print("If you heard the audio source change, it's working!")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test())
