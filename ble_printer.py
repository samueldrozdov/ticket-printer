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
BLE_IMAGE_CHUNK_SIZE = int(os.getenv("BLE_IMAGE_CHUNK_SIZE", "200"))  # Larger chunks for images
BLE_IMAGE_WRITE_GAP_SEC = float(os.getenv("BLE_IMAGE_WRITE_GAP_SEC", "0.01"))  # Faster default
BLE_USE_RESPONSE = os.getenv("BLE_USE_RESPONSE", "true").lower() in ("true", "1", "yes")  # Use response-based flow control
BLE_SCAN_TIMEOUT = float(os.getenv("BLE_SCAN_TIMEOUT", "15"))  # Longer timeout for flaky connections

# Image processing settings
IMAGE_MAX_WIDTH = int(os.getenv("IMAGE_MAX_WIDTH", "384"))  # 384 for 58mm, 576 for 80mm printers
IMAGE_MAX_HEIGHT = int(os.getenv("IMAGE_MAX_HEIGHT", "800"))  # Limit height to control print time
IMAGE_USE_DITHERING = os.getenv("IMAGE_USE_DITHERING", "true").lower() in ("true", "1", "yes")
IMAGE_CONTRAST = float(os.getenv("IMAGE_CONTRAST", "1.5"))  # Contrast boost (1.0 = no change)


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


def _image_to_escpos_raster(image: Image.Image, max_width: int = None, max_height: int = None, use_dithering: bool = None, contrast: float = None) -> bytes:
    """
    Convert PIL Image to ESC/POS raster bitmap format (GS v 0 command).
    
    Args:
        image: PIL Image to convert
        max_width: Maximum width in pixels (default 384 for 58mm thermal printers)
        max_height: Maximum height in pixels (limits print time for tall images)
        use_dithering: Use Floyd-Steinberg dithering for better detail (default True)
        contrast: Contrast enhancement factor (1.0 = no change, 1.5 = 50% boost)
    """
    # Use env var defaults
    if max_width is None:
        max_width = IMAGE_MAX_WIDTH
    if max_height is None:
        max_height = IMAGE_MAX_HEIGHT
    if use_dithering is None:
        use_dithering = IMAGE_USE_DITHERING
    if contrast is None:
        contrast = IMAGE_CONTRAST
    
    # Resize if needed (maintain aspect ratio)
    if image.width > max_width or image.height > max_height:
        ratio = min(max_width / image.width, max_height / image.height)
        new_width = int(image.width * ratio)
        new_height = int(image.height * ratio)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Convert to grayscale first for better processing
    image = image.convert('L')
    
    # Enhance contrast for thermal printer (they need high contrast)
    if contrast != 1.0:
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(contrast)
    
    # Convert to 1-bit with dithering for better detail preservation
    if use_dithering:
        # Floyd-Steinberg dithering - much better for intricate images
        image = image.convert('1', dither=Image.Dither.FLOYDSTEINBERG)
    else:
        # Simple threshold - faster but loses detail
        image = image.convert('1', dither=Image.Dither.NONE)
    
    width = image.width
    height = image.height
    
    # Calculate bytes per line (must be multiple of 8 bits)
    bytes_per_line = (width + 7) // 8
    
    # Fast raster conversion using PIL's tobytes()
    # Pack pixels into bytes (8 pixels per byte, MSB first)
    # PIL's '1' mode tobytes gives us packed bits, but we need to invert
    raw_bytes = image.tobytes()
    
    # Invert bits (PIL: 0=black, 1=white; ESC/POS: 1=print/black, 0=white)
    raster_data = bytes(~b & 0xFF for b in raw_bytes)
    
    # Build GS v 0 command
    # GS v 0 m xL xH yL yH [data]
    xL = bytes_per_line & 0xFF
    xH = (bytes_per_line >> 8) & 0xFF
    yL = height & 0xFF
    yH = (height >> 8) & 0xFF
    
    command = bytes([0x1D, 0x76, 0x30, 0x00, xL, xH, yL, yH])
    
    return command + raster_data


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


async def _find_device_by_address(addr: str, timeout: float = None):
    if timeout is None:
        timeout = BLE_SCAN_TIMEOUT
    addr = addr.upper()

    def matcher(d, _ad):
        return (d.address or "").upper() == addr

    return await BleakScanner.find_device_by_filter(matcher, timeout=timeout)


async def _ble_write(addr: str, payload: bytes, chunk_size: int = None, write_gap: float = None, use_response: bool = None, retries: int = 2):
    if chunk_size is None:
        chunk_size = BLE_CHUNK_SIZE
    if write_gap is None:
        write_gap = BLE_WRITE_GAP_SEC
    if use_response is None:
        use_response = BLE_USE_RESPONSE
    
    last_error = None
    for attempt in range(retries + 1):
        started_writing = False
        try:
            device = await _find_device_by_address(addr)
            if device is None:
                raise RuntimeError(f"Printer not found in BLE scan: {addr}. Is it on (and not connected to another device)?")

            async with BleakClient(device, timeout=20.0) as client:
                if not client.is_connected:
                    raise RuntimeError("BLE connect failed (client not connected).")

                # Use response=True for flow control (faster for images)
                # or response=False with delays for compatibility
                for part in _chunk(payload, chunk_size):
                    await client.write_gatt_char(BLE_WRITE_UUID, part, response=use_response)
                    started_writing = True  # Mark that we've sent data
                    if not use_response and write_gap:
                        await asyncio.sleep(write_gap)
                return  # Success
        except Exception as e:
            last_error = e
            # Don't retry if we already started writing - it would cause duplicate prints
            if started_writing:
                raise
            if attempt < retries:
                await asyncio.sleep(2)  # Wait before retry
            continue
    
    raise last_error


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

