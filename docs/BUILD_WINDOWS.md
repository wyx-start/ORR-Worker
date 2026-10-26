# Windows 原生候选包构建与验收

本机基线：Windows 11 Pro x64，build 26100；Python **3.13.7 x64**。依赖闭包固定在 `requirements/native-build-lock.txt`。浏览器开发环境与原生构建环境分开，最终构建环境不安装 Streamlit 或 PyArrow。

```powershell
py -3.13 -m venv .venv-native
& .venv-native/Scripts/python.exe -m pip install -r requirements/native-build-lock.txt
& .venv-native/Scripts/python.exe -m pip check
& .venv-native/Scripts/python.exe -X utf8 packaging/windows/build_desktop.py
& .venv-native/Scripts/python.exe -X utf8 tools/verify_desktop_exe.py --executable '.release/M7/dist/ORR Worker/ORR Worker.exe'
```

请核对 `py -3.13` 实际为 3.13.7；其他解释器版本不属于本轮固定构建环境。构建器只向子进程提供 Python 和 Windows PATH，避免开发工具的同名 DLL 混入。Qt 收集钩子排除不用的 PDF 与虚拟键盘插件，保留 Widgets、原生窗口与 SVG 图标所需组件。

构建仅收集明确的 application／desktop 模块及 assets，不把真实 examples、预设、verification、分析项目或本机配置放入发行目录。生成的验收样本只用于隐藏的 smoke 流程。

输出包含完整目录、候选 ZIP、ZIP 的 SHA-256、逐文件校验、版本／构建依赖、源码摘要、许可文本与用户指南。Qt DLL 保持独立文件；不是单文件 exe。固定依赖与源码使流程可重复，不承诺不同构建时间产生逐字节相同二进制。

## 验收入口

- 既有全部检查：用含浏览器依赖的开发环境运行 `tools/verify_background_conditions.py`，继续保留 Streamlit AppTest。
- 原生依赖环境：同一运行器以 `--module` 选择应用服务、冻结基线和所有 desktop／task 模块；不导入 Streamlit UI。
- 原生流程：`tools/verify_native_analyses.py`、`tools/verify_native_settings.py`，仅使用生成的 9 样品＋1 背景。
- 真实进程：`tools/verify_native_instance.py` 验证第二次启动被拒绝、正常退出和锁释放。
- 真实 exe：`tools/verify_desktop_exe.py` 使用 OS-only PATH、中文／空格路径、生成数据及完整原生工作流，记录屏幕布局、运行环境与结果。

干净构建环境是没有其他 Python 包的独立环境；它和没有 Python 的全新 Windows 系统是两件事。本轮用户确认没有干净测试机，只完成本机验证；不能把移除 PATH 的测试写成已通过干净机认证。物理显示器、其他 Windows 版本和外部机器结果按最终环境矩阵分别记录。

## 继续改进

更新依赖时先在隔离环境验证，再使用 `tools/freeze_native_requirements.py --output <新锁定文件>` 记录闭包。不要仅改锁定文件来跳过数值对照；冻结夹具只能显式生成新目标，不自动覆盖。

界面事件只能构造补丁；不可把有效背景投影作为存储。新增任务先确定快照、取消检查点、结果失效范围与文件发布顺序，再接控件。所有正式文件先准备，再在主线程确认快照有效后替换。

项目继续读 schema=1／2、写 schema=2。新增持久化字段前先写迁移说明与兼容测试。需要保留浏览器回退时使用原 `启动 ORR.cmd`，无需把原生源码强行改回 Streamlit。
