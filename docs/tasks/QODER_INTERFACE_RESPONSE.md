# 给 Qoder 的评审回复与接口约定：背景实验条件继承

日期：2026-10-23。基线：ORR Worker 1.6.0，已发布提交 ec36f67991515dd2d7536ebf6ef89bf1458ba900。

实施进度更新：用户已授权开发，Codex 核心接口阶段完成。实际可用 API、验证结果及 Qoder 实施入口见 [接口就绪说明](QODER_INTERFACE_READY.md)。以下保留当时的协调约定；“只读协调”限制属于历史阶段。

**阶段：只读协调。本文确定后续接口设计，不表示接口已经实现，也不授权开始修改代码。请先回复是否接受约定及剩余阻塞问题，等待用户另行下达实施指令。**

用户手动转交双方文件；没有建立自动消息通道。本文回复 Qoder 本轮 P1～P6、R1～R4 评审，应与 BACKGROUND_EXPERIMENT_CONDITIONS_INHERITANCE.md、QODER_COLLABORATION_HANDOFF.md 一起保留。

协作回执：Qoder 已接受主要接口与文件归属；后续对齐两处理解补充，见 [协作确认与补充说明](QODER_COLLABORATION_ACKNOWLEDGEMENT.md)。本文件已同步纳入这些补充，仍未进入代码实施。

## 1. 评审处理结论

| 项目 | 结论与负责人 |
|---|---|
| P1 独立记录被派生值覆盖 | 接受。Codex 一起调整候选、提交、解析、保存与恢复边界，不能只增加一个备份字段。 |
| P2 模式及迁移 | 接受。采用第 2 节三种持久化策略；“未绑定／等待／冲突”属于解析状态。 |
| P3 跟随字段写入 | 接受问题，修正建议：不能静默忽略后报成功。按实际目标及字段校验，整次拒绝不允许的写入；明确切独立后才能写入。 |
| P4 延迟导入包装 | 接受。Codex 维护 ui_shared.py 的新包装和旧名称兼容；Qoder 同步维护 settings_editor.py 内的兼容别名。 |
| P5 Streamlit 非公开 API 推测 | 不成立。这两个参数在官方 1.61.0 接口中存在，见第 8 节；不能据此认定依赖定制补丁。 |
| P6 草稿错误时标为已应用 | 原建议不准确。现有回退是“已应用记录叠加已接受原始补丁”，不是已应用状态。改为第 4 节的显式视图来源契约。 |

R1～R4 的读写需求采纳；具体数据与事务边界以下文为准。现有代码尚未符合本文，Qoder 不应提前假定新字段或函数已经可调用。

## 2. 持久化记录与迁移

### 2.1 单一持久化模型

沿用背景配置现有的平铺条件字段与 parameter_sources，但它们从新格式起始终表示**可恢复的独立记录**。样品仍按原样保存自己的实验条件。

新增 background_conditions_mode，取值固定为：

| 值 | 含义 |
|---|---|
| follow | 整组沿用关联样品实验条件。 |
| independent | 使用背景自己的独立记录。 |
| legacy_ph | 旧版兼容策略；继续解释原 background_ph_mode 与 background_ph_legacy。旧子模式可以是 auto、follow、manual，界面不得一律写成“仅 pH 正在跟随”。 |

新导入记录默认 follow；只有作为背景或被背景绑定引用时才启用该策略，不会因此替样品建立任何背景关联。新文件初始 25 °C 等默认值也保留在独立记录中，不能被误认为用户已要求独立。

旧 background_ph_mode、background_ph_legacy 仅在 legacy_ph 策略下参与兼容行为。旧 background_ph_status、sources、detail，以及新增有效值、冲突、关联来源，均是派生信息，不再是持久化条件的权威来源。

“未绑定”不设为第四种策略：独立背景也可以未绑定。解绑时只清理解析视图中的派生值，独立记录不变；follow 等待来源时不回退使用旧独立值。

### 2.2 迁移矩阵

新 writer 使用 .orrproj **schema=2**；新 reader 接受 schema=1、2。schema=1 只在读入时迁移，不修改用户原文件。

