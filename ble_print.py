import asyncio
from bleak import BleakScanner, BleakClient

ADDR = "5A:4A:7B:AE:AE:CA"

# Start with the canonical BLE printer characteristic you found:
CANDIDATE_CHARS = [
    "00002af1-0000-1000-8000-00805f9b34fb",  # svc 18f0
    # fallbacks if 2af1 doesn't actually print on your model:
    "0000ff02-0000-1000-8000-00805f9b34fb",
    "0000ff82-0000-1000-8000-00805f9b34fb",
    "0000fff2-0000-1000-8000-00805f9b34fb",
    "0000fec7-0000-1000-8000-00805f9b34fb",
    "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
    "49535343-8841-43f4-a8d4-ecbe34729bb3",
]

def chunk(b: bytes, n: int = 20):
    # 20 bytes is the safest default for BLE writes without response
    for i in range(0, len(b), n):
        yield b[i:i+n]

async def try_print(client: BleakClient, char_uuid: str) -> bool:
    # ESC/POS: init + text + a few feeds + cut (cut may be ignored)
    data = b"\x1b@" + b"Hello from Raspberry Pi over BLE!\n\n\n" + b"\x1dV\x00"

    try:
        for part in chunk(data, 20):
            await client.write_gatt_char(char_uuid, part, response=False)
            await asyncio.sleep(0.02)  # tiny pacing helps reliability
        return True
    except Exception as e:
        print(f"  failed on {char_uuid}: {type(e).__name__}: {e}")
        return False

async def main():
    print("Scanning...")
    dev = await BleakScanner.find_device_by_address(ADDR, timeout=15.0)
    if dev is None:
        print("Printer not found in scan. Make sure it's ON and advertising.")
        return

    client = BleakClient(dev, timeout=20.0)
    await client.connect()
    try:
        print("Connected:", client.is_connected)

        for cu in CANDIDATE_CHARS:
            print("Trying characteristic:", cu)
            ok = await try_print(client, cu)
            if ok:
                print("✅ Sent print data using:", cu)
                break
        else:
            print("❌ Sent data to all candidates but none succeeded.")
            print("If it printed nothing, it may require a different char or a handshake/notify flow.")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

asyncio.run(main())
