"""
从机服务层 (SlaveService)
"""

from src.data.dao.slave_dao import SlaveDao
from src.data.model import SlaveDict
from src.log import log


class SlaveService:
    """从机服务类"""

    @classmethod
    def get_slaves_by_channel(cls, channel_id: int) -> list[SlaveDict]:
        """获取通道下所有从机"""
        return SlaveDao.get_slaves_by_channel(channel_id)

    @classmethod
    def get_slave_ids_by_channel(cls, channel_id: int) -> list[int]:
        """获取通道下所有从机ID列表"""
        return SlaveDao.get_slave_ids_by_channel(channel_id)

    @classmethod
    def slave_exists(cls, channel_id: int, slave_id: int) -> bool:
        """检查从机是否存在"""
        return SlaveDao.slave_exists(channel_id, slave_id)

    @classmethod
    def create_slave(
        cls,
        channel_id: int,
        slave_id: int,
        name: str | None = None,
        *,
        max_slave_id: int = 255,
    ) -> bool:
        """创建从机"""
        if slave_id < 0 or slave_id > max_slave_id:
            log.error(f"无效的从机地址: {slave_id}（允许范围 0-{max_slave_id}）")
            return False
        return SlaveDao.create_slave(channel_id, slave_id, name)

    @classmethod
    def delete_slave(cls, channel_id: int, slave_id: int) -> bool:
        """删除从机"""
        return SlaveDao.delete_slave(channel_id, slave_id)

    @classmethod
    def update_slave_id(
        cls,
        channel_id: int,
        old_slave_id: int,
        new_slave_id: int,
        *,
        max_slave_id: int = 255,
    ) -> bool:
        """更新从机地址"""
        if new_slave_id < 0 or new_slave_id > max_slave_id:
            log.error(f"无效的新从机地址: {new_slave_id}（允许范围 0-{max_slave_id}）")
            return False
        return SlaveDao.update_slave_id(channel_id, old_slave_id, new_slave_id)

    @classmethod
    def ensure_slave(
        cls,
        channel_id: int,
        slave_id: int,
        name: str | None = None,
        *,
        max_slave_id: int = 65534,
    ) -> bool:
        """确保从机记录存在（点表导入补建用）。"""
        if slave_id < 0 or slave_id > max_slave_id:
            log.error(f"无效的从机地址: {slave_id}（允许范围 0-{max_slave_id}）")
            return False
        return SlaveDao.ensure_slave(channel_id, slave_id, name)

    @classmethod
    def ensure_slaves_from_rtu_addrs(
        cls,
        channel_id: int,
        rtu_addrs: list[int],
        *,
        max_slave_id: int = 65534,
    ) -> int:
        """按测点中的 rtu_addr 批量补建 Slave 表记录。"""
        valid = []
        for raw in rtu_addrs:
            try:
                sid = int(raw)
            except (TypeError, ValueError):
                continue
            if 0 <= sid <= max_slave_id:
                valid.append(sid)
            else:
                log.warning(f"跳过越界从机地址: {sid}")
        return SlaveDao.ensure_slaves(channel_id, valid)
