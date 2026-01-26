#!/usr/bin/env python3
"""Comprehensive Knox Chameleon64i discovery and diagnostic script."""

import asyncio
import sys
sys.path.insert(0, 'custom_components/knoxcham64i')

from chameleon_client import ChameleonClient


async def test_raw_commands(client):
    """Test raw commands to see actual responses."""
    print("\n" + "="*60)
    print("RAW COMMAND TESTING")
    print("="*60)

    commands = [
        ("D28", "Get crosspoint for zone 28"),
        ("$D28", "Get VTB (volume/tone/balance) for zone 28"),
        ("I", "Get firmware version"),
        ("D0136", "Get crosspoint range 1-36"),
    ]

    for cmd, desc in commands:
        print(f"\n{desc}")
        print(f"Command: {cmd}")
        print("-" * 60)
        try:
            response = await client._connection.send_command(cmd)
            print(f"Response:\n{response}")
        except Exception as e:
            print(f"ERROR: {e}")

    print("="*60)


async def discover_zones(client, max_zone=36):
    """Discover which zones are actually configured."""
    print("\n" + "="*60)
    print(f"ZONE DISCOVERY (scanning 1-{max_zone})")
    print("="*60)

    active_zones = []

    for zone in range(1, max_zone + 1):
        try:
            state = await client.get_zone_state(zone)

            # A zone is "active" if it has any real data
            is_active = (
                state.input_id is not None or
                (state.volume is not None and state.volume != zone) or  # Not just fallback
                state.is_muted is not None
            )

            if is_active:
                active_zones.append(zone)
                status = "✅ ACTIVE"
            else:
                status = "⚠️  No data"

            if zone <= 10 or is_active:  # Show first 10 or any active
                print(f"Zone {zone:2d}: {status} | Input={state.input_id}, Vol={state.volume}, Mute={state.is_muted}")

        except Exception as e:
            print(f"Zone {zone:2d}: ❌ ERROR - {e}")

    print("\n" + "-"*60)
    print(f"Summary: Found {len(active_zones)} zones with data")
    if active_zones:
        print(f"Active zones: {active_zones}")
    print("="*60)

    return active_zones


async def test_zone_operations(client, zone):
    """Test all operations on a specific zone."""
    print("\n" + "="*60)
    print(f"ZONE {zone} OPERATION TESTS")
    print("="*60)

    # Get initial state
    print(f"\n1. Initial state:")
    state = await client.get_zone_state(zone)
    print(f"   Input: {state.input_id}")
    print(f"   Volume: {state.volume} (Knox scale 0-63, 0=loudest)")
    print(f"   Muted: {state.is_muted}")

    original_input = state.input_id
    original_volume = state.volume if state.volume is not None else 30
    original_mute = state.is_muted

    # Test input switching
    print(f"\n2. Testing input switch to input 1...")
    try:
        await client.set_input(zone, 1)
        await asyncio.sleep(0.5)
        new_state = await client.get_zone_state(zone)
        if new_state.input_id == 1:
            print(f"   ✅ Success! Input is now: {new_state.input_id}")
        else:
            print(f"   ⚠️  Command sent but input is: {new_state.input_id}")

        # Restore if we had an original
        if original_input:
            await client.set_input(zone, original_input)
    except Exception as e:
        print(f"   ❌ Failed: {e}")

    # Test input switching to input 2
    print(f"\n3. Testing input switch to input 2...")
    try:
        await client.set_input(zone, 2)
        await asyncio.sleep(0.5)
        new_state = await client.get_zone_state(zone)
        if new_state.input_id == 2:
            print(f"   ✅ Success! Input is now: {new_state.input_id}")
        else:
            print(f"   ⚠️  Command sent but input is: {new_state.input_id}")

        # Restore
        if original_input:
            await client.set_input(zone, original_input)
    except Exception as e:
        print(f"   ❌ Failed: {e}")

    # Test volume
    print(f"\n4. Testing volume control (set to 15)...")
    try:
        await client.set_volume(zone, 15)
        await asyncio.sleep(0.5)
        new_state = await client.get_zone_state(zone)
        print(f"   Volume after set: {new_state.volume}")
        if new_state.volume == 15:
            print(f"   ✅ Volume changed successfully")
        else:
            print(f"   ⚠️  Volume may not have changed (expected 15, got {new_state.volume})")

        # Restore
        await client.set_volume(zone, original_volume)
    except Exception as e:
        print(f"   ❌ Failed: {e}")

    # Test mute
    print(f"\n5. Testing mute toggle...")
    try:
        new_mute = not original_mute
        await client.set_mute(zone, new_mute)
        await asyncio.sleep(0.5)
        new_state = await client.get_zone_state(zone)
        if new_state.is_muted == new_mute:
            print(f"   ✅ Mute changed to: {new_state.is_muted}")
        else:
            print(f"   ⚠️  Expected {new_mute}, got {new_state.is_muted}")

        # Restore
        await client.set_mute(zone, original_mute)
    except Exception as e:
        print(f"   ❌ Failed: {e}")

    # Final state
    print(f"\n6. Final state (should match initial):")
    state = await client.get_zone_state(zone)
    print(f"   Input: {state.input_id} (was {original_input})")
    print(f"   Volume: {state.volume} (was {original_volume})")
    print(f"   Muted: {state.is_muted} (was {original_mute})")

    print("="*60)


