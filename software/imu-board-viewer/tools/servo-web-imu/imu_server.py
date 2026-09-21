"""Local-only IMU viewer. It does not import the servo control server."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import ipaddress
import logging
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
import uvicorn

from imu_bridge import (BridgeError, BridgeService, DEFAULT_FIRMWARE, DEFAULT_MAP,
                        validate_probe_settings)

ROOT = Path(__file__).resolve().parent


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def valid_origin(origin: str | None, port: int) -> bool:
    if origin is None:
        return True  # Non-browser loopback clients (e.g. local diagnostic script).
    try:
        parsed = urlsplit(origin)
        return (parsed.scheme in ("http", "https") and parsed.hostname is not None
                and is_loopback(parsed.hostname) and (parsed.port or (443 if parsed.scheme == "https" else 80)) == port
                and not parsed.username and not parsed.password)
    except ValueError:
        return False


def create_app(service: BridgeService, port: int = 8081) -> Starlette:
    control_token = secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(app: Starlette):
        service.start()
        try:
            yield
        finally:
            await asyncio.to_thread(service.stop)

    async def home(request: Request):
        path = ROOT / "imu.html"
        if not path.is_file():
            return PlainTextResponse("imu.html 尚未安装", status_code=503)
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    async def status(request: Request):
        if not valid_origin(request.headers.get("origin"), port):
            return PlainTextResponse("Local origin required", status_code=403)
        data = service.get_status()
        data["control_token"] = control_token
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    async def control(request: Request):
        if (request.client is None or not is_loopback(request.client.host)
                or not valid_origin(request.headers.get("origin"), port)
                or not secrets.compare_digest(request.headers.get("x-imu-control-token", ""), control_token)):
            return PlainTextResponse("Local control token required", status_code=403)
        try:
            if request.url.path.endswith("/reconnect"):
                await asyncio.to_thread(service.reconnect)
            else:
                await asyncio.to_thread(service.disconnect)
        except Exception as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=409)
        return JSONResponse({"ok": True})

    async def asset(request: Request):
        base = (ROOT / request.path_params["kind"]).resolve()
        path = (base / request.path_params["path"]).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(path)

    async def socket(websocket: WebSocket):
        if (websocket.client is None or not is_loopback(websocket.client.host)
                or not valid_origin(websocket.headers.get("origin"), port)):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def receive_close():
            # Commands from clients are deliberately not interpreted.
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return

        closed = asyncio.create_task(receive_close())
        try:
            while not closed.done():
                await websocket.send_json(service.get_status())
                await asyncio.sleep(0.05)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            closed.cancel()
            await asyncio.gather(closed, return_exceptions=True)

    # Explicit mounts keep file serving confined to public directories.
    async def model(request: Request):
        request.path_params["kind"] = "model"
        return await asset(request)

    async def vendor(request: Request):
        request.path_params["kind"] = "vendor"
        return await asset(request)

    routes = [Route("/", home), Route("/imu.html", home), Route("/api/status", status),
              Route("/model/{path:path}", model), Route("/vendor/{path:path}", vendor),
              Route("/api/reconnect", control, methods=["POST"]),
              Route("/api/disconnect", control, methods=["POST"]),
              WebSocketRoute("/ws/imu", socket)]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    return app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="IMU → 3D 鸭子（本机观测工具）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--demo", action="store_true", help="只用合成数据，不打开探针")
    parser.add_argument("--resume", action="store_true", help="固件验证后允许显式 Go 恢复暂停的 CPU；SDK 连接仍可能影响运行状态")
    parser.add_argument("--dll", type=Path, help="真板模式必填：本机安装的 JLink_x64.dll 路径")
    parser.add_argument("--firmware", type=Path, default=DEFAULT_FIRMWARE)
    parser.add_argument("--map", dest="map_file", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--probe-serial", type=int, help="真板模式必填：你的 J-Link 正整数序列号")
    parser.add_argument("--hz", type=float, default=20.0)
    args = parser.parse_args(argv)
    if not is_loopback(args.host):
        parser.error("只允许绑定 127.0.0.1 / localhost / ::1。")
    if not 1 <= args.port <= 65535:
        parser.error("端口范围为 1–65535。")
    if not args.demo:
        try:
            args.dll, args.probe_serial = validate_probe_settings(args.dll, args.probe_serial)
        except BridgeError as exc:
            parser.error(str(exc))
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = BridgeService(demo=args.demo, resume=args.resume, dll_path=args.dll,
                            firmware=args.firmware, map_file=args.map_file,
                            serial=args.probe_serial, hz=args.hz)
    uvicorn.run(create_app(service, args.port), host=args.host, port=args.port, workers=1,
                access_log=False, ws_max_size=4096)


if __name__ == "__main__":
    main()
