"""发送周期（send_period_ms）配置与调度测试。"""

import time
from types import SimpleNamespace

from src.device.simulator.point_simulator import PointSimulator
from src.device.simulator.simulation_controller import SimulationController
from src.enums.modbus_def import ProtocolType
from src.enums.point_data import SimulateMethod
from src.enums.points.yx import Yx


def _device(writes: list | None = None):
    return SimpleNamespace(
        protocol_type=ProtocolType.ModbusTcpServer,
        protocol_handler=None,
        ip="127.0.0.1",
        port=502,
        editPointData=lambda code, value, **_kwargs: writes.append((code, value)) if writes is not None else True,
    )


def test_apply_configuration_sets_and_clamps_send_period():
    controller = SimulationController(_device())
    point = Yx(code="sw", value=0)
    controller.add_point(point, SimulateMethod.Random, 1, is_running=True)

    applied, failed = controller.apply_configuration(
        [{"point_code": "sw", "enabled": True, "send_period_ms": 2500}]
    )
    assert applied == ["sw"] and failed == []
    simulator = controller.points[point]
    assert simulator.send_period_ms == 2500
    assert simulator.next_due == 0.0
    assert controller.get_point_info("sw")["send_period_ms"] == 2500

    controller.apply_configuration([{"point_code": "sw", "send_period_ms": 1}])
    assert simulator.send_period_ms == PointSimulator.MIN_SEND_PERIOD_MS

    controller.apply_configuration([{"point_code": "sw", "send_period_ms": 99_999_999}])
    assert simulator.send_period_ms == PointSimulator.MAX_SEND_PERIOD_MS


def test_simulation_loop_schedules_next_run_by_send_period():
    writes: list = []
    controller = SimulationController(_device(writes))
    point = Yx(code="sw", value=0)
    controller.add_point(point, SimulateMethod.Random, 1, is_running=True)
    controller.points[point].send_period_ms = 500

    # 第一次触发后立即停止循环，只验证调度时间被按周期推后
    def simulate():
        point.value = 1
        controller._stop_event.set()

    controller.points[point].simulate = simulate
    started = time.monotonic()
    controller._run_simulation()

    simulator = controller.points[point]
    assert writes == [("sw", 1)]
    assert simulator.next_due >= started + 0.5
