"""IEC104 报文文件日志

把 IEC104 客户端/服务端的收发帧落盘到独立文件 ``log/iec104_message.log``，
每条记录含时间、方向、设备标签、帧解析摘要与原始十六进制，
便于在看不到界面的环境（如远程服务器）直接 ``tail`` 排查。

默认的报文捕获器 ``MessageCapture`` 只保存在内存中，进程重启即丢失，
这里补的是持久化这一环，两者互不影响。

开关（任一为关即关闭）：
  - config.ini ``[log] iec104_message = off``（默认 on）
  - 环境变量 ``EMS_IEC104_MESSAGE_LOG=0``
"""

from __future__ import annotations

import os

from src.config.config import Config
from src.config.global_config import LOG_DIR
from src.config.log.logger import Log
from src.device.core.message.parsers.iec104 import parse_iec104

MESSAGE_LOG_PATH = os.path.join(LOG_DIR, "iec104_message.log")

_DISABLE_VALUES = ("0", "off", "false", "no")

# 控制台默认不逐帧输出（避免刷屏），文件保留 INFO
log = Log(
    filename=MESSAGE_LOG_PATH,
    cmdlevel="WARNING",
    filelevel="INFO",
    limit="20 MB",
    backup_count=3,
    colorful=False,
)


def is_enabled() -> bool:
    """报文日志是否开启（运行时读取，改配置无需重启也能生效）。"""
    if os.environ.get("EMS_IEC104_MESSAGE_LOG", "").strip().lower() in _DISABLE_VALUES:
        return False
    return str(getattr(Config, "message_log_iec104", True)).strip().lower() not in _DISABLE_VALUES


def set_enabled(enabled: bool) -> None:
    """运行时开关报文日志（供调试或前端开关使用）。"""
    Config.message_log_iec104 = bool(enabled)


def _field_display(parsed: dict, key: str) -> str:
    for field in parsed.get("fields", []):
        if field.get("key") == key:
            return str(field.get("display_value", ""))
    return ""


def _format_objects(parsed: dict, max_objects: int = 4) -> str:
    """格式化信息体：IOA=值（附原始字节），最多显示 max_objects 个。"""
    objects = parsed.get("objects") or []
    if not objects:
        return ""
    items = []
    for obj in objects[:max_objects]:
        address = obj.get("address")
        value = obj.get("value")
        raw_value = obj.get("raw_value")
        # 命令类信息体的解码值会丢掉 SE/QU 位，附原始字节便于核对
        value_text = f"{value}[{raw_value}]" if raw_value else f"{value}"
        items.append(f"IOA={address} 值={value_text}")
    if len(objects) > max_objects:
        items.append(f"...共{len(objects)}个")
    return " | ".join(items)


def summarize(raw: bytes) -> str:
    """把一帧 IEC104 报文解析成一行可读摘要，解析失败也不抛异常。"""
    try:
        parsed = parse_iec104(raw, role="server")
    except Exception as exc:  # 解析异常不应影响协议链路
        return f"解析失败({type(exc).__name__}: {exc})"

    frame_kind = str(parsed.get("frame_kind") or "未知帧")
    summary = str(parsed.get("summary") or "")

    # U/S 帧没有 ASDU，直接给语义摘要即可（其 summary 已含帧类型，避免重复）
    type_display = _field_display(parsed, "type_id")
    if not type_display:
        if frame_kind in ("U格式帧", "S格式帧"):
            return summary or frame_kind
        return " | ".join(part for part in (frame_kind, summary) if part)

    segments = [frame_kind, type_display]

    cot_display = _field_display(parsed, "cot")
    if cot_display:
        segments.append(f"COT={cot_display}")

    ca_display = _field_display(parsed, "common_address")
    if ca_display:
        segments.append(f"CA={ca_display}")

    objects = _format_objects(parsed)
    if objects:
        segments.append(objects)

    if not parsed.get("valid", True):
        failed = [item for item in (parsed.get("validation") or []) if not item.get("passed", True)]
        detail = failed[0].get("detail") if failed else (parsed.get("errors") or ["未知原因"])[0]
        segments.append(f"校验未通过：{detail}")

    return " | ".join(segments)


def log_frame(direction: str, raw: bytes, label: str = "") -> None:
    """记录一帧报文。

    Args:
        direction: 方向，RX（收到）或 TX（发出）
        raw: 原始字节（APCI + ASDU）
        label: 设备/端点标签，如 ``pcs 客户端→192.168.3.24:2404``
    """
    if not is_enabled():
        return
    try:
        hex_string = " ".join(f"{b:02x}" for b in raw)
        head = f"{direction} {label}" if label else direction
        log.info(f"{head} | {summarize(raw)} | {hex_string}")
    except Exception:
        # 日志链路的任何异常都不能影响协议收发
        pass
