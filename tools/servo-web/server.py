# -*- coding: utf-8 -*-
"""飞特舵机网页调试台：串口 + 网页滑块 + 3D 鸭子跟着动。

用法：
  python server.py --port COM5                      # Windows，URT-2
  python server.py --port /dev/ttyUSB0              # 板子上，URT-2 插 USB
  python server.py --port /dev/ttyS2                # 板子上，走半双工转接板（先 sudo systemctl stop robotd）
  python server.py --fake                           # 没舵机，看界面
然后浏览器开 http://<主机>:8080
"""
import argparse
import asyncio
import contextlib
import json
import os
import struct
import time

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

import feetech

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IDS = "20-24,30-34,10-14"
JOINT_NAMES = {
    20: "left_hip_yaw", 21: "left_hip_roll", 22: "left_hip_pitch", 23: "left_knee", 24: "left_ankle",
    30: "neck_pitch", 31: "head_pitch", 32: "head_yaw", 33: "head_roll", 34: "mouth",
    10: "right_hip_yaw", 11: "right_hip_roll", 12: "right_hip_pitch", 13: "right_knee", 14: "right_ankle",
}


def parse_ids(text):
    ids = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            ids += list(range(int(a), int(b) + 1))
        else:
            ids.append(int(part))
    return ids


class FakeBus:
    """没舵机时的替身：位置一阶跟随目标，别的字段编个像样的数。"""

    def __init__(self, ids):
        self.pos = {i: 2048 for i in ids}
        self.goal = {i: 2048 for i in ids}
        self.torque = {i: 0 for i in ids}
        self.stats = {"tx": 0, "rx_ok": 0, "timeout": 0, "bad_checksum": 0, "bad_id": 0}

    def ping(self, sid):
        return 0 if sid in self.pos else None

    def states(self, ids):
        out = {}
        for i in ids:
            if i not in self.pos:
                out[i] = None
                continue
            if self.torque[i]:
                self.pos[i] += int((self.goal[i] - self.pos[i]) * 0.3)
            out[i] = {"err": 0, "pos": self.pos[i], "speed": 0, "load": 0, "volt": 7.9, "temp": 31,
                      "status": 0, "moving": int(abs(self.goal[i] - self.pos[i]) > 2), "goal": self.goal[i],
                      "current_ma": 0.0, "status_text": ""}
        self.stats["tx"] += 1
        self.stats["rx_ok"] += len(ids)
        return out

    def write_u16(self, sid, addr, v):
        if addr == 42:
            self.goal[sid] = v
        return 0

    def write_u8(self, sid, addr, v):
        if addr == 40:
            self.torque[sid] = 1 if v == 1 else 0
        return 0

    def sync_write(self, addr, length, id_values):
        for sid, data in id_values:
            if addr == 42:
                self.goal[sid] = struct.unpack("<H", bytes(data[:2]))[0]
            if addr == 41 and length >= 3:   # 加速度 + 目标位置 + 时间 + 速度
                self.goal[sid] = struct.unpack("<H", bytes(data[1:3]))[0]
            if addr == 40:
                self.torque[sid] = data[0]

    def sync_read(self, ids, addr, n):
        return {i: (0, bytes(n)) if i in self.pos else None for i in ids}

    def dump(self, sid):
        raw = [0] * 91
        raw[5], raw[8], raw[21], raw[22], raw[33], raw[55] = sid, 1, 32, 32, 4, 1
        rows = [{"addr": a, "name": feetech.REGISTERS[a][0], "area": feetech.REGISTERS[a][2],
                 "size": feetech.REGISTERS[a][1], "value": raw[a]} for a in sorted(feetech.REGISTERS)]
        return {"rows": rows, "raw": raw}

    def read(self, sid, addr, n):
        return 0, bytes(n)

    def reboot(self, sid):
        pass

    def unlock(self, sid):
        return 0

    def lock(self, sid):
        return 0

    def set_id(self, old, new):
        self.pos[new] = self.pos.pop(old, 2048)
        self.goal[new] = self.goal.pop(old, 2048)
        self.torque[new] = self.torque.pop(old, 0)
        return True

    def close(self):
        pass


