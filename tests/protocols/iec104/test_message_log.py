"""IEC104 报文文件日志测试

覆盖：解析摘要内容、命令值附带原始字节、开关生效、异常报文不抛出。
"""

import pytest

from src.config.config import Config
from src.proto.iec104 import message_log

# C_DC_NA_1 双点遥控激活：CA=257, IOA=24577, DCO=0x82（合 + 选择）
CMD_ACTIVATION = bytes.fromhex("680e160022002e010600010101600082")
# 同一命令的否定激活确认 COT=0x47
CMD_ACTIVATION_CON_NEG = bytes.fromhex("680e220018002e014700010101600082")
# 未知类型标识（否定）COT=0x6C
CMD_UNKNOWN_TYPE = bytes.fromhex("680e240018002e016c00010101600082")
TESTFR_ACT = bytes.fromhex("680443000000")
S_FRAME = bytes.fromhex("680401000600")


def test_summarize_command_frame():
    summary = message_log.summarize(CMD_ACTIVATION)
    assert "C_DC_NA_1" in summary
    assert "COT=6 激活" in summary
    assert "CA=257" in summary
    assert "IOA=24577" in summary
    # 命令解码值会丢掉 SE/QU 位，摘要需保留原始字节
    assert "82" in summary


def test_summarize_negative_confirmation():
    summary = message_log.summarize(CMD_ACTIVATION_CON_NEG)
    assert "COT=7 激活确认，否定" in summary


def test_summarize_unknown_type_cot_name():
    summary = message_log.summarize(CMD_UNKNOWN_TYPE)
    assert "COT=44 未知类型标识，否定" in summary


def test_summarize_u_and_s_frames():
    assert "TESTFR_ACT" in message_log.summarize(TESTFR_ACT)
    assert "S格式" in message_log.summarize(S_FRAME)


def test_summarize_invalid_frame_does_not_raise():
    summary = message_log.summarize(bytes.fromhex("6801"))
    assert summary


def test_log_frame_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(message_log.log, "logger", _RecordingLogger())
    monkeypatch.setattr(Config, "message_log_iec104", True)
    monkeypatch.delenv("EMS_IEC104_MESSAGE_LOG", raising=False)

    message_log.log_frame("RX", CMD_ACTIVATION, "pcs 客户端→192.168.3.24:2404")

    assert len(message_log.log.logger.messages) == 1
    line = message_log.log.logger.messages[0]
    assert line.startswith("RX pcs 客户端→192.168.3.24:2404 |")
    assert line.endswith(CMD_ACTIVATION.hex(" "))


def test_log_frame_respects_switch(monkeypatch):
    monkeypatch.setattr(message_log.log, "logger", _RecordingLogger())
    monkeypatch.setattr(Config, "message_log_iec104", False)

    message_log.log_frame("RX", TESTFR_ACT, "pcs")

    assert message_log.log.logger.messages == []


class _RecordingLogger:
    """替代 loguru logger，记录调用而不落盘。"""

    def __init__(self):
        self.messages: list[str] = []

    def info(self, message, *args, **kwargs):
        self.messages.append(message)


@pytest.fixture(autouse=True)
def _restore_config():
    original = Config.message_log_iec104
    yield
    Config.message_log_iec104 = original
