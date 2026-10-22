import threading
import time

from src.device.simulator.log import log
from src.device.simulator.point_simulator import PointSimulator
from src.enums.point_data import SimulateMethod, Yc, Yt, Yx
from src.enums.points.change_tracker import ChangeSource, track_change


class SimulationController:
    # 调度循环的最小等待粒度（秒），避免高频率发送周期空转
    MIN_TICK_SECONDS = 0.005
    # 单次等待上限（秒）：保持原有的 1 秒巡检节奏
    MAX_TICK_SECONDS = 1.0

    def __init__(self, device):
        self.points: dict[Yc | Yx, PointSimulator] = {}
        self.device = device
        self._simulation_thread = None  # 单线程控制
        self._stop_event = threading.Event()  # 线程停止信号
        # IEC61850 重建设备时模型尚未加载，按测点身份暂存待恢复的设置。
        self._pending_configuration: dict[tuple, dict] = {}

    def add_point(
        self,
        point: Yc | Yx,
        simulate_method: SimulateMethod,
        step: float,
        *,
        is_running: bool = False,
        send_period_ms: int | None = None,
    ):
        # IEC61850 标准元数据 DA（品质 q、时标 t、描述 dU）不参与模拟
        from src.enums.modbus_def import ProtocolType

        if self.device.protocol_type in (ProtocolType.Iec61850Server,):
            addr = str(point.hex_address)
            if addr.endswith(".q") or addr.endswith(".t") or addr.endswith(".dU"):
                return
        simulator = PointSimulator(point, simulate_method, step)
        simulator.is_running = is_running
        if send_period_ms is not None:
            simulator.send_period_ms = self.normalize_send_period(send_period_ms)
        self.points[point] = simulator
        self._restore_point_configuration(point, simulator)

    @staticmethod
    def normalize_send_period(send_period_ms: int | float | None) -> int:
        """规整发送周期（毫秒）：空值/非法值回退默认值，并夹取到允许范围。"""
        if send_period_ms is None:
            return PointSimulator.DEFAULT_SEND_PERIOD_MS
        try:
            value = int(send_period_ms)
        except (TypeError, ValueError):
            return PointSimulator.DEFAULT_SEND_PERIOD_MS
        if value <= 0:
            return PointSimulator.DEFAULT_SEND_PERIOD_MS
        return max(PointSimulator.MIN_SEND_PERIOD_MS, min(PointSimulator.MAX_SEND_PERIOD_MS, value))

    @staticmethod
    def _configuration_key(point) -> tuple:
        return (str(point.rtu_addr), point.frame_type, point.code)

    def snapshot_configuration(self) -> dict[tuple, dict]:
        """复制模拟设置，不携带旧测点引用、线程或波形执行进度。"""
        configs = {key: dict(value) for key, value in self._pending_configuration.items()}
        for point, simulator in tuple(self.points.items()):
            config = {
                field: getattr(simulator, field)
                for field in (
                    "simulate_method",
                    "step",
                    "fixed_value",
                    "is_running",
                    "cycle",
                    "phase",
                    "ramp_time",
                    "send_period_ms",
                )
            }
            if isinstance(point, (Yc, Yt)):
                config["min_value_limit"] = point.min_value_limit
                config["max_value_limit"] = point.max_value_limit
            configs[self._configuration_key(point)] = config
        return configs

    def restore_configuration(self, configs: dict[tuple, dict], *, defer_missing: bool = False) -> None:
        """恢复相同测点的设置；新测点保留默认值，延迟加载的模型可稍后恢复。"""
        self._pending_configuration = {key: dict(value) for key, value in configs.items()}
        for point, simulator in tuple(self.points.items()):
            self._restore_point_configuration(point, simulator)
        if not defer_missing:
            self._pending_configuration.clear()

    def _restore_point_configuration(self, point, simulator: PointSimulator) -> None:
        config = self._pending_configuration.pop(self._configuration_key(point), None)
        if config is None:
            return
        for field, value in config.items():
            if field in ("min_value_limit", "max_value_limit"):
                if isinstance(point, (Yc, Yt)):
                    setattr(point, field, value)
            else:
                setattr(simulator, field, value)

    def set_all_point_simulate_method(self, simulate_method: SimulateMethod):
        for point_simulator in self.points.values():
            point_simulator.simulate_method = simulate_method

    def apply_configuration(self, items: list[dict]) -> tuple[list[str], list[dict]]:
        """批量应用测点模拟配置（无逐点日志，避免海量日志导致卡顿）。

        配置是"要模拟的测点"的完整定义：未包含在配置中的测点停止模拟。
        返回 (成功编码列表, 失败项列表)。
        """
        configured_codes = {item.get("point_code") for item in items if item.get("point_code")}
        # 重置：未出现在配置中的测点不参与模拟
        for point, simulator in self.points.items():
            if point.code not in configured_codes:
                simulator.is_running = False
        applied: list[str] = []
        failed: list[dict] = []
        for item in items:
            point_code = item.get("point_code")
            if not point_code:
                failed.append({"point_code": point_code, "reason": "缺少 point_code"})
                continue
            simulator = next((s for p, s in self.points.items() if p.code == point_code), None)
            if simulator is None:
                failed.append({"point_code": point_code, "reason": "未找到测点"})
                continue
            try:
                if item.get("simulate_method") is not None:
                    simulator.simulate_method = SimulateMethod(item["simulate_method"])
                if item.get("step") is not None:
                    simulator.step = float(item["step"])
                if item.get("fixed_value") is not None:
                    simulator.fixed_value = float(item["fixed_value"])
                if item.get("send_period_ms") is not None:
                    self._apply_send_period(point, simulator, item["send_period_ms"])
                if item.get("enabled") is not None:
                    simulator.is_running = bool(item["enabled"])
                applied.append(point_code)
            except (ValueError, TypeError) as exc:
                failed.append({"point_code": point_code, "reason": str(exc)})
        return applied, failed

    def _apply_send_period(self, point: Yc | Yx, simulator: PointSimulator, send_period_ms: int | float) -> None:
        """写入发送周期：重置调度时间，并同步给支持周期上送的协议层。"""
        simulator.send_period_ms = self.normalize_send_period(send_period_ms)
        simulator.next_due = 0.0
        sync = getattr(self.device, "apply_simulation_send_period", None)
        if callable(sync):
            try:
                sync(point, simulator.send_period_ms)
            except Exception as exc:  # 协议层不支持时不影响模拟配置生效
                log.warning(f"同步测点 {point.code} 发送周期到协议层失败: {exc}")

    def set_single_point_send_period(self, point_code: str, send_period_ms: int | float) -> bool:
        """设置单个点的发送周期（毫秒）"""
        for point, simulator in self.points.items():
            if point.code == point_code:
                self._apply_send_period(point, simulator, send_period_ms)
                log.info(f"设置点 {point_code} 的发送周期为 {simulator.send_period_ms} ms")
                return True
        log.error(f"未找到点 {point_code}")
        return False

    def set_point_status(self, point: Yc | Yx, is_running: bool):
        if point in self.points:
            self.points[point].is_running = is_running

    def set_point_status_by_code(self, point_code: str, is_running: bool) -> bool:
        """按测点编码设置模拟启停状态"""
        for point, simulator in self.points.items():
            if point.code == point_code:
                simulator.is_running = is_running
                log.info(f"设置点 {point_code} 的模拟状态为 {'运行' if is_running else '停止'}")
                return True
        log.error(f"未找到点 {point_code}")
        return False

    def set_single_point_simulate_method(self, point_code: str, simulate_method: SimulateMethod):
        """设置单个点的模拟方法"""
        for point, simulator in self.points.items():
            if point.code == point_code:
                simulator.simulate_method = simulate_method
                log.info(f"设置点 {point_code} 的模拟方法为 {simulate_method.value}")
                return True
        log.error(f"未找到点 {point_code}")
        return False

    def set_single_point_step(self, point_code: str, step: float):
        """设置单个点的模拟步长"""
        for point, simulator in self.points.items():
            if point.code == point_code:
                simulator.step = float(step)
                log.info(f"设置点 {point_code} 的模拟步长为 {step}")
                return True
        log.error(f"未找到点 {point_code}")
        return False

    def set_single_point_fixed_value(self, point_code: str, fixed_value: float | int) -> bool:
        """设置单个点的定值模拟目标值"""
        for point, simulator in self.points.items():
            if point.code == point_code:
                simulator.fixed_value = float(fixed_value)
                log.info(f"设置点 {point_code} 的模拟定值为 {fixed_value}")
                return True
        log.error(f"未找到点 {point_code}")
        return False

    def get_point_info(self, point_code: str) -> dict | None:
        """获取单个点的信息"""
        for point, simulator in self.points.items():
            if point.code == point_code:
                info = {
                    "code": point.code,
                    "name": point.name,
                    "rtu_addr": point.rtu_addr,
                    "reg_addr": point.hex_address,
                    "func_code": point.func_code,
                    "decode_code": point.decode,
                    "value": point.real_value if isinstance(point, (Yc, Yt)) else point.value,
                    "simulate_method": simulator.simulate_method.value,
                    "step": simulator.step,
                    "fixed_value": simulator.fixed_value,
                    "send_period_ms": simulator.send_period_ms,
                    "is_running": simulator.is_running,
                    "frame_type": point.frame_type,
                    "iec_type_id": getattr(point, "iec_type_id", None),
                    "iec_quality": getattr(point, "iec_quality_value", 0),
                }
                # 遥测和遥调特有字段
                if isinstance(point, (Yc, Yt)):
                    info["mul_coe"] = point.mul_coe
                if isinstance(point, Yt):
                    info["add_coe"] = point.add_coe
                if isinstance(point, Yx):
                    info["bit"] = point.bit
                # 上下限值（Yc/Yt 都有）
                if isinstance(point, (Yc, Yt)):
                    info["min_value"] = point.min_value_limit
                    info["max_value"] = point.max_value_limit
                return info
        return None

    def set_point_simulation_range(self, point_code: str, min_value: float, max_value: float):
        """设置单个点的模拟范围"""
        for point, _simulator in self.points.items():
            if point.code == point_code and isinstance(point, (Yc, Yt)):
                point.min_value_limit = min_value
                point.max_value_limit = max_value
                log.info(f"设置点 {point_code} 的模拟范围为 [{min_value}, {max_value}]")
                return True
        log.error(f"未找到点 {point_code} 或该点不支持设置模拟范围")
        return False

    def start_simulation(self):
        """启动单线程模拟"""
        if not self._simulation_thread or not self._simulation_thread.is_alive():
            self._stop_event.clear()
            self._simulation_thread = threading.Thread(target=self._run_simulation, daemon=True)
            self._simulation_thread.start()

    def stop_simulation(self, timeout: float = 1.0) -> bool:
        """停止模拟线程，并返回线程是否已在超时内退出。"""
        self._stop_event.set()
        if self._simulation_thread and self._simulation_thread.is_alive():
            self._simulation_thread.join(timeout=max(0.0, timeout))
        return not self.is_simulation_running()

    def _run_simulation(self):
        """单线程模拟循环"""
        running_count = sum(1 for s in self.points.values() if s.is_running)
        log.info(f"模拟线程启动, 模拟测点个数: {running_count}")
        # 获取设备本地地址信息
        from src.enums.modbus_def import ProtocolType

        if self.device.protocol_type in (
            ProtocolType.ModbusRtu,
            ProtocolType.ModbusRtuClient,
            ProtocolType.ModbusRtuServer,
            ProtocolType.ModbusRtuOverTcp,
        ):
            local_addr = self.device.serial_port or "未知串口"
        else:
            local_addr = f"{self.device.ip}:{self.device.port}"
        while not self._stop_event.is_set():
            # IEC 61850 服务端必须按轮次批量提交。逐点调用 IedServer_update*
            # 会让每个变化都立即生成报告，订阅后很容易形成报告风暴。
            batch_writer = getattr(self.device.protocol_handler, "write_values_batch", None)
            batch_values = [] if callable(batch_writer) else None

            now = time.monotonic()
            next_due = now + self.MAX_TICK_SECONDS

            # 配置接口可能同时增删模拟点，使用快照避免迭代期间字典变化。
            for point_simulator in tuple(self.points.values()):
                if not point_simulator.is_running or self._stop_event.is_set():
                    continue
                # 发送周期：每个测点独立调度，未到期的点本轮跳过
                due = getattr(point_simulator, "next_due", 0.0)
                if now < due:
                    next_due = min(next_due, due)
                    continue
                point = point_simulator.point

                # 性能优化：仅当开启追溯时才进入上下文
                if point.change_tracking_enabled:
                    with track_change(ChangeSource.SIMULATION, f"自动模拟 {point.code}", local_addr):
                        changed = self._perform_point_simulation(
                            point_simulator,
                            write_protocol=batch_values is None,
                        )
                else:
                    changed = self._perform_point_simulation(
                        point_simulator,
                        write_protocol=batch_values is None,
                    )

                period_ms = getattr(point_simulator, "send_period_ms", PointSimulator.DEFAULT_SEND_PERIOD_MS)
                point_simulator.next_due = now + max(period_ms, PointSimulator.MIN_SEND_PERIOD_MS) / 1000.0
                next_due = min(next_due, point_simulator.next_due)

                if batch_values is not None and changed:
                    # 与 PointOperator.edit_value 保持一致：协议层接收编码后
                    # 的 point.value，而变化判断仍使用 Yc.real_value。
                    batch_values.append((point, point.value))

            if batch_values:
                try:
                    if not batch_writer(batch_values):
                        log.warning(f"IEC61850 模拟值批量写入失败: count={len(batch_values)}")
                except Exception as e:
                    log.error(f"IEC61850 模拟值批量写入异常: count={len(batch_values)}, error={e}")

            wait_seconds = max(
                self.MIN_TICK_SECONDS,
                min(next_due - time.monotonic(), self.MAX_TICK_SECONDS),
            )
            self._stop_event.wait(wait_seconds)  # 可被 stop 立即唤醒

    def _perform_point_simulation(self, point_simulator: PointSimulator, *, write_protocol: bool = True) -> bool:
        """执行单个点的模拟逻辑"""
        point = point_simulator.point
        before = point.real_value if isinstance(point, Yc) else point.value
        point_simulator.simulate()
        after = point.real_value if isinstance(point, Yc) else point.value
        changed = after != before
        if not changed or not write_protocol:
            return changed

        try:
            slave_id = int(point.rtu_addr) if hasattr(point, "rtu_addr") and point.rtu_addr else None
            if isinstance(point, Yc):
                self.device.editPointData(
                    point.code,
                    point.real_value,
                    source=ChangeSource.SIMULATION,
                    detail=f"自动模拟 {point.code}",
                    slave_id=slave_id,
                )
            else:
                self.device.editPointData(
                    point.code,
                    point.value,
                    source=ChangeSource.SIMULATION,
                    detail=f"自动模拟 {point.code}",
                    slave_id=slave_id,
                )
        except ValueError:
            # 忽略模拟超出范围异常，避免停止后续测点的模拟
            pass
        return changed

    def is_simulation_running(self) -> bool:
        """检查模拟线程是否运行"""
        return self._simulation_thread is not None and self._simulation_thread.is_alive()
