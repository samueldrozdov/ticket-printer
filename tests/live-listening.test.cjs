const { test } = require('node:test');
const assert = require('node:assert/strict');
const { LiveListening } = require('../frontend/live-listening.js');

const idle = { state: 'idle', id: null, mode: 'live' };
const session = (overrides = {}) => ({ id: 'session-a', mode: 'live', state: 'recording', seconds: 2,
    cadence_seconds: 10, duration_seconds: null, text: '', printing: null, ...overrides });
const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};
function fixture(rememberedId = null) {
    const requests = [], changes = [], statuses = [], endings = [], remembered = [], replies = [], timers = [];
    const controller = new LiveListening({
        api: async (path, options) => {
            requests.push({ path, options });
            assert.ok(replies.length, `Unexpected request: ${path}`);
            const reply = replies.shift();
            if (reply instanceof Error) throw reply;
            return reply;
        },
        onChange: state => changes.push(state), onStatus: data => statuses.push(data),
        onFinish: data => endings.push(data), remember: id => remembered.push(id), rememberedId,
        schedule: (fn, delay) => { timers.push({ fn, delay }); return timers.length; }, cancel: () => {}
    });
    return { controller, requests, changes, statuses, endings, remembered, replies, timers };
}

test('opening the page discovers status without starting the microphone', async () => {
    const f = fixture();
    assert.equal(f.controller.busy, true);
    f.replies.push(idle);
    await f.controller.refresh();
    assert.equal(f.controller.busy, false);
    assert.deepEqual(f.requests, [{ path: '/microphone/live', options: undefined }]);
});

test('failed startup checks do not imply a listening session and recover without starting one', async () => {
    const f = fixture();
    f.replies.push(new Error('Offline'), new Error('Offline'), idle);
    for (let attempt = 0; attempt < 2; attempt++) {
        await f.controller.refresh();
        assert.equal(f.changes.at(-1).trackingSession, false);
        assert.equal(f.controller.state.checking, true);
        assert.equal(f.controller.state.offline, true);
        assert.doesNotMatch(f.controller.state.error, /may still be listening/);
    }
    await f.controller.refresh();
    assert.equal(f.controller.busy, false);
    assert.equal(f.changes.at(-1).trackingSession, false);
    assert.equal(f.controller.state.error, '');
    assert.equal(f.statuses.length, 0);
    assert.ok(f.requests.every(request => request.path === '/microphone/live' && !request.options?.method));
});

test('an offline reload with a remembered session still warns until its status is known', async () => {
    const f = fixture('session-a');
    f.replies.push(new Error('Offline'), idle);
    await f.controller.refresh();
    assert.equal(f.changes.at(-1).trackingSession, true);
    assert.equal(f.controller.busy, true);
    assert.match(f.controller.state.error, /may still be listening/);
    await f.controller.refresh();
    assert.equal(f.changes.at(-1).trackingSession, false);
    assert.equal(f.controller.busy, false);
    assert.equal(f.remembered.at(-1), null);
});

test('start sends exactly the chosen settings and blocks a second start', async () => {
    const f = fixture();
    f.replies.push(idle, session());
    await f.controller.refresh();
    const options = { cadence_seconds: 30, duration_seconds: 300 };
    assert.equal(await f.controller.start(options), true);
    assert.equal(await f.controller.start(options), false);
    assert.deepEqual(f.requests[1], { path: '/microphone/live/start', options: { method: 'POST', body: options } });
    assert.equal(f.remembered.at(-1), 'session-a');
    assert.equal(f.controller.busy, true);
});

test('refresh discovers an existing session and its applied timing', async () => {
    const f = fixture();
    f.replies.push(session({ cadence_seconds: 60, duration_seconds: 900 }));
    await f.controller.refresh();
    assert.equal(f.controller.state.session.duration_seconds, 900);
    assert.equal(f.controller.busy, true);
    assert.equal(f.requests.length, 1);
    assert.equal(f.endings.length, 0);
});

test('an old completed session does not restore old words into a new draft', async () => {
    const f = fixture();
    f.replies.push(session({ state: 'done', text: 'old words' }));
    await f.controller.refresh();
    assert.equal(f.endings.length, 0);
    assert.equal(f.statuses.length, 0);
    assert.equal(f.controller.busy, false);
});

test('a session that finished while the page reloaded restores its result once', async () => {
    const f = fixture('session-a');
    const result = session({ state: 'done', text: 'keep these words' });
    f.replies.push(result, result);
    await f.controller.refresh();
    await f.controller.refresh();
    assert.equal(f.endings.length, 1);
    assert.equal(f.endings[0].text, 'keep these words');
    assert.equal(f.remembered.at(-1), null);
});

test('duration expiry finishes and preserves backend test-mode status', async () => {
    const f = fixture();
    f.replies.push(session(), session({ state: 'done', stop_reason: 'duration', test_mode: true }));
    await f.controller.refresh();
    await f.controller.refresh();
    assert.equal(f.controller.busy, false);
    assert.equal(f.endings[0].test_mode, true);
    assert.equal(f.endings[0].stop_reason, 'duration');
});

