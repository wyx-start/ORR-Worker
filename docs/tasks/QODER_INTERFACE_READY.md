# Qoder 接口就绪说明：背景实验条件继承

日期：2026-10-23。源码：D:\Codex\ustc\orr_workbench。
当前开发版本：**1.7.0-dev**；GitHub 已发布版本仍为 1.6.0。

**核心接口已实现并完成本阶段验证。用户已明确下达“开始实施”，本文件交付后，Qoder 可按既定分工开始两个 UI 文件及三个新测试文件，无需再做一轮接口确认。**本说明不是整版发布完成声明，界面接入和最终集成验收仍待后续交付。

## 1. 你可以修改的文件

仅以下五个文件归 Qoder：

- condition_ui.py
- settings_editor.py
- 新增 tests/test_background_conditions_ui.py
- 新增 tests/browser_background_conditions.cjs
- 新增 tests/create_background_conditions_fixture.py

其他核心、公共模块、app_pages、streamlit_app.py、既有测试、文档、版本及发布由 Codex 负责。需要表外接口时说明具体原因，不在 UI 中补写背景解析逻辑。用户继续手动转交消息，不控制另一 agent 的界面。

设计依据为 QODER_INTERFACE_RESPONSE.md 与 QODER_COLLABORATION_ACKNOWLEDGEMENT.md；本文提供实际就绪 API、实现补充和验证结果。前述文件的“只读协调”是历史阶段限制，已由用户的实施指令更新。

## 2. 实际已就绪的持久化与解析接口

background_conditions.py 导出：

    INHERITED_FIELDS
    MODES = ("follow", "independent", "legacy_ph")
    default_background_conditions()
    resolved_configs(configs, names=None)
    canonical_config(cfg)
    canonical_configs(configs)
    controlled_fields(cfg)
    activate_links(configs, ids)
    condition_error(cfg)

跟随字段仍为：

    potential_method, pH, temperature_C,
    reference, filling, ref_V_SHE, reference_source, reference_preset_C,
    rhe_offset_V

平铺字段及 parameter_sources 始终是独立记录。resolved_configs 返回有效副本；其 background_conditions 含原约定的 mode、legacy_ph_mode、status、effective、independent、linked_samples、field_states、effective_sources、assumptions、migration、detail。

实现额外带出 independent_sources、independent_present_fields、independent_sources_present，专供无损恢复稀疏记录。canonical_config 可以从本解析器的有效投影恢复独立记录，但 UI 编辑仍直接使用 records，不能把整份投影构造成补丁。旧 background_ph_status/sources/detail 是兼容只读别名。

每个 field_states[field] 现有：

    status, value, active, editable, sources, conflicts, detail

参比字段可额外有 representative_source，标明整组参比快照来自哪个样品。不要依赖额外键一定存在。

**只读权限读取 editable。**整组 follow 的等待、冲突、未绑定字段仍不可直接填写；legacy_ph 只按旧规则控制 pH，其余字段独立。active／not_required 说明换算用途，不授予写权限。已知 pH／温度差异仍展示。

不要调用旧 synchronize_ph_links 改写记录。旧 background_ph.py 仅保留兼容辅助；实际处理、视图和项目均走新入口。

## 3. ui_shared 的实际读接口

### 摘要和来源

    get_draft_view() -> {
      "view_basis": "applied" | "candidate" | "applied_fallback",
      "revision": int,
      "has_pending": bool,
      "records": dict,
      "configs": dict,
      "settings": dict,
      "errors": [{"domain": str | None, "message": str}],
      "rejected_domains": list,
      "staged_edits": {domain: {file_id: patch}},
      "staged_setting_edits": {domain: global_patch},
      "rejected_edits": {domain: {file_id: rejected_patch}}
    }

records、configs、settings 来自同一个依据；configs 是 records 的有效投影。get_draft_configs()、get_draft_settings() 是对应兼容包装。

- applied：无草稿，显示已应用记录的解析结果。
- candidate：合法候选，没有未解决拒绝域。
- applied_fallback：真实已应用快照；失败输入保存在各编辑域。摘要文案使用“草稿待修正；下方条件基于已应用设置”。

**同值消除适用于有效 applied 或 candidate，不适用于 applied_fallback。**模式转换、主动复制当前有效值建立独立记录不做消除。同值字段连同其来源叶一并从写入意图移除，不能写进独立缓存。

### 编辑控件的待修正输入

    get_edit_configs(domain=None)
    get_edit_settings()

这是本次实际提供的修复入口，返回**未解析编辑记录**，不得用于计算、导出或保存。

