const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { LiveListening } = require('../frontend/live-listening.js');

const source = fs.readFileSync(require.resolve('../frontend/chat.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

async function fixture({ contentFetch, memeFetch, liveFetch, rememberedId = null } = {}) {
    const nodes = new Map(), requests = [];
    let listener;
    const document = {
        activeElement: null,
        getElementById: byId,
        querySelector: byId,
        createElement: node,
        createElementNS: (_, tag) => node(tag),
        addEventListener() {}
    };
    function node() {
        const classes = new Set();
        return {
            value: '', textContent: '', className: '', hidden: false, disabled: false,
            maxLength: 1000, scrollHeight: 25, clientHeight: 800, offsetHeight: 80,
            style: {}, dataset: {}, children: [], events: {},
            classList: {
                add: value => classes.add(value),
                remove: value => classes.delete(value),
                contains: value => classes.has(value),
                toggle(value, enabled) { enabled ? classes.add(value) : classes.delete(value); }
            },
            addEventListener(name, callback) { this.events[name] = callback; },
            setAttribute(name, value) { this[name] = value; },
            removeAttribute(name) { delete this[name]; },
            toggleAttribute(name, enabled) { this[name] = enabled; },
            append(...children) {
                children.forEach(child => { child.parentNode = this; });
                this.children.push(...children);
            },
            after(child) {
                child.parentNode = this.parentNode;
                const siblings = this.parentNode.children;
                siblings.splice(siblings.indexOf(this) + 1, 0, child);
            },
            focus() { document.activeElement = this; },
            querySelector(selector) {
                return this.children.find(child => child.className.split(' ').includes(selector.slice(1))) || null;
            },
            remove() {
                if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1);
                this.parentNode = null;
            },
            requestSubmit() { this.events.submit({ preventDefault() {} }); }
        };
    }
    function byId(id) {
        if (!nodes.has(id)) nodes.set(id, node());
        return nodes.get(id);
    }
    const settings = { includeDate: true, feedLines: 3, fontFamily: 'mono', fontSize: 'medium', setApiReachable() {} };
    byId('stopListening').querySelector = () => byId('stopListeningLabel');
    vm.runInNewContext(source, {
        document, AbortController,
        window: {
            PRINTER_API_URL: 'http://samson.test', SamsonSettings: settings,
            LiveListening: class {
                constructor(options) {
                    if (liveFetch) return listener = new LiveListening({ ...options, schedule: () => 1, cancel() {} });
                }
                refresh() {}
            },
            addEventListener() {}, matchMedia: () => ({ matches: true })
        },
        sessionStorage: { getItem() { return rememberedId; }, setItem() {}, removeItem() {} },
        setTimeout: (callback, delay) => { if (delay === 500) setImmediate(callback); return 1; }, clearTimeout() {},
        FileReader: class {
            readAsDataURL(file) { this.result = file.data; this.onload(); }
        },
        Image: class { async decode() {} },
        fetch: (address, options) => {
            if (!address.startsWith('http://samson.test')) {
                assert.ok(contentFetch, `Unexpected content request: ${address}`);
                return contentFetch(address, options);
            }
            if (address.endsWith('/microphone')) {
                return Promise.resolve({ ok: true, json: async () => ({ success: true, enabled: false }) });
            }
            if (address.includes('/random-meme')) {
                assert.ok(memeFetch, 'Unexpected meme request');
                return memeFetch(address, options);
            }
            if (liveFetch && address.includes('/microphone/')) return liveFetch(new URL(address).pathname, options);
            assert.ok(address.endsWith('/print'));
            return new Promise((resolve, reject) => requests.push({
                body: JSON.parse(options.body),
                succeed(data = { success: true, test_mode: true }) {
                    resolve({ ok: true, json: async () => data });
                },
                respond: resolve,
                fail: reject
            }));
        }
    });
    await settle();
    return {
        byId, document, requests, settings, listener,
        outgoing: () => byId('messageTrack').children.filter(node => node.className === 'message outgoing'),
        type(text) { byId('messageInput').value = text; byId('messageInput').events.input(); },
        send() { byId('messageForm').requestSubmit(); },
        async attach(name) {
            byId('imageInput').files = [{ name, type: 'image/png', size: 10, data: `data:image/png;base64,${name}` }];
            await byId('imageInput').events.change();
        }
    };
}

test('audio-gap warnings keep live listening active and remain visible after stopping', async () => {
    let state = 'recording';
    const warning = 'Some audio was missed. Check the transcript and printed tickets for missing words.';
    const f = await fixture({ liveFetch: async () => ({ ok: true, json: async () => ({
        id: 'overflow-session', state, seconds: 5, cadence_seconds: 10, printed_count: 0,
        warning, text: '', printing: null, stop_reason: state === 'done' ? 'manual' : null
    }) }) });
    assert.equal(f.byId('listeningWarning').textContent, warning);
    assert.equal(f.byId('listeningWarning').hidden, false);
    assert.equal(f.byId('listeningLabel').textContent, 'Listening');
    assert.equal(f.byId('stopListening').disabled, false);
    state = 'done';
    await f.listener.refresh();
    assert.equal(f.byId('listeningBar').hidden, true);
    assert.match(f.byId('messageTrack').children.at(-1).children[0].textContent,
        /Listening stopped.*Some audio was missed/);
    assert.equal(f.requests.length, 0);
});

test('an HTML gateway timeout preserves the message without blaming the API address or retrying', async () => {
    const f = await fixture();
    f.type('Keep this ticket');
    f.send();
    await settle();
    f.requests[0].respond({ ok: false, status: 504, json: async () => { throw new SyntaxError('HTML'); } });
    await settle();
    assert.equal(f.requests.length, 1);
    const reply = f.byId('messageTrack').children[1];
    assert.match(reply.children[0].textContent, /connection to Samson timed out \(HTTP 504\)/);
    assert.doesNotMatch(reply.children[0].textContent, /API address/);
    assert.equal(f.outgoing()[0].children[0].textContent, 'Keep this ticket');
    assert.match(f.outgoing()[0].children.at(-1).textContent, /not confirmed/i);
});

test('Send waits through a health check that explicitly rejected admission, then prints once', async () => {
    const f = await fixture();
    f.type('One ticket');
    f.send();
    await settle();
    f.requests[0].respond({ ok: false, status: 503,
        json: async () => ({ success: false, printer_state: 'checking' }) });
    await settle(); await settle();
    assert.equal(f.requests.length, 2);
    assert.deepEqual(f.requests[0].body, f.requests[1].body);
    f.requests[1].succeed();
    await settle();
    assert.equal(f.outgoing().length, 1);
    assert.match(f.outgoing()[0].children.at(-1).textContent, /Logged in test mode/);
});

test('Send waits while another ticket owns the printer, without duplicating either message', async () => {
    const f = await fixture();
    f.type('Second ticket');
    f.send();
    await settle();
    for (let attempt = 0; attempt < 3; attempt++) {
        f.requests[attempt].respond({ ok: false, status: 503,
            json: async () => ({ success: false, printer_state: 'busy' }) });
        await settle(); await settle();
        assert.equal(f.outgoing()[0].children.at(-1).textContent, 'Waiting for printer…');
    }
    assert.equal(f.requests.length, 4);
    assert.ok(f.requests.every(request => JSON.stringify(request.body) === JSON.stringify(f.requests[0].body)));
    f.requests[3].succeed();
    await settle();
    assert.equal(f.outgoing().length, 1);
    assert.match(f.outgoing()[0].children.at(-1).textContent, /Logged in test mode/);
});

test('a bounded busy wait reports Not sent without an ambiguous printing warning', async () => {
    const f = await fixture();
    f.type('Still waiting');
    f.send();
    await settle();
    for (let attempt = 0; attempt <= 120; attempt++) {
        f.requests[attempt].respond({ ok: false, status: 503,
            json: async () => ({ success: false, printer_state: 'busy', error: 'Printer is busy.' }) });
        await settle(); await settle();
    }
    assert.equal(f.requests.length, 121);
    assert.equal(f.outgoing()[0].children.at(-1).textContent, 'Not sent');
    const error = f.byId('messageTrack').children[1].children[0].textContent;
    assert.match(error, /not sent to the printer/);
    assert.doesNotMatch(error, /check the printer|not confirmed/i);
});

test('waiting for admission never retries a subsequent ambiguous print failure', async () => {
    const f = await fixture();
    f.type('Only try once after admission');
    f.send();
    await settle();
    f.requests[0].respond({ ok: false, status: 503,
        json: async () => ({ success: false, printer_state: 'busy' }) });
    await settle(); await settle();
    f.requests[1].respond({ ok: false, status: 500,
        json: async () => ({ success: false, error: 'Bluetooth interrupted' }) });
    await settle(); await settle();
    assert.equal(f.requests.length, 2);
    assert.match(f.outgoing()[0].children.at(-1).textContent, /not confirmed/i);
});

test('an actual printer failure is never retried even when it returns 503', async () => {
    const f = await fixture();
    f.type('Unconfirmed ticket');
    f.send();
    await settle();
    f.requests[0].respond({ ok: false, status: 503,
        json: async () => ({ success: false, printer_state: 'unavailable', error: 'No acknowledgement' }) });
    await settle(); await settle();
    assert.equal(f.requests.length, 1);
    assert.match(f.outgoing()[0].children.at(-1).textContent, /not confirmed/i);
});

test('a failed page-load status check keeps the listening bar hidden through retries and recovery', async () => {
    let offline = true;
    const f = await fixture({ liveFetch: async (path, options) => {
        assert.equal(path, '/microphone/live');
        assert.equal(options.method, 'GET');
        if (offline) throw new Error('Offline');
        return { ok: true, json: async () => ({ state: 'idle', id: null, mode: 'live' }) };
    } });
    assert.equal(f.byId('listeningBar').hidden, true);
    assert.equal(f.byId('liveStatus').textContent, '');
    await f.listener.refresh();
    assert.equal(f.byId('listeningBar').hidden, true);
    offline = false;
    await f.listener.refresh();
    assert.equal(f.byId('listeningBar').hidden, true);
});

test('a remembered listening session still displays the connection warning on an offline reload', async () => {
    const f = await fixture({ rememberedId: 'session-a', liveFetch: async () => { throw new Error('Offline'); } });
    assert.equal(f.byId('listeningBar').hidden, false);
    assert.equal(f.byId('listeningLabel').textContent, 'Connection lost');
    assert.match(f.byId('listeningWarning').textContent, /may still be listening/);
});

test('Send clears and focuses immediately, with back-to-back messages printed in order', async () => {
    const f = await fixture();
    f.type('First');
    f.send();
    assert.equal(f.byId('messageInput').value, '');
    assert.equal(f.byId('messageInput').readOnly, false);
    assert.equal(f.document.activeElement, f.byId('messageInput'));
    assert.equal(f.byId('sendButton').hidden, true);
    // Another click/Enter on the now-empty composer must not duplicate the print.
    f.send();
    await settle();
    assert.equal(f.requests.length, 1);

    f.settings.includeDate = false;
    f.settings.feedLines = 5;
    f.settings.fontFamily = 'serif';
    f.settings.fontSize = 'large';
    f.type('Second');
    assert.equal(f.byId('sendButton').disabled, false);
    f.byId('messageInput').events.keydown({ key: 'Enter', preventDefault() {} });
    assert.equal(f.byId('messageInput').value, '');
    assert.equal(f.outgoing().length, 2);
    assert.equal(f.outgoing()[1].children.at(-1).textContent, 'Waiting to print…');
    f.settings.includeDate = true;
    f.settings.feedLines = 10;
    f.settings.fontFamily = 'sans';
    f.settings.fontSize = 'small';
    f.type('Next draft');
    await settle();
    assert.equal(f.requests.length, 1);

    f.requests[0].succeed();
    await settle();
    assert.deepEqual(f.requests.map(request => request.body), [
        { type: 'text', content: 'First', include_date: true, feed_lines: 3, font_family: 'mono', font_size: 'medium' },
        { type: 'text', content: 'Second', include_date: false, feed_lines: 5, font_family: 'serif', font_size: 'large' }
    ]);
    f.requests[1].succeed();
    await settle();
    assert.equal(f.byId('messageInput').value, 'Next draft');
    assert.ok(f.outgoing().every(node => node.children.at(-1).textContent.startsWith('Logged in test mode')));
});

test('sending photos snapshots each attachment and preserves the next photo draft', async () => {
    const f = await fixture();
    await f.attach('first.png');
    f.type('First caption');
    f.send();
    assert.equal(f.byId('imageAttachment').hidden, true);
    assert.equal(f.byId('imageInput').value, '');
    await settle();
    await f.attach('second.png');
    f.settings.feedLines = 0;
    f.send();
    await f.attach('third.png');
    f.type('Third caption');
    f.requests[0].succeed();
    await settle();
    assert.deepEqual(f.requests.map(request => request.body), [
        { type: 'image', content: 'data:image/png;base64,first.png', caption: 'First caption', include_date: true, feed_lines: 3, font_family: 'mono', font_size: 'medium' },
        { type: 'image', content: 'data:image/png;base64,second.png', caption: '', include_date: true, feed_lines: 0, font_family: 'mono', font_size: 'medium' }
    ]);
    f.requests[1].succeed();
    await settle();
    assert.equal(f.byId('imageAttachment').hidden, false);
    assert.equal(f.byId('imagePreview').src, 'data:image/png;base64,third.png');
    assert.equal(f.byId('messageInput').value, 'Third caption');
});

test('each print preview appears directly after its sender even when more messages are queued', async () => {
    const f = await fixture();
    f.type('First message');
    f.send();
    await f.attach('second.png');
    f.type('Photo caption');
    f.send();
    const [first, second] = f.outgoing();
    await settle();
    const preview = { image: 'data:image/png;base64,ticket', text: 'First message', width: 384, height: 220 };
    f.requests[0].succeed({ success: true, test_mode: false, preview });
    await settle();
    const firstReply = f.byId('messageTrack').children[1];
    assert.deepEqual(f.byId('messageTrack').children, [first, firstReply, second]);
    assert.equal(firstReply.className, 'message incoming');
    assert.equal(firstReply.children[0].className, 'paper-ticket');
    assert.equal(firstReply.children[0].children[0].src, preview.image);
    assert.equal(firstReply.children[1].children[1].textContent, '1 ticket printed');
    f.requests[1].succeed({ success: true, test_mode: true, preview: { ...preview, text: 'Photo caption' } });
    await settle();
    const secondReply = f.byId('messageTrack').children[3];
    assert.deepEqual(f.byId('messageTrack').children, [first, firstReply, second, secondReply]);
    assert.equal(second.children[0].src, 'data:image/png;base64,second.png');
    assert.equal(second.children[1].textContent, 'Photo caption');
    assert.equal(secondReply.children[0].textContent, 'Ticket logged in test mode. No paper printed.');
    assert.equal(secondReply.children[1].children[0].src, preview.image);
    assert.equal(secondReply.children.length, 2);
});

test('a random meme is reviewed in the composer, then sent as a sender message followed by its print', async () => {
    const meme = { title: 'A funny cat', url: 'https://images.test/cat.png', nsfw: false, spoiler: false };
    const image = { type: 'image/png', size: 10, data: 'data:image/png;base64,cat' };
    const f = await fixture({
        async memeFetch(address) {
            assert.equal(address, 'http://samson.test/random-meme');
            return { ok: true, json: async () => ({ success: true, image: image.data, title: meme.title, url: meme.url }) };
        }
    });
    f.type('For you');
    await f.byId('memeButton').events.click();
    assert.equal(f.requests.length, 0);
    assert.equal(f.outgoing().length, 0);
    assert.equal(f.byId('imagePreview').src, image.data);
    assert.equal(f.byId('messageInput').value, 'For you');
    f.type('Reviewed caption');
    f.send();
    assert.equal(f.byId('imageAttachment').hidden, true);
    const sent = f.outgoing()[0];
    assert.equal(sent.children[0].src, image.data);
    assert.equal(sent.children[0].alt, meme.title);
    assert.equal(sent.children[1].textContent, 'Reviewed caption');
    await settle();
    assert.deepEqual(f.requests[0].body, { type: 'image', content: image.data, caption: 'Reviewed caption', include_date: true, feed_lines: 3, font_family: 'mono', font_size: 'medium' });
    const preview = { image: 'data:image/png;base64,printed-cat', width: 384, height: 500 };
    f.requests[0].succeed({ success: true, preview });
    await settle();
    const conversation = f.byId('messageTrack').children;
    assert.equal(conversation.length, 2);
    assert.equal(conversation[0], sent);
    assert.equal(conversation[1].className, 'message incoming');
    assert.equal(conversation[1].children[0].children[0].src, preview.image);
});

test('meme failure preserves the existing caption and photo and unlocks the composer', async () => {
    for (const reply of [new Error('Network unavailable'), { success: false, error: 'No memes available' },
                         { success: true, image: '<html>not an image</html>' }]) {
        const f = await fixture({ memeFetch: async () => {
            if (reply instanceof Error) throw reply;
            return { ok: reply.success, status: reply.success ? 200 : 503, json: async () => reply };
        } });
        await f.attach('original.png');
        f.type('Keep my caption');
        await f.byId('memeButton').events.click();
        assert.equal(f.byId('imagePreview').src, 'data:image/png;base64,original.png');
        assert.equal(f.byId('imageAttachment').hidden, false);
        assert.equal(f.byId('messageInput').value, 'Keep my caption');
        assert.equal(f.byId('messageInput').readOnly, false);
        assert.equal(f.byId('plusButton').disabled, false);
        assert.equal(f.byId('sendButton').disabled, false);
        assert.equal(f.requests.length, 0);
        assert.match(f.byId('liveStatus').textContent, /draft is kept/);
    }
});

test('meme loading ignores repeated taps and excludes the last successful image', async () => {
    const addresses = [];
    let finish;
    const f = await fixture({ memeFetch: (address) => {
        addresses.push(address);
        return new Promise(resolve => { finish = () => resolve({ ok: true, json: async () => ({
            success: true, image: 'data:image/png;base64,meme', title: 'Meme', url: 'https://i.redd.it/meme.png'
        }) }); });
    } });
    const loading = f.byId('memeButton').events.click();
    await f.byId('memeButton').events.click();
    assert.equal(addresses.length, 1);
    assert.equal(f.byId('plusButton').disabled, true);
    finish();
    await loading;
    const next = f.byId('memeButton').events.click();
    assert.equal(new URL(addresses[1]).searchParams.get('exclude'), 'https://i.redd.it/meme.png');
    finish();
    await next;
    assert.equal(f.requests.length, 0);
});

for (const offline of [false, true]) {
    test(`a vocab word can be reviewed and edited before its message and print appear (${offline ? 'offline' : 'online'})`, async () => {
        const f = await fixture({
            async contentFetch(address) {
                assert.ok(address.startsWith('https://api.dictionaryapi.dev/api/v2/entries/en/'));
                if (offline) throw new Error('Dictionary unavailable');
                return { ok: true, json: async () => [{ word: 'lucid', meanings: [{ partOfSpeech: 'adjective',
                    definitions: [{ definition: 'Clear and easy to understand.' }] }] }] };
            }
        });
        f.type('Today’s word');
        await f.byId('vocabButton').events.click();
        const draft = f.byId('messageInput').value;
        assert.ok(draft.startsWith('Today’s word\n\n'));
        assert.ok(draft.length > 'Today’s word\n\n'.length);
        if (!offline) assert.ok(draft.includes('LUCID\n\n[adjective]\n\nClear and easy to understand.'));
        assert.equal(f.requests.length, 0);
        assert.equal(f.outgoing().length, 0);
        const edited = `${draft}\nMy note`;
        f.type(edited);
        f.send();
        const sent = f.outgoing()[0];
        assert.equal(sent.children[0].textContent, edited);
        await settle();
        assert.deepEqual(f.requests[0].body, { type: 'text', content: edited, include_date: true, feed_lines: 3, font_family: 'mono', font_size: 'medium' });
        const preview = { image: 'data:image/png;base64,printed-word', text: edited, width: 384, height: 400 };
        f.requests[0].succeed({ success: true, preview });
        await settle();
        const conversation = f.byId('messageTrack').children;
        assert.equal(conversation.length, 2);
        assert.equal(conversation[0], sent);
        assert.equal(conversation[1].children[0].children[0].src, preview.image);
    });
}

test('a failed print keeps its message, leaves the new draft alone, and does not stall or retry the queue', async () => {
    const f = await fixture();
    f.type('First');
    f.send();
    f.type('Second');
    f.send();
    f.type('Still writing');
    f.byId('plusButton').focus();
    await settle();
    f.requests[0].fail(new Error('Connection lost'));
    await settle();
    const failedMessage = f.outgoing()[0];
    assert.equal(failedMessage.children[0].textContent, 'First');
    assert.equal(failedMessage.children.at(-1).textContent, 'Print not confirmed');
    assert.equal(failedMessage.children.at(-1).classList.contains('failed'), true);
    assert.equal(f.byId('messageTrack').children[1].className, 'message incoming error-message');
    assert.equal(f.byId('messageTrack').children[2], f.outgoing()[1]);
    assert.equal(f.requests.length, 2);
    assert.equal(f.requests[1].body.content, 'Second');
    f.requests[1].succeed();
    await settle();
    assert.equal(f.requests.length, 2);
    assert.equal(f.byId('messageInput').value, 'Still writing');
    assert.equal(f.document.activeElement, f.byId('plusButton'));
});

test('empty and oversized drafts are not queued or cleared', async () => {
    const f = await fixture();
    f.type('   ');
    f.send();
    f.type('x'.repeat(1001));
    f.send();
    await settle();
    assert.equal(f.requests.length, 0);
    assert.equal(f.outgoing().length, 0);
    assert.equal(f.byId('messageInput').value.length, 1001);
});
