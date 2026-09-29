"""Slave 表与测点 rtu_addr 同步、编辑补建回归。"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.device.core.slave_manager import SlaveManager
from src.enums.modbus_def import ProtocolType


def test_edit_slave_ensures_missing_slave_row():
    """内存有从机 256（来自点表），Slave 表无行时，编辑 256→255 仍应成功。"""
    device = MagicMock()
    device.protocol_type = ProtocolType.Iec104Server
    device.device_id = 1
    device.point_manager.slave_id_list = [256]
    device.point_manager.yc_dict = {256: []}
    device.point_manager.yx_dict = {256: []}
    device.point_manager.yk_dict = {256: []}
    device.point_manager.yt_dict = {256: []}
    device.point_manager.get_points_by_slave.return_value = ([], [], [], [])
    device.server = None
    device._reinit_protocol_for_iec104 = MagicMock()
    device.log = SimpleNamespace(
        info=lambda *a, **k: None,
        error=lambda *a, **k: None,
        warning=lambda *a, **k: None,
    )

    mgr = SlaveManager(device)
    with (
        patch("src.data.service.slave_service.SlaveService.ensure_slave", return_value=True) as ensure,
        patch("src.data.service.slave_service.SlaveService.update_slave_id", return_value=True),
        patch("src.data.dao.point_dao.PointDao.update_slave_id", return_value=1),
    ):
        assert mgr.edit_slave(256, 255) is True
        ensure.assert_called_once_with(1, 256, max_slave_id=65534)

    assert 255 in device.point_manager.slave_id_list
    assert 256 not in device.point_manager.slave_id_list
    device._reinit_protocol_for_iec104.assert_called_once()


def test_update_slave_id_dao_creates_when_old_row_missing():
    """DAO：旧 Slave 行不存在时直接按新地址插入。"""
    from src.data.dao.slave_dao import SlaveDao
    from src.data.model import Slave

    added: list[Slave] = []

    class _Result:
        def __init__(self, value=None, rowcount=0):
            self._value = value
            self.rowcount = rowcount

        def scalar_one_or_none(self):
            return self._value

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def begin(self):
            return self

        def execute(self, stmt):
            # 1) select new_slave exists -> None
            # 2) update old -> 0 rows
            if not hasattr(self, "n"):
                self.n = 0
            self.n += 1
            if self.n == 1:
                return _Result(None)
            return _Result(None, rowcount=0)

        def add(self, obj):
            added.append(obj)

    with patch("src.data.dao.slave_dao.local_session", return_value=_Session()):
        ok = SlaveDao.update_slave_id(1, 256, 255)

    assert ok is True
    assert len(added) == 1
    assert added[0].slave_id == 255
    assert added[0].channel_id == 1
