const { test } = require('node:test');
const assert = require('node:assert/strict');
const { AudioMeter } = require('../frontend/audio-meter.js');

function fixture() {
    const timers = new Map();
    let nextTimer = 0;
    const document = { createElement: () => ({ ownerDocument: document, children: [], style: {}, dataset: {},
        append(...children) { this.children.push(...children); },
        setAttribute(name, value) { this[name] = value; }
    }) };
    const root = document.createElement('div');
    const meter = new AudioMeter(root, {
        schedule: callback => { timers.set(++nextTimer, callback); return nextTimer; },
        cancel: id => timers.delete(id)
    });
    return { root, meter, timers };
}
const recording = (detected = true, levels = [0.1, 0.2, 0.4, 0.8, 0.5, 0.3, 0.1]) =>
    ({ state: 'recording', audio: { detected, levels } });

test('measured sound animates the bars and silence returns them to their baseline', () => {
    const { root, meter } = fixture();
    assert.equal(root.hidden, true);
    meter.update(recording());
    assert.equal(root.hidden, false);
    assert.equal(root.dataset.state, 'sound');
    assert.match(root['aria-label'], /Samson microphone: Sound detected/);
    assert.equal(root.children.length, 1); // The waveform is the icon; no visible label.
    assert.notEqual(meter.bars[0].style.transform, meter.bars[3].style.transform);
    meter.update(recording(false, Array(7).fill(0)));
    assert.equal(root['aria-label'], 'Samson microphone: Quiet');
    assert.ok(meter.bars.every(bar => bar.style.transform === 'scaleY(0.12)'));
});

test('network loss, stale input and older backends never show fake silence or old activity', () => {
    const { root, meter, timers } = fixture();
    meter.update(recording());
    [...timers.values()][0]();
    assert.equal(root['aria-label'], 'Samson microphone: Audio level unavailable');
    for (const [session, options] of [
        [recording(), { offline: true }], [{ state: 'recording', audio: null }],
        [{ state: 'recording' }], [recording(true, [NaN])]
    ]) {
        meter.update(session, options);
        assert.equal(root.dataset.state, 'unavailable');
        assert.ok(meter.bars.every(bar => bar.style.transform === 'scaleY(0.12)'));
    }
    meter.update(recording());
    assert.equal(root.dataset.state, 'sound');
    assert.equal(timers.size, 1);
});

test('stop, completion, errors and a new startup clear the meter and its stale timer', () => {
    const { root, meter, timers } = fixture();
    for (const state of ['starting', 'stopping', 'transcribing', 'done', 'error']) {
        meter.update(recording());
        meter.update({ ...recording(), state });
        assert.equal(root.hidden, true);
        assert.equal(timers.size, 0);
    }
    meter.update(recording());
    meter.update(recording(), { stopping: true });
    assert.equal(root.hidden, true);
    assert.equal(timers.size, 0);
    meter.update(null);
    assert.equal(root.dataset.state, 'unavailable');
});