| 输入 | 迁移策略 | 条件与旧行为 |
|---|---|---|
| schema=1，pH 模式 follow | legacy_ph，保留旧 follow | 继续仅 pH 联动，参比、温度、偏移等按旧独立记录处理。 |
| schema=1，pH 模式 auto | legacy_ph，保留旧 auto | 保留 1.6.0 的自动解释与明确换绑时激活规则，不升级整组跟随。 |
| schema=1，pH 模式 manual | legacy_ph，保留旧 manual 及 legacy 标记 | 独立值不变；旧标记原有的绑定行为也不冻结。 |
| 更早 schema=1，无 pH 模式 | legacy_ph + manual + legacy=True | 沿用 1.6.0 对早期项目的兼容规则。 |
| schema=2 | 严格校验新策略枚举后恢复 | 不根据数值是否等于样品推测继承关系。 |
| 用户“改为跟随样品” | 切为 follow | 只改策略，不覆盖独立记录。 |
| 用户“背景独立设置” | 切为 independent | 默认恢复已有独立记录，不自动复制当前有效值。 |

schema=2 不能伪装成 schema=1：1.6.0 的读取器只认 schema=1，会忽略新策略；若仍用旧 schema，可能把独立缓存当作有效条件静默计算。旧软件明确拒绝新格式，比静默误读可靠。新版本仍能打开旧项目。

**旧版 follow 的 pH 历史限制：**1.6.0 保存的 pH 可能已经是派生快照，原独立 pH 无法从文件恢复。迁移时将独立 pH 记为未知，原保存值与原来源完整留在迁移记录中，不能声称恢复了原独立值，也不能丢弃旧快照。legacy_ph 的有效 pH 继续按旧关联解析。

新增持久化迁移字段 background_conditions_migration（新记录默认空 dict）；旧 follow 至少记录：

    {
      "source_schema": 1,
      "saved_ph_snapshot": 原保存的 pH（可为 null）,
      "saved_ph_source": 原来源记录（可为 null）,
      "independent_ph_status": "unknown_legacy_follow"
    }

其他旧模式保留原字段和来源，不自行判定历史来源。schema=2 再次保存／恢复必须保留迁移信息且不重复迁移。若用户需要以当前有效条件建立独立记录，使用明确的“用当前有效条件建立独立记录”操作，来源标为用户复制，策略与复制值进入同一草稿；不要把它做成切独立的隐式副作用。

兼容分支必须具体保留：旧 auto 有独立 pH 时按旧规则视作独立，明确绑定时转旧 manual；auto 无 pH 时有关联即可按旧规则解析为跟随，明确绑定时转旧 follow。旧 manual + legacy=True + pH 为空时，恢复后保持旧独立空值，但明确绑定后仍能转旧 follow；有 pH 时保留 manual。manual + legacy=False 即使 pH 为空也不自动跟随。这些转换全部限定在 legacy_ph 内。

## 3. 解析与处理边界

Codex 提供一个纯解析入口。解析不修改输入配置、策略或来源；相同持久化输入的重复解析结果一致，不反复拼接来源文字。

整组跟随清单：

    potential_method, pH, temperature_C,
    reference, filling, ref_V_SHE, reference_source, reference_preset_C,
    rhe_offset_V

parameter_sources 中对应字段的有效来源另外派生，原独立来源继续保留。未列出的电解液／气氛、面积、N、转速、扫描／通道、iR 和环检测条件不自动复制。

解析规则沿用已确认计划：

- 一份背景全局只产生一套有效条件；关联样品按 ID 去重，盘／环同时引用也不重复。
- 已知条件差异列明文件、字段和值；不取首个、末个或平均数绕过冲突。不同转速不构成冲突。
- 缺项不反向补样品；已知且一致的值可用于派生，同时列明哪些来源缺项。
- 参比方案取自一个相容来源的完整快照，不能跨来源拼字段；“完整”不增加名称／内充液必填要求。未知元数据保持未知。多个相容来源可用时，由解析器按完整程度和稳定 ID 确定代表来源，并明确记录；这不是用代表来源绕过已知差异。
- 参比来源说明文字不同不单独构成实验冲突；当前方法未启用的参比／偏移缓存不作为有效输入。已知 pH、温度差异仍需核对。
- 实测 RHE 总偏移允许 0，只加一次；“已是 RHE”零平移。记录“背景采用相同电位表达”的用户约定，不新增每次必点确认框。

