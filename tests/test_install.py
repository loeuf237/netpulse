import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cairo
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / 'install.sh').read_text()


def heredoc(marker):
    return INSTALL.split("<<'" + marker + "'\n", 1)[1].split('\n' + marker, 1)[0]


class InstallerTests(unittest.TestCase):
    def test_generated_icons_have_requested_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            icon = destination / 'scalable/apps/netpulse.svg'
            icon.parent.mkdir(parents=True)
            icon.write_bytes((ROOT / 'icons/netpulse.svg').read_bytes())
            subprocess.run([sys.executable, '-c', heredoc('PYICONS'), directory], check=True, capture_output=True, timeout=10)
            for size in (16, 24, 32, 48, 64, 128, 256, 512):
                surface = cairo.ImageSurface.create_from_png(str(destination / f'{size}x{size}/apps/netpulse.png'))
                self.assertEqual((surface.get_width(), surface.get_height()), (size, size))

    def test_desktop_launcher_handles_spaces_in_path(self):
        with tempfile.TemporaryDirectory(prefix='netpulse user ') as directory:
            destination = Path(directory)
            executable = destination / 'netpulse-gui'
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o755)
            desktop = destination / 'netpulse.desktop'
            desktop.write_bytes((ROOT / 'desktop/netpulse.desktop').read_bytes())
            subprocess.run([sys.executable, '-c', heredoc('PYDESKTOP'), str(desktop), str(executable)], check=True, capture_output=True, timeout=10)
            info = Gio.DesktopAppInfo.new_from_filename(str(desktop))
            self.assertIsNotNone(info)
            self.assertEqual(GLib.shell_parse_argv(info.get_commandline())[1], [str(executable)])


if __name__ == '__main__':
    unittest.main()
