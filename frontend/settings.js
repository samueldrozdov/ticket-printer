(() => {
    'use strict';

    const byId = id => document.getElementById(id);
    const dialog = byId('samsonSettings');
    const toggle = byId('includeDate');
    const storageKey = `samson-include-date:${window.PRINTER_API_URL}`;
    const feedOptions = [[byId('feedLinesNone'), 0], [byId('feedLinesDefault'), 3], [byId('feedLinesLarge'), 10]];
    let feedLines = 3;
    const feedStorageKey = `samson-feed-lines:${window.PRINTER_API_URL}`;
    const fontFamily = byId('fontFamily');
    const fontStorageKey = `samson-font-family:${window.PRINTER_API_URL}`;
    const fontSizeStorageKey = `samson-font-size:${window.PRINTER_API_URL}`;
    const fontSizeOptions = [[byId('fontSizeSmall'), 'small'], [byId('fontSizeMedium'), 'medium'], [byId('fontSizeLarge'), 'large']];
    const endpoint = new URL(window.PRINTER_API_URL);
    const localAddress = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(endpoint.hostname);
    const refreshButton = byId('refreshConnections');
    let refreshTimer = null;
    let checking = false;
    let lastHealth = null;
    let apiReachable = null;

    try { toggle.checked = localStorage.getItem(storageKey) !== 'false'; }
    catch { /* The preference still works for this page if storage is disabled. */ }

    function readFeedLines(value) {
        return value === '0' ? 0 : value === '10' ? 10 : 3;
    }
    function updateFeedLines(value, save = false) {
        feedLines = readFeedLines(value);
        feedOptions.forEach(([input, lines]) => { input.checked = lines === feedLines; });
        if (save) {
            try { localStorage.setItem(feedStorageKey, String(feedLines)); }
            catch { /* Keep the in-memory preference. */ }
        }
    }
    updateFeedLines('3');
    try { updateFeedLines(localStorage.getItem(feedStorageKey)); }
    catch { /* Keep the default if storage is disabled. */ }

    function preference(key, fallback, values, render) {
        let value = fallback;
        function update(next, save = false) {
            value = values.includes(next) ? next : fallback;
            render(value);
            if (save) {
                try { localStorage.setItem(key, value); }
                catch { /* Keep the in-memory preference. */ }
            }
        }
        update(fallback);
        try { update(localStorage.getItem(key)); }
        catch { /* Keep the default if storage is disabled. */ }
        return { get value() { return value; }, update };
    }
    const fontPreference = preference(fontStorageKey, 'mono', ['mono', 'sans', 'serif'], value => { fontFamily.value = value; });
    const fontSizePreference = preference(fontSizeStorageKey, 'medium', ['small', 'medium', 'large'], value => {
        fontSizeOptions.forEach(([input, size]) => { input.checked = size === value; });
    });

    window.SamsonSettings = {
        get includeDate() { return toggle.checked; },
        get feedLines() { return feedLines; },
        get fontFamily() { return fontPreference.value; },
        get fontSize() { return fontSizePreference.value; },
        setApiReachable(reachable) {
            if (!reachable) { apiReachable = false; updateAvatar(); }
            else if (apiReachable === false) refreshConnections(true);
        }
    };
    byId('serverAddress').textContent = endpoint.host;
    toggle.addEventListener('change', () => {
        try { localStorage.setItem(storageKey, String(toggle.checked)); }
        catch { /* Keep the in-memory preference. */ }
    });
    feedOptions.forEach(([input, lines]) => input.addEventListener('change', () => {
        if (input.checked) updateFeedLines(String(lines), true);
    }));
    fontFamily.addEventListener('change', () => fontPreference.update(fontFamily.value, true));
    fontSizeOptions.forEach(([input, size]) => input.addEventListener('change', () => {
        if (input.checked) fontSizePreference.update(size, true);
    }));
    window.addEventListener('storage', event => {
        if (event.key === storageKey || event.key === null) toggle.checked = event.newValue !== 'false';
        if (event.key === feedStorageKey || event.key === null) updateFeedLines(event.newValue);
        if (event.key === fontStorageKey || event.key === null) fontPreference.update(event.newValue);
        if (event.key === fontSizeStorageKey || event.key === null) fontSizePreference.update(event.newValue);
    });

    function status(id, state, label) {
        const row = byId(id);
        row.dataset.state = state;
        row.textContent = label;
    }

    function updateAvatar() {
        const ready = apiReachable === true && lastHealth?.printer_connected === true && !lastHealth.test_mode;
        const label = apiReachable === false ? 'Samson server unavailable'
            : lastHealth?.test_mode ? 'Samson, test mode — no paper will print'
            : ready ? 'Samson, printer available'
            : lastHealth ? 'Samson, printer needs attention. Open settings for details.'
            : 'Samson, printer connection not verified';
        byId('piAvatar').dataset.connection = ready ? 'connected' : apiReachable === false ? 'offline' : 'checking';
        byId('piAvatar').setAttribute('aria-label', label);
        byId('contactButton').title = label;
    }

    function notice(title, text) {
        byId('serverNotice').hidden = !title;
        byId('serverNoticeTitle').textContent = title;
        byId('serverNoticeText').textContent = text;
    }

    function showHealth(data) {
        const pi = data.server?.kind === 'raspberry_pi';
        const computer = data.server?.kind === 'computer';
        byId('serverLabel').textContent = pi ? 'Pi' : 'Server';
        status('piConnection', computer && localAddress ? 'idle' : 'active',
            computer && localAddress ? 'Local' : 'Active');
        if (pi) notice('', '');
        else if (computer) {
            const name = data.server.name || 'Computer';
            const host = localAddress ? (name === 'Mac' ? 'this Mac' : 'this computer')
                : name === 'Computer' ? 'another computer' : `a ${name}`;
            notice(`Running on ${host}`, 'For your Pi’s printer, open Samson at the Pi’s address.');
        } else notice('Server type unverified', 'Update Samson on this server to identify the device and show detailed connection info.');
        const transports = { usb: 'USB', ble: 'Bluetooth', bluetooth: 'Bluetooth', serial: 'Serial', network: 'Network' };
        byId('printerTransport').textContent = transports[data.printer_type] || 'Unknown connection';
        const states = {
            ready: ['active', 'Active'], available: ['active', 'Available'],
            setup_required: ['warning', 'Setup needed'], disconnected: ['offline', 'Disconnected'],
            unavailable: ['warning', 'Needs attention'], test_mode: ['idle', 'Test mode'],
            busy: ['idle', 'Busy'], checking: ['idle', 'Checking…']
        };
        const state = data.test_mode ? 'test_mode' : data.printer_state || (data.printer_connected ? 'ready' : 'disconnected');
        status('printerConnection', ...(states[state] || ['idle', 'Unknown']));
        byId('printerExplanation').hidden = data.printer_connected && !data.test_mode;
        byId('printerExplanation').textContent = data.printer_message || (data.test_mode
            ? 'Tickets are previewed only. No paper will print.'
            : data.printer_connected ? 'Printer connection is available.' : 'Check the printer’s power and connection to this server.');
    }

    async function read(path) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 10000);
        try {
            const response = await fetch(`${window.PRINTER_API_URL}${path}`, {
                signal: controller.signal, cache: 'no-store'
            });
            const data = await response.json();
            const valid = path === '/health'
                ? typeof data?.printer_connected === 'boolean' && typeof data?.printer_type === 'string'
                : data?.success === true && typeof data?.enabled === 'boolean';
            if (!response.ok || !valid || data.success === false) throw new Error('Connection check unavailable');
            return data;
        } finally { clearTimeout(timer); }
    }

    async function refreshConnections(force = false) {
        if ((!dialog.open && !force) || checking) return;
        clearTimeout(refreshTimer);
        checking = true;
        refreshButton.disabled = true;
        refreshButton.textContent = 'Checking…';
        const [health, microphone] = await Promise.allSettled([read('/health'), read('/microphone')]);
        apiReachable = health.status === 'fulfilled' || microphone.status === 'fulfilled';
        lastHealth = health.status === 'fulfilled' ? health.value : null;
        if (lastHealth) showHealth(lastHealth);
        else {
            byId('serverLabel').textContent = 'Server';
            status('piConnection', apiReachable ? 'idle' : 'offline', apiReachable ? 'Reachable' : 'Offline');
            status('printerConnection', 'idle', 'Unknown');
            byId('printerTransport').textContent = '';
            byId('printerExplanation').hidden = true;
            byId('printerExplanation').textContent = '';
            notice(apiReachable ? 'Connection details unavailable' : '', apiReachable
                ? 'Samson responds, but its device and printer status could not be verified.'
                : '');
        }
        if (microphone.status === 'fulfilled') {
            const data = microphone.value;
            if (!data.enabled) status('microphoneConnection', 'idle', 'Disabled');
            else if (data.connected === true) status('microphoneConnection', 'active', 'Active');
            else if (data.connected === false) status('microphoneConnection', 'warning', 'Unavailable');
            else status('microphoneConnection', 'idle', 'Unknown');
        } else status('microphoneConnection', 'offline', 'Unavailable');
        checking = false;
        updateAvatar();
        refreshButton.disabled = false;
        refreshButton.textContent = 'Check again';
        if (dialog.open) refreshTimer = setTimeout(refreshConnections, 15000);
    }

    byId('contactButton').addEventListener('click', () => {
        byId('addMenu').hidden = true;
        byId('listenSettings').hidden = true;
        byId('plusButton').setAttribute('aria-expanded', 'false');
        dialog.showModal();
        refreshConnections();
    });
    byId('closeSamsonSettings').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
        const bounds = dialog.getBoundingClientRect();
        if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
    });
    dialog.addEventListener('close', () => {
        clearTimeout(refreshTimer);
        byId('contactButton').focus();
    });
    refreshButton.addEventListener('click', () => refreshConnections(true));
    window.addEventListener('focus', () => refreshConnections(true));
    refreshConnections(true);
})();
