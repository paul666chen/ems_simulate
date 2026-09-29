"""TCP 服务端绑定端点预检与装配透传的单元测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.config import Config
from src.device.protocol.endpoint_check import check_tcp_endpoint
from src.enums.modbus_def import ProtocolType
from src.web.api.channel.helpers import configure_builder_network, resolve_bind_ip


def test_resolve_bind_ip_empty_falls_back_to_default():
    assert resolve_bind_ip(None) == Config.DEFAULT_IP
    assert resolve_bind_ip("") == Config.DEFAULT_IP
    assert resolve_bind_ip("  ") == Config.DEFAULT_IP
    assert resolve_bind_ip("192.168.1.10") == "192.168.1.10"


def test_configure_builder_network_passes_server_bind_ip():
    builder = MagicMock()
    configure_builder_network(
        builder,
        conn_type=2,
        protocol_type=ProtocolType.ModbusTcpServer,
        ip="127.0.0.1",
        port=15502,
        channel_data={"protocol_type": 1, "conn_type": 2},
    )
    builder.setDeviceNetConfig.assert_called_once_with(port=15502, ip="127.0.0.1")


def test_configure_builder_network_server_empty_ip_defaults():
    builder = MagicMock()
    configure_builder_network(
        builder,
        conn_type=2,
        protocol_type=ProtocolType.Iec104Server,
        ip="",
        port=2404,
        channel_data={"protocol_type": 2, "conn_type": 2},
    )
    builder.setDeviceNetConfig.assert_called_once_with(port=2404, ip=Config.DEFAULT_IP)


def test_configure_builder_network_client_keeps_remote_ip():
    builder = MagicMock()
    configure_builder_network(
        builder,
        conn_type=1,
        protocol_type=ProtocolType.ModbusTcpClient,
        ip="10.0.0.5",
        port=502,
        channel_data={"protocol_type": 1, "conn_type": 1},
    )
    builder.setDeviceNetConfig.assert_called_once_with(port=502, ip="10.0.0.5")


def test_check_tcp_endpoint_rejects_invalid_port():
    ok, reason = check_tcp_endpoint("127.0.0.1", 0)
    assert ok is False
    assert "端口" in reason


def test_check_tcp_endpoint_rejects_non_local_ip():
    with patch(
        "src.device.protocol.endpoint_check._iter_local_ipv4",
        return_value={"127.0.0.1", "192.168.1.10"},
    ):
        ok, reason = check_tcp_endpoint("203.0.113.9", 15020)
    assert ok is False
    assert "未配置在本机网卡" in reason


def test_check_tcp_endpoint_rejects_invalid_ip():
    ok, reason = check_tcp_endpoint("not-an-ip", 502)
    assert ok is False
    assert "格式无效" in reason


def test_check_tcp_endpoint_wildcard_port_probe():
    """0.0.0.0 仅做端口试绑；使用系统分配的临时端口降低冲突概率。"""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    ok, reason = check_tcp_endpoint("0.0.0.0", port)
    assert ok is True
    assert reason == ""


@pytest.mark.asyncio
async def test_reload_starts_modbus_tcp_server():
    """Modbus TCP 服务端 reload(is_start=True) 必须显式 start。"""
    from src.web.api.channel import helpers

    new_device = SimpleNamespace(
        name="modbus-srv",
        device_id=1,
        protocol_type=ProtocolType.ModbusTcpServer,
        start=AsyncMock(return_value=True),
        set_device_provider=MagicMock(),
        get_auto_read_status=MagicMock(return_value={}),
        isSimulationRunning=MagicMock(return_value=False),
        simulation_controller=SimpleNamespace(
            snapshot_configuration=MagicMock(return_value=None),
            restore_configuration=MagicMock(),
        ),
        is_protocol_running=MagicMock(return_value=False),
        last_start_error=None,
    )

    channel = {
        "id": 1,
        "name": "modbus-srv",
        "code": "MB-SRV",
        "protocol_type": "ModbusTcpServer",
        "conn_type": 2,
        "ip": "127.0.0.1",
        "port": 15510,
    }
    controller = SimpleNamespace(
        device_list=[],
        device_map={},
        remove_device_by_id=AsyncMock(return_value=True),
        get_device_by_id=MagicMock(return_value=None),
    )

    with (
        patch.object(helpers.ChannelService, "get_channel_by_id", return_value=channel),
        patch.object(helpers.ChannelService, "get_protocol_type", return_value=ProtocolType.ModbusTcpServer),
        patch.object(
            helpers,
            "get_device_builder",
            return_value=SimpleNamespace(makeGeneralDevice=MagicMock(return_value=new_device)),
        ),
        patch.object(helpers, "configure_builder_network"),
        patch.object(helpers.PointMappingService, "get_all_mappings", return_value=[]),
    ):
        result = await helpers.reload_device_instance(controller, 1, is_start=True)

    assert result is new_device
    new_device.start.assert_awaited_once()
    assert controller.device_map["modbus-srv"] is new_device
