#!/usr/bin/env python3
"""Test script for Knox Chameleon64i device connectivity and commands."""

import asyncio
import sys
sys.path.insert(0, 'custom_components/knoxcham64i')

from chameleon_client import ChameleonClient


async def test_knox():
    """Run comprehensive tests on Knox device."""

    host = "192.168.0.69"
    port = 8899

    print(f"\n{'='*60}")
    print(f"Knox Chameleon64i Connection Test")
    print(f"{'='*60}")
    print(f"Host: {host}")
    print(f"Port: {port}\n")

    client = ChameleonClient(host=host, port=port, timeout=5.0, max_retries=3)

    try:
        # Test 1: Connection
        print("Test 1: Connecting...")
        await client.connect()
        print("✅ Connection successful\n")

        # Test 2: Firmware version (I command)
        print("Test 2: Getting firmware version (I command)...")
        try:
            version = await client.get_firmware_version()
            if version:
                print(f"✅ Firmware: {version}\n")
            else:
                print("⚠️  No firmware version returned\n")
        except Exception as e:
            print(f"❌ Firmware command failed: {e}\n")

        # Test 3: Zone 28 state
        print("Test 3: Getting zone 28 state...")
        try:
            state = await client.get_zone_state(28)
            print(f"✅ Zone 28 State:")
            print(f"   - Input ID: {state.input_id}")
            print(f"   - Volume: {state.volume} (0-63, 0=loudest)")
            print(f"   - Muted: {state.is_muted}\n")
        except Exception as e:
            print(f"❌ Zone 28 state failed: {e}\n")

        # Test 4: Set input test
        print("Test 4: Testing input change (zone 28 → input 1)...")
        try:
            result = await client.set_input(28, 1)
            if result:
                print("✅ Set input command accepted\n")
            else:
                print("⚠️  Set input command not confirmed\n")
        except Exception as e:
            print(f"❌ Set input failed: {e}\n")

        # Test 5: Volume control test
        print("Test 5: Testing volume control (zone 28)...")
        try:
            # Save current volume
            current_state = await client.get_zone_state(28)
            original_volume = current_state.volume if current_state.volume is not None else 30

            # Test setting volume to 20 (mid-level)
            result = await client.set_volume(28, 20)
            if result:
                print("✅ Set volume command accepted")

                # Verify it changed
                await asyncio.sleep(0.5)
                new_state = await client.get_zone_state(28)
                print(f"   - New volume: {new_state.volume}\n")

                # Restore original volume
                await client.set_volume(28, original_volume)
                print(f"   - Restored to: {original_volume}\n")
            else:
                print("⚠️  Set volume command not confirmed\n")
        except Exception as e:
            print(f"❌ Volume test failed: {e}\n")

        # Test 6: Mute control test
        print("Test 6: Testing mute control (zone 28)...")
        try:
            # Get current mute state
            current_state = await client.get_zone_state(28)
            original_mute = current_state.is_muted

            # Toggle mute
            result = await client.set_mute(28, not original_mute)
            if result:
                print(f"✅ Set mute to {not original_mute}")

                # Restore original
                await asyncio.sleep(0.5)
                await client.set_mute(28, original_mute)
                print(f"   - Restored to: {original_mute}\n")
            else:
                print("⚠️  Set mute command not confirmed\n")
        except Exception as e:
            print(f"❌ Mute test failed: {e}\n")

        # Test 7: Multiple zones state (test coordinator behavior)
        print("Test 7: Testing multiple zones state fetch...")
        try:
            zones = [28, 1, 2]  # Test a few zones
            states = await client.get_all_zones_state(zones)
            print(f"✅ Retrieved {len(states)} zone states:")
            for zone_id, state in states.items():
                print(f"   - Zone {zone_id}: input={state.input_id}, vol={state.volume}, mute={state.is_muted}")
            print()
        except Exception as e:
            print(f"❌ Multiple zones test failed: {e}\n")

        print(f"{'='*60}")
        print("Test Summary:")
        print("If you see mostly ✅, the integration should work!")
        print("If you see ❌, copy the output and send it back.")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"❌ Fatal error: {e}\n")
        import traceback
        traceback.print_exc()

    finally:
        print("Disconnecting...")
        await client.disconnect()
        print("✅ Disconnected\n")


if __name__ == "__main__":
    asyncio.run(test_knox())
