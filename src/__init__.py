"""EMS Simulate - 电力模拟仿真系统"""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys

try:
    __version__ = version("ems_simulate")
except PackageNotFoundError:
    # 开发模式未安装包 / 打包后无 dist-info 时，从 pyproject.toml 读取版本
    _candidates: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller 打包：spec 将 pyproject.toml 放在 bundle 根目录
        _candidates.append(Path(sys._MEIPASS) / "pyproject.toml")
    _candidates.append(Path(__file__).resolve().parent.parent / "pyproject.toml")

    __version__ = "0.0.0"
    for _pyproject in _candidates:
        try:
            import tomllib

            with _pyproject.open("rb") as f:
                __version__ = tomllib.load(f)["project"]["version"]
            break
        except Exception:
            continue
