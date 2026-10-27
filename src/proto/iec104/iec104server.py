"""
IEC104 服务端实现

基于 c104 库，支持多 Station（多从站/多公共地址）。
每个从站（slave_id）映射为一个独立的 common_address 的 c104.Station。
"""

import threading
from typing import Any

import c104
from c104 import Quality

from src.device.core.message.message_capture import MessageCapture
from src.proto.iec104.log import log
from src.proto.iec104.message_log import log_frame
from src.proto.iec104.tls import IEC104OneWayTlsConfig, TlsServerBridge, allocate_loopback_port

ServerConnection = getattr(c104, "ServerConnection", Any)
ServerConnectionState = getattr(c104, "ServerConnectionState", Any)


def _has_connection_monitoring_extension() -> bool:
    """Return whether c104 exposes the EMS fork's connection lifecycle API."""
    return hasattr(c104, "ServerConnection") and hasattr(c104, "ServerConnectionState")


# ---------------------------------------------------------------------------
# 遥控命令模式（命令传输模式）
#
# c104（lib60870）对命令点有两种互斥的传输模式，主站与从站必须一致，否则从站一律回
# 否定激活确认（COT=0x47）：
#   * DIRECT            直接执行：主站只发执行令（SE=0）；主站若发选择令（SE=1）→ 回 0x47
#   * SELECT_AND_EXECUTE 选择后执行：主站必须先发选择令（SE=1）再发执行令（SE=0）；
#                        未选择直接执行 → 回 0x47
#
# 两者互斥，且与主站流程必须一致，因此作为设备运行参数由使用者显式选择；
# 模式不匹配时服务端会在日志中给出诊断提示（见 _diagnose_command_mode）。
# ---------------------------------------------------------------------------
IEC104_COMMAND_MODE_DIRECT = "direct"
IEC104_COMMAND_MODE_SELECT_AND_EXECUTE = "select_and_execute"
IEC104_COMMAND_MODES = (IEC104_COMMAND_MODE_DIRECT, IEC104_COMMAND_MODE_SELECT_AND_EXECUTE)

# 带“选择/执行”语义（信息体末字节 bit7 = SE）的命令 ASDU 类型
# C_SC_NA_1 / C_DC_NA_1 / C_RC_TA_1 / C_SE_NA_1 / C_SE_NB_1 / C_SE_NC_1
_SELECTABLE_COMMAND_TYPE_IDS = frozenset({45, 46, 47, 48, 49, 50})
_COT_ACTIVATION = 6


def normalize_command_mode(value: str | None, default: str = IEC104_COMMAND_MODE_DIRECT) -> str:
    """规范化命令传输模式配置值，非法值回退到 default。"""
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in IEC104_COMMAND_MODES:
            return candidate
    return default


def parse_select_command(data: bytes) -> tuple[int, int] | None:
    """从接收到的 I 帧中识别“选择(SELECT)命令”，返回 (公共地址, 信息体地址)。

    Args:
        data: 完整的 APDU 字节（可含多帧，仅解析首帧）

    Returns:
        命中选择命令时返回 ``(common_address, ioa)``，否则返回 None。
    """
    # APCI: 0x68 + 长度 + 4 字节控制域；I 帧要求控制域最低位为 0
    # 最短命令帧 = 6(APCI) + 类型(1) + VSQ(1) + COT(2) + CA(2) + IOA(3) + 命令限定词(1) = 16
    if len(data) < 16 or data[0] != 0x68:
        return None
    apdu_length = data[1]
    if apdu_length + 2 > len(data):
        return None
    if data[2] & 0x01:  # 非 I 帧（S/U 帧）
        return None
    type_id = data[6]
    if type_id not in _SELECTABLE_COMMAND_TYPE_IDS:
        return None
    cot = data[8]
    if (cot & 0x3F) != _COT_ACTIVATION:  # 仅激活（含选择/执行）
        return None
    if not data[-1] & 0x80:  # 信息体末字节 bit7 = SE，1 表示选择命令
        return None
    common_address = data[10] | (data[11] << 8)
    ioa = data[12] | (data[13] << 8) | (data[14] << 16)
    return common_address, ioa


