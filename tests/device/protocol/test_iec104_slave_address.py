"""IEC104 从机/装置地址变更后协议热重载测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.device.core.device import Device
from src.device.protocol.iec104_handler import IEC104ServerHandler
from src.enums.modbus_def import ProtocolType


def test_reinit_iec104_server_preserves_running_and_applies_new_station():
    """运行中修改公共地址后：旧监听释放，新 Station 生效且仍在运行。"""
    from src.device.protocol.endpoint_check import is_tcp_port_listening

    log = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)
    device = Device()
    device.protocol_type = ProtocolType.Iec104Server
    device.device_id = 99001
    device.ip = "127.0.0.1"
    device.port = 15611
    device.point_manager.slave_id_list = [1]

    handler = IEC104ServerHandler(log=log)
    handler.initialize(
        {
            "ip": "127.0.0.1",
            "port": 15611,
            "slave_id_list": [1],
            "runtime": {},
            "security": {},
        }
    )
    device.protocol_handler = handler
    assert device._start_iec_handler_sync(handler) is True
    assert is_tcp_port_listening("127.0.0.1", 15611)

    try:
        device.point_manager.slave_id_list = [42]
        device._reinit_protocol_for_iec104()

        new_handler = device.protocol_handler
        assert isinstance(new_handler, IEC104ServerHandler)
        assert new_handler.is_running is True
        assert 42 in new_handler.server.stations
        assert 1 not in new_handler.server.stations
        assert is_tcp_port_listening("127.0.0.1", 15611)
    finally:
        if device.protocol_handler:
            device._stop_iec_handler_sync(device.protocol_handler)


def test_slave_manager_iec_allows_common_address_above_255():
    from unittest.mock import patch

    from src.device.core.slave_manager import SlaveManager

    device = MagicMock()
    device.protocol_type = ProtocolType.Iec104Server
    device.device_id = 1
    device.point_manager.slave_id_list = [1]
    device.log = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)
    device.server = None
    device._reinit_protocol_for_iec104 = MagicMock()

    mgr = SlaveManager(device)
    assert mgr._max_slave_id() == 65534

    with patch("src.data.service.slave_service.SlaveService.create_slave", return_value=True):
        ok = mgr.add_slave(1001)
    assert ok is True
    assert 1001 in device.point_manager.slave_id_list
    device._reinit_protocol_for_iec104.assert_called_once()
