# EMS Simulate 项目长期记忆

## 项目概况
- 电力协议模拟仿真系统：FastAPI 后端(`src/`) + Vue3 前端(`front/`，构建产物输出到 `www/`) + Tauri 桌面壳(`src-tauri/`)。
- 后端入口 `start_back_end.py`：会自动创建 data/log/config/upload/plan 运行时目录，SQLite 库 `data/ems.db` 由 SQLAlchemy create_all 自动初始化。
- 依赖管理：uv（pyproject + uv.lock，含 git 依赖 c104 fork、pydnp3-pure）；前端 npm。
- 后端默认端口 8991（config.ini），前端 dev 默认 8080（vite.config.ts），dev 模式经 `VUE_APP_API_BASE` 直连后端。

## 多IP/绑定相关（重要架构事实）
- **多IP绑定改造已实现（2026-09-29，工作区未提交）**：服务端通道 ip 现在真实生效——创建/启动/重载三条路径均透传通道 ip（`resolve_bind_ip`，空值回退 0.0.0.0）；modbus 已接线（ModbusServer 支持 ip）；新增 `src/device/protocol/endpoint_check.py` 预检（非本机 IP/端口占用 → 明确失败）；`SERVER_PROTOCOLS` 统一"先停旧→显式启新"生命周期（修复了 Modbus/DLT645 restart/编辑重载后不重启、create-and-start 假成功）。已在源码与打包 exe 中双双实测通过。
- 历史背景（改造前行为）：服务端 ip 被强制 0.0.0.0，同端口不同 IP 静默冲突；改动前证据见 plan/features/server-bind-address/ 方案文档附录。
- 客户端协议（conn_type=1）的 ip = 远端目标 IP；无本地源地址绑定。
- 需要模拟"多设备多 IP"：优先用具体 IP + 同端口（已支持）；不同端口方式依然可用。
- GOOSE 发布/订阅/抓包是唯一按物理网卡选择的功能（需 Npcap）。

## Windows 打包（exe）流程
- 官方脚本 `scripts/build_windows.ps1`：版本同步 → `npm run build:fast`（front → www/）→ PyInstaller onedir（`ems_simulate_backend.spec`，env: EMS_PYINSTALLER_MODE=onedir/NAME=ems_simulate/CONSOLE=1）→ 组装 `build/windows/ems-simulate/` + `build/ems-simulate_windows_X.Y.Z.zip`。
- 构建依赖：`uv sync --extra dev --extra build`（pyinstaller+altgraph+pillow，走 7892 代理）。
- 本机测试打包产物须 `--port 9002`（8991 被系统保留）；打包 exe 运行时会自建 data/log/config/upload/plan。
- 已知瑕疵：frozen 版 /api/health version=0.0.0（bundle 无版本元数据；修复思路见当日日志）。

## 本机环境注意事项（Windows / ROG-STRIX）
- **端口 8991 被 Windows 保留区间(8902-9001)占用，禁止绑定**；本地运行后端用 `--port 9002`（或修改 config.ini）。8080 常被其他程序占用，vite 用 `--port 8090 --strictPort`。
- **代理**：环境变量代理 127.0.0.1:13846 对 GitHub 不通（502）；可用的代理是 127.0.0.1:7892。安装 git 依赖（uv sync）时需 `HTTPS_PROXY=http://127.0.0.1:7892 HTTP_PROXY=http://127.0.0.1:7892`。
- npm install 首次可能在 esbuild postinstall 报 EBUSY，重试即可。

## 运行命令（本机）
```bash
# 后端
uv run python start_back_end.py --port 9002
# 前端（换端口 + API 指向）
cd front && VUE_APP_API_BASE=http://127.0.0.1:9002 VITE_BACKEND_URL=http://127.0.0.1:9002 npm run dev -- --port 8090 --strictPort
```
