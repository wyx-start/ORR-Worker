# M1 浏览器版 exe

日期：2026-10-26。源码入口：`packaging/windows/browser_entry.py`。

本阶段保留浏览器界面，提供携带 Python 的目录式启动程序。后续原生桌面版沿 M2—M7 继续；本阶段不是原生窗口改写完成。

## 构建与使用

使用 Python 3.13.7、根 requirements.txt 与 packaging/windows/requirements-build.txt 固定依赖，在独立环境运行：

```powershell
python packaging/windows/build_browser.py
```

完整发行目录为 `.release/M1/dist/ORR Worker Browser`。必须整体保留，不能只复制 exe。双击 `ORR Worker Browser.exe` 自动打开浏览器；启动窗口的“停止服务并退出”只停止该程序创建的服务。先下载项目再退出。

程序资源和可写状态分开。默认日志、实例记录和 Matplotlib 缓存位于 `%LOCALAPPDATA%/ORR Worker/browser/<实例标识>`；不修改用户已有 8765 会话。重复启动复用自己的服务，端口占用不结束其他进程。

构建仅包含公开源码及自动生成示例，不收集工作区的真实 examples、预设或分析项目。PyInstaller 在冻结环境使用明确的 `--serve` 分支，不寻找外部 python.exe，也不递归启动启动器。

## 验收

验收工具：`tools/verify_browser_exe.py --executable "<发行目录>/ORR Worker Browser.exe"`。工具在隔离目录和 18766 端口运行实际 exe，PATH 只保留 Windows 目录，清除 Python 环境变量；核对重复启动、占用端口、停止及四组浏览器流程。

实际结果：281 项隔离回归通过；进程归属修正后另外 2 项启动器检查通过。实际冻结 exe 的 4 组浏览器流程全部通过，覆盖默认条件、继承冲突、独立缓存、旧 pH 策略、10 文件批量操作、RRDE、参数导出及项目往返；重复启动复用 PID、拒绝占用端口、停止自有服务均通过。最终报告：`verification/frozen_browser_soux9t8d/verification/report.json`；全量报告：`verification/background_conditions_lhvhqzr_/result.json`。

实际测试发现并修复冻结目录误判开发模式、动态 magic_funcs 与 SVG 后端漏收集三个打包问题。构建中排除了全局环境的无关大型可选依赖。

当前机器本身安装了 Python，因此上述方法不能代替无 Python 的全新 Windows 机器测试。用户已确认目前没有干净机，先完成本机验证。此包按本机迁移试验验收，不标为正式跨机器发行版本；干净机测试单列为后续环境验收项，继续推进共享服务和原生桌面工作。
