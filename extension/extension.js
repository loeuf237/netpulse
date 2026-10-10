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

        this._updatingSwitch = false;
        this._userToggledAt = 0;
        this._targetState = false;
        this._proxyActive = false;
        this._connectionProtected = true;
        this._destroyed = false;
        this._reading = false;
        this._cancellable = new Gio.Cancellable();

        // Panel Bar Layout: [NetPulse Icon] [Speed Label]
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
            style: 'font-family: monospace; font-size: 11px; margin-left: 5px; font-weight: bold;',
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
        this._sessionSection = sessionSection;
        this._sessionHeader = new PopupMenu.PopupMenuItem(_('📊 Données échangées (Session) :'), {reactive: false});
        this._sessionHeader.label.style = 'font-weight: bold; color: #8b949e;';
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
        this._protectionItem = new PopupMenu.PopupMenuItem(_('🔒 Connexion protégée : confirmer dans NetPulse'), {reactive: false});
        this.menu.addMenuItem(this._protectionItem);
        this._proxySwitch = new PopupMenu.PopupSwitchMenuItem(_('⚡ Forcer le Proxy (Mode TUN)'), false);
        this._proxySwitch.connect('toggled', (_item, state) => this._onProxyToggled(state));
        this.menu.addMenuItem(this._proxySwitch);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 4. Quick Actions
        const openAppItem = new PopupMenu.PopupMenuItem(_('🖥️ Ouvrir NetPulse...'));
        openAppItem.connect('activate', () => {
            this._spawn([this._guiBin]);
        });
        this.menu.addMenuItem(openAppItem);

        const resetItem = new PopupMenu.PopupMenuItem(_('🔄 Réinitialiser les compteurs'));
        resetItem.connect('activate', () => {
            this._spawn([this._monBin, '--reset']);
        });
        this.menu.addMenuItem(resetItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // 5. Quit Action
        const quitItem = new PopupMenu.PopupMenuItem(_('🛑 Quitter NetPulse'));
        quitItem.connect('activate', () => {
            this._requestNetworkAction('quit');
        });
        this.menu.addMenuItem(quitItem);

        // Start periodic update loop
        this._update();
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._update();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _requestNetworkAction(action) {
        if (this._destroyed)
            return false;
        if (this._connectionProtected) {
            Main.notify(_('Connexion protégée'), _('Pour modifier ou arrêter le tunnel, ouvrez NetPulse et confirmez le changement.'));
            this._spawn([this._guiBin]);
            return false;
        }
        this._spawn([this._ctlBin, action], true);
        return true;
    }

    _onProxyToggled(state) {
        if (this._updatingSwitch || this._destroyed)
            return;
        if (this._requestNetworkAction(state ? 'start' : 'stop')) {
            this._userToggledAt = Date.now();
            this._targetState = state;
        } else {
            this._userToggledAt = 0;
            this._updatingSwitch = true;
            try {
                this._proxySwitch.setToggleState(this._proxyActive);
            } finally {
                this._updatingSwitch = false;
            }
        }
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

    _spawn(argv, allowPrompt = false) {
        try {
            const launcher = new Gio.SubprocessLauncher({flags: Gio.SubprocessFlags.NONE});
            if (allowPrompt)
                launcher.setenv('NETPULSE_ALLOW_GUI_PROMPT', '1', true);
            launcher.spawnv(argv);
        } catch (error) {
            console.error(`NetPulse: ${error.message}`);
        }
    }

    _update() {
        if (this._destroyed || this._reading)
            return;
        this._reading = true;
        const file = Gio.File.new_for_path(STATS_FILE);
        file.load_contents_async(this._cancellable, (source, result) => {
            try {
                const [ok, contents] = source.load_contents_finish(result);
                if (ok && !this._destroyed) {
                    const text = new TextDecoder().decode(contents);
                    const data = JSON.parse(text);
                    this._connectionProtected = data.connection_protected !== false || data.network_actions_deferred === true;
                    this._protectionItem.actor.visible = this._connectionProtected;

                    const rx = data.rx_speed_formatted || '0 o/s';
                    const tx = data.tx_speed_formatted || '0 o/s';
                    const speeds = [];
                    if (data.show_download !== false)
                        speeds.push(`↓ ${rx}`);
                    if (data.show_upload !== false)
                        speeds.push(`↑ ${tx}`);
                    this._speedLabel.text = speeds.join('  ');
                    this._sessionSection.actor.visible = data.show_session_total !== false;

                    this._downSpeedItem.label.text = `📥 Réception : ${rx}`;
                    this._upSpeedItem.label.text = `📤 Envoi : ${tx}`;

                    const totRx = data.session_rx_formatted || '0 o';
                    const totTx = data.session_tx_formatted || '0 o';
                    this._sessionRxItem.label.text = `Total reçu : ${totRx}`;
                    this._sessionTxItem.label.text = `Total envoyé : ${totTx}`;

                    const dur = this._formatDuration(data.session_duration_sec || 0);
                    this._sessionDurationItem.label.text = `Durée de session : ${dur}`;

                    if ('proxy_active' in data) {
                        const isActive = !!data.proxy_active;
                        this._proxyActive = isActive;
                        const elapsed = Date.now() - (this._userToggledAt || 0);

                        let shouldUpdate = true;
                        if (elapsed < 6000) {
                            if (isActive === this._targetState) {
                                this._userToggledAt = 0;
                            } else {
                                shouldUpdate = false;
                            }
                        }

                        if (shouldUpdate && this._proxySwitch.state !== isActive) {
                            this._updatingSwitch = true;
                            try {
                                this._proxySwitch.setToggleState(isActive);
                            } finally {
                                this._updatingSwitch = false;
                            }
                        }
                    }
                }
            } catch (e) {
                // ignore transient read
            } finally {
                this._reading = false;
            }
        });
    }

    destroy() {
        this._destroyed = true;
        this._cancellable.cancel();
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
