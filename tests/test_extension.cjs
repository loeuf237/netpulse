const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

function fixture(data) {
    const state = {callback: null, removed: [], spawns: [], prompts: [], notifications: []};
    const context = {
        TextDecoder, console,
        GObject: {registerClass: cls => cls},
        PanelMenu: {Button: class {destroy() {state.destroyed = true;}}},
        Extension: class {},
        _: text => text,
        Main: {notify: (...args) => state.notifications.push(args)},
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
        _proxyActive: false, _connectionProtected: true, _protectionItem: {actor: {}},
        _ctlBin: '/test/netpulse-ctl', _guiBin: '/test/netpulse-gui',
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

test('protected switch restores actual state and opens GUI without stopping tunnel', () => {
    const {subject, state} = fixture({proxy_active: true, connection_protected: true});
    subject._update(); state.complete();
    subject._onProxyToggled(false);
    assert.equal(subject._proxySwitch.state, true);
    assert.deepEqual(state.spawns, [['/test/netpulse-gui']]);
    assert.equal(state.notifications.length, 1);
    assert.equal(subject._protectionItem.actor.visible, true);
    assert.equal(subject._userToggledAt, 0);
});

test('complete shutdown from protected indicator opens GUI without quitting NetPulse', () => {
    const {subject, state} = fixture({});
    assert.equal(subject._requestNetworkAction('quit'), false);
    assert.deepEqual(state.spawns, [['/test/netpulse-gui']]);
    assert.equal(state.notifications.length, 1);
});

test('unknown protection state stays guarded and explicit unlock allows a switch', () => {
    const {subject, state} = fixture({proxy_active: true, connection_protected: false});
    assert.equal(subject._connectionProtected, true);
    subject._update(); state.complete();
    subject._onProxyToggled(false);
    assert.deepEqual(state.spawns, [['/test/netpulse-ctl', 'stop']]);
    assert.equal(state.notifications.length, 0);
    assert.equal(subject._protectionItem.actor.visible, false);
    assert.equal(subject._targetState, false);
    assert.deepEqual(state.prompts, [['NETPULSE_ALLOW_GUI_PROMPT', '1', true]]);
});

test('deferred network actions retain protection even if configuration is unlocked', () => {
    const {subject, state} = fixture({proxy_active: true, connection_protected: false, network_actions_deferred: true});
    subject._update(); state.complete();
    assert.equal(subject._connectionProtected, true);
    assert.equal(subject._requestNetworkAction('stop'), false);
    assert.deepEqual(state.spawns, [['/test/netpulse-gui']]);
});
