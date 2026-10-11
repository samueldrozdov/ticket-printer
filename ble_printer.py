import asyncio
import base64
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from PIL import Image
from printer_worker import timeout_setting

logger = logging.getLogger(__name__)


BLE_WRITE_UUID = os.getenv("BLE_WRITE_UUID", "").strip() or "00002af1-0000-1000-8000-00805f9b34fb"
BLE_CHUNK_SIZE = int(os.getenv("BLE_CHUNK_SIZE", "20"))
BLE_WRITE_GAP_SEC = float(os.getenv("BLE_WRITE_GAP_SEC", "0.02"))
BLE_IMAGE_CHUNK_SIZE = int(os.getenv("BLE_IMAGE_CHUNK_SIZE", "200"))  # Larger chunks for images
BLE_IMAGE_WRITE_GAP_SEC = float(os.getenv("BLE_IMAGE_WRITE_GAP_SEC", "0.01"))  # Faster default
BLE_USE_RESPONSE = os.getenv("BLE_USE_RESPONSE", "true").lower() in ("true", "1", "yes")  # Use response-based flow control
BLE_SCAN_TIMEOUT = float(os.getenv("BLE_SCAN_TIMEOUT", "15"))  # Longer timeout for flaky connections
BLE_WRITE_TIMEOUT = timeout_setting("BLE_WRITE_TIMEOUT", 5)
BLE_PROCESS_TIMEOUT = timeout_setting("BLE_PROCESS_TIMEOUT", 60)

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
    image = prepare_thermal_image(image, max_width, max_height, use_dithering, contrast)
    return encode_raster(image)


def prepare_thermal_image(image: Image.Image, max_width: int = None, max_height: int = None, use_dithering: bool = None, contrast: float = None) -> Image.Image:
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
        new_width = max(1, int(image.width * ratio))
        new_height = max(1, int(image.height * ratio))
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
    
    return image


