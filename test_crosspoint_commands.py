#!/usr/bin/env python3
"""Test different crosspoint query commands to find what works."""

import asyncio
import sys
sys.path.insert(0, 'custom_components/knoxcham64i')

from chameleon_client import ChameleonClient


async def test_commands():
    """Test various crosspoint commands."""
    host = "192.168.0.69"
    port = 8899

    client = ChameleonClient(host=host, port=port, timeout=5.0, max_retries=3)

    try:
        await client.connect()
        print("Connected\n")

        commands = [
            ("D", "Query all crosspoints (no zone number)"),
            ("D01", "Query zone 1"),
            ("D25", "Query zone 25"),
            ("D0125", "Query range 1-25"),
            ("D2536", "Query range 25-36"),
            ("D0136", "Query range 1-36"),
            ("D0164", "Query range 1-64 (all zones)"),
        ]

        for cmd, desc in commands:
            print("="*60)
            print(f"{desc}")
            print(f"Command: {cmd}")
            print("-"*60)
            try:
                response = await client._connection.send_command(cmd)
                print(f"Response:\n{response}\n")

                # Parse OUTPUT lines
                if "OUTPUT" in response:
                    print("Found OUTPUT lines:")
                    for line in response.split('\n'):
                        if "OUTPUT" in line and "VIDEO" in line:
                            parts = line.split()
                            if len(parts) >= 6:
                                try:
                                    out_num = int(parts[1])
                                    vid_input = int(parts[3])
                                    aud_input = int(parts[5])
                                    print(f"  OUTPUT {out_num}: Video={vid_input}, Audio={aud_input}")
                                except:
                                    pass
                    print()
            except Exception as e:
                print(f"ERROR: {e}\n")

        print("="*60)
        print("\nNOW LET'S SEE IF WE CAN FIND ZONE 25:")
        print("="*60)

        # Try D (all zones)
        print("\nTrying command: D (query all)")
        response = await client._connection.send_command("D")
        zone_25_found = False

        for line in response.split('\n'):
            if "OUTPUT" in line and "VIDEO" in line:
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        out_num = int(parts[1])
                        if out_num == 25:
                            vid_input = int(parts[3])
                            aud_input = int(parts[5])
                            print(f"✅ FOUND ZONE 25: Video={vid_input}, Audio={aud_input}")
                            zone_25_found = True
                    except:
                        pass

        if not zone_25_found:
            print("❌ Zone 25 not found in 'D' response")

        print("\n" + "="*60)

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test_commands())
