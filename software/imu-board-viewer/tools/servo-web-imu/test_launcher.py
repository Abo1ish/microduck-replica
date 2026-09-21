"""Portable launcher checks; no server, probe, or installer is started."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

import launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_config(self, data, name='config.json'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8-sig')
        return path

    def live_config(self):
        for name in ('driver.dll', 'image.bin', 'image.map'):
            (self.root / name).write_bytes(b'test fixture')
        return {'probe_serial': 12345678, 'dll': 'driver.dll',
                'firmware': 'image.bin', 'map': 'image.map', 'hz': 15}

    def test_live_without_config_requires_first_time_setup(self):
        with self.assertRaisesRegex(ValueError, '首次安装'):
            launcher.launch_settings(launcher.parse_args([]), self.root)

    def test_configured_live_uses_default_port_and_explicit_probe(self):
        self.write_config(self.live_config())
        port, command, _ = launcher.launch_settings(launcher.parse_args([]), self.root)
        self.assertEqual(port, 8081)
        self.assertIn('--resume', command)
        self.assertEqual(command[command.index('--probe-serial') + 1], '12345678')

    def test_demo_defaults_do_not_pass_probe_or_resume(self):
        port, command, _ = launcher.launch_settings(launcher.parse_args(['--demo']), self.root)
        self.assertEqual(port, 8082)
        self.assertIn('--demo', command)
        self.assertNotIn('--resume', command)
        self.assertNotIn('--dll', command)

    def test_template_demo_needs_no_driver_firmware_or_serial(self):
        config = json.loads((launcher.ROOT / 'config.example.json').read_text(encoding='utf-8'))
        self.write_config(config)
        port, command, _ = launcher.launch_settings(launcher.parse_args(['--demo']), self.root)
        self.assertEqual(port, 8082)
        self.assertEqual(command[-2:], ['--hz', '20'])

    def test_relative_paths_follow_config_not_working_directory(self):
        config = self.live_config()
        path = self.write_config(config)
        loaded = launcher.load_config(path)
        self.assertEqual(loaded['dll'], str((self.root / 'driver.dll').resolve()))
        self.assertEqual(loaded['firmware'], str((self.root / 'image.bin').resolve()))

    def test_absolute_paths_and_explicit_config(self):
        config = self.live_config()
        config['dll'] = str((self.root / 'driver.dll').resolve())
        path = self.write_config(config, 'alternate.json')
        _, command, _ = launcher.launch_settings(launcher.parse_args(['--config', str(path)]), self.root)
        self.assertIn(config['dll'], command)
        self.assertEqual(command[command.index('--probe-serial') + 1], '12345678')
        self.assertIn('--firmware', command)
        self.assertIn('--map', command)

    def test_command_line_port_overrides_config(self):
        self.write_config({'port': 8181})
        port, command, _ = launcher.launch_settings(launcher.parse_args(['--demo', '--port', '8182']), self.root)
        self.assertEqual(port, 8182)
        self.assertEqual(command[command.index('--port') + 1], '8182')

    def test_config_port_is_used_when_not_overridden(self):
        self.write_config({'port': 8183})
        port, _, _ = launcher.launch_settings(launcher.parse_args(['--demo']), self.root)
        self.assertEqual(port, 8183)

    def test_explicit_missing_config_has_clear_error(self):
        with self.assertRaisesRegex(ValueError, '无法读取配置'):
            launcher.load_config(self.root / 'missing.json', demo=True)

    def test_no_automatic_random_probe_selection(self):
        for value in (None, 0, -1, True, '12345678', 2**32):
            with self.subTest(value=value):
                config = self.live_config()
                config['probe_serial'] = value
                with self.assertRaisesRegex(ValueError, 'probe_serial'):
                    launcher.load_config(self.write_config(config))

    def test_missing_live_file_fails_before_starting_server(self):
        config = self.live_config()
        config['dll'] = 'missing.dll'
        with self.assertRaisesRegex(ValueError, 'dll 文件不存在'):
            launcher.load_config(self.write_config(config))

    def test_invalid_port_hz_or_typo_fail(self):
        for data in ({'port': 0}, {'port': True}, {'port': 65536}, {'hz': float('nan')},
                     {'hz': 0}, {'hz': '20'}, {'probe_serail': 12345678}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                launcher.load_config(self.write_config(data), demo=True)

    def test_existing_service_must_match_mode_and_identity(self):
        for data in ({'service': 'other', 'mode': 'demo'},
                     {'service': 'microduck-imu-viewer', 'mode': 'live'}, []):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                launcher.validate_service(data, demo=True, port=8082, config={})
        launcher.validate_service({'service': 'microduck-imu-viewer', 'mode': 'demo'},
                                  demo=True, port=8082, config={})

    def test_existing_connected_probe_must_match_config(self):
        payload = {'service': 'microduck-imu-viewer', 'mode': 'live', 'probe_serial': 1111}
        with self.assertRaisesRegex(RuntimeError, '其他 J-Link'):
            launcher.validate_service(payload, demo=False, port=8081, config={'probe_serial': 2222})

    def test_existing_compatible_service_is_reused_without_process(self):
        with mock.patch.object(launcher, 'launch_settings', return_value=(8182, ['unused.exe'], {})), \
             mock.patch.object(launcher, 'status', return_value={'service': 'microduck-imu-viewer', 'mode': 'demo'}), \
             mock.patch.object(launcher.subprocess, 'Popen') as popen:
            self.assertEqual(launcher.main(['--demo', '--no-browser', '--port', '8182']), 0)
            popen.assert_not_called()

    def test_startup_poll_also_rejects_incompatible_service(self):
        fake_python = self.root / 'python.exe'
        fake_python.write_bytes(b'fake')
        process = mock.Mock(pid=123, returncode=None)
        process.poll.return_value = None
        with mock.patch.object(launcher, 'ROOT', self.root), \
             mock.patch.object(launcher, 'launch_settings', return_value=(8182, [str(fake_python)], {})), \
             mock.patch.object(launcher, 'status', side_effect=[None, {'service': 'microduck-imu-viewer', 'mode': 'live'}]), \
             mock.patch.object(launcher.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, '其他模式'):
                launcher.main(['--demo', '--no-browser'])


if __name__ == '__main__':
    unittest.main()
