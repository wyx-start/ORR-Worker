# ORR Worker 原生桌面架构与接续开发

版本：1.7.0-dev；本机交付日期：2026-10-27。功能和证据见 [M7 验收](migration/M7_LOCAL_RELEASE.md)，构建见 [Windows 构建指南](BUILD_WINDOWS.md)。

## 入口与边界

`desktop.main` 建立 PySide6 窗口；`packaging/windows/desktop_entry.py` 是冻结入口。桌面版不启动 Streamlit 或本机 HTTP 服务。原浏览器版继续保留，由 `ui_shared.py` 等适配共享服务。

```text
desktop/ 窗口、表格、事件、任务控制
                  ↓
application/ 工作区、草稿事务、分析、绘图、导出、任务快照
                  ↓
orr_core.py 与 background_*.py / settings_draft.py 等纯业务模块
```

核心不依赖 Qt；桌面层不导入 Streamlit UI。两种前端共同读 schema=1／2，写 schema=2。不要为了新界面另存一套不兼容的项目格式。

## 文件职责

| 文件 | 主要责任 |
|---|---|
| `application/workspace.py` | 原始文件、持久化设置、草稿、条件解析、处理、项目与导出状态 |
| `application/editing.py` | 条件补丁、背景模式及显式复制；浏览器适配层也调用它 |
| `application/curves.py`、`results.py`、`analysis.py` | 极化／环电流、K–L、RRDE、覆盖预览及结果组织 |
| `application/potentials.py` | 处理后未平滑盘电流的阈值起始／平台半波、单调支线与交点／平台质量检查 |
| `application/figures.py`、`data.py` | 无 Qt 的图形构建、PNG／SVG、CSV／ZIP |
| `application/tasks.py` | 工作区快照、有效性摘要、任务执行与待发布文件 |
| `desktop/window.py`、`models.py`、`settings.py` | 五页导航、可编辑文件表、条件与扫描／背景设置 |
| `desktop/quick_import.py` | 默认导入摘要、按需批量 pH／参比／背景和直接后台绘图；仅主动修改字段构造补丁 |
| `desktop/analysis.py` | 分析输入、图表、结果与 CSV 优先的保存操作 |
| `desktop/jobs.py` | 单个后台线程、进度、协作取消、主线程接收 |
| `desktop/lifecycle.py` | 未保存修改、项目保存／打开／关闭与替换提示 |
| `desktop/main.py`、`fonts.py` | 单实例、图标、字体与窗口启动 |
| `desktop/demo.py`、`smoke.py` | 明确触发才运行的合成验收流程，不读取真实样本 |

## 设置的唯一来源

编辑器从 `get_draft_view()` 的 `records` 构造补丁。背景有效条件、摘要和处理投影只读；写权限以字段 `editable` 为准。先预览范围，再暂存整批修改，最后统一应用或应用并执行任务。非法整批更新不能部分成功。

2026-10-28 起，默认导入页收起完整编辑器，直接显示实际条件摘要。快速范围默认全部样品，排除背景；未知／不同值不补成统一默认。展开常用设置后主动修改单项进入草稿，背景绑定仍经批量构造器校验。直接绘图按钮复用原生分析任务；所有分析页的修改条件入口会展开原完整编辑器。测试 `test_quick_import.py` 覆盖真实按钮点击、原值修正及范围隔离，不能只验证同步辅助方法。

`follow`、`independent`、`legacy_ph` 保持既有语义。平铺字段始终是独立记录；切换到跟随不回写派生值，也不清空独立缓存。跟随等待或冲突时不能回退缓存。显式“用当前有效条件建立独立记录”才复制条件并记录来源。共享背景关联条件冲突必须指出字段和样品。

新导入的默认是 SCE／饱和 KCl／25 °C、pH 13、5 mm 盘、N=0.369；旧项目人工值、明确空值和历史未知状态不被新默认覆盖。面积单位、rpm 换算、RHE、iR、盘环扣背景和模型判定沿用原核心。平滑只改变显示及对应绘图 CSV，计算保留未平滑电流。

2026-10-30 增加极化曲线起始／半波指标。选项在 `settings.plot.potentials`，结果在 `results.curves.potentials`，新 CSV 参与盘曲线失效清理。使用原始处理结果而非显示平滑列，导出 JSON 保存算法、实际平台与来源快照。平台自动策略是带质量门槛的候选，不是物理平台认证；有歧义留空。详见 [方法与验收](tasks/POLARIZATION_POTENTIALS.md)。

## 后台与保存

每次任务复制工作区和输入，内部不可变快照使用 pickle 字节；它只在本程序内生成和消费，不是用户文件格式。用户项目仍走已有 ZIP／JSON 解析，不能把外部 pickle 作为项目读取。

一次只运行一个工作线程。长任务在检查点响应取消，不强制终止线程。Qt 控件和画布由主线程操作；后台创建无交互图形及导出内容。运行期间避免主画布绘制与后台 Matplotlib 绘图交错。

主线程接收前同时检查工作区摘要、编辑器修订、输入令牌和取消状态；过期结果整体丢弃。摘要涵盖配置、草稿、原始数据与结果／导出内容，因此修改不能让旧任务悄悄覆盖新状态。错误保留当前输入，日志放在用户本地目录。

保存先在目标同目录生成临时文件并完成 flush／fsync，任务返回后由主线程再次校验，调用 `os.replace` 发布，最后接收任务状态。取消、过期、写失败不能替换正式文件或假装保存成功。关闭／打开项目会处理未保存修改；有效但尚未计算的分析输入也保存进现有设置字段，非法原始输入阻止保存并保留编辑内容。

## 验证与构建

冻结基线在 `tests/migration_fixtures.py` 等文件；只用生成数据。新增功能先建立独立答案或行为检查，不能改旧答案或放宽容差来通过回归。

全量检查继续涵盖浏览器与核心。原生环境单独执行服务／Qt／任务检查，真实 exe 再运行 `tools/verify_desktop_exe.py`，覆盖导入、批量、模型、导出、项目、冲突、取消与过期结果。环境和未覆盖项目见 M7 矩阵；合成短曲线耗时不能作为真实大数据性能承诺。

`requirements/native-build-lock.txt` 固定构建闭包。构建器限制子进程 PATH，避免开发工具的同名 DLL 混入；自定义 QtGui 收集钩子仅排除未用 PDF／虚拟键盘插件，不修改 Qt 库。发行包含独立 DLL、许可文本、版本和逐文件哈希。源码摘要采用 UTF-8／LF 归一化 SHA-256，兼容 Git 换行规范；不承诺二进制构建逐字节一致。

后续优先补全无 Python 干净 Windows 环境、物理显示器缩放与其他目标系统验收，再决定正式版本标签和公开二进制发行。新增持久化字段、并行任务或自动更新应单独设计兼容、失效与回退规则。真实 `examples/`、预设、项目和 `verification/` 不上传仓库。