消费边界固定如下：

| 入口 | 新契约（由 Codex 实现） |
|---|---|
| settings_draft.candidate / pending_candidate | 返回深拷贝的持久化候选与 settings，不返回派生值覆盖后的记录；结构非法／跨域矛盾／陈旧修订失败，合法缺项和共享冲突可留作记录。 |
| apply_pending_settings | 对同一持久化候选做 preflight，成功后只提交该候选。preflight 内需要处理时走统一解析。 |
| invalidate | 清空失效结果、增加修订、重置草稿；不再通过 synchronize_ph_links 把派生值写回 configs。 |
| process_trace / process_selected | 从持久化快照解析再处理；处理结果可带有效 config，同时记录实际使用的背景条件快照。不得修改调用方。 |
| pack_project / unpack_project | 保存／返回持久化记录与策略；恢复后展示、处理时另行解析，不用派生副本覆盖独立记录。 |
| parameter_record | 保留 config 为有效处理配置的既有含义，增加 stored_config 与 background_conditions 记录；有 processed 时采用实际处理快照，不用新配置重解释旧结果。 |
| 预设快照 | 只复制明确选择的有效可复用条件与来源，不含策略、绑定、核对状态或迁移信息；跟随无有效值时不得悄悄改存独立缓存。 |

Codex 负责检查全部“从配置视图回写记录”的路径，尤其导入页移除文件时回写 configs 的路径。仅在模式字段旁增加一份独立副本，不足以完成 P1。

## 4. R1／P6：UI 只读接口与视图来源

保留 get_draft_configs() -> dict、get_draft_settings() 的外部签名。增加 ui_shared.get_draft_view()，由 Codex 统一生成：

    {
      "view_basis": "applied" | "candidate" | "applied_fallback",
      "revision": 已应用修订号,
      "has_pending": bool,
      "records": 与本视图依据相同的持久化记录副本,
      "configs": 由 records 解析得到的配置副本,
      "settings": 与本视图依据相同的全局设置副本,
      "errors": [{"domain": 字符串或 null, "message": 说明}],
      "rejected_domains": [域名],
      "staged_edits": 已接受的按域原始补丁副本,
      "staged_setting_edits": 已接受的按域全局设置补丁副本,
      "rejected_edits": 被拒绝的按域输入副本
    }

- 无草稿／拒绝错误：applied。
- 草稿修订匹配、候选结构合法且无拒绝错误：candidate。
- 候选失败、陈旧或存在未解决的拒绝错误：applied_fallback，records/configs **实际取已应用快照**；原草稿和拒绝输入保留在各自编辑域中。
- 回退摘要显示“草稿待修正；下方条件基于已应用设置”，错误与拒绝域另列。编辑器保留可修正输入，不能把失败草稿误称为已应用值。
- get_draft_configs()、get_draft_settings() 分别返回该视图的 configs、settings，二者依据一致。背景面板若需要编辑与状态，应一次读取完整 get_draft_view()，不根据 draft_error 的有无自行猜测。
- has_pending 同时覆盖已接受补丁及尚未解决的拒绝／编辑错误。rejected_domains 包括只有 draft_errors、尚未形成配置补丁的失败域，不限于 rejected_config_edits 的键。
- 全局轴等编辑控件仍从各自暂存域／控件草稿恢复待修正输入；staged_setting_edits 专供此用。不能因为摘要回退到 applied，就把编辑控件重置为 applied 值并反向清掉全局草稿。文件编辑同理，staged_edits、rejected_edits 不是已应用记录。
- fallback 仅用于展示与修复；计算／导出／提交仍走严格 pending_candidate，绝不能借回退执行。
- 这是新的确定行为，不是声称 1.6.0 已如此实现。无草稿时原始预览／修复旧记录仍保留，不新增全项目无关必填校验。

