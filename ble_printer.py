import asyncio
import os
from typing import Optional

from bleak import BleakClient, BleakScanner


BLE_WRITE_UUID = os.getenv("BLE_WRITE_UUID", "").strip() or "00002af1-0000-1000-8000-00805f9b34fb"
BLE_CHUNK_SIZE = int(os.getenv("BLE_CHUNK_SIZE", "20"))
BLE_WRITE_GAP_SEC = float(os.getenv("BLE_WRITE_GAP_SEC", "0.02"))


def _chunk(data: bytes, n: int):
    for i in range(0, len(data), n):
        yield data[i : i + n]


def _escpos_frame(text: str) -> bytes:
    """
    Minimal ESC/POS:
      ESC @      initialize
      text
      \n\n\n     feed
      GS V 0     cut (some printers ignore)
    """
    return (
        b"\x1b@" +
        text.encode("utf-8", errors="replace") +
        b"\n\n\n" +
        b"\x1dV\x00"
    )


async def _find_device_by_address(addr: str, timeout: float = 8.0):
    addr = addr.upper()

    def matcher(d, _ad):
        return (d.address or "").upper() == addr

    return await BleakScanner.find_device_by_filter(matcher, timeout=timeout)


async def _ble_write(addr: str, payload: bytes):
    device = await _find_device_by_address(addr, timeout=8.0)
    if device is None:
        raise RuntimeError(f"Printer not found in BLE scan: {addr}. Is it on (and not connected to another device)?")

    async with BleakClient(device, timeout=20.0) as client:
        if not client.is_connected:
            raise RuntimeError("BLE connect failed (client not connected).")

        # Many printers are happiest with small writes (20 bytes) + tiny delay.
        for part in _chunk(payload, BLE_CHUNK_SIZE):
            await client.write_gatt_char(BLE_WRITE_UUID, part, response=False)
            if BLE_WRITE_GAP_SEC:
                await asyncio.sleep(BLE_WRITE_GAP_SEC)


def ble_print_text(addr: str, text: str):
    payload = _escpos_frame(text)
    asyncio.run(_ble_write(addr, payload))


def ble_is_available(addr: str) -> bool:
    async def _check():
        device = await _find_device_by_address(addr, timeout=3.0)
        return device is not None

    return asyncio.run(_check())