get_edit_configs 先以已应用独立记录叠加全部已接受文件补丁；指定 domain 时再叠加该域的拒绝输入。get_edit_settings 叠加已接受全局补丁。控件本身仍按 key／revision／draft_epoch 保留最新输入；本地校验失败尚无合法补丁时，以编辑器自己的输入草稿为准。

摘要使用 get_draft_view，编辑种子使用对应原始编辑记录。不能因摘要回退，就用 records/configs 中的已应用值重置正在修正的输入；尤其切换来源、范围、条件组、页面时要保留已暂存输入。明确拟切换独立模式后可编辑拟议独立字段，模式和值同次暂存，摘要仍按其视图来源标注。

## 4. 实际写接口与模式切换

    stage_config_updates(domain, updates_by_id, _retry=True, *, replace=False) -> bool
    reject_config_updates(domain, updates_by_id, message) -> False
    apply_pending_settings(preflight=None)
    pending_candidate() -> (canonical_records, settings)

背景专用编辑域：background_conditions:{bgid}。

- stage 返回 False 时整次不接受，保留该域错误及拒绝输入。
- 构建补丁时先检查全部目标；不要逐文件 stage 造成部分更新。
- 在调用 stage 之前发生本地错误，可用 reject_config_updates 登记；有原始输入时传 updates_by_id，没有可用补丁时传 None，并保留编辑器原始输入。
- 新本地错误不会被旧拒绝操作的自动重试清除。内部只重试明确的跨域矛盾，且重试要通过候选校验；UI 不使用 _retry 或内部重试标记做业务判断。
- settings_draft.validate_config_patch(trace, cfg, patch) 已提供底层持久化／受控字段守卫。派生键、未知键及未明确转独立的受控字段写入会被拒绝。
- 缺项、共享冲突可应用和保存；实际计算／结果导出仍走任务 preflight。

replace=False 保留旧行为：同域后续输入合并既有叶值。**模式切换需要去掉该域上一次尚未应用的独立输入时，使用 replace=True，提交该背景当前完整补丁意图。**它只替换本次指定文件在该域的补丁，不删除其他文件／其他域。

例子：

    # 跟随 -> 独立并填写：一次暂存
    stage_config_updates(
        "background_conditions:" + bgid,
        {bgid: {
            "background_conditions_mode": "independent",
            "pH": 12.0,
            "parameter_sources": {"pH": "人工独立填写背景 pH"}
        }},
        replace=True
    )

    # 尚未应用时又切回跟随：仅模式意图，去掉本域旧独立字段补丁
    stage_config_updates(
        "background_conditions:" + bgid,
        {bgid: {"background_conditions_mode": "follow"}},
        replace=True
    )

切换后原已应用独立记录仍在。尚未应用的独立输入可由 UI 自身草稿保留供再次切换，但不能混进跟随提交。不要用普通合并把旧独立字段补丁和 follow 一起提交，否则守卫会正确拒绝。

“用当前有效条件建立独立记录”保持独立显式动作，来源标为用户复制；只从已确认有效视图取得用户选定的当前有效字段。未启用方式的 None 不代表用户要求清空历史缓存；等待／冲突／未绑定时不冒充一套完整可复制的有效条件。

## 5. 条件业务与预设

experiment_conditions.py 保留原 apply_conditions 签名及 bool 返回：

    apply_conditions(cfg, values, source="人工输入",
                     overwrite=True, background_ph_edit=True)
    snapshot_conditions(cfg)
    missing_conditions(cfg, purpose="curves", axis="RHE", density=False)

apply_conditions 现在原子修改独立记录；传有效投影会拒绝。整组 follow 请求写入继承字段也会拒绝，需先明确转 independent。同值消除在 UI 的 condition_updates 中使用同一有效视图完成，底层业务函数不自行猜测样品关联。legacy_ph 的旧直接 pH 人工编辑语义保留，样品批量更新不会写入背景独立 pH 缓存。

snapshot_conditions 可以从解析投影提取有效可复用条件；直接从原始 follow 背景保存预设会拒绝，避免误存独立缓存。保存前按统一入口应用，随后读取新的有效视图，而不是直接读取 session_state.configs[bgid] 作为模板。

预设不携带模式、绑定、迁移或确认状态。门控按实际写目标与字段判定；来源为跟随背景、目标为普通样品时允许复制。目标含非法写入则整次拒绝，不能静默跳过。

missing_conditions 继续返回字符串列表，已区分等待样品／背景自身缺项。UI 不解析字符串判断模式或写权限。0 pH／0 偏移有效；原始预览不新增换算必填项；实际使用的已知共享冲突仍阻断。

## 6. 项目、处理与参数

orr_core.py 实际提供：