BUS = None
IDS = []
PRESENT = []
CLIENTS = set()
LOG = []
STREAM_HZ = 10
SPEED_UNIT = 1.0   # 速度寄存器 46 一个单位 = 多少步/秒：相位 18 BIT2=1 → 1（0.0146 rpm），BIT2=0 → 50（0.732 rpm）
MAX_SPEED_REG = 3000   # "不限速"写多少：相位 BIT3=1 时 0 = 最快；BIT3=0 时 0 = 停，得写个大数（HD-1910 满速约 3000 步/秒）
STREAM_LAST = {}       # goals_stream 上一帧给每颗的目标，用来算这一帧该多快


def release_speed(ids):
    """把速度上限放开、加速度设最大（41 = 0，46 = MAX_SPEED_REG），目标位置保持当前目标不变。"""
    st = BUS.states(ids)
    items = [(i, bytes([0]) + struct.pack("<H", st[i]["goal"] & 0xFFFF) + struct.pack("<H", 0) + struct.pack("<H", MAX_SPEED_REG))
             for i in ids if st.get(i)]
    if items:
        BUS.sync_write(41, 7, items)


def read_phase():
    """开机读一颗的相位 18，定速度单位和"不限速"的写法；顺手把所有舵机的速度上限放开。"""
    global SPEED_UNIT, MAX_SPEED_REG
    if is_fake() or not PRESENT:
        return
    try:
        ph = BUS.read_u8(PRESENT[0], 18)
        SPEED_UNIT = 1.0 if ph & 0x04 else 50.0
        MAX_SPEED_REG = 0 if ph & 0x08 else int(3000 / SPEED_UNIT)
        log(f"相位 18 = {ph}（BIT2={'1' if ph & 4 else '0'} → 速度单位 {SPEED_UNIT:g} 步/秒；BIT3={'1 速度0=最快' if ph & 8 else '0 速度0=停'} → 不限速写 {MAX_SPEED_REG}）")
        release_speed(PRESENT)
        log("已把全部舵机速度上限放开、加速度设最大")
    except Exception as e:
        log(f"读相位失败，速度单位按 1 步/秒：{e}")


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    LOG.append(line)
    del LOG[:-200]
    print(line, flush=True)
    return line


def is_fake():
    return isinstance(BUS, FakeBus)


async def index(request):
    return FileResponse(os.path.join(HERE, "index.html"))


async def model_file(request):
    name = request.path_params["name"]
    if name not in ("model.json", "meshes.bin"):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = os.path.join(HERE, "model", name)
    if not os.path.exists(path):
        return JSONResponse({"error": "model 目录没生成，跑 build_model.py"}, status_code=404)
    return FileResponse(path)


POSES_DIR = os.path.join(HERE, "poses")


def list_poses():
    out = []
    if os.path.isdir(POSES_DIR):
        for fn in sorted(os.listdir(POSES_DIR)):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(POSES_DIR, fn), encoding="utf-8") as f:
                        p = json.load(f)
                    out.append({"file": fn, "name": p.get("name", fn[:-5]), "time": p.get("time", ""), "note": p.get("note", ""),
                                "goals": {r["id"]: r["pos"] for r in p.get("rows", [])},
                                "steps": p.get("steps")})
                except Exception as e:
                    log(f"pose {fn} 读不了: {e}")
    return out