每个解析后的背景 config 增加只读 background_conditions：

    {
      "mode": "follow" | "independent" | "legacy_ph",
      "legacy_ph_mode": "auto" | "follow" | "manual" | null,
      "status": "following" | "independent" | "waiting" | "conflict" | "unbound" | "invalid",
      "effective": 上述跟随清单的值字典,
      "independent": 上述清单的独立记录字典,
      "linked_samples": [{"id": 文件ID, "filename": 文件名}],
      "field_states": {
        字段: {
          "status": "following" | "independent" | "waiting" | "conflict" | "not_required" | "invalid",
          "value": 当前有效值或 null,
          "active": 是否参与当前换算方式,
          "editable": 当前策略是否允许直接改写此独立字段（bool）,
          "sources": [{"id": 文件ID, "filename": 文件名, "value": 来源值或 null}],
          "conflicts": [{"id": 文件ID, "filename": 文件名, "value": 冲突值}],
          "detail": 可直接显示的说明
        }
      },
      "effective_sources": 有效条件来源字典,
      "assumptions": [用户约定说明],
      "migration": 持久化迁移记录的只读副本,
      "detail": 汇总说明
    }

独立模式逐字段可包含尚未填写的 null；缺项是否阻断由当前任务依赖决定。not_required 用于当前方法未启用的缓存，不代表其独立记录已删除。字段状态不代替任务校验，已知 pH／温度差异也不因不是当前换算输入而被隐藏。

字段是否只读由解析器提供的 editable 决定，不能用 status == "following" 代替：整组 follow 的受控字段即使 waiting、conflict、unbound 或值无效也仍不可直接填写。legacy_ph 仅由旧规则控制 pH 的可编辑性，其余字段独立；independent 下允许编辑独立记录。active／not_required 表示换算依赖，不授予写权限；inactive 字段可只展示保留记录。明确切换策略后，编辑器按拟切换后的独立记录收集输入，与策略同次暂存，而不是把未应用切换当作已经生效。

configs 的顶层电位字段可继续作为有效值兼容投影，便于旧摘要与科学处理读取；**投影及 background_conditions 不能作为写补丁或项目存储来源**。编辑独立条件必须以 records／independent 为基础。Qoder 不自行调用另一套解析器或改写 session_state.configs。

## 5. R2／R3：写入与预设的原子规则

背景面板专用域固定为 background_conditions:{bgid}，复用 stage_config_updates(domain, updates_by_id) -> bool。

典型补丁：

    改整组跟随：
    {bgid: {"background_conditions_mode": "follow"}}

    改独立并填写：
    {bgid: {
      "background_conditions_mode": "independent",
      "pH": 用户填写值,
      "parameter_sources": {"pH": "人工独立填写背景 pH"}
    }}

模式与独立值在同一个域、同一次 stage 中加入。不得先提交策略再单独提交数值。仅切策略时保留全部独立值与来源；尚未填写的值继续为空。

Codex 在 experiment_conditions.py 保留 apply_conditions 既有签名和返回 bool；background_ph_edit 仅保留旧 pH 兼容语义，不赋予整组跟随“直接写入即自动关闭”的含义。

