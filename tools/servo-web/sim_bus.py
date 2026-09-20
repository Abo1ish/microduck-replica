# -*- coding: utf-8 -*-
"""协议级的 HD-1910 模拟器：假装是一个串口，收飞特指令包、按寄存器表回应答包。

跟 server.py 里的 FakeBus 不一样：FakeBus 模拟的是高层接口，测不到 feetech.py；
这个让真实的 FeetechBus 对着它收发字节，包格式、校验和、同步读写、锁、扭矩、中位校准的前提条件都按真机来。

  bus = feetech.FeetechBus(None, ser=SimSerial([20, 21, ...]))

模拟的真机行为（有出处的）：
- 扭矩开关写 128：HD-1910（固件 3.46）回「成功」但什么都不做（2026-09-20 实测 4 轮，解锁、扭矩关着也一样；
  协议手册里 HLS ≥3.43 也不支持）。accept_128=True 时按 STS 的规矩：锁标志 = 0 且扭矩开关 = 0 才校准
- 0x0B 位置校准：当前位置的读数改成参数值（没参数 = 2048）。support_0b=False 模拟不认这条指令的舵机
- 寄存器表到 86 为止，读过头只回剩下的字节（真机实测：读 80 起 10 个回 7 个）
- 位置、速度、电流第 15 位是符号位；偏移寄存器 31 同样按第 15 位记符号（真机读到过 34279 = -1511）
- REBOOT (0x08) 不回包
"""
import struct

import feetech

TABLE_END = 87


def enc15(v):
    return (0x8000 | (-v & 0x7FFF)) if v < 0 else (v & 0x7FFF)


class SimServo:
    def __init__(self, sid, phys=2048):
        self.r = bytearray(TABLE_END)
        r = self.r
        r[0], r[1], r[2], r[3], r[4] = 3, 46, 0, 3, 10      # 固件 3.46，END=0 小端
        r[5], r[6], r[8] = sid, 0, 1                        # ID、波特率 1M、应答级别 1
        struct.pack_into("<HH", r, 9, 0, 4095)
        r[13], r[15] = 70, 40
        struct.pack_into("<H", r, 16, 1000)
        r[18], r[21], r[22], r[33] = 52, 32, 32, 4          # 相位 52、P/D 32、模式 4
        struct.pack_into("<H", r, 48, 1000)
        r[55] = 1                                           # 出厂锁着
        r[62], r[63] = 74, 30
        self.phys = phys          # 编码器的物理读数（没加偏移）
        self.off = 0              # 偏移：报告的位置 = phys + off
        self.goal = None
        self.calibrations = 0     # 真正做了几次中位校准，测试用
        self.muted = set()        # 读这些地址不回包，模拟中途掉线
        self.accept_128 = False   # HD-1910 不认 128
        self.support_0b = True
        self.mute_after_calib = set()   # 校准一做完就把这些地址加进 muted

    @property
    def id(self):
        return self.r[5]

    def pos(self):
        return self.phys + self.off

    def tick(self):
        """扭矩开着就直接走到目标（模拟器不管动力学）。"""
        if self.r[40] == 1 and self.goal is not None:
            self.phys = self.goal - self.off
        p = self.pos()
        struct.pack_into("<H", self.r, 56, enc15(p))
        struct.pack_into("<H", self.r, 67, enc15(self.goal if self.goal is not None else p))
        struct.pack_into("<H", self.r, 31, enc15(self.off))

    def write(self, addr, data):
        for k, b in enumerate(data):
            a = addr + k
            if a >= TABLE_END:
                break
            if a == 40 and b == 128:
                if self.accept_128 and self.r[40] == 0 and self.r[55] == 0:
                    self.recalibrate(2048)
                continue                                     # 回成功，什么都不做
            self.r[a] = b
        # 多字节寄存器落地
        if addr <= 42 < addr + len(data):
            self.goal = feetech.sign15(struct.unpack_from("<H", self.r, 42)[0])
        if addr <= 31 < addr + len(data):
            self.off = feetech.sign15(struct.unpack_from("<H", self.r, 31)[0])
        if addr <= 40 < addr + len(data) and self.r[40] == 1 and self.goal is None:
            self.goal = self.pos()

    def recalibrate(self, value):
        self.off = value - self.phys
        self.calibrations += 1
        self.muted |= self.mute_after_calib

    def read(self, addr, n):
        self.tick()
        return bytes(self.r[addr:min(addr + n, TABLE_END)])


class SimSerial:
    """假串口：write() 收指令，按总线上的舵机生成应答；read() 把应答吐出来。"""

    def __init__(self, ids, phys=None):
        self.timeout = 0.02
        self.servos = {i: SimServo(i, (phys or {}).get(i, 2048)) for i in ids}
        self.rx = bytearray()

    # ---- 串口接口 ----
    def reset_input_buffer(self):
        self.rx.clear()

    def read(self, n=1):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def close(self):
        pass

    def write(self, data):
        data = bytes(data)
        while len(data) >= 6:
            if data[0] != 0xFF or data[1] != 0xFF:
                data = data[1:]
                continue
            sid, length = data[2], data[3]
            pkt = data[:4 + length]
            data = data[4 + length:]
            instr, params = pkt[4], pkt[5:-1]
            if ((~sum(pkt[2:-1])) & 0xFF) != pkt[-1]:
                continue                                         # 校验错：真舵机不理
            self._handle(sid, instr, params)
        return len(data)

    # ---- 舵机 ----
    def _by_id(self, sid):
        for s in self.servos.values():
            if s.id == sid:
                return s
        return None

    def _reply(self, s, params=b""):
        s.tick()
        err = s.r[65]
        length = len(params) + 2
        body = bytes([s.id, length, err]) + bytes(params)
        self.rx += bytes([0xFF, 0xFF]) + body + bytes([(~sum(body)) & 0xFF])

    def _handle(self, sid, instr, p):
        if instr == feetech.SYNC_WRITE:
            addr, ln = p[0], p[1]
            rest = p[2:]
            for k in range(0, len(rest), ln + 1):
                s = self._by_id(rest[k])
                if s:
                    s.write(addr, rest[k + 1:k + 1 + ln])
            return
        if instr == feetech.SYNC_READ:
            addr, ln = p[0], p[1]
            for i in p[2:]:
                s = self._by_id(i)
                if s:
                    self._reply(s, s.read(addr, ln))
            return
        s = self._by_id(sid)
        if s is None:
            return
        if instr == feetech.PING:
            self._reply(s)
        elif instr == feetech.READ:
            if p[0] in s.muted:
                return
            self._reply(s, s.read(p[0], p[1]))
        elif instr == feetech.WRITE:
            s.write(p[0], p[1:])
            self._reply(s)                                       # 改 ID 时用新 ID 回
        elif instr == feetech.CALIBRATE:
            if s.support_0b:
                s.recalibrate(2048 if len(p) < 2 else feetech.sign15(p[0] | p[1] << 8))
            self._reply(s)
        elif instr == feetech.REBOOT:
            s.r[40] = 0                                          # 不回包，回来时扭矩关
