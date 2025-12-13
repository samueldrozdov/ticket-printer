import os
import asyncio
from datetime import datetime
from typing import Optional

from bleak import BleakClient

# --- Config via env vars ---
BLE_PRINTER_ADDR = os.getenv("BLE_PRINTER_ADDR", "")  # e.g. "5A:4A:7B:AE:AE:CA"
# If you already know the correct writable characteristic UUID, set it.
# Otherwise we'll auto-pick the first characteristic that supports write / write-without-response.
BLE_WRITE_CHAR_UUID = os.getenv("BLE_WRITE_CHAR_UUID", "").strip().lower()

# BLE writes are often limited; 20 is safest. Some stacks allow bigger once MTU is negotiated.
BLE_CHUNK_SIZE = int(os.getenv("BLE_CHUNK_SIZE", "20"))


def _build_escpos_ticket(from_name: str, question: str) -> bytes:
    """
    Build ESC/POS bytes that most receipt printers understand.
    This is deliberately simple (text + cut).
    """
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%B %d, %Y")

    lines = [
        "================================",
        "TICKET",
        "--------------------------------",
        f"From: {from_name}",
        f"Time: {time_str}",
        f"Date: {date_str}",
        "--------------------------------",
        "Question/Comment",
        question.strip(),
        "--------------------------------",
        "================================",
        "",
        "",
    ]
    text = "\n".join(lines) + "\n"

    # ESC/POS basics
    ESC = b"\x1b"
    GS = b"\x1d"

    init = ESC + b"@"                 # Initialize
    # Cut: GS V 0 (full cut). Some printers want a few feeds before cutting.
    feed_and_cut = b"\n\n\n" + (GS + b"V" + b"\x00")

    return init + text.encode("utf-8", errors="replace") + feed_and_cut


async def _auto_pick_write_char_uuid(client: BleakClient) -> str:
    """
    Try to pick a writable characteristic automatically.
    Works with Bleak versions where services are available via client.services.
    """
    services = getattr(client, "services", None)

    # Some Bleak versions used to require explicit discovery; keep a fallback.
    if services is None and hasattr(client, "get_services"):
        services = await client.get_services()

    if services is None:
        raise RuntimeError("BLE services not available; cannot auto-pick writable characteristic.")

    # Prefer write-without-response if available (usually fastest/simplest)
    for svc in services:
        for ch in svc.characteristics:
            props = set((ch.properties or []))
            if "write-without-response" in props or "write" in props:
                return str(ch.uuid)

    raise RuntimeError("No writable BLE characteristic found on this device.")


async def _print_over_ble(from_name: str, question: str) -> None:
    if not BLE_PRINTER_ADDR:
        raise RuntimeError("Missing BLE_PRINTER_ADDR env var (e.g. 5A:4A:7B:AE:AE:CA).")

    payload = _build_escpos_ticket(from_name, question)

    async with BleakClient(BLE_PRINTER_ADDR, timeout=20.0) as client:
        # Ensure we're connected
        if not client.is_connected:
            raise RuntimeError("BLE client failed to connect.")

        char_uuid = BLE_WRITE_CHAR_UUID
        if not char_uuid:
            char_uuid = (await _auto_pick_write_char_uuid(client)).lower()

        # Write in small chunks (BLE-safe)
        for i in range(0, len(payload), BLE_CHUNK_SIZE):
            chunk = payload[i : i + BLE_CHUNK_SIZE]
            # Most printers accept write-without-response
            await client.write_gatt_char(char_uuid, chunk, response=False)


def print_ticket_over_ble(from_name: str, question: str) -> None:
    """
    Synchronous wrapper (Flask route is sync).
    """
    try:
        asyncio.run(_print_over_ble(from_name, question))
    except RuntimeError as e:
        # If you're ever running inside an existing event loop, asyncio.run() can fail.
        # Flask normally isn't, but keep this readable error.
        raise
