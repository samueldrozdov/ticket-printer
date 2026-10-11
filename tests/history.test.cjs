const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require.resolve('../frontend/history.js'), 'utf8');
const entry = (id, options = {}) => ({ id, text: `Ticket ${id}`, source: 'chat',
    status: 'printed', created_at: '2026-10-10T14:00:00+00:00', ...options });

function fixture(responses) {
    const nodes = new Map(), requests = [];
    const node = () => ({ children: [], events: {}, textContent: '', hidden: false,
        scrollTop: 0, scrollHeight: 500, classList: { add() {} },
        append(...children) { this.children.push(...children); },
        prepend(...children) { this.children.unshift(...children); },
        addEventListener(name, fn) { this.events[name] = fn; }
    });
    const byId = id => {
        if (!nodes.has(id)) nodes.set(id, node());
        return nodes.get(id);
    };
    const window = { PRINTER_API_URL: 'https://samson.test' };
    vm.runInNewContext(source, { window, AbortController,
        document: { getElementById: byId, createElement: node },
        setTimeout: () => 1, clearTimeout() {},
        fetch: async (url, options) => {
            requests.push({ url, options });
            const response = responses.shift();
            if (response instanceof Error) throw response;
            return { ok: true, json: async () => response };
        }
    });
    return { window, byId, requests, ready: window.SamsonHistory.ready };
}

test('opening the site restores saved content, status and ticket previews without printing', async () => {
    const injection = '<img src=x onerror=alert(1)>';
    const f = fixture([{ success: true, next_before: null, entries: [
        entry(1, { text: injection }),
        entry(2, { status: 'test_mode', preview: { image: 'data:image/png;base64,photo', width: 384, height: 200 } }),
        entry(3, { status: 'failed', source: 'listening' }),
        entry(4, { status: 'unconfirmed' })
    ] }]);
    await f.ready;
    const rows = f.byId('historyEntries').children;
    assert.equal(rows.length, 4);
    assert.equal(rows[0].children[1].textContent, injection);
    assert.equal(rows[0].children[1].innerHTML, undefined);
    assert.equal(rows[0].children.at(-1).textContent, 'Printed');
    assert.match(rows[1].children.at(-1).textContent, /no paper printed/);
    assert.equal(rows[1].children[2].className, 'paper-ticket');
    assert.equal(rows[1].children[2].children[0].src, 'data:image/png;base64,photo');
    assert.equal(rows[2].children.at(-1).textContent, 'Print not confirmed');
    assert.equal(rows[3].children.at(-1).textContent, 'Print not confirmed');
    assert.equal(f.window.SamsonHistory.has(2), true);
    assert.equal(f.byId('historyMore').hidden, true);
    assert.equal(f.byId('historyNotice').hidden, true);
    assert.deepEqual(f.requests.map(request => request.url), ['https://samson.test/history']);
    assert.equal(f.requests[0].options.cache, 'no-store');
    assert.equal(f.requests[0].options.method, undefined);
});

test('older pages are prepended chronologically and existing IDs are not duplicated', async () => {
    const f = fixture([
        { success: true, entries: [entry(3), entry(4)], next_before: 3 },
        { success: true, entries: [entry(1), entry(2), entry(3)], next_before: null }
    ]);
    await f.ready;
    assert.equal(f.byId('historyMore').hidden, false);
    await f.byId('historyMore').events.click();
    assert.equal(f.requests[1].url, 'https://samson.test/history?before=3');
    assert.deepEqual(f.byId('historyEntries').children.map(row => row.children[1].textContent),
        ['Ticket 1', 'Ticket 2', 'Ticket 3', 'Ticket 4']);
    assert.equal(f.byId('historyMore').hidden, true);
});

test('failed loading preserves entries and retries the same cursor', async () => {
    const f = fixture([
        { success: true, entries: [entry(2)], next_before: 2 },
        new Error('Offline'),
        { success: true, entries: [entry(1)], next_before: null }
    ]);
    await f.ready;
    await f.byId('historyMore').events.click();
    assert.equal(f.byId('historyEntries').children.length, 1);
    assert.equal(f.byId('historyMore').hidden, true);
    assert.equal(f.byId('historyNotice').hidden, false);
    assert.equal(f.byId('historyNoticeText').textContent, 'Couldn’t load message history.');
    assert.equal(f.byId('historyRetry').hidden, false);
    const retry = f.byId('historyRetry').events.click();
    assert.equal(f.byId('historyRetry').disabled, true);
    await retry;
    assert.equal(f.requests[1].url, f.requests[2].url);
    assert.equal(f.byId('historyEntries').children.length, 2);
    assert.equal(f.byId('historyRetry').hidden, true);
    assert.equal(f.byId('historyRetry').disabled, false);
});

test('an empty history explains when tickets will appear', async () => {
    const f = fixture([{ success: true, entries: [], next_before: null }]);
    await f.ready;
    assert.equal(f.byId('historyNotice').hidden, false);
    assert.match(f.byId('historyNoticeText').textContent, /No saved tickets yet/);
    assert.equal(f.byId('historyMore').hidden, true);
});

test('a print completed during initial history loading is not displayed twice', async () => {
    const f = fixture([{ success: true, entries: [entry(1)], next_before: null }]);
    f.window.SamsonHistory.markCurrent(1);
    await f.ready;
    assert.equal(f.byId('historyEntries').children.length, 0);
    assert.equal(f.window.SamsonHistory.has(1), true);
});
