"""PointManager 支持 IEC104 公共地址 > 255。"""

from src.device.core.point.point_manager import PointManager
from src.enums.point_data import Yc, Yk, Yt, Yx


def test_add_point_with_common_address_256():
    pm = PointManager()
    yc = Yc(code="PCS_DC_V", name="直流电压", address=16385, rtu_addr=256)
    yx = Yx(code="PCS_RUN", name="运行", address=1, rtu_addr=256)
    yk = Yk(code="PCS_START", name="启动", address=24577, rtu_addr=256)
    yt = Yt(code="PCS_P_SET", name="有功设定", address=25089, rtu_addr=256)

    pm.add_point(256, yc)
    pm.add_point(256, yx)
    pm.add_point(256, yk)
    pm.add_point(256, yt)

    assert pm.slave_id_list == [256]
    assert len(pm.yc_dict[256]) == 1
    assert len(pm.yx_dict[256]) == 1
    assert len(pm.yk_dict[256]) == 1
    assert len(pm.yt_dict[256]) == 1
    assert pm.get_point_by_code("PCS_DC_V", 256) is yc


def test_add_point_with_common_address_1001():
    pm = PointManager()
    yc = Yc(code="P1", name="p1", address=1, rtu_addr=1001)
    pm.add_point(1001, yc)
    assert 1001 in pm.slave_id_list
    yc_list, _, _, _ = pm.get_points_by_slave(1001)
    assert yc_list == [yc]