async def test_crosspoint_parsing(client):
    """Test how crosspoint data is being parsed."""
    print("\n" + "="*60)
    print("CROSSPOINT DATA PARSING TEST")
    print("="*60)

    # Get raw crosspoint response
    print("\nSending D28 command...")
    response = await client._connection.send_command("D28")
    print(f"\nRaw response:\n{repr(response)}")

    # Try to parse it
    print("\nParsing for OUTPUT lines:")
    lines = response.split('\n')
    for i, line in enumerate(lines):
        print(f"  Line {i}: {repr(line)}")
        if "OUTPUT" in line:
            parts = line.split()
            print(f"    -> Parts: {parts}")
            if len(parts) >= 6:
                try:
                    output_num = int(parts[1])
                    video_input = int(parts[3])
                    audio_input = int(parts[5])
                    print(f"    -> OUTPUT {output_num}: Video={video_input}, Audio={audio_input}")
                except Exception as e:
                    print(f"    -> Parse error: {e}")

    print("="*60)


async def main():
    """Run all diagnostic tests."""
    host = "192.168.0.69"
    port = 8899

    print("\n" + "="*60)
    print("KNOX CHAMELEON64i COMPREHENSIVE DIAGNOSTIC")
    print("="*60)
    print(f"Host: {host}:{port}")
    print("="*60)

    client = ChameleonClient(host=host, port=port, timeout=5.0, max_retries=3)

    try:
        print("\nConnecting...")
        await client.connect()
        print("✅ Connected\n")

        # Test 1: Raw commands
        await test_raw_commands(client)

        # Test 2: Crosspoint parsing
        await test_crosspoint_parsing(client)

        # Test 3: Discover zones
        active_zones = await discover_zones(client, max_zone=36)

        # Test 4: Detailed test on a few zones
        if active_zones:
            print("\n\nDETAILED TESTING ON SPECIFIC ZONES")
            # Test first active zone
            if len(active_zones) > 0:
                await test_zone_operations(client, active_zones[0])

            # Test zone 28 specifically since you mentioned it
            if 28 in active_zones or True:  # Always test 28
                await test_zone_operations(client, 28)

        print("\n" + "="*60)
        print("DIAGNOSTIC COMPLETE")
        print("="*60)
        print("\nPlease copy ALL the output above and send it back.")
        print("This will help identify exactly what's happening.")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("\nDisconnecting...")
        await client.disconnect()
        print("✅ Disconnected\n")


if __name__ == "__main__":
    asyncio.run(main())