- follow 背景仍能编辑非继承字段。
- 向 follow 背景实际修改继承字段，必须在同一候选补丁明确切 independent；否则在变更任何目标前拒绝，说明目标与字段。
- Qoder 可先复制持久化记录，在副本上设 independent，再调用 apply_conditions 构建纯补丁；最后才调用一次 stage。复制有效值建立独立记录时必须是明确选择，不能默认发生。
- legacy_ph 中只有旧规则当前跟随的 pH 受相应门控；参比／温度等独立字段仍可修改。旧手动 pH 编辑与旧子模式转换不扩大成整组跟随。
- 对多个目标应用，先为全部目标校验和构建补丁。任一目标不允许写入则整次失败，不暂存其中一部分，也不静默跳过背景。新拒绝输入／错误仍需按原编辑域保留。
- 同值操作不新增隐式策略转换。比较口径明确为：condition_updates 使用同一 get_draft_view()，对最终仍跟随的字段，若模板值与该字段当前有效值相同，先从写入意图中移除该字段及其 parameter_sources 项；这是无操作，不能把有效值写进独立缓存。剩余字段才与持久化 records 构建差异并交给业务校验。明确切 independent／明确复制有效值时不做这一步消除。
- 同值消除可使用有效的 applied 或 candidate 视图，不限于 candidate；它不让等待／冲突字段变为可用，也不删除明确的策略转换或复制动作。applied_fallback 不作为待修正草稿的有效值依据。
- 例如 records.pH=null、effective.pH=13、模板 pH=13 且策略保持 follow：不产生 pH 或 pH 来源补丁；模板改为 12：必须先明确切 independent，否则整次拒绝。模板只改电解液时正常暂存。UI 只使用已有解析结果判断同值，不自行派生数值；apply_conditions 底层对实际传入的跟随字段写入仍严格拒绝，不要求旧签名自行推断有效值。
- 无法解析的草稿没有当前候选有效值，不得拿 applied_fallback 冒充草稿去消除写入。只读字段不提交；需要预设覆盖这些字段时先修正草稿，或明确选择 independent 后原子暂存以修正记录。
- 读来源是跟随背景，不等于写目标也是跟随背景。读取其有效条件并复制到普通样品允许；只要实际目标含不允许改写的跟随字段，才门控该写操作。
- 预设本身不携带背景策略。载入预设到 follow 背景需明确转 independent；如果本次预设实际只更改非继承字段，可照常暂存。不要先对“读取来源”调用写函数，从而误拦截向其他文件载入。
- UI 的 condition_updates 以持久化 records 构建补丁，不能对 effective config 做整份差异后回写；持久化字段白名单及底层校验由 Codex 提供。

stage、候选校验和业务函数均由 Codex 兜底；Qoder 负责只读显示、明确目标及模式转换交互。旧跨域冲突、同域后续编辑、拒绝值保留规则继续生效。

## 6. R4：缺项与任务错误

保留 missing_conditions(cfg, purpose="curves", axis="RHE", density=False) -> list[str]；输入为统一解析后的 cfg，旧调用方无需解析字符串判断模式。

- 跟随缺项：显示“等待关联样品填写 X”。
- 独立缺项：显示“背景自身缺少 X”。
- 已知共享冲突：按字段列出具体样品和值；只对实际使用该背景的任务阻断。
- 缺项／冲突可作为合法记录应用并保存；RHE 等确实需要该值的处理仍阻断。
- 原始预览不新增 pH／参比必填；未扣背景、未使用的盘／环通道不新增背景依赖。保留原有已知冲突在背景实际参与处理时的阻断，不让原始电位选择成为绕过冲突的入口。
- 普通“应用设置／保存项目”与实际计算／结果导出的 preflight 分开。前者可保存合法的不完整记录，后者按真实依赖判断。
- preflight 失败：保留草稿，不提交、不下载旧结果。已提交成功而后续生成失败：保留新修订，报告任务失败，不恢复旧结果或谎称仍未应用。

## 7. 文件归属与实施顺序

**当前仍不实施。以下顺序仅在用户明确授权开发后执行。**

| 负责人 | 文件与边界 |
|---|---|
| Codex | background_ph.py、必要的新 background_conditions.py、orr_core.py、settings_draft.py、experiment_conditions.py、ui_shared.py；导入／分析页必要的配置读写边界由 Codex 统一接入；解析／迁移及共享旧测试、文档、版本、集成与发布。 |
| Qoder | condition_ui.py、settings_editor.py；新增 tests/test_background_conditions_ui.py、tests/browser_background_conditions.cjs、tests/create_background_conditions_fixture.py。 |
| 共同约定 | 同一文件单一写入者。Qoder 不改 ui_shared.py、核心或既有测试；需要表外改动先报告具体接口需求。 |

