const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../frontend/settings.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
const localHealth = { service: 'samson', server: { kind: 'computer', name: 'Mac' },
    test_mode: false, printer_type: 'usb', printer_connected: false,
    printer_state: 'setup_required', printer_message: 'USB support is unavailable on this server.' };

async function fixture(health = localHealth, url = 'http://127.0.0.1:8792', storage = new Map()) {
    const nodes = new Map(), requests = [];
    const replies = { '/health': health, '/microphone': { success: true, enabled: false, connected: false } };
    const byId = id => {
        if (!nodes.has(id)) nodes.set(id, { textContent: '', hidden: false, open: false, checked: true,
            dataset: {}, attributes: {}, events: {},
            addEventListener(name, fn) { this.events[name] = fn; },
            setAttribute(name, value) { this.attributes[name] = value; },
            showModal() { this.open = true; }, close() { this.open = false; }, focus() {} });
        return nodes.get(id);
    };
    const events = {};
    const window = { PRINTER_API_URL: url, addEventListener(name, fn) { events[name] = fn; } };
    vm.runInNewContext(source, {
        window, document: { getElementById: byId }, URL, AbortController,
        localStorage: { getItem(key) { return storage.get(key) ?? null; }, setItem(key, value) { storage.set(key, value); } },
        setTimeout: () => 1, clearTimeout() {},
        fetch: async (address, options) => {
            requests.push({ address, method: options.method || 'GET' });
            const value = replies[new URL(address).pathname];
            if (value instanceof Error) throw value;
            return { ok: true, json: async () => value };
        }
    });
    await settle();
    return { byId, replies, requests, storage, events, settings: window.SamsonSettings,
        async refresh() { await byId('refreshConnections').events.click(); await settle(); } };
}

test('message spacing defaults to six lines and remembers small spacing after reload', async () => {
    const f = await fixture();
    assert.equal(f.settings.feedLines, 6);
    f.byId('feedLinesSmall').checked = true;
    f.byId('feedLinesSmall').events.change();
    assert.equal(f.settings.feedLines, 3);
    const reopened = await fixture(localHealth, undefined, f.storage);
    assert.equal(reopened.settings.feedLines, 3);
    const otherPrinter = await fixture(localHealth, 'http://another-printer.test', f.storage);
    assert.equal(otherPrinter.settings.feedLines, 6);
});

test('spacing synchronizes between tabs and falls back safely for invalid saved values', async () => {
    const f = await fixture();
    const key = 'samson-feed-lines-v2:http://127.0.0.1:8792';
    f.events.storage({ key, newValue: '12' });
    assert.equal(f.settings.feedLines, 12);
    f.events.storage({ key: 'unrelated', newValue: '1' });
    assert.equal(f.settings.feedLines, 12);
    f.events.storage({ key: null, newValue: null });
    assert.equal(f.settings.feedLines, 6);
    for (const value of ['-1', '13', '1.5', '', 'invalid', '0', '1', '5', '9', '10']) {
        const saved = await fixture(localHealth, undefined, new Map([[key, value]]));
        assert.equal(saved.settings.feedLines, 6);
    }
});

test('original spacing preferences preserve the selected size until a new choice is saved', async () => {
    const key = 'samson-feed-lines:http://127.0.0.1:8792';
    for (const [legacy, lines, id] of [['0', 3, 'feedLinesSmall'], ['3', 6, 'feedLinesDefault'], ['10', 12, 'feedLinesLarge']]) {
        const f = await fixture(localHealth, undefined, new Map([[key, legacy]]));
        assert.equal(f.settings.feedLines, lines);
        assert.equal(f.byId(id).checked, true);
        f.byId('feedLinesSmall').checked = true;
        f.byId('feedLinesSmall').events.change();
        const reopened = await fixture(localHealth, undefined, f.storage);
        assert.equal(reopened.settings.feedLines, 3);
    }
});

test('font and size preferences persist per server and synchronize between tabs', async () => {
    const f = await fixture();
    assert.equal(f.settings.fontFamily, 'mono');
    assert.equal(f.settings.fontSize, 'medium');
    f.byId('fontFamily').value = 'serif';
    f.byId('fontFamily').events.change();
    f.byId('fontSizeLarge').checked = true;
    f.byId('fontSizeLarge').events.change();
    const reopened = await fixture(localHealth, undefined, f.storage);
    assert.equal(reopened.settings.fontFamily, 'serif');
    assert.equal(reopened.settings.fontSize, 'large');
    assert.equal(reopened.byId('fontSizeLarge').checked, true);
    assert.equal(reopened.byId('fontSizeMedium').checked, false);
    const other = await fixture(localHealth, 'https://another-printer.test', f.storage);
    assert.equal(other.settings.fontFamily, 'mono');
    assert.equal(other.settings.fontSize, 'medium');
    reopened.events.storage({key: 'samson-font-family:http://127.0.0.1:8792', newValue: 'sans'});
    reopened.events.storage({key: 'samson-font-size:http://127.0.0.1:8792', newValue: 'small'});
    assert.equal(reopened.settings.fontFamily, 'sans');
    assert.equal(reopened.settings.fontSize, 'small');
    reopened.events.storage({key: null, newValue: null});
    assert.equal(reopened.settings.fontFamily, 'mono');
    assert.equal(reopened.settings.fontSize, 'medium');
});

