"""Modbus 服务端 handler 绑定地址接线测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.config.config import Config
from src.device.protocol.modbus_handler import ModbusServerHandler
from src.enums.modbus_def import ProtocolType


def test_modbus_server_handler_initialize_passes_ip():
    handler = ModbusServerHandler(log=SimpleNamespace(info=lambda *a, **k: None))
    fake_server = MagicMock()
    fake_server.ip = None

    with patch("src.proto.pyModbus.server.ModbusServer", return_value=fake_server) as ctor:
        handler.initialize(
            {
                "ip": "127.0.0.2",
                "port": 15502,
                "slave_id_list": [1],
                "protocol_type": ProtocolType.ModbusTcpServer,
                "security": {},
                "runtime": {},
            }
        )

    assert ctor.call_args.kwargs["ip"] == "127.0.0.2"
    assert ctor.call_args.kwargs["port"] == 15502
    assert handler._server is fake_server


def test_modbus_server_handler_initialize_defaults_ip():
    handler = ModbusServerHandler(log=SimpleNamespace(info=lambda *a, **k: None))
    fake_server = MagicMock()

    with patch("src.proto.pyModbus.server.ModbusServer", return_value=fake_server) as ctor:
        handler.initialize(
            {
                "ip": "",
                "port": 502,
                "slave_id_list": [1],
                "protocol_type": ProtocolType.ModbusTcpServer,
                "security": {},
                "runtime": {},
            }
        )

    assert ctor.call_args.kwargs["ip"] == Config.DEFAULT_IP
