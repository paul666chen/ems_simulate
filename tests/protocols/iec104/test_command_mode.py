"""IEC104 服务端遥控命令传输模式（DIRECT / SELECT_AND_EXECUTE）测试。"""

from __future__ import annotations

import socket
import time

import c104
import pytest

from src.proto.iec104.iec104server import (
    IEC104_COMMAND_MODE_DIRECT,
    IEC104_COMMAND_MODE_SELECT_AND_EXECUTE,
    IEC104Server,
    normalize_command_mode,
    parse_select_command,
)

IOA = 24579
CA = 1
FRAME_SELECT = bytes.fromhex("680e0400ec012e010600010003600082")  # C_DC_NA_1 激活 + DCO=0x82(SE=1)
FRAME_EXECUTE = bytes.fromhex("680e0400ec012e010600010003600002")


def test_parse_select_command_recognizes_select_command():
    assert parse_select_command(FRAME_SELECT) == (CA, IOA)


def test_parse_select_command_ignores_execute_and_other_frames():
    assert parse_select_command(FRAME_EXECUTE) is None  # SE=0
    assert parse_select_command(bytes.fromhex("680443000000")) is None  # U 帧
    # 45(C_SC_NA_1 单点遥控) 同样支持选择/执行语义
    assert parse_select_command(bytes.fromhex("680e0400ec012d010600010003600082")) == (CA, IOA)
    # 100(C_IC_NA_1 总召唤) 不属于命令类，不参与选择/执行判定
    assert parse_select_command(bytes.fromhex("680e0400ec0164010600010003600082")) is None
    assert parse_select_command(bytes.fromhex("6801")) is None  # 残帧


def test_parse_select_command_rejects_non_activation_cause():
    frame = bytearray(FRAME_SELECT)
    frame[8] = 0x08  # 停止激活
    assert parse_select_command(bytes(frame)) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("direct", "direct"),
        ("SELECT_AND_EXECUTE", "select_and_execute"),
        (" direct ", "direct"),
        ("bogus", "direct"),
        (None, "direct"),
    ],
)
def test_normalize_command_mode(raw, expected):
    assert normalize_command_mode(raw) == expected


class _Master:
    """极简主站：维护收发序号，按 APDU 切帧。"""

    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.send_seq = 0
        self.recv_seq = 0
        self.buffer = b""
        self.sock.sendall(bytes.fromhex("680407000000"))  # STARTDT act
        self.wait(1.0)

    def send_command(self, asdu: bytes) -> None:
        apci = bytes(
            [
                0x68,
                len(asdu) + 4,
                (self.send_seq << 1) & 0xFF,
                (self.send_seq << 1) >> 8,
                (self.recv_seq << 1) & 0xFF,
                (self.recv_seq << 1) >> 8,
            ]
        )
        self.send_seq += 1
        self.sock.sendall(apci + asdu)

    def wait(self, seconds: float = 1.2) -> list[bytes]:
        self.sock.settimeout(0.3)
        frames: list[bytes] = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                data = self.sock.recv(1024)
            except TimeoutError:
                continue
            if not data:
                break
            self.buffer += data
            while len(self.buffer) >= 2 and self.buffer[0] == 0x68:
                length = self.buffer[1] + 2
                if len(self.buffer) < length:
                    break
                frame = self.buffer[:length]
                self.buffer = self.buffer[length:]
                frames.append(frame)
                if not frame[2] & 0x01:  # 服务端发出的 I 帧
                    self.recv_seq += 1
        return frames

    def close(self) -> None:
        self.sock.close()


def _asdu(type_id: int, cot: int, ioa: int, qualifier: int) -> bytes:
    return bytes(
        [
            type_id,
            0x01,
            cot,
            0x00,
            CA & 0xFF,
            CA >> 8,
            ioa & 0xFF,
            (ioa >> 8) & 0xFF,
            (ioa >> 16) & 0xFF,
            qualifier,
        ]
    )


def _causes(frames: list[bytes]) -> list[int]:
    causes: list[int] = []
    for frame in frames:
        if len(frame) >= 10 and not frame[2] & 0x01:  # I 帧
            causes.append(frame[8])
    return causes


@pytest.fixture
def server_factory():
    created: list[IEC104Server] = []
    port_counter = {"value": 42700}

    def _create(command_mode: str) -> tuple[IEC104Server, int]:
        port_counter["value"] += 1
        port = port_counter["value"]
        server = IEC104Server(ip="127.0.0.1", port=port, command_mode=command_mode)
        server.add_command_point(io_address=IOA, point_type=c104.Type.C_DC_NA_1, common_address=CA)
        server.start()
        created.append(server)
        return server, port

    yield _create
    for server in created:
        server.stop()
    time.sleep(0.2)


def test_direct_mode_rejects_select_but_executes(server_factory):
    _, port = server_factory(IEC104_COMMAND_MODE_DIRECT)
    master = _Master(port)
    master.send_command(_asdu(0x2E, 0x06, IOA, 0x82))  # SELECT
    assert _causes(master.wait()) == [0x47]  # 激活确认·否定
    master.send_command(_asdu(0x2E, 0x06, IOA, 0x02))  # EXECUTE
    assert _causes(master.wait()) == [0x07]  # 激活确认·肯定
    master.close()


def test_select_and_execute_mode_accepts_select_then_execute(server_factory):
    _, port = server_factory(IEC104_COMMAND_MODE_SELECT_AND_EXECUTE)
    master = _Master(port)
    master.send_command(_asdu(0x2E, 0x06, IOA, 0x82))  # SELECT
    assert _causes(master.wait()) == [0x07]
    master.send_command(_asdu(0x2E, 0x06, IOA, 0x02))  # EXECUTE
    # 执行成功后 c104 会清理选择记录并补发激活终止(COT=0x0a)
    causes = _causes(master.wait())
    assert 0x07 in causes
    master.close()


def test_select_and_execute_mode_rejects_execute_without_selection(server_factory):
    _, port = server_factory(IEC104_COMMAND_MODE_SELECT_AND_EXECUTE)
    master = _Master(port)
    master.send_command(_asdu(0x2E, 0x06, IOA, 0x02))  # 未选择直接执行
    assert _causes(master.wait()) == [0x47]
    master.close()


def test_set_point_command_mode_switches_at_runtime(server_factory):
    server, port = server_factory(IEC104_COMMAND_MODE_DIRECT)
    master = _Master(port)
    master.send_command(_asdu(0x2E, 0x06, IOA, 0x82))
    assert _causes(master.wait()) == [0x47]

    assert server.set_point_command_mode(IOA, c104.CommandMode.SELECT_AND_EXECUTE, common_address=CA)
    master.send_command(_asdu(0x2E, 0x06, IOA, 0x82))  # 再次选择
    assert _causes(master.wait()) == [0x07]
    master.close()
