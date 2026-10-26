# M3 原生桌面最小流程

桌面入口为 `python -m desktop.main`，使用 requirements/desktop.txt；开发者构建入口为 `packaging/windows/build_desktop.py`。产物是 `.release/M3/dist/ORR Worker/ORR Worker.exe`，必须携带同目录 `_internal`；不打开浏览器、不启动 Streamlit 服务。

已实现原生文件选择／拖入、默认条件核对、单文件条件草稿／应用、自动 A／B 与方向、人工段选择、Matplotlib Qt 画布和缩放／平移工具栏、Origin XY CSV／PNG／SVG、分析项目保存／恢复。均调用 M2 的 Workspace 与原科学核心；界面控件不直接写入有效条件视图。

本阶段 K–L 与 RRDE 标签明确禁用并标记迁移中，完整条件、背景和批量界面留给 M4，完整分析与导出留给 M5。当前最小流程的曲线单位为 mA，尚不是全部功能迁移完成。

## 验收方式

- `desktop.smoke.verify` 用生成的单通道 CV 和中文／空格路径操作真实 Qt 控件，检查 pH 修改、人工第 2 段、图形和项目闭环；不读取实际样品。
- 新增原生控件测试，另核对坏候选不输出上一轮曲线。缺少 Qt 的浏览器开发环境明确跳过这两项；本阶段验收在已安装 Qt 的独立环境中实际执行。
- `tools/verify_desktop_exe.py` 启动实际冻结 exe，移除 PATH 中的 Python 并清除 Qt 插件路径，使用随包 Qt 插件完成同一闭环。无界面截图模式仍创建真实原生控件，不能代替不同显示缩放的人工验收。
- Qt offscreen 插件的字体库为空，已显式加载系统微软雅黑供验收截图使用；正常 Windows 平台沿用系统字体。已检查最终源码截图中文字、曲线和工具栏。

全量源码验收：291 项通过、失败／错误 0，Qt 用例实际执行而非跳过，64.02 秒；报告 `verification/background_conditions_xiujwby_/result.json`。随后参数来源修正的 2 项原生闭环补验通过，报告 `verification/background_conditions_ec_9rxoy/result.json`。最终自动构建的真实 exe 通过全部最小闭环，报告 `verification/native_exe_1h06q422/中文 测试/report.json`。干净机测试按用户要求留待后续，目前只验收本机。

构建修正：开发工具 PATH 中的 Poppler 带有同名 ICU DLL，首次冻结包误收集后导致 QtWidgets 加载失败。构建器现仅向子构建进程提供 Python／Windows 目录，避免读取无关工具 DLL；不修改系统 PATH 或用户环境。发行验收须来自重新自动构建的完整目录，不能把人工调整过的诊断包当作最终产物。