- default_config：新记录默认整组 follow，无旧派生状态持久化字段。
- migrate_background_config(cfg, schema=1)：显式旧记录迁移；schema=2 时校验新策略与迁移结构。
- pack_project：schema=2，保存独立记录与模式。
- unpack_project：读取 schema=1／2，返回持久化记录。
- process_trace：解析后处理，不修改输入，新增 stored_config、background_conditions、backgrounds。
- parameter_record：config 为有效条件；增加 stored_config、background_conditions、backgrounds、config_snapshot_basis，优先使用实际处理快照。

backgrounds[bgid] 含 id、filename、sha256、config、stored_config、background_conditions、channels、segments。盘环共用同一背景时去重，仍记录各通道扫描段。共享背景混入不同历史处理条件时参数导出拒绝，要求重新处理。

schema=1 旧 follow 的独立 pH 如实记未知，旧保存值／来源归档；旧 auto/manual 与 legacy 标记的绑定行为保留。schema=2 不重复解释迁移历史。新格式被 1.6.0 拒绝，避免旧软件把独立缓存误当有效条件。

合成夹具可参考 tests/test_background_conditions_core.py 的 trace()/fixture()：其 raw 是可由 parse_chi 再解析的合成 CV，能 pack/unpack。不要使用仅为内存校验而手工构造假 raw 的 Trace 生成项目文件。

## 7. 验证结果与一个明确待接入项

**新增 77 项核心／业务／草稿测试全部通过。**

最终回归报告：verification/background_conditions__8t9sog4/result.json。77 项新增测试均在该报告对应全套运行中通过；独立针对运行的前 75 项证据另存 verification/background_conditions_edw05dea/result.json。
覆盖纯解析、独立记录恢复、共享来源／参比整组、方法缓存、0 值、schema=1／2、实际处理参数快照、业务写入、拒绝域、回退与模式替换。

整套隔离回归：**235 项，234 项通过，1 项失败，0 项执行错误**。
报告：verification/background_conditions__8t9sog4/result.json。该结果基于当前尚未替换的旧 UI，不能写成整版验收通过。

接口基线与文件 SHA-256：verification/background_conditions_core_ready.json。两个 Qoder UI 文件与 1.6.0 基线相同；开发从此基线继续。

剩余失败：

    test_app.AppTests.test_invalid_saved_area_can_be_repaired_without_blocking_current

可复现步骤：

1. 合成样品的旧面积记录无效，进入电流密度设置。
2. 填入 0.25 cm²；此时另有未修正样品，摘要使用 applied_fallback。
3. 改“应用范围”为自选并扩展目标。
4. 旧编辑器从回退摘要重新创建控件，面积重置为空；复制并应用后仍缺面积。

**Qoder 必须在 condition_ui.py 用 get_edit_configs／各域输入草稿初始化可编辑控件，保持已输入面积跨范围切换，再使用原子补丁。**这是第 3 节已就绪读接口的消费工作。保留旧回归，不跳过或改成期望丢失；若新 UI 标签改变，向 Codex 报告，由 Codex 更新既有测试定位。除该明确问题外，本轮没有未解决的核心测试失败。

新增测试文件已由 Codex 完成：

    tests/test_background_conditions.py
    tests/test_background_conditions_business.py
    tests/test_background_conditions_core.py
    tests/test_background_conditions_draft.py
    tests/test_background_conditions_shared.py

Qoder 的三个新测试文件尚未创建；它们仍由你负责。完整新面板、模式切换、预设门控及真实浏览器流程尚未验收。

## 8. 测试与交付方式

环境：Python 3.13、Streamlit 1.61.0。可使用：

    C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe

新增隔离运行器 tools/verify_background_conditions.py：

    python -X utf8 tools/verify_background_conditions.py
    python -X utf8 tools/verify_background_conditions.py --module test_background_conditions_ui

它复制源码／测试到 verification 下独立目录，只使用 .release/1.6.0/examples 的公开合成数据，并隔离本机预设。不要直接运行会读取根 examples 或 user_settings 的全套测试，不把真实数据当验证夹具。

真实浏览器仅使用合成项目与自己的隔离服务；先确认端口可用，不停止用户现有服务，不操作用户 8765 会话。不安装依赖或写外部账号，不执行 GitHub 发布。需要环境变更先报告具体原因。

请交付：

1. 两个 UI 文件与三个新测试文件的精确清单。
2. UI 验证报告：摘要各态、editable、跨范围待修正输入、模式原子切换、只读与预设目标门控、失败无部分暂存。
3. 合成浏览器操作／下载验证及异常信息；未执行的项目明确标明。
4. 表外需求或接口偏差先列触发路径，不自行修改公共层。

交付后用户将结果转回 Codex，由 Codex 完成既有测试定位适配、集成回归、使用／开发文档和最终版本发布。请按本就绪接口进入实施，不再回复“等待 Codex 接口就绪”。