def save_pose(name):
    st = BUS.states(PRESENT or IDS)
    rows = [{"id": i, "joint": JOINT_NAMES.get(i), "pos": s["pos"], "deg": round((s["pos"] - 2048) * 360 / 4096, 1)}
            for i, s in st.items() if s]
    os.makedirs(POSES_DIR, exist_ok=True)
    safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "pose"
    fn = f"{safe}-{time.strftime('%Y-%m-%d')}.json"
    with open(os.path.join(POSES_DIR, fn), "w", encoding="utf-8") as f:
        json.dump({"name": safe, "time": time.strftime("%Y-%m-%d %H:%M"), "rows": rows}, f, ensure_ascii=False, indent=1)
    log(f"姿态已存 poses/{fn}（{len(rows)} 颗）")
    return fn


async def poses(request):
    return JSONResponse(list_poses())


async def info(request):
    return JSONResponse({"ids": IDS, "present": PRESENT, "names": JOINT_NAMES, "fake": is_fake(),
                         "stats": BUS.stats, "log": LOG[-50:]})


def do_scan(ids):
    global PRESENT
    found = [i for i in ids if BUS.ping(i) is not None]
    PRESENT = found
    log(f"scan {ids[0]}..{ids[-1]}: 在线 {found}")
    return found


def do_timing(n=200):
    """sync_read 全部在线舵机 n 次，看耗时和失败。"""
    ids = PRESENT or IDS
    times, fails = [], 0
    for _ in range(n):
        t = time.perf_counter()
        r = BUS.sync_read(ids, 56, 15)
        times.append((time.perf_counter() - t) * 1000)
        fails += sum(1 for v in r.values() if v is None)
    times.sort()
    res = {"n": n, "ids": len(ids), "min_ms": round(times[0], 2), "avg_ms": round(sum(times) / n, 2),
           "p99_ms": round(times[max(0, int(n * 0.99) - 1)], 2), "max_ms": round(times[-1], 2), "fails": fails,
           "stats": dict(BUS.stats)}
    log(f"timing: {res}")
    return res