def encode_raster(image: Image.Image) -> bytes:
    """Encode prepared pixels without resizing, contrast changes, or dithering."""
    if image.mode != '1':
        raise ValueError("Raster must be a prepared monochrome image")
    # White padding prevents black marks in the unused bits of the last byte.
    if image.width % 8:
        padded = Image.new('1', ((image.width + 7) // 8 * 8, image.height), 1)
        padded.paste(image)
        image = padded
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


async def _connected_bluez_device(addr):
    """A connected peripheral may no longer advertise; use BlueZ's live device."""
    from dbus_fast import BusType, Message
    from dbus_fast.aio import MessageBus

    bus = MessageBus(bus_type=BusType.SYSTEM)
    try:
        await asyncio.wait_for(bus.connect(), 1)
        reply = await asyncio.wait_for(bus.call(Message(
            destination='org.bluez', path='/', interface='org.freedesktop.DBus.ObjectManager',
            member='GetManagedObjects')), 1)
        for path, interfaces in reply.body[0].items():
            properties = {key: value.value for key, value in interfaces.get('org.bluez.Device1', {}).items()}
            if properties.get('Address', '').upper() == addr.upper() and properties.get('Connected'):
                return BLEDevice(properties['Address'], properties.get('Name'),
                                 {'path': path, 'props': properties})
    finally:
        bus.disconnect()


async def _find_device_by_address(addr: str, timeout: float = None):
    if timeout is None:
        timeout = BLE_SCAN_TIMEOUT
    addr = addr.upper()
    if sys.platform == 'linux':
        try:
            connected = await _connected_bluez_device(addr)
            if connected is not None:
                return connected
        except Exception:
            logger.warning('Could not read the existing Bluetooth connection; scanning instead')

    def matcher(d, _ad):
        return (d.address or "").upper() == addr

    return await BleakScanner.find_device_by_filter(matcher, timeout=timeout)


async def _ble_write(addr: str, payload: bytes, chunk_size: int = None, write_gap: float = None, use_response: bool = None, retries: int = 2, on_written=None):
    if chunk_size is None:
        chunk_size = BLE_CHUNK_SIZE
    if write_gap is None:
        write_gap = BLE_WRITE_GAP_SEC
    if use_response is None:
        use_response = BLE_USE_RESPONSE
    
    last_error = None
    for attempt in range(retries + 1):
        started_writing = False
        write_complete = False
        client = None
        try:
            device = await asyncio.wait_for(_find_device_by_address(addr), BLE_SCAN_TIMEOUT + 1)
            if device is None:
                raise RuntimeError(f"Printer not found in BLE scan: {addr}. Is it on (and not connected to another device)?")

            client = BleakClient(device, timeout=20.0)
            try:
                await asyncio.wait_for(client.connect(), 20)
                if not client.is_connected:
                    raise RuntimeError("BLE connect failed (client not connected).")
                characteristic = client.services.get_characteristic(BLE_WRITE_UUID)
                if characteristic is None:
                    raise RuntimeError("The printer's Bluetooth write service is unavailable.")
                response = use_response
                if response and 'write' not in characteristic.properties:
                    response = False
                # A large acknowledged write can become an unsupported ATT long
                # write on small printers. Stay within one negotiated packet.
                packet_limit = (max(1, client.mtu_size - 3) if response else
                                characteristic.max_write_without_response_size)
                size = min(chunk_size, packet_limit, 512)
                if size <= 0:
                    raise ValueError("Bluetooth chunk size must be positive")
                logger.info("Bluetooth sending %d bytes in %d-byte packets (response=%s)",
                            len(payload), size, response)
                for part in _chunk(payload, size):
                    # A lost first acknowledgement can still mean bytes reached
                    # the printer. Never replay any attempted write.
                    started_writing = True
                    await asyncio.wait_for(client.write_gatt_char(characteristic, part, response=response),
                                           BLE_WRITE_TIMEOUT)
                    if write_gap:
                        await asyncio.sleep(write_gap)
                write_complete = True  # All data sent successfully
                if on_written:
                    on_written()
                return  # Success
            finally:
                try:
                    await asyncio.wait_for(client.disconnect(), 3)
                except Exception:
                    logger.warning("Bluetooth disconnect did not complete", exc_info=True)
        except Exception as e:
            # If all data was sent, treat disconnect errors as success
            # (the printer got all the data, disconnect is just cleanup)
            if write_complete:
                return  # Data was sent, ignore disconnect errors
            
            last_error = e
            # Don't retry if we already started writing - it would cause duplicate prints
            if started_writing:
                if isinstance(e, asyncio.TimeoutError):
                    raise RuntimeError("Bluetooth stopped responding during the ticket. "
                                       "Check the paper before resending.") from e
                raise
            if attempt < retries:
                await asyncio.sleep(2)  # Wait before retry
            continue
    
    raise last_error


def _run_ble_process(command, *, payload=b'', timeout):
    """Kill and reap stuck BLE code before releasing the shared hardware slot."""
    try:
        result = subprocess.run(command, input=payload, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        # subprocess.run has already killed and waited for the child. A flushed
        # receipt means every packet was accepted; only cleanup was stuck.
        if b'written\n' in (error.stdout or b'').splitlines(keepends=True):
            logger.warning("Bluetooth cleanup stalled after all bytes were sent; process stopped")
            return b'written'
        logger.error("Stopped stalled Bluetooth process after %.1fs", timeout)
        raise RuntimeError("Bluetooth timed out and its connection was reset. Printing was not confirmed. "
                           "Check the paper before resending.") from error
    if result.stderr:
        logger.log(logging.ERROR if result.returncode else logging.INFO,
                   "Bluetooth worker: %s", result.stderr.decode(errors='replace').strip())
    if result.returncode:
        logger.error("Bluetooth worker exited with status %s", result.returncode)
        raise RuntimeError("Bluetooth could not finish the ticket. Its connection was reset. "
                           "Check the paper before resending.")
    return result.stdout.strip()


def _print_in_process(addr, payload, chunk_size=BLE_CHUNK_SIZE, write_gap=BLE_WRITE_GAP_SEC):
    result = _run_ble_process([sys.executable, str(Path(__file__).resolve()), 'write', addr,
                               str(chunk_size), str(write_gap)], payload=payload, timeout=BLE_PROCESS_TIMEOUT)
    if result != b'written':
        raise RuntimeError("The Bluetooth worker exited without confirming the ticket. Check the paper before resending.")


def ble_print_text(addr: str, text: str):
    payload = _escpos_frame(text)
    _print_in_process(addr, payload)


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
    _print_in_process(addr, payload, BLE_IMAGE_CHUNK_SIZE, BLE_IMAGE_WRITE_GAP_SEC)


def ble_print_raster_ticket(addr: str, payload: bytes):
    """Send an already rendered ticket without changing its pixels."""
    _print_in_process(addr, payload, BLE_IMAGE_CHUNK_SIZE, BLE_IMAGE_WRITE_GAP_SEC)


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
        _print_in_process(addr, payload, BLE_IMAGE_CHUNK_SIZE, BLE_IMAGE_WRITE_GAP_SEC)
    else:
        _print_in_process(addr, payload)


def ble_is_available(addr: str) -> bool:
    return _run_ble_process([sys.executable, str(Path(__file__).resolve()), 'check', addr],
                            timeout=4.5) == b'available'


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        if sys.argv[1] == 'check':
            device = asyncio.run(_find_device_by_address(sys.argv[2], timeout=3))
            print('available' if device is not None else 'unavailable', flush=True)
        elif sys.argv[1] == 'write':
            asyncio.run(_ble_write(sys.argv[2], sys.stdin.buffer.read(), int(sys.argv[3]), float(sys.argv[4]),
                                   on_written=lambda: print('written', flush=True)))
        else:
            raise ValueError('Unknown Bluetooth operation')
    except Exception:
        logger.exception('Bluetooth operation failed')
        raise SystemExit(1)
