"""Start the local IMU viewer using the environment beside this file."""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def integer(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f'{name} 必须是 1–{maximum} 的整数。')
    return value


def load_config(path, *, demo=False):
    """Resolve paths against the config, never the caller's current directory."""
    if path is None:
        if not demo:
            raise ValueError('真板模式缺少 config.json：请先运行“首次安装.cmd”，再填写配置中的 probe_serial 和 dll 路径。')
        return {}
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'无法读取配置 {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError('配置文件的顶层必须是 JSON 对象。')
    supported = {'dll', 'probe_serial', 'firmware', 'map', 'hz', 'port'}
    unknown = [key for key in data if key not in supported and not key.startswith('_')]
    if unknown:
        raise ValueError(f'不支持的配置字段: {", ".join(unknown)}')
    config = {}
    if 'port' in data:
        config['port'] = integer(data['port'], 'port', 65535)
    if 'hz' in data:
        hz = data['hz']
        if isinstance(hz, bool) or not isinstance(hz, (int, float)) or not math.isfinite(hz) or not 1 <= hz <= 100:
            raise ValueError('hz 必须是 1–100 范围内的有限数字。')
        config['hz'] = hz
    # Demo needs neither J-Link nor firmware; the unedited template is usable.
    if not demo:
        config['probe_serial'] = integer(data.get('probe_serial'), 'probe_serial（J-Link 序列号，请填写配置文件）', 0xFFFFFFFF)
        for name in ('dll', 'firmware', 'map'):
            value = data.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'真板模式需要在 {path} 中填写 {name} 文件路径。')
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = path.parent / candidate
            candidate = candidate.resolve()
            if not candidate.is_file():
                raise ValueError(f'{name} 文件不存在: {candidate}；请修改 {path}。')
            config[name] = str(candidate)
    return config


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--config', type=Path, help='JSON 配置；默认查找启动器旁的 config.json')
    parser.add_argument('--port', type=int, help='覆盖配置中的端口；默认真板 8081 / 演示 8082')
    return parser.parse_args(argv)


def launch_settings(args, root=ROOT):
    path = args.config
    if path is None and (root / 'config.json').exists():
        path = root / 'config.json'
    config = load_config(path, demo=args.demo)
    port = args.port if args.port is not None else config.get('port', 8082 if args.demo else 8081)
    port = integer(port, 'port', 65535)
    python = root / '.venv' / 'Scripts' / 'python.exe'
    command = [str(python), str(root / 'imu_server.py'), '--port', str(port)]
    command += ['--demo'] if args.demo else ['--resume']
    for name, flag in [('dll', '--dll'), ('probe_serial', '--probe-serial'),
                       ('firmware', '--firmware'), ('map', '--map'), ('hz', '--hz')]:
        if name in config:
            command += [flag, str(config[name])]
    return port, command, config


def validate_service(payload, *, demo, port, config):
    if not isinstance(payload, dict) or payload.get('service') != 'microduck-imu-viewer':
        raise RuntimeError(f'端口 {port} 已被其他服务占用；可使用 --port 更换端口。')
    if payload.get('mode') != ('demo' if demo else 'live'):
        raise RuntimeError(f'端口 {port} 上的网页处于其他模式；请关闭该服务或更换端口。')
    if not demo and 'probe_serial' in config and payload.get('probe_serial') is not None:
        if payload['probe_serial'] != config['probe_serial']:
            raise RuntimeError(f'端口 {port} 的服务连接了其他 J-Link；请更换端口或关闭旧服务。')


def status(url):
    try:
        with urllib.request.urlopen(url + '/api/status', timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def main(argv=None):
    args = parse_args(argv)
    port, command, config = launch_settings(args)
    url = f'http://127.0.0.1:{port}'
    existing = status(url)
    if existing is not None:
        validate_service(existing, demo=args.demo, port=port, config=config)
        if not args.no_browser:
            webbrowser.open(url)
        print(url)
        return 0

    log_dir = ROOT / 'logs'
    temp_dir = ROOT / 'runtime-temp'
    log_dir.mkdir(exist_ok=True)
    temp_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(TEMP=str(temp_dir), TMP=str(temp_dir), PYTHONNOUSERSITE='1',
               PYTHONUNBUFFERED='1', PYTHONUTF8='1')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    logfile = log_dir / f'{"demo" if args.demo else "live"}-{stamp}.log'
    if not Path(command[0]).is_file():
        raise RuntimeError('尚未创建本工程的 Python 环境，请先运行“首次安装.cmd”。')
    with logfile.open('a', encoding='utf-8') as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=stream,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (log_dir / f'server-{port}.json').write_text(json.dumps({
        'pid': process.pid, 'command': command, 'url': url, 'started_at': stamp,
        'log': str(logfile), 'root': str(ROOT),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Server exited ({process.returncode}); see {logfile}')
        current = status(url)
        if current is not None:
            validate_service(current, demo=args.demo, port=port, config=config)
            if not args.no_browser:
                webbrowser.open(url)
            print(url)
            return 0
        time.sleep(.25)
    raise RuntimeError(f'Server did not become ready; see {logfile}')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        (ROOT / 'logs').mkdir(exist_ok=True)
        error_path = ROOT / 'logs' / 'launcher-error.txt'
        error_path.write_text(str(exc), encoding='utf-8')
        # pythonw has no terminal; show the concrete error in the user's text viewer.
        if sys.stdout is None:
            os.startfile(error_path)
        else:
            print(str(exc), file=sys.stderr)
        raise SystemExit(1)