def handle(cmd):
    """WebSocket 指令，同步执行（在线程里跑）。返回要回给前端的 dict 或 None。"""
    op = cmd.get("op")
    if op == "goal":
        BUS.write_u16(int(cmd["id"]), 42, int(cmd["pos"]) & 0xFFFF)
    elif op == "goals":  # {id: pos}
        items = [(int(i), struct.pack("<H", int(p) & 0xFFFF)) for i, p in cmd["goals"].items()]
        BUS.sync_write(42, 2, items)
    elif op == "goals_stream":
        # 连续流：每帧给目标位置，同时把速度上限设成"正好在 dt 内走到"，加速度最大。
        # 舵机就以匹配的速度连续走，不会每帧冲一下停一下。结束时发 stream_end 放开速度。
        dt = max(0.01, float(cmd.get("dt", 0.05)))
        want = {int(i): int(p) & 0xFFFF for i, p in cmd["goals"].items()}
        fresh = [i for i in want if i not in STREAM_LAST]
        if fresh:
            st = BUS.states(fresh)
            for i in fresh:
                STREAM_LAST[i] = (st[i]["pos"] & 0xFFFF) if st.get(i) else want[i]
        items = []
        for i, p in want.items():
            sps = abs(p - STREAM_LAST[i]) / dt * 1.2          # 留 20% 余量，宁可早到一点
            reg = max(3, min(32767, int(round(sps / SPEED_UNIT))))
            items.append((i, bytes([0]) + struct.pack("<H", p) + struct.pack("<H", 0) + struct.pack("<H", reg)))
            STREAM_LAST[i] = p
        BUS.sync_write(41, 7, items)
    elif op == "stream_end":
        ids = [int(i) for i in cmd.get("ids", [])] or list(STREAM_LAST)
        if ids:
            release_speed(ids)
        for i in ids:
            STREAM_LAST.pop(i, None)
    elif op == "goals_profile":
        # 平滑运动：一次写 41..47 = 加速度(1) 目标位置(2) 时间(2)=0 速度(2)，舵机自己走梯形曲线到终点。
        # 速度按 |终点-当前| / 秒数 算，单位由相位 BIT2 定（SPEED_UNIT 步/秒 每单位）。
        # 发完立刻返回，不在这里等——等的话会把后面的指令（比如灵动的头部流）全堵住。页面等完自己发 goals_verify 和 release。
        seconds = max(0.2, float(cmd.get("seconds", 2)))
        acc = max(1, min(254, int(cmd.get("acc", 30))))
        want = {int(i): int(p) & 0xFFFF for i, p in cmd["goals"].items()}
        st = BUS.states(list(want))
        items, speeds = [], {}
        for i, p in want.items():
            cur = (st[i]["pos"] if st.get(i) else p) & 0xFFFF
            sps = abs(p - cur) / seconds                       # 步/秒
            reg = max(1, min(32767, int(round(sps / SPEED_UNIT)))) if sps > 0 else 1
            speeds[i] = reg
            items.append((i, bytes([acc]) + struct.pack("<H", p) + struct.pack("<H", 0) + struct.pack("<H", reg)))
        BUS.sync_write(41, 7, items)
        for i in want:
            STREAM_LAST.pop(i, None)
        log(f"profile {seconds}s acc={acc} 速度单位={SPEED_UNIT:g}步/s → " + " ".join(f"{i}:{want[i]}@{speeds[i]}" for i in want))
    elif op == "release":
        ids = [int(i) for i in cmd.get("ids", [])] or (PRESENT or IDS)
        release_speed(ids)
        for i in ids:
            STREAM_LAST.pop(i, None)
    elif op == "goals_verify":  # 同上，但回读舵机里的目标位置，没收到的重发，最多 4 轮
        want = {int(i): int(p) & 0xFFFF for i, p in cmd["goals"].items()}
        for attempt in range(4):
            BUS.sync_write(42, 2, [(i, struct.pack("<H", p)) for i, p in want.items()])
            time.sleep(0.02)
            st = BUS.states(list(want))
            want = {i: p for i, p in want.items() if not st.get(i) or (st[i]["goal"] & 0xFFFF) != p}
            if not want:
                break
        if want:
            log(f"goals_verify: {len(want)} 颗 4 轮后目标仍没写进去 {sorted(want)}")
        return {"type": "goals_verify", "missing": sorted(want), "attempts": attempt + 1}
    elif op == "torque":
        if cmd.get("ids"):
            ids = [int(i) for i in cmd["ids"]]
        else:
            ids = [int(cmd["id"])] if cmd.get("id") is not None else (PRESENT or IDS)
        BUS.sync_write(40, 1, [(i, bytes([int(cmd["on"])])) for i in ids])
        log(f"torque {int(cmd['on'])} -> {ids}")
    elif op == "scan":
        return {"type": "scan", "present": do_scan(parse_ids(cmd.get("ids") or DEFAULT_IDS))}
    elif op == "scan_all":
        return {"type": "scan", "present": do_scan(list(range(0, 254)))}
    elif op == "dump":
        sid = int(cmd["id"])
        d = BUS.dump(sid)
        r = d["raw"]
        log(f"dump id {sid}: 固件 {r[0]}.{r[1]} 舵机 {r[3]}.{r[4]} END={r[2]} 模式={r[33]} 相位={r[18]} "
            f"P/D/I={r[21]}/{r[22]}/{r[23]} 锁={r[55]} 应答级别={r[8]}")
        return {"type": "dump", "id": sid, **d}
    elif op == "write_reg":
        sid, addr, size, val = int(cmd["id"]), int(cmd["addr"]), int(cmd.get("size", 1)), int(cmd["value"])
        if cmd.get("unlock"):
            BUS.unlock(sid)
        (BUS.write_u8 if size == 1 else BUS.write_u16)(sid, addr, val)
        if cmd.get("unlock"):
            BUS.lock(sid)
        log(f"write id {sid} addr {addr} = {val}" + ("（解锁写入）" if cmd.get("unlock") else ""))
    elif op == "reboot":
        sid = int(cmd["id"])
        BUS.write_u8(sid, 40, 0)
        BUS.reboot(sid)
        log(f"reboot 0x08 -> id {sid}")
    elif op == "calibrate":
        sid = int(cmd["id"])
        BUS.write_u8(sid, 40, 128)
        log(f"中位校准（40 写 128）-> id {sid}")
    elif op == "set_id":
        ok = BUS.set_id(int(cmd["old"]), int(cmd["new"]))
        log(f"set_id {cmd['old']} -> {cmd['new']}: {'ok' if ok else 'ping 不通'}")
        return {"type": "scan", "present": do_scan(IDS)}
    elif op == "timing":
        return {"type": "timing", **do_timing(int(cmd.get("n", 200)))}
    elif op == "log":
        return {"type": "log", "lines": LOG[-50:]}
    elif op == "save_pose":
        save_pose(str(cmd.get("name") or "pose"))
        return {"type": "poses", "poses": list_poses()}
    elif op == "poses":
        return {"type": "poses", "poses": list_poses()}
    else:
        log(f"未知指令 {cmd}")
    return None


