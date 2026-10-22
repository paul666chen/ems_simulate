"""IEC104 发送周期 → 协议层自动上报间隔（report_ms）联动测试。"""

from types import SimpleNamespace

from src.device.protocol.iec104_handler import IEC104ServerHandler
from src.enums.points.yc import Yc


def _log():
    return SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)


def _handler(port: int = 15630) -> IEC104ServerHandler:
    handler = IEC104ServerHandler(log=_log())
    handler.initialize(
        {
            "ip": "127.0.0.1",
            "port": port,
            "slave_id_list": [1],
            "runtime": {},
            "security": {},
        }
    )
    return handler


def _report_ms(handler: IEC104ServerHandler, io_address: int = 1) -> int:
    point = handler._server.stations[1].get_point(io_address=io_address)
    return point.report_ms


def test_send_period_updates_running_point_report_interval():
    handler = _handler()
    point = Yc(code="yc_sp", address="1", rtu_addr=1)
    handler.add_points([point])
    assert _report_ms(handler) == 1000  # 建点默认 1 秒

    assert handler.set_point_send_period(point, 4000) is True
    assert _report_ms(handler) == 4000


def test_send_period_is_cached_before_points_are_added():
    handler = IEC104ServerHandler(log=_log())
    point = Yc(code="yc_sp2", address="2", rtu_addr=1)
    # 设备未初始化：此时只缓存，返回 False 但不报错
    assert handler.set_point_send_period(point, 2500) is False

    handler.initialize(
        {
            "ip": "127.0.0.1",
            "port": 15631,
            "slave_id_list": [1],
            "runtime": {},
            "security": {},
        }
    )
    handler.add_points([point])
    assert _report_ms(handler, io_address=2) == 2500