test('Stop cancels pending prints and cannot be double submitted', async () => {
    const f = fixture();
    const response = deferred();
    f.replies.push(session(), response.promise);
    await f.controller.refresh();
    f.controller.stop();
    f.controller.stop();
    assert.equal(f.requests.length, 2);
    assert.deepEqual(f.requests[1], { path: '/microphone/live/session-a/stop', options: { method: 'POST', body: { flush: false } } });
    response.resolve(session({ state: 'stopping' }));
    await new Promise(setImmediate);
    f.replies.push(session({ state: 'done', text: 'unprinted remainder' }));
    await f.controller.refresh();
    assert.equal(f.controller.busy, false);
    assert.equal(f.endings[0].text, 'unprinted remainder');
});

test('a stale poll cannot overwrite the result of Stop', async () => {
    const f = fixture();
    const oldPoll = deferred();
    f.replies.push(session(), oldPoll.promise, session({ state: 'done', text: 'final' }));
    await f.controller.refresh();
    const poll = f.controller.refresh();
    f.controller.stop();
    await new Promise(setImmediate);
    oldPoll.resolve(session({ text: 'stale partial' }));
    await poll;
    assert.equal(f.controller.state.session.state, 'done');
    assert.equal(f.endings.length, 1);
    assert.equal(f.endings[0].text, 'final');
});

test('lost start response is recovered by reading status, never by starting again', async () => {
    const f = fixture();
    f.replies.push(idle, new Error('Network lost'), session());
    await f.controller.refresh();
    await f.controller.start({ cadence_seconds: 10, duration_seconds: null });
    assert.equal(f.controller.busy, true);
    assert.equal(f.controller.state.uncertain, true);
    assert.equal(f.changes.at(-1).trackingSession, true);
    await f.controller.refresh();
    assert.equal(f.controller.state.session.id, 'session-a');
    assert.equal(f.requests.filter(r => r.path === '/microphone/live/start').length, 1);
});

test('Stop during an uncertain start is applied to the recovered session', async () => {
    const f = fixture();
    f.replies.push(idle, new Error('Timeout'), session(), session({ state: 'stopping' }));
    await f.controller.refresh();
    await f.controller.start({ cadence_seconds: 10, duration_seconds: null });
    f.controller.stop();
    await f.controller.refresh();
    await new Promise(setImmediate);
    assert.equal(f.requests.at(-1).path, '/microphone/live/session-a/stop');
    assert.equal(f.controller.state.stopRequested, true);
});

test('network loss never announces an indefinite session as stopped', async () => {
    const f = fixture();
    f.replies.push(session(), new Error('Offline'), new Error('Offline'), session({ seconds: 22 }));
    await f.controller.refresh();
    await f.controller.refresh();
    await f.controller.refresh();
    assert.equal(f.controller.busy, true);
    assert.equal(f.controller.state.offline, true);
    assert.equal(f.changes.at(-1).trackingSession, true);
    assert.equal(f.endings.length, 0);
    await f.controller.refresh();
    assert.equal(f.controller.state.offline, false);
    assert.equal(f.controller.state.session.seconds, 22);
});

test('an unconfirmed Stop is retried after reconnecting, without another start', async () => {
    const f = fixture();
    f.replies.push(session(), new Error('Stop response lost'));
    await f.controller.refresh();
    f.controller.stop();
    await new Promise(setImmediate);
    assert.equal(f.controller.state.stopRequested, true);
    assert.equal(f.controller.busy, true);
    f.replies.push(session(), session({ state: 'done' }));
    await f.controller.refresh();
    await new Promise(setImmediate);
    assert.equal(f.requests.filter(r => r.path.endsWith('/stop')).length, 2);
    assert.equal(f.controller.busy, false);
});

test('error state with an in-flight print remains busy until that print ends', async () => {
    const f = fixture();
    const error = session({ state: 'error', error: 'Queue full', printing: { id: 1, text: 'in flight' } });
    f.replies.push(error, { ...error, printing: null });
    await f.controller.refresh();
    assert.equal(f.controller.busy, true);
    assert.equal(f.endings.length, 0);
    await f.controller.refresh();
    assert.equal(f.controller.busy, false);
    assert.equal(f.endings.length, 1);
});

test('page close only suspends polling; returning resumes discovery', async () => {
    const f = fixture();
    f.replies.push(session());
    await f.controller.refresh();
    f.controller.suspend();
    await f.controller.refresh();
    assert.equal(f.requests.length, 1);
    f.replies.push(session({ seconds: 60 }));
    f.controller.resume();
    await new Promise(setImmediate);
    assert.equal(f.controller.state.session.seconds, 60);
    assert.ok(f.requests.every(r => !r.options?.method));
});

test('missing session after a Pi restart triggers discovery instead of repeated stale requests', async () => {
    const f = fixture();
    f.replies.push(session(), Object.assign(new Error('Gone'), { status: 404 }), idle);
    await f.controller.refresh();
    await f.controller.refresh();
    assert.equal(f.controller.busy, true);
    await f.controller.refresh();
    assert.equal(f.requests.at(-1).path, '/microphone/live');
    assert.equal(f.controller.busy, false);
});

test('older backends leave review mode available and recover after an upgrade', async () => {
    const f = fixture();
    f.replies.push(Object.assign(new Error('Not found'), { status: 404 }), idle);
    await f.controller.refresh();
    assert.equal(f.controller.busy, false);
    assert.equal(f.controller.state.available, false);
    await f.controller.refresh();
    assert.equal(f.controller.state.available, true);
});
