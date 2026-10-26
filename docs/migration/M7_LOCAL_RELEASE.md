# M7：Windows 原生候选包与本机最终验收

日期：2026-10-27（北京时间）。源码版本 **1.7.0-dev**；本阶段提交基于 M6 `413571248ddc346330e53868a75392d52ace9ee2`。本提交为 M7 源码交付；实际 SHA 见 GitHub 提交记录。

用户已确认没有无 Python 的干净 Windows 测试机，先完成本机验证。因此 M0—M7 的本机工作交付完成，跨机器最终认证仍待执行。未创建正式版本标签或 GitHub Release，未把二进制塞入源码仓库。

## 候选包

- 目录：`.release/M7/dist/ORR Worker/`；双击其中 `ORR Worker.exe`。
- 完整 ZIP：`.release/M7/ORR-Worker-1.7.0-dev-Windows-x64.zip`，**106,095,277 字节**（约 106.1 MB）。
- ZIP SHA-256：`5f2cdd47a434c2a1e8acaa819c4728a7c0fe5a917e92278f9e79cf39640ae4b4`。
- 解压目录：1,245 个文件，252,974,264 字节（约 253 MB），包括运行库、指南、许可与校验文件。必须保留整个文件夹及 `_internal`。
- 内附 `VERSION.json`、`SOURCE_MANIFEST.json`、`CHECKSUMS.sha256`、`THIRD_PARTY_NOTICES.md`、`licenses/`、使用与构建指南。

发行包带 Python／Qt 运行时，不需要用户安装 Python。此能力已在本机以仅 Windows PATH 和全部 bundle 内模块路径验证；没有据此声称全新系统验收通过。GitHub 的 Code → Download ZIP 是源码，不是上述运行包。

构建使用 Python 3.13.7、PySide6 6.12.0、PyInstaller 6.22.3；26 项固定依赖闭包见 `requirements/native-build-lock.txt`。干净原生构建环境没有 Streamlit／PyArrow，依赖检查通过。最终 bundle 只收集使用的 Qt 组件，未包含 WebEngine、PDF、虚拟键盘或 Streamlit。

## 实际检查

| 检查 | 结果与本机证据 |
|---|---|
| 全量回归 | **347 通过，0 失败／错误**，68.59 秒；`verification/background_conditions_t5zsvn82/result.json` |
| 无浏览器依赖的原生环境 | **68 通过**，24.23 秒；`verification/background_conditions_gm9b0ct6/result.json` |
| 保留浏览器版 | 条件、背景整组、旧 pH、批量 4 组流程通过；同隔离目录的 `verification/simplified_browser_report.json`；自有 8766 服务已停，未触碰用户 8765 会话 |
| 最终真实 exe | **3 组完整工作流通过**：offscreen 100%、offscreen 150%、Qt Windows 平台；`verification/native_exe_yfb36fjh/report.json` |
| 资源／来源 | 全部文件校验通过；运行前后程序目录哈希不变；UTF-8／LF 归一化运行源码摘要与待提交源码一致 |
| 进程 | 第二次启动返回 2，原进程正常返回 0；退出后重新启动返回 0；只检查本次启动的自有进程 |

真实 exe 在生成的中文／空格目录中运行，复制的程序文件被设为只读，清除外部 Python／Qt 环境变量，只保留 Windows PATH。三次均检查图标、原生窗口和 bundle 内 `sys.path`，均未导入 Streamlit。已查看原生截图，中文控件及模型曲线可读。

每个 exe 流程实际执行：9 样品＋1 背景导入与错误文件隔离；缺转速手填、批量背景盘环配对、人工选段、显示平滑；K–L 已知 n=3.2；RRDE n=3.2／过氧化物 40% 与异常点保留；跨样品环电流；CSV／PNG／SVG／JSON／ZIP；schema=1 读取及 schema=2 保存恢复；背景独立缓存与跟随冲突；取消、任务期间修改后丢弃旧结果、只读目标写失败保留原文件。

以下计时仅来自每文件 26 个原始点的合成短曲线，不代表大文件性能。初始化时间从应用建立窗口计起，不包括全部冷启动／系统加载时间。总时间包含进程启动和完整自动化流程。

| 最终 exe 场景 | 窗口初始化／秒 | 完整流程／秒 | 进程总时间／秒 | 峰值工作集／MiB |
|---|---:|---:|---:|---:|
| offscreen 100% | 1.42 | 7.42 | 9.67 | 282.8 |
| offscreen 150% | 1.11 | 7.45 | 8.96 | 296.3 |
| Qt Windows 平台 | 1.47 | 7.43 | 9.35 | 343.6 |

## 环境边界

| 环境 | 状态 |
|---|---|
| Windows 11 Pro x64 build 26100 本机 | 已验证 |
| 无 Streamlit／PyArrow 的独立原生 Python 环境 | 已验证 |
| 真实 exe，仅 Windows PATH，内置运行时 | 已验证 |
| 中文／空格程序路径；程序文件只读且未被运行改写 | 已验证 |
| offscreen 100%／150% 布局与截图 | 已验证 |
| Qt Windows 平台隐藏窗口的自动控件／绘图流程 | 已验证 |
| 物理显示器缩放、真人逐步操作 | 本轮未执行，自动化缩放不能代替 |
| 程序目录 ACL 禁止写入 | 未执行；文件只读属性不等于目录 ACL |
| 无 Python 的全新 Windows 系统／虚拟机 | 用户当前没有环境，待验收 |
| 其他 Windows 版本、其他系统架构 | 未验证 |

## 交接

[原生使用指南](../NATIVE_USER_GUIDE.md)、[构建与再验收](../BUILD_WINDOWS.md)、[架构与后续开发](../NATIVE_ARCHITECTURE.md) 已完成；[公开验收摘要](M7_ACCEPTANCE.json) 仅保留白名单指标，不含个人目录、原始实验文件或预设。

`tools/record_native_acceptance.py` 从实际报告生成该 JSON，并检查 ZIP 哈希及源文件摘要；新构建必须重新执行 exe 验收和摘要生成，不能复制本次成功结果。原始本机证据和截图不上传 GitHub。冻结基线与既有测试完整保留，后续改进不得通过改答案消除数值偏差。

下一轮具备独立 Windows 环境后，先补齐矩阵中的待验收项，再决定正式版本号、标签和公开二进制发行。原浏览器入口继续保留，现有项目仍读 schema=1／2、写 schema=2。