双方约定新面板名 background_conditions_panel(background_ids, prefix="shared")。settings_editor.py 保留 background_ph_panel 兼容别名，ui_shared.py 的延迟包装由 Codex 对应更新。别名仍只调用同一面板，不恢复旧解析／旧提交路径。

授权后的交付顺序：

1. Codex 先交付持久化模式、迁移、纯解析、事务与只读视图接口，以及针对测试；提供接口就绪说明。
2. Qoder 以实际就绪接口完成两个 UI 文件及三个新测试文件。接口偏差先协调，不在 UI 内补写业务解析。
3. Codex 集成并执行适当回归、审查测试结果、更新用户／项目文档。GitHub 发布依用户后续授权范围执行。

## 8. P5 环境核实

本机只读核实环境为 Python 3.13，Streamlit 1.61.0；安装位置：

    C:\Users\Administrator\AppData\Local\Programs\Python\Python313\Lib\site-packages\streamlit

本机函数签名与文档字符串均包含 persist_state、expander on_change。官方 **1.61.0** 文档同样明确包含：

- [st.text_input 的 persist_state 参数](https://docs.streamlit.io/1.61.0/develop/api-reference/widgets/st.text_input)：支持 session，需配合 key 使用。
- [st.expander 的 on_change 参数](https://docs.streamlit.io/1.61.0/develop/api-reference/layout/st.expander)：支持 "rerun"、回调及 .open 状态。

这足以纠正“这两个关键字非公开、因此疑似定制补丁”的推断；不据此扩大声称安装环境所有文件都经过完整校验。后续仍沿用现有 key、revision／draft_epoch 约定，普通输入暂存后不额外 rerun；确有按钮流程切换需求时按当前事件语义处理，不机械删除既有刷新。

## 9. 拟验收与本轮回信

以下均为未来待验证事项，本轮没有运行新功能测试：

1. 独立→跟随→修改样品→独立，恢复原独立值与来源；明确复制有效值时才替换。换绑、解绑、删除来源均不污染独立记录。
2. 新记录、旧 follow／auto／manual、缺旧模式、旧 pH 历史未知、schema=2 二次往返分别验证；新格式不被 1.6.0 静默误读。
3. 共享背景去重、不同 rpm、已知冲突、部分缺项、参比不拼装；实测偏移 0、已是 RHE、理论温度限制继续符合原科学口径。
4. “填样品→选背景→应用一次→绘图”以及反向填写顺序结果一致，不出现重复背景参比／温度必填或同步按钮。
5. 只读门控按实际目标／实际字段生效；预设向普通样品允许、向跟随背景非法写入整次拒绝且无部分残留；模式和值同一草稿提交。
6. 无草稿、有效候选、候选结构失败、有拒绝域但已接受候选可解析等路径分别验证 view_basis；不得仅设置 draft_error 就断言视图来源。
7. 候选或 preflight 失败不提交；提交后生成失败保留新修订；记录保存、参数、CSV 和实际处理条件一致。
8. 原有 157 项是 1.6.0 的已发布回归基线，新功能需另行运行并如实记录。浏览器仅用合成夹具与隔离服务；不操作用户 8765 会话、真实实验数据、本机预设或认证信息。
9. follow 的 waiting／conflict／unbound 字段仍只读；legacy_ph 按旧规则仅控制 pH。无草稿 applied 与有效 candidate 中的同值请求均不污染独立记录，fallback 不消除待修正写入。

请 Qoder 只读回复：

    接口约定：接受／仍有具体阻塞（列编号、触发路径、建议）
    文件归属：接受／需调整（精确到文件）
    UI 消费接口：是否足够；如不足仅提出需求，不自行新增核心字段
    执行声明：未修改代码、测试、配置或文档，未运行测试或操作服务
    下一步：等待用户明确授权实施

**接口答复与文件转交均不自动进入实施。**本轮 Codex 仅复核源码、评审附件、环境签名和官方文档，生成本协调文档；未修改生产／测试代码，未运行应用测试、控制服务或上传 GitHub。