test('unsupported saved font choices fall back to the original typography', async () => {
    const f = await fixture(localHealth, undefined, new Map([
        ['samson-font-family:http://127.0.0.1:8792', '../../font.ttf'],
        ['samson-font-size:http://127.0.0.1:8792', '2000']
    ]));
    assert.equal(f.settings.fontFamily, 'mono');
    assert.equal(f.settings.fontSize, 'medium');
});

test('local Mac is labeled as a server and USB setup failure does not turn the avatar green', async () => {
    const f = await fixture();
    assert.equal(f.byId('serverLabel').textContent, 'Server');
    assert.equal(f.byId('piConnection').textContent, 'Local');
    assert.equal(f.byId('serverNoticeTitle').textContent, 'Running on this Mac');
    assert.equal(f.byId('printerConnection').textContent, 'Setup needed');
    assert.equal(f.byId('printerTransport').textContent, 'USB');
    assert.equal(f.byId('printerExplanation').textContent, localHealth.printer_message);
    f.settings.setApiReachable(true);
    assert.notEqual(f.byId('piAvatar').dataset.connection, 'connected');
    assert.ok(f.requests.every(request => request.method === 'GET'));
});

test('Pi identity comes from hardware even when reached through localhost', async () => {
    const f = await fixture({ ...localHealth, server: { kind: 'raspberry_pi', name: 'Raspberry Pi' },
        printer_connected: true, printer_type: 'ble', printer_state: 'available' });
    assert.equal(f.byId('serverLabel').textContent, 'Pi');
    assert.equal(f.byId('piConnection').textContent, 'Active');
    assert.equal(f.byId('serverNotice').hidden, true);
    assert.equal(f.byId('printerConnection').textContent, 'Available');
    assert.equal(f.byId('piAvatar').dataset.connection, 'connected');
});

test('remote Mac is not described as this computer', async () => {
    const f = await fixture(localHealth, 'https://samson.example');
    assert.equal(f.byId('serverNoticeTitle').textContent, 'Running on a Mac');
    assert.equal(f.byId('serverAddress').textContent, 'samson.example');
});

test('busy and stalled printers keep the Pi online with an accurate printer label', async () => {
    for (const [state, label] of [['busy', 'Busy'], ['checking', 'Checking…'], ['unavailable', 'Needs attention']]) {
        const f = await fixture({ ...localHealth, server: { kind: 'raspberry_pi' },
            printer_state: state, printer_message: 'The website is still available.' });
        assert.equal(f.byId('piConnection').textContent, 'Active');
        assert.equal(f.byId('printerConnection').textContent, label);
        assert.notEqual(f.byId('piAvatar').dataset.connection, 'offline');
        assert.equal(f.byId('printerExplanation').textContent, 'The website is still available.');
    }
});

test('legacy backend does not invent a Pi identity', async () => {
    const f = await fixture({ status: 'healthy', printer_type: 'usb', printer_connected: false });
    assert.equal(f.byId('serverLabel').textContent, 'Server');
    assert.equal(f.byId('serverNoticeTitle').textContent, 'Server type unverified');
});

test('test mode never indicates physical printing is ready', async () => {
    const f = await fixture({ ...localHealth, test_mode: true, printer_connected: true });
    assert.equal(f.byId('printerConnection').textContent, 'Test mode');
    assert.notEqual(f.byId('piAvatar').dataset.connection, 'connected');
});

test('failed health check clears stale Pi and printer status even when microphone API responds', async () => {
    const f = await fixture({ ...localHealth, server: { kind: 'raspberry_pi' }, printer_connected: true });
    f.replies['/health'] = new Error('Timeout');
    await f.refresh();
    assert.equal(f.byId('serverLabel').textContent, 'Server');
    assert.equal(f.byId('piConnection').textContent, 'Reachable');
    assert.equal(f.byId('printerConnection').textContent, 'Unknown');
    assert.notEqual(f.byId('piAvatar').dataset.connection, 'connected');
});

test('offline status recovers on Check again without printing', async () => {
    const f = await fixture();
    f.replies['/health'] = f.replies['/microphone'] = new Error('Offline');
    await f.refresh();
    assert.equal(f.byId('piConnection').textContent, 'Offline');
    assert.equal(f.byId('serverNotice').hidden, true);
    f.replies['/health'] = localHealth;
    await f.refresh();
    assert.equal(f.byId('piConnection').textContent, 'Local');
    assert.equal(f.byId('printerConnection').textContent, 'Setup needed');
    assert.equal(f.byId('refreshConnections').disabled, false);
    assert.ok(f.requests.every(request => request.method === 'GET'));
});

test('unrelated JSON responses cannot pass as a connected Samson server', async () => {
    const f = await fixture({ success: true });
    f.replies['/microphone'] = { success: true };
    await f.refresh();
    assert.equal(f.byId('piConnection').textContent, 'Offline');
    assert.equal(f.byId('printerConnection').textContent, 'Unknown');
});
