const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

function fixture(data) {
    const state = {callback: null, removed: [], spawns: [], prompts: []};
    const context = {
        TextDecoder, console,
        GObject: {registerClass: cls => cls},
        PanelMenu: {Button: class {destroy() {state.destroyed = true;}}},
        Extension: class {},
        Gio: {
            File: {new_for_path: () => ({load_contents_async: (cancel, callback) => {state.callback = callback;}})},
            SubprocessFlags: {NONE: 0},
            SubprocessLauncher: class {
                setenv(...args) {state.prompts.push(args);}
                spawnv(argv) {state.spawns.push(Array.from(argv));}
            },
        },
        GLib: {Source: {remove: id => state.removed.push(id)}},
    };
    vm.createContext(context);
    const source = fs.readFileSync(path.join(__dirname, '../extension/extension.js'), 'utf8')
        .replace(/^import .*;\n/gm, '').replace('export default class', 'class');
    vm.runInContext(source + '\nglobalThis.Subject = NetSpeedButton;', context);
    const subject = Object.create(context.Subject.prototype);
    Object.assign(subject, {
        _destroyed: false, _reading: false, _cancellable: {cancel: () => {state.cancelled = true;}},
        _speedLabel: {}, _sessionSection: {actor: {}}, _userToggledAt: 0, _targetState: false,
        _proxySwitch: {state: false, setToggleState: value => {subject._proxySwitch.state = value;}},
    });
    for (const name of ['_downSpeedItem', '_upSpeedItem', '_sessionRxItem', '_sessionTxItem', '_sessionDurationItem'])
        subject[name] = {label: {}};
    state.complete = () => state.callback({load_contents_finish: () => [true, new TextEncoder().encode(JSON.stringify(data))]}, {});
    return {subject, state};
}

test('preferences hide upload and session totals', () => {
    const {subject, state} = fixture({rx_speed_formatted: '1 Ko/s', tx_speed_formatted: '2 Ko/s', show_upload: false, show_session_total: false});
    subject._update(); state.complete();
    assert.equal(subject._speedLabel.text, '↓ 1 Ko/s');
    assert.equal(subject._sessionSection.actor.visible, false);
});

test('overlapping reads are suppressed', () => {
    const {subject, state} = fixture({});
    subject._update();
    const first = state.callback;
    subject._update();
    assert.equal(state.callback, first);
    state.complete();
    assert.equal(subject._reading, false);
});

test('destroy cancels outstanding reads and prevents later widget mutation', () => {
    const {subject, state} = fixture({rx_speed_formatted: '100 Mo/s'});
    subject._timerId = 42;
    subject._update(); subject.destroy(); state.complete();
    assert.equal(state.cancelled, true);
    assert.deepEqual(state.removed, [42]);
    assert.equal(subject._speedLabel.text, undefined);
});

test('program arguments preserve paths containing spaces and enable authentication on clicks', () => {
    const {subject, state} = fixture({});
    subject._spawn(['/home/test user/.local/bin/netpulse-ctl', 'start'], true);
    assert.deepEqual(state.spawns, [['/home/test user/.local/bin/netpulse-ctl', 'start']]);
    assert.deepEqual(state.prompts, [['NETPULSE_ALLOW_GUI_PROMPT', '1', true]]);
});

test('proxy switch accepts the daemon state', () => {
    const {subject, state} = fixture({proxy_active: true});
    subject._update(); state.complete();
    assert.equal(subject._proxySwitch.state, true);
    assert.equal(subject._updatingSwitch, false);
});
