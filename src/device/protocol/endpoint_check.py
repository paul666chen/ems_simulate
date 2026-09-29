"""TCP 服务端监听端点预检。

启动前检查绑定 IP 是否属于本机、端口是否可用，避免"启动成功但无监听"。
预检与实际绑定之间存在 TOCTOU 窗口，实际绑定异常仍需各协议 handler 兜底捕获。
"""

from __future__ import annotations

from collections.abc import Iterable
import ipaddress
import socket

import psutil


def _iter_local_ipv4() -> set[str]:
    """收集本机网卡上已配置的 IPv4 地址（含 127.0.0.0/8 回路）。"""
    addresses: set[str] = set()
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if getattr(addr, "family", None) != socket.AF_INET:
                continue
            ip = (addr.address or "").strip()
            if ip:
                addresses.add(ip)
    return addresses


def _is_local_ipv4(ip: str, local_ips: Iterable[str] | None = None) -> bool:
    locals_ = set(local_ips) if local_ips is not None else _iter_local_ipv4()
    if ip in locals_:
        return True
    # 127.0.0.0/8 在多数系统上均可绑定，即使 net_if_addrs 未枚举全部地址
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def is_tcp_port_listening(ip: str | None, port: int) -> bool:
    """检查本机是否已有进程在指定 IP:port 上 LISTEN。"""
    bind_ip = (ip or "").strip() or "0.0.0.0"
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, PermissionError):
        return False
    for conn in connections:
        if conn.status != psutil.CONN_LISTEN:
            continue
        if not conn.laddr:
            continue
        if int(conn.laddr.port) != int(port):
            continue
        listen_ip = conn.laddr.ip
        if bind_ip in ("0.0.0.0", ""):
            return True
        if listen_ip in (bind_ip, "0.0.0.0"):
            return True
    return False


def check_tcp_endpoint(ip: str | None, port: int) -> tuple[bool, str]:
    """启动前预检 TCP 监听端点。

    Returns:
        (是否可用, 失败原因)。成功时原因为空字符串。
    """
    bind_ip = (ip or "").strip() or "0.0.0.0"
    try:
        port_num = int(port)
    except (TypeError, ValueError):
        return False, f"端口无效: {port}"
    if port_num < 1 or port_num > 65535:
        return False, f"端口超出范围: {port_num}"

    if bind_ip != "0.0.0.0":
        try:
            parsed = ipaddress.ip_address(bind_ip)
        except ValueError:
            return False, f"IP 地址格式无效: {bind_ip}"
        if parsed.version != 4:
            return False, f"仅支持 IPv4 监听地址，当前为: {bind_ip}"
        if not _is_local_ipv4(bind_ip):
            return (
                False,
                f"地址 {bind_ip} 未配置在本机网卡上，请先在系统中添加该 IP",
            )

    # 试绑探测端口占用（与实际监听短窗口 TOCTOU，仅作友好提示）
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind_ip if bind_ip != "0.0.0.0" else "0.0.0.0", port_num))
    except OSError as exc:
        return False, f"监听 {bind_ip}:{port_num} 失败：端口已被占用或无法绑定 ({exc})"
    finally:
        sock.close()

    return True, ""
