import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Clutter from 'gi://Clutter';
import St from 'gi://St';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

const STATS_FILE = '/tmp/netpulse_stats.json';

const NetSpeedButton = GObject.registerClass(
class NetSpeedButton extends PanelMenu.Button {
    _init(extension) {
        super._init(0.0, _('NetPulse'), false);

        this._extension = extension;
        this._ctlBin = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'netpulse-ctl']);
        this._guiBin = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'netpulse-gui']);
        this._monBin = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'netpulse-monitor']);

        // Panel Bar Layout: [Icon] [Label with Download/Upload]
        const box = new St.BoxLayout({
            style_class: 'panel-status-menu-box',
            x_expand: true,
            y_expand: true,
        });

        this._icon = new St.Icon({
            icon_name: 'netpulse',
            style_class: 'system-status-icon',
        });
        box.add_child(this._icon);

        this._speedLabel = new St.Label({
            text: '↓ 0 o/s  ↑ 0 o/s',
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-family: monospace; font-size: 11px; margin-left: 4px; font-weight: bold;',
        });
        box.add_child(this._speedLabel);

        this.add_child(box);

        // -------------------------------------------------------------
        // Dropdown Menu Content
        // -------------------------------------------------------------
        // 1. Live Speeds
        const liveSection = new PopupMenu.PopupMenuSection();
        this._downSpeedItem = new PopupMenu.PopupMenuItem(_('📥 Réception : 0 o/s'), {reactive: false});
        this._upSpeedItem = new PopupMenu.PopupMenuItem(_('📤 Envoi : 0 o/s'), {reactive: false});
        liveSection.addMenuItem(this._downSpeedItem);
        liveSection.addMenuItem(this._upSpeedItem);
        this.menu.addMenuItem(liveSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 2. Session Totals
        const sessionSection = new PopupMenu.PopupMenuSection();
        this._sessionHeader = new PopupMenu.PopupMenuItem(_('📊 Données échangées (Session) :'), {reactive: false});
        this._sessionHeader.actor.add_style_class_name('popup-subtitle-menu-item');
        sessionSection.addMenuItem(this._sessionHeader);

        this._sessionRxItem = new PopupMenu.PopupMenuItem(_('Total reçu : 0 o'), {reactive: false});
        this._sessionTxItem = new PopupMenu.PopupMenuItem(_('Total envoyé : 0 o'), {reactive: false});
        this._sessionDurationItem = new PopupMenu.PopupMenuItem(_('Durée : 00:00'), {reactive: false});
        sessionSection.addMenuItem(this._sessionRxItem);
        sessionSection.addMenuItem(this._sessionTxItem);
        sessionSection.addMenuItem(this._sessionDurationItem);
        this.menu.addMenuItem(sessionSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 3. Proxy & TUN Control
        this._proxySwitch = new PopupMenu.PopupSwitchMenuItem(_('Forcer le Proxy (Mode TUN)'), false);
        this._proxySwitch.connect('toggled', (item, state) => {
            const action = state ? 'start' : 'stop';
            GLib.spawn_command_line_async(`${this._ctlBin} ${action}`);
        });
        this.menu.addMenuItem(this._proxySwitch);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 4. Quick Actions
        const openAppItem = new PopupMenu.PopupMenuItem(_('🖥️ Moniteur Réseau & Applications (GlassWire)...'));
        openAppItem.connect('activate', () => {
            GLib.spawn_command_line_async(this._guiBin);
        });
        this.menu.addMenuItem(openAppItem);

        const resetItem = new PopupMenu.PopupMenuItem(_('🔄 Réinitialiser les données de session'));
        resetItem.connect('activate', () => {
            GLib.spawn_command_line_async(`${this._monBin} --reset`);
        });
        this.menu.addMenuItem(resetItem);

        // Start periodic update loop
        this._update();
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._update();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _formatDuration(sec) {
        const hrs = Math.floor(sec / 3600);
        const mins = Math.floor((sec % 3600) / 60);
        const s = sec % 60;
        if (hrs > 0) {
            return `${hrs}h ${mins.toString().padStart(2, '0')}m`;
        }
        return `${mins}m ${s.toString().padStart(2, '0')}s`;
    }

    _update() {
        const file = Gio.File.new_for_path(STATS_FILE);
        file.load_contents_async(null, (source, result) => {
            try {
                const [ok, contents] = source.load_contents_finish(result);
                if (ok) {
                    const text = new TextDecoder().decode(contents);
                    const data = JSON.parse(text);

                    const rx = data.rx_speed_formatted || '0 o/s';
                    const tx = data.tx_speed_formatted || '0 o/s';
                    this._speedLabel.text = `↓ ${rx}  ↑ ${tx}`;

                    this._downSpeedItem.label.text = `📥 Réception : ${rx}`;
                    this._upSpeedItem.label.text = `📤 Envoi : ${tx}`;

                    const totRx = data.session_rx_formatted || '0 o';
                    const totTx = data.session_tx_formatted || '0 o';
                    this._sessionRxItem.label.text = `Total reçu : ${totRx}`;
                    this._sessionTxItem.label.text = `Total envoyé : ${totTx}`;

                    const dur = this._formatDuration(data.session_duration_sec || 0);
                    this._sessionDurationItem.label.text = `Durée de session : ${dur}`;
                }
            } catch (e) {
                // ignore transient file read error
            }
        });

        // Check proxy state asynchronously
        try {
            const [ok, out] = GLib.spawn_command_line_sync(`${this._ctlBin} status --json`);
            if (ok && out) {
                const pdata = JSON.parse(new TextDecoder().decode(out));
                const isActive = !!pdata.active;
                if (this._proxySwitch.state !== isActive) {
                    this._proxySwitch.setToggleState(isActive);
                }
                if (isActive) {
                    this._icon.icon_name = 'network-vpn-symbolic';
                } else {
                    this._icon.icon_name = 'network-transmit-receive-symbolic';
                }
            }
        } catch (e) {
            // ignore
        }
    }

    destroy() {
        if (this._timerId) {
            GLib.Source.remove(this._timerId);
            this._timerId = null;
        }
        super.destroy();
    }
});

export default class NetPulseExtension extends Extension {
    enable() {
        this._indicator = new NetSpeedButton(this);
        Main.panel.addToStatusArea('force-proxy-meter', this._indicator, 1, 'right');
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
