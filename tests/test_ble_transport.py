import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import ble_printer as ble


class BluetoothDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_connected_bluez_device_can_be_used_without_an_advertisement(self):
        properties = {'Address': SimpleNamespace(value='AA:BB'), 'Name': SimpleNamespace(value='Printer'),
                      'Connected': SimpleNamespace(value=True)}
        bus = Mock()
        bus.connect = AsyncMock()
        bus.call = AsyncMock(return_value=SimpleNamespace(body=[{
            '/org/bluez/hci0/dev_AA_BB': {'org.bluez.Device1': properties}}]))
        modules = {'dbus_fast': SimpleNamespace(BusType=SimpleNamespace(SYSTEM=1), Message=Mock()),
                   'dbus_fast.aio': SimpleNamespace(MessageBus=Mock(return_value=bus))}
        with patch.dict(sys.modules, modules):
            device = await ble._connected_bluez_device('aa:bb')
        self.assertEqual(device.address, 'AA:BB')
        self.assertEqual(device.details['path'], '/org/bluez/hci0/dev_AA_BB')
        self.assertTrue(device.details['props']['Connected'])
        bus.disconnect.assert_called_once()

    async def test_existing_connection_skips_scanning_and_missing_connection_falls_back(self):
        connected = object()
        advertised = object()
        with patch.object(ble.sys, 'platform', 'linux'), \
                patch.object(ble, '_connected_bluez_device', new_callable=AsyncMock) as cache, \
                patch.object(ble.BleakScanner, 'find_device_by_filter', new_callable=AsyncMock) as scan:
            cache.return_value = connected
            self.assertIs(await ble._find_device_by_address('aa:bb'), connected)
            scan.assert_not_awaited()
            cache.return_value = None
            scan.return_value = advertised
            self.assertIs(await ble._find_device_by_address('aa:bb'), advertised)
            scan.assert_awaited_once()


class BluetoothPacketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.characteristic = Mock(properties=['write', 'write-without-response'],
                                   max_write_without_response_size=20)
        self.client = Mock(is_connected=True, mtu_size=23)
        self.client.services.get_characteristic.return_value = self.characteristic
        self.client.connect = AsyncMock()
        self.client.disconnect = AsyncMock()
        self.client.write_gatt_char = AsyncMock()
        for target, replacement in [('BleakClient', Mock(return_value=self.client)),
                                    ('_find_device_by_address', AsyncMock(return_value=object()))]:
            setting = patch.object(ble, target, replacement)
            setting.start()
            self.addCleanup(setting.stop)

    async def test_raster_chunks_fit_the_negotiated_packet_and_keep_flow_control(self):
        with patch.object(ble.asyncio, 'sleep', new_callable=AsyncMock) as sleep:
            await ble._ble_write('printer', b'x' * 47, chunk_size=200, write_gap=0.01, use_response=True)
        self.assertEqual([call.args[1] for call in self.client.write_gatt_char.call_args_list],
                         [b'x' * 20, b'x' * 20, b'x' * 7])
        self.assertTrue(all(call.kwargs['response'] for call in self.client.write_gatt_char.call_args_list))
        self.assertEqual(sleep.await_count, 3)
        self.client.disconnect.assert_awaited_once()

    async def test_without_response_uses_the_characteristic_limit(self):
        self.characteristic.properties = ['write-without-response']
        await ble._ble_write('printer', b'x' * 21, chunk_size=200, write_gap=0, use_response=True)
        self.assertEqual(self.client.write_gatt_char.await_count, 2)
        self.assertFalse(self.client.write_gatt_char.call_args.kwargs['response'])

    async def test_missing_first_acknowledgement_is_never_retried(self):
        self.client.write_gatt_char.side_effect = RuntimeError('Lost first acknowledgement')
        with self.assertRaisesRegex(RuntimeError, 'Lost first acknowledgement'):
            await ble._ble_write('printer', b'one ticket', write_gap=0)
        self.client.connect.assert_awaited_once()
        self.client.write_gatt_char.assert_awaited_once()
        self.client.disconnect.assert_awaited_once()

    async def test_stuck_write_times_out_disconnects_and_allows_a_later_ticket(self):
        async def stall(*args, **kwargs):
            await asyncio.Event().wait()
        self.client.write_gatt_char.side_effect = stall
        with patch.object(ble, 'BLE_WRITE_TIMEOUT', 0.02):
            with self.assertRaisesRegex(RuntimeError, 'stopped responding'):
                await ble._ble_write('printer', b'first', write_gap=0)
        self.client.disconnect.assert_awaited_once()
        self.client.write_gatt_char.side_effect = None
        await ble._ble_write('printer', b'second', write_gap=0)
        self.assertEqual(self.client.write_gatt_char.await_count, 2)

    async def test_completed_write_is_not_replayed_when_disconnect_fails(self):
        self.client.disconnect.side_effect = RuntimeError('Cleanup failed')
        written = Mock()
        await ble._ble_write('printer', b'ticket', write_gap=0, on_written=written)
        written.assert_called_once()
        self.client.write_gatt_char.assert_awaited_once()


class BluetoothProcessTests(unittest.TestCase):
    def test_uncancellable_child_is_dead_before_a_new_operation_can_start(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'pid'
            code = ('import os, pathlib, signal, time; '
                    'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                    'pathlib.Path(__import__("sys").argv[1]).write_text(str(os.getpid())); '
                    'time.sleep(60)')
            with self.assertRaisesRegex(RuntimeError, 'connection was reset'):
                ble._run_ble_process([sys.executable, '-c', code, str(pid_file)], timeout=0.5)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)
            self.assertEqual(ble._run_ble_process([sys.executable, '-c', 'print("written")'], timeout=2),
                             b'written')

    def test_completed_ticket_is_confirmed_if_only_child_cleanup_hangs(self):
        code = 'import time; print("written", flush=True); time.sleep(60)'
        self.assertEqual(ble._run_ble_process([sys.executable, '-c', code], timeout=0.5), b'written')

    def test_failed_child_does_not_claim_success(self):
        with self.assertRaisesRegex(RuntimeError, 'could not finish'):
            ble._run_ble_process([sys.executable, '-c', 'raise SystemExit(1)'], timeout=2)


if __name__ == '__main__':
    unittest.main()