async def stream():
    """按 STREAM_HZ 广播全部舵机状态。"""
    while True:
        t0 = time.monotonic()
        if CLIENTS and PRESENT:
            try:
                st = await asyncio.to_thread(BUS.states, PRESENT)
                msg = json.dumps({"type": "state", "t": time.time(), "states": st, "stats": BUS.stats})
                for ws in list(CLIENTS):
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        CLIENTS.discard(ws)
            except Exception as e:
                log(f"stream error: {e}")
        await asyncio.sleep(max(0.0, 1.0 / STREAM_HZ - (time.monotonic() - t0)))


async def ws_endpoint(ws):
    await ws.accept()
    CLIENTS.add(ws)
    await ws.send_text(json.dumps({"type": "hello", "ids": IDS, "present": PRESENT, "names": JOINT_NAMES,
                                   "fake": is_fake(), "log": LOG[-50:]}))
    try:
        while True:
            cmd = json.loads(await ws.receive_text())
            try:
                reply = await asyncio.to_thread(handle, cmd)
            except Exception as e:
                reply = {"type": "error", "msg": f"{cmd.get('op')}: {e}"}
                log(reply["msg"])
            if reply:
                await ws.send_text(json.dumps(reply))
    except WebSocketDisconnect:
        pass
    finally:
        CLIENTS.discard(ws)


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(stream())
    yield
    task.cancel()


app = Starlette(routes=[
    Route("/", index),
    Route("/api/info", info),
    Route("/api/poses", poses),
    Route("/model/{name}", model_file),
    WebSocketRoute("/ws", ws_endpoint),
], lifespan=lifespan)


def main():
    global BUS, IDS, PRESENT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="串口，如 COM5 / /dev/ttyUSB0 / /dev/ttyS2")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--ids", default=DEFAULT_IDS, help="要管的 ID，如 20-24,30-34,10-14")
    ap.add_argument("--fake", action="store_true", help="不接舵机，界面演示")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--http-port", type=int, default=8080)
    a = ap.parse_args()
    IDS = parse_ids(a.ids)
    if a.fake or not a.port:
        BUS = FakeBus(IDS)
        PRESENT = list(IDS)
        log("假总线模式（--fake 或没给 --port）")
    else:
        BUS = feetech.FeetechBus(a.port, a.baud)
        log(f"串口 {a.port} @ {a.baud}")
        do_scan(IDS)
        read_phase()
    print(f"浏览器开 http://127.0.0.1:{a.http_port}  （局域网用本机 IP）", flush=True)
    uvicorn.run(app, host=a.host, port=a.http_port, log_level="warning")


if __name__ == "__main__":
    main()
