# Qoder 实施交付：背景实验条件继承（UI 部分）

对应 QODER_INTERFACE_READY.md §8。交付日期 2026-10-23。基线：1.6.0 发布副本 + Codex 核心接口（background_conditions.py / ui_shared.py / settings_draft.py / experiment_conditions.py 现状）。

## 1. 交付文件清单（恰为授权的 5 个）

| 文件 | 动作 | 内容 |
|---|---|---|
| `condition_ui.py` | 重写 | 摘要新增"背景条件"列（跟随/独立/等待/冲突/未绑定各态）；编辑器只消费 `field_states[f].editable`；跟随来源显示有效值且控件禁用；同值消除仅在 applied/candidate 视图且目标受控时执行；`condition_updates(view, targets, values, ...)` 先为全部目标构建补丁再暂存（原子）；控件以 `get_edit_configs(domain)` 初始化，applied_fallback 下已输入面积跨范围切换保留；预设载入种子取自 `snapshot_conditions(resolved_cfg)`，保存读应用后的新有效视图 |
| `settings_editor.py` | 重写 | `background_conditions_panel`：模式/状态/关联样品/假设/迁移说明 + 模式按钮 + 九字段明细表（字段/有效值/状态/可编辑/独立记录/有效来源/说明）+ 独立模式内联编辑；`legacy_ph` 分派到逐字保留的旧版 pH 面板并附"升级为整组跟随（推荐）"；`stage_background_mode` 以 `replace=True` 写入 `background_conditions:{bgid}` 并清理另两个 UI 域中该文件的暂存；`background_ph_panel` 为兼容别名 |
| `tests/test_background_conditions_ui.py` | 新增 | 12 个 AppTest 用例（见 §2） |
| `tests/create_background_conditions_fixture.py` | 新增 | 全内存合成 parse_chi 可解析曲线；两样品的 pH 13/12 真实冲突 + 共享背景 follow 且保留独立缓存 pH 11/20 °C/独立参比；`pack_project` 写出 schema=2；不读任何真实样例 |
| `tests/browser_background_conditions.cjs` | 新增 | 合成浏览器流程（见 §3） |

未触碰任何其他文件。

## 2. UI 验证报告（AppTest，隔离运行器）

命令：`python -X utf8 tools/verify_background_conditions.py`（全量）与 `--module test_background_conditions_ui`（单模块）。

- **全量回归**：247 通过 / 0 失败 / 0 错误（含既有 235 + 新增 12；含此前失败的 `test_app.py::test_invalid_saved_area_can_be_repaired_without_blocking_current`）。证据：`verification/background_conditions_u18b5s0v/result.json`。
- **摘要各态**：跟随（"整组跟随样品 · 有效值"）、等待（两样品均缺 pH → "等待关联样品"）、冲突（13 vs 12 → 含字段名与"冲突"）、独立（"独立记录"）；存储记录始终保持 pH 11 独立缓存不被有效值覆盖。
- **editable**：跟随/等待/冲突下 pH、换算方式、参比方案均 disabled 且显示有效值；电解液等非继承字段不受控；仅消费 `editable`，未从 status 推导。
- **跨范围待修正输入**：面积非法 → 局部校验失败进入 applied_fallback →"仅此文件"输入 0.25 → 切"自选"两个样品后控件仍显示 0.25 → 复制 → 应用成功（`get_edit_configs` 初始化生效）。
- **模式原子切换**：编辑器"切到独立设置"与同域 pH 修改合并在 `conditions:{bgid}` 一个域；"改为跟随关联样品"（replace=True）丢弃该文件在三个 UI 域的全部未应用暂存；存储记录应用前不变。
- **只读与预设目标门控**：向跟随背景写入真实差异（pH 14）→ 草稿错误含"跟随"且 `settings_draft["configs"]=={}`、无 rejected_config_edits；预设 {pH 7} 以跟随背景为目标 → 整体失败无任何暂存；改目标为样品后成功。
- **失败无部分暂存**：上述两类失败均为先构建全部补丁再暂存，失败时零写入。
- 另覆盖：预设保存自跟随背景来源时存有效值（pH 13/25 °C）而存储不变；legacy_ph 面板保留旧标签并可升级；独立模式背景 pH 接受 0 且来源记为"人工独立设置背景条件"。

## 3. 浏览器验证（合成流程，隔离服务）

- 服务：`verification/background_conditions_u18b5s0v` 隔离副本自带服务于 127.0.0.1:8766（启动前已确认 8766 空闲；用户 8765 会话未触碰，验证后已停止该服务）。夹具在隔离副本内由 `tests/create_background_conditions_fixture.py` 生成。
- 流程（`tests/browser_background_conditions.cjs`，全部通过）：恢复夹具 → 摘要与编辑器显示"状态：条件冲突"、跟随字段只读、"用当前有效条件建立独立记录"禁用（截图）→"切到独立设置"后编辑器以保留缓存 pH 11.000 播种 → 改 pH 10 → 应用 → `parameters.json` 断言 stored_config：mode=independent、pH=10、20 °C、ref .110、无 `background_conditions` 派生键；样品 13/12 不变 → 面板"改为跟随关联样品"→ 冲突复现（截图）→ 再次仅模式切回独立 → stored pH 仍为 10（有效值从未物化）→ 保存 .orrproj → 恢复 → `stored_config` 与 `config` 逐项一致。
- 证据：`verification/background_conditions_browser_report.json`（passed: true，pageErrors 空）、`background_conditions_conflict.png`、`background_conditions_follow_conflict.png`、三份 parameters JSON、夹具与往返项目文件（均已复制到 `verification/`）。
- **未执行项**：①等待/未绑定态仅 AppTest 覆盖，浏览器未单独跑；②legacy_ph 面板的浏览器流程未跑（AppTest 已覆盖升级路径）；③摘要"背景条件"列为 st.dataframe 画布渲染，DOM 不可断言，以截图 + 编辑器/面板文字断言替代。

## 4. 表外需求（请 Codex 处理，UI 未绕行）

1. **既有浏览器脚本标签过期**（触发路径：集成回归跑 `tests/browser_background_ph.cjs`、`tests/browser_conditions.cjs`）：两脚本仍引用 1.5 时代标签——"应用背景 pH 设置"、"背景 pH：…"、"背景独立 pH（允许 0）"、"应用实验参数"、"导出全部参数与处理记录 JSON"、"保存分析项目 .orrproj"。当前实际标签：统一"应用设置"、"背景实验条件 · <文件名>"、"背景 pH（允许 0）"（仅独立/旧版面板内）、参数导出为"下载全部完整数据 CSV"后在"更多导出"内取 `parameters.json`、保存按钮为"保存分析项目"。参数 JSON 结构为每文件 `config`（有效）+ `stored_config`（规范）+ 顶层 `background_conditions`；断言存储值请用 `stored_config`。按分工这两个脚本的定位器适配属 Codex。
2. **`st.segmented_control` 无 stSegmentedControl testid**：1.61 渲染为 `role=radiogroup` + `role=radio` 按钮；浏览器定位用 `getByRole('radio', {name})`（我的新脚本已如此）。Codex 适配既有脚本时若遇分段控件同此。
3. **`test_app.py` 旧版 pH 面板回归**：旧标签经逐字保留得以通过，属设计而非巧合；后续若改 legacy 面板文案需同步该测试（文件属 Codex）。

## 5. 环境

Windows 10/11 + Python 3.13（`C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`）+ Streamlit 1.61.0 + Node 24 + Playwright（codex 运行时缓存解析）+ Edge headless。无新装依赖，无外部账户，无 Git 操作。
