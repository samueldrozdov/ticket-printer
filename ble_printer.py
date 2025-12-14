import asyncio
import base64
import io
import os
from typing import Optional

from bleak import BleakClient, BleakScanner
from PIL import Image


BLE_WRITE_UUID = os.getenv("BLE_WRITE_UUID", "").strip() or "00002af1-0000-1000-8000-00805f9b34fb"
BLE_CHUNK_SIZE = int(os.getenv("BLE_CHUNK_SIZE", "20"))
BLE_WRITE_GAP_SEC = float(os.getenv("BLE_WRITE_GAP_SEC", "0.02"))
BLE_IMAGE_CHUNK_SIZE = int(os.getenv("BLE_IMAGE_CHUNK_SIZE", "100"))  # Larger chunks for images
BLE_IMAGE_WRITE_GAP_SEC = float(os.getenv("BLE_IMAGE_WRITE_GAP_SEC", "0.05"))  # Slower for images


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


def _image_to_escpos_raster(image: Image.Image, max_width: int = 384) -> bytes:
    """
    Convert PIL Image to ESC/POS raster bitmap format (GS v 0 command).
    """
    # Resize if needed
    if image.width > max_width:
        ratio = max_width / image.width
        new_height = int(image.height * ratio)
        image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
    
    # Convert to 1-bit black and white
    image = image.convert('1')
    
    width = image.width
    height = image.height
    
    # Calculate bytes per line (must be multiple of 8 bits)
    bytes_per_line = (width + 7) // 8
    
    # Build raster data
    pixels = list(image.getdata())
    raster_data = bytearray()
    
    for y in range(height):
        for x_byte in range(bytes_per_line):
            byte_val = 0
            for bit in range(8):
                x = x_byte * 8 + bit
                if x < width:
                    pixel_index = y * width + x
                    # In mode '1', 0 is black, 255 is white
                    # For thermal printers, 1 bit = print (black)
                    if pixels[pixel_index] == 0:
                        byte_val |= (0x80 >> bit)
            raster_data.append(byte_val)
    
    # Build GS v 0 command
    # GS v 0 m xL xH yL yH [data]
    xL = bytes_per_line & 0xFF
    xH = (bytes_per_line >> 8) & 0xFF
    yL = height & 0xFF
    yH = (height >> 8) & 0xFF
    
    command = bytes([0x1D, 0x76, 0x30, 0x00, xL, xH, yL, yH])
    
    return command + bytes(raster_data)


def process_image_base64(image_base64: str, max_width: int = 384) -> Optional[Image.Image]:
    """Process base64 image string to PIL Image."""
    try:
        # Remove data URL prefix if present
        if ',' in image_base64:
            image_base64 = image_base64.split(',')[1]
        
        image_data = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(image_data))
        
        # Handle transparency
        if image.mode in ('RGBA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'RGBA':
                background.paste(image, mask=image.split()[3])
            else:
                background.paste(image)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        return image
    except Exception:
        return None


async def _find_device_by_address(addr: str, timeout: float = 8.0):
    addr = addr.upper()

    def matcher(d, _ad):
        return (d.address or "").upper() == addr

    return await BleakScanner.find_device_by_filter(matcher, timeout=timeout)


async def _ble_write(addr: str, payload: bytes, chunk_size: int = None, write_gap: float = None):
    if chunk_size is None:
        chunk_size = BLE_CHUNK_SIZE
    if write_gap is None:
        write_gap = BLE_WRITE_GAP_SEC
    
    device = await _find_device_by_address(addr, timeout=8.0)
    if device is None:
        raise RuntimeError(f"Printer not found in BLE scan: {addr}. Is it on (and not connected to another device)?")

    async with BleakClient(device, timeout=20.0) as client:
        if not client.is_connected:
            raise RuntimeError("BLE connect failed (client not connected).")

        # Many printers are happiest with small writes (20 bytes) + tiny delay.
        for part in _chunk(payload, chunk_size):
            await client.write_gatt_char(BLE_WRITE_UUID, part, response=False)
            if write_gap:
                await asyncio.sleep(write_gap)


def ble_print_text(addr: str, text: str):
    payload = _escpos_frame(text)
    asyncio.run(_ble_write(addr, payload))


def ble_print_image(addr: str, image: Image.Image):
    """Print a PIL Image via BLE."""
    # Initialize printer
    init_cmd = b"\x1b@"
    # Convert image to ESC/POS raster format
    image_data = _image_to_escpos_raster(image)
    # Feed and cut
    footer = b"\n\n\n\x1dV\x00"
    
    payload = init_cmd + image_data + footer
    
    # Use larger chunks and slower timing for image data
    asyncio.run(_ble_write(addr, payload, BLE_IMAGE_CHUNK_SIZE, BLE_IMAGE_WRITE_GAP_SEC))


def ble_print_text_with_image(addr: str, text: str, image: Optional[Image.Image] = None):
    """Print text with optional image via BLE."""
    # Initialize printer
    init_cmd = b"\x1b@"
    # Text content
    text_data = text.encode("utf-8", errors="replace")
    
    payload = init_cmd + text_data
    
    # Add image if provided
    if image is not None:
        payload += b"\n"
        payload += _image_to_escpos_raster(image)
    
    # Feed and cut
    payload += b"\n\n\n\x1dV\x00"
    
    # Use image timing if we have an image, otherwise text timing
    if image is not None:
        asyncio.run(_ble_write(addr, payload, BLE_IMAGE_CHUNK_SIZE, BLE_IMAGE_WRITE_GAP_SEC))
    else:
        asyncio.run(_ble_write(addr, payload))


def ble_is_available(addr: str) -> bool:
    async def _check():
        device = await _find_device_by_address(addr, timeout=3.0)
        return device is not None

    return asyncio.run(_check())

