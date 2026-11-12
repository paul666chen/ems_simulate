"""IEC104 客户端遥控命令阶段（预置 / 执行 / 自动）测试。

用一个假 RTU（裸 socket）接收真实 ``IEC104Client`` 发出的命令帧，
直接断言报文里命令信息体末字节的 S/E 位，确保：

- ``select``  只发一条 S/E=1 的预置命令；
- ``execute`` 只发一条 S/E=0 的执行命令；
- ``auto``    跟随点自身的命令传输模式（默认 DIRECT，只发执行命令）；
- 先 ``select`` 再 ``execute`` 可拼出标准的「预置-执行」两步流程。
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import c104
import pytest

from src.proto.iec104.iec104client import IEC104Client, supports_command_stage
from src.proto.iec104.iec104server import IEC104_COMMAND_MODE_SELECT_AND_EXECUTE, IEC104Server

CA = 1
IOA = 1001
POINT_TYPE = c104.Type.C_DC_NA_1

FRAME_STARTDT_ACT = bytes.fromhex("680407000000")
FRAME_STARTDT_CON = bytes.fromhex("68040b000000")
FRAME_TESTFR_CON = bytes.fromhex("680483000000")

COT_ACTIVATION = 0x06
COT_ACTIVATION_CON = 0x07
COT_ACTIVATION_TERM = 0x0A


def _split_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """按 0x68 起始符和长度字节切分 APDU，返回 (完整帧, 残留)。"""
    frames: list[bytes] = []
    while len(buffer) >= 2 and buffer[0] == 0x68:
        length = buffer[1] + 2
        if len(buffer) < length:
            break
        frames.append(buffer[:length])
        buffer = buffer[length:]
    return frames, buffer


class _FakeRtu:
    """极简 RTU：响应 STARTDT，对激活命令回肯定确认（可选补发激活终止）。"""

    def __init__(self) -> None:
        self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen.bind(("127.0.0.1", 0))
        self._listen.listen(1)
        self.port = self._listen.getsockname()[1]
        self.commands: list[bytes] = []  # 收到的命令 ASDU
        self.send_termination = True  # 是否在确认后补发 ACT_TERM
        self.reply_cot = COT_ACTIVATION_CON  # 确认报文的原因码
        self._conn: socket.socket | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    # -- 内部 -------------------------------------------------------------
    def _serve(self) -> None:
        try:
            self._conn, _ = self._listen.accept()
        except OSError:
            return
        self._conn.settimeout(0.2)
        buffer = b""
        recv_seq = 0
        send_seq = 0
        while not self._stop.is_set():
            try:
                data = self._conn.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if not data:
                break
            buffer += data
            frames, buffer = _split_frames(buffer)
            for frame in frames:
                ctrl = frame[2]
                if ctrl & 0x03 == 0x03:  # U 帧
                    if ctrl == 0x07:
                        self._send(FRAME_STARTDT_CON)
                    elif ctrl == 0x43:
                        self._send(FRAME_TESTFR_CON)
                    continue
                if ctrl & 0x01:  # S 帧：仅确认，无需处理
                    continue
                recv_seq += 1
                asdu = frame[6:]
                self.commands.append(asdu)
                if len(asdu) >= 10 and asdu[2] & 0x3F == COT_ACTIVATION:
                    reply = self._confirmation(asdu, self.reply_cot)
                    self._send(self._i_frame(reply, send_seq, recv_seq))
                    send_seq += 1
                    # 真实设备只对执行命令（S/E=0）补发激活终止，预置只回激活确认
                    if self.send_termination and not asdu[-1] & 0x80:
                        termination = self._confirmation(asdu, COT_ACTIVATION_TERM)
                        self._send(self._i_frame(termination, send_seq, recv_seq))
                        send_seq += 1

    @staticmethod
    def _confirmation(asdu: bytes, cot: int) -> bytes:
        """构造确认/终止 ASDU：类型、CA、IOA、信息体原样回显，只改 COT。"""
        reply = bytearray(asdu)
        reply[2] = cot
        return bytes(reply)

    @staticmethod
    def _i_frame(asdu: bytes, send_seq: int, recv_seq: int) -> bytes:
        apci = bytes(
            [
                0x68,
                len(asdu) + 4,
                (send_seq << 1) & 0xFF,
                (send_seq << 1) >> 8,
                (recv_seq << 1) & 0xFF,
                (recv_seq << 1) >> 8,
            ]
        )
        return apci + asdu

    def _send(self, frame: bytes) -> None:
        if self._conn is None:
            return
        try:
            self._conn.sendall(frame)
        except OSError:
            pass

    # -- 外部 -------------------------------------------------------------
    def close(self) -> None:
        self._stop.set()
        for sock in (self._conn, self._listen):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._thread.join(timeout=2)


@pytest.fixture
def rtu_and_client():
    if not supports_command_stage():
        pytest.skip("当前 c104 版本不支持 transmit(stage=...)")

    rtu = _FakeRtu()
    client = IEC104Client(
        ip="127.0.0.1",
        port=rtu.port,
        connection_timeout=3,
        message_timeout=5,
        general_interrogation_on_connect=False,
    )
    assert asyncio.run(client.connect(timeout=3)), "客户端连接假 RTU 失败"
    client.add_point(io_address=IOA, point_type=POINT_TYPE, common_address=CA)

    yield rtu, client

    client.disconnect()
    rtu.close()


def _wait_commands(rtu: _FakeRtu, expected: int, timeout: float = 3.0) -> list[bytes]:
    deadline = time.time() + timeout
    while time.time() < deadline and len(rtu.commands) < expected:
        time.sleep(0.05)
    return list(rtu.commands)


def _se_bits(commands: list[bytes]) -> list[bool]:
    """取每条命令信息体末字节（DCO）的 S/E 位。"""
    return [bool(asdu[-1] & 0x80) for asdu in commands]


def _states(commands: list[bytes]) -> list[int]:
    """取每条命令的信息体低 2 位（双点遥控状态：1=分, 2=合）。"""
    return [asdu[-1] & 0x03 for asdu in commands]


def test_client_select_only_sends_select_command(rtu_and_client):
    rtu, client = rtu_and_client

    assert client.write_point(IOA, True, frame_type=2, common_address=CA, command_stage="select")

    commands = _wait_commands(rtu, 1)
    assert len(commands) == 1
    assert commands[0][2] == COT_ACTIVATION
    assert _se_bits(commands) == [True]  # S/E=1 预置
    assert _states(commands) == [2]  # 合


def test_client_execute_only_sends_execute_command(rtu_and_client):
    rtu, client = rtu_and_client

    assert client.write_point(IOA, True, frame_type=2, common_address=CA, command_stage="execute")

    commands = _wait_commands(rtu, 1)
    assert len(commands) == 1
    assert _se_bits(commands) == [False]  # S/E=0 执行
    assert _states(commands) == [2]


def test_client_select_then_execute_forms_standard_sequence(rtu_and_client):
    rtu, client = rtu_and_client

    assert client.write_point(IOA, True, frame_type=2, common_address=CA, command_stage="select")
    _wait_commands(rtu, 1)
    assert client.write_point(IOA, True, frame_type=2, common_address=CA, command_stage="execute")

    commands = _wait_commands(rtu, 2)
    assert len(commands) == 2
    assert _se_bits(commands) == [True, False]
    assert _states(commands) == [2, 2]


def test_client_auto_stage_follows_direct_mode(rtu_and_client):
    rtu, client = rtu_and_client

    # 未显式指定阶段时走 point 自身的命令传输模式（客户端默认 DIRECT）
    assert client.write_point(IOA, False, frame_type=2, common_address=CA)

    commands = _wait_commands(rtu, 1)
    assert _se_bits(commands) == [False]
    assert _states(commands) == [1]  # 分


def test_client_auto_stage_follows_select_and_execute_mode(rtu_and_client):
    rtu, client = rtu_and_client
    point = client.stations[CA].get_point(io_address=IOA)
    point.command_mode = c104.CommandMode.SELECT_AND_EXECUTE

    # 未显式指定阶段时跟随点模式：先预置(S/E=1)再执行(S/E=0)
    assert client.write_point(IOA, True, frame_type=2, common_address=CA)

    commands = _wait_commands(rtu, 2)
    assert len(commands) == 2
    assert _se_bits(commands) == [True, False]
    assert _states(commands) == [2, 2]


def test_select_then_execute_accepted_by_ems_server():
    """端到端：本系统服务端（预置-执行模式）能接受分两步发来的预置与执行命令。"""
    if not supports_command_stage():
        pytest.skip("当前 c104 版本不支持 transmit(stage=...)")

    server = IEC104Server(ip="127.0.0.1", port=_free_port(), command_mode=IEC104_COMMAND_MODE_SELECT_AND_EXECUTE)
    server.add_command_point(io_address=IOA, point_type=POINT_TYPE, common_address=CA)
    server.start()
    client = IEC104Client(
        ip="127.0.0.1",
        port=server.port,
        connection_timeout=3,
        message_timeout=5,
        general_interrogation_on_connect=False,
    )
    try:
        assert asyncio.run(client.connect(timeout=3))
        client.add_point(io_address=IOA, point_type=POINT_TYPE, common_address=CA)

        assert client.write_point(IOA, True, frame_type=2, common_address=CA, command_stage="select")
        assert client.write_point(IOA, True, frame_type=2, common_address=CA, command_stage="execute")

        deadline = time.time() + 3
        value = server.get_point_value(IOA, frame_type=2, common_address=CA)
        while time.time() < deadline and not value:
            time.sleep(0.05)
            value = server.get_point_value(IOA, frame_type=2, common_address=CA)
        assert bool(value) is True
    finally:
        client.disconnect()
        server.stop()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
