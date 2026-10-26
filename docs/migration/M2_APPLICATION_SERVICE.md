# M2 共享应用服务

`application.workspace.Workspace` 是两个前端共用的工作区。默认创建独立 `State`；浏览器适配器传入现有会话代理，保留原有键、revision、workspace_epoch 和 draft_epoch，因此不更换用户会话的存储结构。

## 接口

| 操作 | 接口及约束 |
|---|---|
| 导入 | `add_files([(name, raw_bytes), ...])`；逐文件报告错误、重复文件不重复导入；有草稿时拒绝导入 |
| 编辑 | `get_draft_view()`、`get_edit_configs(domain)`；前者区分 records、只读有效 configs、候选／回退与拒绝输入 |
| 暂存 | `stage_config_updates`、`stage_settings_updates`；保留原子域、字段权限、拒绝与重试规则 |
| 应用 | `pending_candidate()`、`apply_pending_settings(preflight)`；任务校验在提交前完成，失败不部分应用 |
| 处理 | `process_selected`、`process_all`；直接调用原科学核心，不依赖控件 |
| 分析 | `calculate_kl(inputs)`、`calculate_rrde(selected)`；调用 orr_core 计算，先清除该任务旧结果，成功后提交候选和新结果 |
| 项目 | `project_bytes()`、`restore_project(raw, discard=False)`；只处理字节，不弹对话框；恢复完整验证后才替换工作区，继续读 schema=1／2、写 schema=2 |
| 快照 | `snapshot()`；脱离实时记录与原始数组的副本，供后续后台任务使用 |
| 导出 | `set_export`、`store_table`、`parameters`；返回字节／数据，不操作用户文件路径 |

`application.data` 提供原有合并表、坐标名和 ZIP 字节；`application.figures` 提供 Figure 与 PNG／SVG 构建，不强制设置全局图形后端。浏览器仍自行管理 pyplot 的关闭，桌面可使用 Qt 画布。

`ui_shared.py` 保留公开函数作为轻量适配。浏览器 K–L／RRDE 的计算入口现调用共享服务，原有页面展示和下载流程保留。核心、浏览器和桌面依赖分别列于 requirements/，根 requirements.txt 继续兼容原安装方式。

## 验收

新增 8 项服务测试：禁止 UI 导入时的服务与 PNG／SVG、K–L 已知答案与全部选择要求、RRDE 逐表比较与异常行、项目独立缓存、schema=1 空值保留、失败恢复／preflight 原子性、快照隔离、坏文件／重复导入。

最终全量：289 项通过，失败／错误 0，55.97 秒；报告 `verification/background_conditions_ml1dja1i/result.json`。此前四组完整浏览器流程全部通过，报告 `verification/background_conditions_iqij265o/verification/simplified_browser_report.json`；随后保存／恢复入口统一为 Workspace 后，再补跑最终快照的条件／参数／项目闭环，通过，报告 `verification/background_conditions_ml1dja1i/verification/simplified_browser_report.json`。

图形、K–L／RRDE、保存／恢复入口和事务适配均由最终回归覆盖。Qt 界面尚未开始；本阶段不宣称桌面前端完成。
