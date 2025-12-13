import asyncio
from bleak import BleakScanner, BleakClient

TARGET_ADDR = "5A:4A:7B:AE:AE:CA"

async def main():
    print("Scanning for BLE advertisements...")
    device = await BleakScanner.find_device_by_address(TARGET_ADDR, timeout=15.0)
    if device is None:
        print("Not found. Make sure the printer is ON and advertising.")
        return

    print("Found:", device)

    client = BleakClient(device, timeout=20.0)
    try:
        await client.connect()
        print("Connected:", client.is_connected)

        # In Bleak 2.x, services are enumerated automatically on connect.
        services = client.services  # <-- property, not a method
        for service in services:
            for char in service.characteristics:
                props = ",".join(char.properties)
                if "write" in char.properties or "write-without-response" in char.properties:
                    print(f"WRITEABLE: svc={service.uuid} char={char.uuid} props={props}")

    finally:
        try:
            await client.disconnect()
        except Exception as e:
            # BlueZ/dbus can be noisy on disconnect; not fatal for our purposes.
            print("Disconnect warning:", repr(e))

asyncio.run(main())