class IEC104Server:
    def __init__(
        self,
        ip="0.0.0.0",
        port=2404,
        connection_timeout: int = 10,
        message_timeout: int = 15,
        confirm_interval: int = 10,
        keep_alive_interval: int = 20,
        send_window_size: int = 12,
        receive_window_size: int = 8,
        max_connections: int = 0,
        transport_security: c104.TransportSecurity | None = None,
        one_way_tls_config: IEC104OneWayTlsConfig | None = None,
        connection_history_size: int = 100,
        message_log_label: str = "",
        command_mode: str = IEC104_COMMAND_MODE_DIRECT,
    ):
        """
        初始化IEC 104服务器
        :param ip: 服务器监听IP地址，默认0.0.0.0表示监听所有接口
        :param port: 服务器监听端口，默认2404是IEC 104标准端口
        :param message_log_label: 报文文件日志中的设备/端点标签
        :param command_mode: 遥控命令传输模式，direct / select_and_execute / auto
        """
        self.ip = ip
        self.port = port
        self.message_log_label = message_log_label or f"服务端 {ip}:{port}"
        self.command_mode = normalize_command_mode(command_mode)
        # 创建c104服务器实例
        backend_ip = ip
        backend_port = port
        self._tls_bridge = None
        self._connection_state_callback = None
        self._pending_bridge_origins: dict[tuple[str, int], tuple[tuple[str, int], str]] = {}
        self._bridge_origin_lock = threading.Lock()
        tls_bridge_context = None
        if one_way_tls_config:
            backend_ip = "127.0.0.1"
            backend_port = allocate_loopback_port()
            tls_bridge_context = one_way_tls_config.create_server_context()

        # ARM64 packages use the official PyPI c104 build.  Connection history
        # and per-connection lifecycle types are extensions of the EMS fork and
        # must not be passed to the official Server constructor.
        has_monitoring_extension = _has_connection_monitoring_extension()
        server_kwargs: dict[str, Any] = dict(
            ip=backend_ip,
            port=backend_port,
            transport_security=transport_security,
        )
        if has_monitoring_extension:
            server_kwargs["connection_history_size"] = connection_history_size
        self.server = c104.Server(**server_kwargs)

        connection_callback = getattr(self.server, "on_connection_state_change", None)
        self.connection_monitoring_supported = bool(
            has_monitoring_extension
            and callable(connection_callback)
            and hasattr(self.server, "connections")
            and callable(getattr(self.server, "set_connection_origin", None))
        )
        if tls_bridge_context is not None:
            self._tls_bridge = TlsServerBridge(
                listen_host=ip,
                listen_port=port,
                backend_port=backend_port,
                context=tls_bridge_context,
                on_session_origin=(self._on_bridge_session_origin if self.connection_monitoring_supported else None),
            )

        self.server.protocol_parameters.connection_timeout = connection_timeout
        self.server.protocol_parameters.message_timeout = message_timeout
        self.server.protocol_parameters.confirm_interval = confirm_interval
        self.server.protocol_parameters.keep_alive_interval = keep_alive_interval
        self.server.protocol_parameters.send_window_size = send_window_size
        self.server.protocol_parameters.receive_window_size = receive_window_size
        self.server.max_connections = max_connections
        if self.connection_monitoring_supported:
            connection_callback(callable=self._on_connection_state_change)
        # 多 Station 支持：common_address -> c104.Station
        self.stations: dict[int, c104.Station] = {}
        # 存储所有监控点的列表
        self.points: list[c104.Point] = []
        # 存储所有命令点的列表
        self.commands: list[c104.Point] = []
        # (common_address, IOA) -> 命令点，用于运行时切换命令传输模式
        self.command_points: dict[tuple[int, int], c104.Point] = {}
        # 已输出过模式不匹配诊断提示的命令点，避免重复刷屏
        self._command_mode_hinted: set[tuple[int, int]] = set()
        # 关联测点map
        self.related_point_map = {}
        # 命令接收后的应用层回调（由 handler 注册，用于同步应用层 BasePoint）
        self._on_command_received_callback = None
        # IOA → common_address 映射，用于命令回调反查站地址
        self._ioa_to_ca: dict[int, int] = {}
        # 设置默认回调函数
        self._setup_callbacks()

        # 报文捕获器
        self.message_capture = MessageCapture()

        # 注册原始报文回调（监控缺失时跳过，不影响服务器运行）
        if self.server:
            if hasattr(self.server, "on_receive_raw"):
                self.server.on_receive_raw(callable=self._on_receive_raw)
            if hasattr(self.server, "on_send_raw"):
                self.server.on_send_raw(callable=self._on_send_raw)

    def _on_receive_raw(self, server: c104.Server, data: bytes) -> None:
        """接收原始报文回调"""
        try:
            self.message_capture.add_rx(data)
        except Exception as e:
            log.error(f"记录接收报文失败: {e}")
        log_frame("RX", data, self.message_log_label)
        self._diagnose_command_mode(data)

    def _diagnose_command_mode(self, data: bytes) -> None:
        """命令传输模式不匹配时给出一次诊断提示。

        原始报文回调由 c104 异步投递，晚于 ASDU 处理，无法在同一帧内纠正模式，
        因此这里只记录可操作的排查建议。
        """
        try:
            target = parse_select_command(data)
        except Exception as e:  # 解析失败不影响主流程
            log.debug(f"解析选择命令失败: {e}")
            return
        if target is None or target in self._command_mode_hinted:
            return
        point = self.command_points.get(target)
        if point is None:
            return
        self._command_mode_hinted.add(target)
        try:
            if point.command_mode == c104.CommandMode.DIRECT:
                log.warning(
                    f"命令点 CA={target[0]} IOA={target[1]} 收到主站的选择(SELECT)命令，但当前命令传输模式为"
                    "直接执行(DIRECT)，该命令会被否定确认（COT=0x47）。"
                    "若主站采用“先选择后执行”流程，请将设备运行参数 command_mode 设为 select_and_execute 后重启设备。"
                )
        except Exception as e:  # 读取属性失败不影响主流程
            log.debug(f"读取命令点传输模式失败: {e}")

    def set_point_command_mode(
        self,
        io_address: int,
        command_mode: c104.CommandMode,
        common_address: int = 1,
        note: str = "",
    ) -> bool:
        """运行时切换命令点的传输模式（DIRECT / SELECT_AND_EXECUTE）。

        Args:
            io_address: 信息对象地址(IOA)
            command_mode: c104.CommandMode 目标模式
            common_address: 站地址
            note: 附加到日志中的说明

        Returns:
            切换成功返回 True
        """
        point = self.command_points.get((common_address, io_address))
        if point is None:
            return False
        try:
            if point.command_mode == command_mode:
                self._command_mode_switched.add((common_address, io_address))
                return True
            point.command_mode = command_mode
        except Exception as e:
            log.error(f"切换命令点传输模式失败: CA={common_address}, IOA={io_address}, {e}")
            return False
        self._command_mode_hinted.discard((common_address, io_address))
        if command_mode == c104.CommandMode.SELECT_AND_EXECUTE:
            mode_name = "选择后执行(SELECT_AND_EXECUTE)"
        else:
            mode_name = "直接执行(DIRECT)"
        suffix = f"（{note}）" if note else ""
        log.info(f"命令点 CA={common_address} IOA={io_address} 传输模式切换为{mode_name}{suffix}")
        return True

    def _on_send_raw(self, server: c104.Server, data: bytes) -> None:
        """发送原始报文回调"""
        try:
            self.message_capture.add_tx(data)
        except Exception as e:
            log.error(f"记录发送报文失败: {e}")
        log_frame("TX", data, self.message_log_label)

    def set_connection_state_callback(self, callback) -> None:
        """Register the application lifecycle callback."""
        self._connection_state_callback = callback

    def _on_bridge_session_origin(
        self,
        observed_endpoint: tuple[str, int],
        remote_endpoint: tuple[str, int],
        correlation_id: str,
    ) -> None:
        if not self.connection_monitoring_supported:
            return
        observed = (str(observed_endpoint[0]), int(observed_endpoint[1]))
        with self._bridge_origin_lock:
            for connection in self.server.connections:
                if (connection.observed_remote_ip, connection.observed_remote_port) == observed:
                    self.server.set_connection_origin(
                        id=connection.id,
                        remote_ip=str(remote_endpoint[0]),
                        remote_port=int(remote_endpoint[1]),
                        correlation_id=correlation_id,
                    )
                    return
            self._pending_bridge_origins[observed] = (
                (str(remote_endpoint[0]), int(remote_endpoint[1])),
                correlation_id,
            )

    def _on_connection_state_change(
        self,
        server: c104.Server,
        connection: ServerConnection,
        state: ServerConnectionState,
    ) -> None:
        if state == c104.ServerConnectionState.ESTABLISHED:
            observed = (connection.observed_remote_ip, connection.observed_remote_port)
            with self._bridge_origin_lock:
                origin = self._pending_bridge_origins.pop(observed, None)
            if origin:
                remote_endpoint, correlation_id = origin
                server.set_connection_origin(
                    id=connection.id,
                    remote_ip=remote_endpoint[0],
                    remote_port=remote_endpoint[1],
                    correlation_id=correlation_id,
                )
        if self._connection_state_callback:
            self._connection_state_callback(server, connection, state)

    def get_captured_messages(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取捕获的报文列表"""
        return self.message_capture.get_messages(limit)

    def clear_captured_messages(self) -> None:
        """清空捕获的报文"""
        self.message_capture.clear()

    def _setup_callbacks(self):
        """设置默认的回调函数"""
        # 初始化通用命令接收处理函数
        self._on_command_received = self._default_command_handler

    def get_station(self, common_address: int) -> c104.Station:
        """获取或创建指定公共地址的 Station

        Args:
            common_address: 公共地址（对应从站 slave_id）

        Returns:
            c104.Station 对象
        """
        if common_address not in self.stations:
            self.stations[common_address] = self.server.add_station(common_address=common_address)
        return self.stations[common_address]

    def add_monitoring_point(
        self,
        io_address: int,
        point_type: c104.Type = c104.Type.M_ME_NC_1,
        report_ms: int = 1000,
        common_address: int = 1,
    ) -> c104.Point | None:
        """
        添加一个监控点到指定站
        :param io_address: 信息对象地址(IOA)
        :param point_type: 点类型，默认是归一化值测量量(M_ME_NC_1)
        :param report_ms: 自动上报间隔(毫秒)
        :param common_address: 站地址（对应从站 slave_id）
        :return: 创建的监控点对象
        """
        station = self.get_station(common_address)
        # 创建监控点
        point = station.add_point(io_address=io_address, type=point_type, report_ms=report_ms)
        if point:
            self.points.append(point)
            self._ioa_to_ca[io_address] = common_address
        return point

    def add_command_point(
        self,
        io_address: int,
        point_type: c104.Type = c104.Type.C_RC_TA_1,
        related_point_ioa: int | None = None,
        common_address: int = 1,
        command_mode: str | None = None,
    ) -> c104.Point | None:
        """
        添加一个命令点到指定站
        :param io_address: 信息对象地址(IOA)
        :param point_type: 点类型，默认是调节步命令(C_RC_TA_1)
        :param related_point_ioa: 关联的监控点IOA
        :param common_address: 站地址（对应从站 slave_id）
        :param command_mode: 命令传输模式，None 表示沿用服务器配置（self.command_mode）
        :return: 创建的命令点对象
        """
        station = self.get_station(common_address)
        # 命令传输模式与主站流程必须一致，否则命令会被否定确认（COT=0x47）
        mode = normalize_command_mode(command_mode or self.command_mode)
        c104_mode = (
            c104.CommandMode.SELECT_AND_EXECUTE
            if mode == IEC104_COMMAND_MODE_SELECT_AND_EXECUTE
            else c104.CommandMode.DIRECT
        )
        # 创建命令点
        command = station.add_point(io_address=io_address, type=point_type, command_mode=c104_mode)
        if not command:
            log.warning(f"创建命令点失败: IOA={io_address}, type={point_type}, common_address={common_address}")
            return None
        # 注册命令接收回调（c104 接收到命令后自动更新 point.value，然后触发此回调）
        command.on_receive(callable=self._on_command_received)
        # 添加到命令点列表
        self.commands.append(command)
        self.command_points[(common_address, io_address)] = command
        self._ioa_to_ca[io_address] = common_address
        return command

    def get_point_value(self, io_address: int, frame_type: int = 0, common_address: int = 1) -> float:
        """
        获取指定站中指定IOA的监控点值
        :param io_address: 信息对象地址(IOA)
        :param frame_type: 帧类型
        :param common_address: 站地址（对应从站 slave_id）
        :return: 监控点值（Python float）
        """
        station = self.stations.get(common_address)
        if not station:
            return 0
        try:
            point = station.get_point(io_address=io_address)
            if point:
                # 遥控点(2)返回 bool，其余返回 float
                if frame_type == 2:
                    return bool(point.value)
                return float(point.value)
            return 0
        except Exception as e:
            log.info(f"获取监控点值失败: {e}")
            raise e

    def set_point_value(self, io_address: int, value, frame_type: int = 0, common_address: int = 1) -> None:
        """
        设置指定站中指定IOA的监控点值
        :param io_address: 信息对象地址(IOA)
        :param value: 要设置的值（c104 原生类型，如 NormalizedFloat、Int16、float、bool）
        :param frame_type: 帧类型，默认遥测
        :param common_address: 站地址（对应从站 slave_id）
        """
        station = self.stations.get(common_address)
        if not station:
            return
        try:
            point = station.get_point(io_address=io_address)
            if point:
                point.value = value
        except Exception as e:
            log.info(f"设置监控点值失败: {e}")
            raise e

    def set_point_report_period(self, io_address: int, report_ms: int, common_address: int = 1) -> bool:
        """
        设置指定站中指定IOA监控点的自动上报间隔（周期上送）

        :param io_address: 信息对象地址(IOA)
        :param report_ms: 自动上报间隔（毫秒），0 表示仅变化时上送
        :param common_address: 站地址（对应从站 slave_id）
        :return: 是否设置成功
        """
        station = self.stations.get(common_address)
        if not station:
            return False
        try:
            point = station.get_point(io_address=io_address)
            if point is None:
                return False
            point.report_ms = max(0, int(report_ms))
            return True
        except Exception as e:
            log.info(f"设置监控点上报周期失败: IOA={io_address}, report_ms={report_ms}, error={e}")
            return False

    def set_point_quality(self, io_address: int, quality: int, frame_type: int = 0, common_address: int = 1) -> None:
        """
        设置指定站中指定IOA的品质描述符
        :param io_address: 信息对象地址(IOA)
        :param quality: 品质描述符整数值 (位标志: OV=0x01 BL=0x02 SB=0x04 NT=0x08 IV=0x10)
        :param frame_type: 帧类型，默认遥测
        :param common_address: 站地址（对应从站 slave_id）
        """
        station = self.stations.get(common_address)
        if not station:
            return
        try:
            point = station.get_point(io_address=io_address)
            if point and hasattr(point, "quality"):
                point.quality = Quality(value=quality)
        except Exception as e:
            log.error(f"设置监控点品质失败: {e}")
            raise

    def get_point_quality(self, io_address: int, frame_type: int = 0, common_address: int = 1) -> int:
        """
        获取指定站中指定IOA的品质描述符
        :param io_address: 信息对象地址(IOA)
        :param frame_type: 帧类型
        :param common_address: 站地址（对应从站 slave_id）
        :return: 品质描述符整数值
        """
        station = self.stations.get(common_address)
        if not station:
            return 0
        try:
            point = station.get_point(io_address=io_address)
            if point and hasattr(point, "quality"):
                return int(point.quality)
            return 0
        except Exception as e:
            log.error(f"获取监控点品质失败: {e}")
            raise

    def start(self):
        """启动IEC 104服务器"""
        self.server.start()
        if self._tls_bridge:
            try:
                self._tls_bridge.start()
            except Exception:
                self.server.stop()
                raise

    def stop(self):
        """停止IEC 104服务器"""
        if self.server:
            if self._tls_bridge:
                self._tls_bridge.stop()
            self.server.stop()
            log.info("IEC 104服务器已停止")

    async def run(self, timeout=30):
        """
        运行服务器主循环
        :param timeout: 超时时间(秒)，默认30秒
        """
        import asyncio

        # 等待客户端连接
        while not self.server.has_active_connections:
            print("等待客户端连接...")
            await asyncio.sleep(1)

        await asyncio.sleep(1)

        c = 0
        # 保持连接直到超时或连接断开
        while self.server.has_open_connections and c < timeout:
            c += 1
            print("保持连接中...")
            await asyncio.sleep(1)

    def isRunning(self) -> bool:
        """检查服务器是否运行中"""
        return self.server.is_running

    def _default_command_handler(
        self,
        point: c104.Point,
        previous_info: c104.Information,
        message: c104.IncomingMessage,
    ) -> c104.ResponseState:
        """
        默认的通用命令接收处理函数
        处理单点遥控(C_SC_NA_1)、双点遥控(C_DC_NA_1)、设定值(C_SE_*)等命令。

        c104 在收到命令后会先更新 point.value 再触发此回调，
        回调只需返回响应状态即可。

        :param point: 命令点对象（point.value 已更新为接收到的命令值）
        :param previous_info: 前一个信息对象
        :param message: 接收到的消息
        :return: 响应状态(SUCCESS/FAILURE)
        """
        log.info(f"收到命令 - IOA: {point.io_address}, 类型: {point.type}, 值: {point.value}")
        # 查找 IOA 对应的站地址
        common_address = self._ioa_to_ca.get(point.io_address, 1)
        # 通知应用层回调（如果有注册），传递 IOA、值、帧类型和站地址
        if self._on_command_received_callback:
            try:
                self._on_command_received_callback(
                    point.io_address,
                    point.value,
                    point.type,
                    common_address,
                )
            except Exception as e:
                log.error(f"命令接收回调执行失败: {e}")
        return c104.ResponseState.SUCCESS

    def set_on_command_callback(self, callback):
        """
        设置命令接收通知回调
        当服务端收到客户端的遥控/遥调命令时，会调用此回调通知应用层。
        :param callback: 回调函数，签名 callback(io_address, value, point_type, common_address)
        """
        self._on_command_received_callback = callback

    # 绑定关联测点
    def bind_related_point(self, io_address: int, related_io_address: int, common_address: int = 1):
        """
        绑定遥调点到遥测点上面
        :param io_address: 遥调点IOA
        :param related_io_address: 遥测点IOA
        :param common_address: 站地址（对应从站 slave_id）
        """
        station = self.stations.get(common_address)
        if not station:
            log.error(f"绑定104关联测点失败，未找到站地址 {common_address}")
            return
        a_point = station.get_point(io_address=io_address)
        b_point = station.get_point(io_address=related_io_address)
        if a_point:
            log.info(f"找到测点A (IOA={io_address})")
        if b_point:
            log.info(f"找到测点B (IOA={related_io_address})")
        if a_point and b_point:
            self.related_point_map[a_point] = b_point
            if hasattr(self, "_before_read"):
                a_point.on_before_read(callable=self._before_read)
            log.info(f"绑定成功, {a_point.io_address} 关联 {b_point.io_address}")
        else:
            log.error("绑定104关联测点失败")


if __name__ == "__main__":
    import asyncio

    async def main():
        # 创建服务器实例
        server = IEC104Server(ip="0.0.0.0", port=2404)

        # 添加监控点(IOA=11)和命令点(IOA=12)到站地址1
        server.add_monitoring_point(io_address=11, common_address=1)
        server.add_command_point(io_address=12, common_address=1)

        # 启动服务器并运行主循环
        server.start()
        await server.run(timeout=30)

    asyncio.run(main())
