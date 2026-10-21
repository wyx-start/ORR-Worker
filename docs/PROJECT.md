# ORR Worker 项目说明

版本：1.6.0。首次交付：2026-10-14；1.5.0 环图与配对背景于 2026-10-18 实现、2026-10-19 复核。本轮统一设置草稿、组合操作和 Origin 绘图 CSV。本文件供后续开发者或 Codex 会话继续改进。

## 1. 已确认的需求与边界

本机 Windows 使用，依赖本机已安装 Python；双击启动后打开浏览器。不要求免安装运行环境或部署服务器。按每批 10 个文件做验证。

第一版专做 ORR，支持辰华 CHI760F 的文本导出、批量导入、CV 单向支线提取、独立背景、多转速 K–L、RRDE、pH/参比影响、电流密度、PNG/SVG/CSV/JSON 分别导出以及项目保存恢复。

重要决定：

| 项目 | 确定规则 |
|---|---|
| 扫描选择 A | 最后完整循环中的指定方向支线，默认电位递减 |
| 扫描选择 B | 最后完整的指定方向支线 |
| 人工调整 | 允许选择任何扫描段，包括不完整段，并留下记录 |
| 完整性 | 读取程序上下限，端点公差为 1.01 个采样步；不补造终点 |
| 起止电位 | 程序识别，无须用户手填 |
| 自动识别 | 文件名明确转速标记优先，兼容末尾数字推测；来源可查，人工值优先，编辑表格后确认应用 |
| 异常文件 | 单独报告，其他文件继续 |
| 电位 | 默认 RHE；保留原始电位，支持原始坐标预览 |
| 背景 | 可一对多；新 RRDE 可配对，盘扣盘环扣环；保留分别指定及旧项目绑定，同方向、按电位对齐、不外推 |
| 环图 | 跨样品比较，μA/mA、处理后/未扣背景；允许转速/环设定电位差异和缺失记录，阻止其他已知冲突 |
| iR | 默认关闭；用户明确剩余电阻与已补偿情况后开启 |
| 归一化 | I 内部为 A；新文件默认直径 5 mm、面积 π/16 cm²，可改尺寸或直接填面积；旧项目面积优先 |
| 条件输入 | 根据当前页面/纵轴显示必要条件，必填标注 *；其余高级设置折叠 |
| 设置生效 | 文件配置与全局坐标先汇入共享草稿，统一应用；来源和目标分开，默认当前组，切换不自动复制 |
| 组合操作 | 有草稿时支持应用并计算／导出／保存项目；分析先做任务预检查，合法缺项记录可单独应用保存 |
| 常用条件 | 载入到草稿，默认不覆盖人工非空值；一个保存入口选择项目／本机，不继承核对状态 |
| 平滑 | 默认关闭；仅极化曲线绘图 SG 二阶；11/21/51 点或自定义奇数窗口 |
| K–L | 表观 n；2e/4e 标为两路径模型估算 |
| RRDE | 过氧化物产率、n、两产物模型下的四电子比例 |
| 输出 | 优先导出当前绘图 CSV；各样品独立 XY；保留 PNG 300 dpi、SVG、完整数据、JSON 及 ZIP |
| 项目 | `.orrproj` ZIP 中包含原始文件、配置和设置，不使用 pickle |

## 2. 启动与开发环境

入口：`启动 ORR.cmd`、`停止 ORR.cmd`。两者优先调用项目虚拟环境：

```text
.venv\Scripts\pythonw.exe
```

未创建虚拟环境时通过 `pyw -3.13` 调用本机 Python Launcher。首次安装按 README 创建 `.venv` 并安装依赖，无需修改用户专属绝对路径。

实际验证版本：Python 3.13.7，Streamlit 1.61.0，NumPy 2.3.4，pandas 3.0.5，Matplotlib 3.10.8，SciPy 1.17.1。依赖在 `requirements.txt` 中固定。

启动器 `launch.py`：

- 仅监听 127.0.0.1，从 8765–8794 选择空闲端口。
- 服务地址形如 `http://127.0.0.1:8765/orr-workbench/`。
- 后台运行，日志为 `.runtime/server.log`，PID、进程创建时间和端口保存在 `.runtime/server.json`。
- 重复启动时复用本应用健康服务，停止时校验 PID 与创建时间。
- 健康检查绕开系统代理，避免本机请求被代理转发。
- `.streamlit/config.toml` 关闭文件监视和使用统计。改代码后需要停止并重启实际服务。

开发时可用控制台执行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.address=127.0.0.1 --server.fileWatcherType=auto
```

## 3. 代码结构

```text
orr_workbench/
  streamlit_app.py          应用入口、全局状态初始化、侧栏电位坐标、页面导航
  orr_core.py               纯数据解析和科学计算，不依赖 Streamlit
  plot_smoothing.py         独立绘图副本平滑、连续段/采样检查与记录
  experiment_conditions.py  纯参数校验、面积换算、预设存取与应用规则
  background_ph.py          独立的背景 pH 依赖、模式、来源及冲突解析
  background_pairing.py     配对背景通道和绑定校验
  ring_comparison.py        已知环图条件冲突及缺失记录审查
  settings_draft.py         不依赖 Streamlit 的草稿域、冲突检测和候选校验
  settings_editor.py        扫描／背景／背景 pH 编辑，只暂存不提交
  condition_ui.py           已应用／待修改摘要、来源和范围、条件与预设草稿
  origin_export.py          当前绘图数值到独立列组 CSV 的纯映射
  download_ui.py            统一导出区；校验成功后把固定字节交给 v2 下载桥
  ui_shared.py              共享草稿包装、统一应用、所选处理、状态、图形与导出
  launch.py                 Windows 本地启动与停止
  app_pages/
    import_data.py          导入、元数据核对、实验条件、扫描/通道/背景设置
    curves.py               分组叠图、样式设置、曲线导出
    kl.py                   物性、共同电位区间、K–L 拟合和模型估算
    rrde.py                 RRDE 比值、符号/阈值检查和选择性图
    export.py               独立导出、结果 ZIP、项目保存
  examples/                 本地可保留原始样例；公开包只使用标明 SYNTHETIC 的合成样例
  tests/test_core.py         已知答案、真实样例和异常边界数值测试
  tests/test_app.py          Streamlit AppTest 界面流程
  tests/test_launcher.py     本机健康接口与代理回归测试
  tests/test_smoothing.py    已知信号、缺口、短段、非均匀采样、关闭行为
  tests/test_rpm.py          转速写法、边界、来源、补空白与旧项目兼容
  tests/test_conditions.py   默认面积、用途校验、预设、隐藏参数及旧项目面积兼容
  tests/test_condition_draft.py  来源／范围隔离、预设接续手改、错误保留及统一提交
  tests/test_settings_draft.py   纯候选状态、冲突与事务校验
  tests/test_shared_draft_ui.py  共享候选、组合操作、错误与修订的界面回归
  tests/test_origin_export.py    独立网格、显示变量、缺口和数值 CSV 回读
  tests/browser_conditions.cjs  隔离服务上的条件表单与项目恢复验证
  tests/browser_rpm.cjs      真实浏览器上传、旧项目、补空白和保存恢复
  tests/create_rpm_browser_fixture.py  生成旧版项目浏览器夹具
  tests/browser_smoke.cjs    本机浏览器导航、截图、CSV/项目下载验证
  verification/             自动生成的验证产物，不作为原始实验结论
  docs/USER_GUIDE.md         用户操作说明
  docs/PROJECT.md            本文档
  docs/CHANGELOG.md          版本记录
  docs/tasks/RPM_FROM_FILENAME.md  已确认并完成的转速任务
  docs/tasks/SIMPLIFY_EXPERIMENT_INPUTS.md  简化条件与默认面积任务
  user_settings/            用户主动保存的本机预设（不纳入版本控制）
```

后续改公式或单位，应首先改 `orr_core.py` 并增加有独立正确答案的测试；不要只在页面中修改计算。

## 4. 数据流与关键接口

```text
TXT bytes
  -> parse_chi -> Trace（原字节、表头、列、SI/指定内部单位、SHA-256）
  -> default_config / infer_rpm_from_name -> 用户核对并编辑配置
  -> settings_draft -> 候选配置＋候选全局设置 -> 校验／统一应用
  -> scan_segments / select_segment -> 扫描段
  -> base_curve -> 可选原始总电流 iR + RHE 平移
  -> process_trace -> 背景插值、带符号相减、盘面积归一化
      -> plot_smoothing.smooth_for_plot -> 独立绘图副本（极化页）
      -> kl_calculate 或 rrde_calculate（未平滑数据）
  -> origin_export（当前图独立列组）或完整数据长表
  -> CSV / PNG / SVG / 参数 JSON / .orrproj
```

`Trace.values[:,0]` 始终为 V，后续电流列始终为 A。`disk_channel` 和 `ring_channel` 是**电流列的 0 起索引**，不含电位列。CSV 的 `row_1based` 是**原始数据区中 1 起的数据行编号**，不是含表头的文件总行号。

主要处理结果：

- `E_original_V`：原始电位；`E_V`：选定坐标、可选 iR 后的电位。
- `I_disk_raw_A`、`I_ring_raw_A`：原始盘环电流。
- `I_disk_background_A`、`I_ring_background_A`：实际参与并对齐后的背景。盘／完整处理未绑定背景可保留 0；环单通道未参与的背景保留 NaN。以处理状态判定未绑定、未参与或真实零背景，不从数值猜测。
- `I_disk_A`、`I_ring_A`：带符号扣背景后的电流。
- `I_disk_mA`、可选 `j_disk_mA_cm2`：显示与输出用列。
- RRDE：`peroxide_pct`、`n_RRDE`、`four_e_pct_model`、`valid_two_product_model`、`status`。
- K–L：`n_KL`、两条模型比例、斜率/截距/R²、斜率标准误和 n 标准误、状态。
- 仅极化页的平滑副本：`I_disk_smoothed_plot_only_A`、`I_disk_smoothed_plot_only_mA`、可选 `j_disk_smoothed_plot_only_mA_cm2`、`smoothing_plot_status`。所有原有列逐值保留。
- 当前盘／环图均记录 `plotted_current_value`、单位、通道和平滑开关；这些显示列随当前图变化，不能用于“未平滑科学列逐值不变”的比较，也不能作为 K–L／RRDE 输入。

文件 ID 为 SHA-256(name + NUL + raw) 的前 16 个十六进制字符；完整 SHA-256 用于原始字节校验。相同内容不同文件名可作为不同记录，便于重复实验。

### 文件名转速与来源（1.2.0）

`infer_rpm_from_name(name)` 是纯函数，只取 basename 的去扩展名部分，不读取目录、正文或用户后来修改的图例。返回 rpm、来源、状态、匹配片段及位置、候选和默认分组。

明确标记支持 `1600转`、`1600 转`、`1600转每分钟`、`1600rpm`、`1600 RPM`、`RPM1600`、`rpm=1600`、`转速1600`、`转速=1600`。英文不分大小写，匹配可位于名称中间。没有明确标记时兼容末尾分隔符后的 2–5 位整数，标为推测。

多个相同明确候选去重，不同候选冲突留空且不退回末尾数字。带小数、负号等无效标记不会拆取局部数字；rps 不转换。0 可以作为最终记录，但 K–L 使用原有大于零检查。明确标记预填仍需用户确认，不等于实验认证。

`RPM_FIELDS` 定义持久化字段：`rpm`、`rpm_source`、`rpm_status`、`rpm_matches`、`rpm_candidates`、`rpm_note`。来源为 filename_explicit、filename_legacy、manual、saved_project 或 none；状态独立区分 recognized、inferred、ambiguous、invalid、unsupported 等。`rpm_source_label()` 把冲突/无效情况优先显示为待填写。

`set_manual_rpm()` 验证非负有限值或空白，只有实际改值才记为 manual，单纯查看不会丢掉自动来源。`fill_missing_rpms()` 只补空白，0 和任何非空值都保留，不改现有分组。1.6.0 起，表格手改和补全都读取当前候选、进入明确的草稿域，统一应用后调用 `invalidate()`；不因展示识别结果自动提交。

默认分组移除明确匹配片段或旧式末尾数字，清理多余分隔符和空括号；不删除浓度、日期、扫描速度、重复编号等信息。冲突或无效时不盲目合并。人工分组和项目分组保留。

项目仍是 schema=1。恢复缺少完整 RPM 来源字段的旧项目时，用保存的 rpm（包括 None）覆盖新默认值，来源记为 saved_project，清空新推测依据；不能将旧人工值冒充新算法识别。新项目完整保留来源、匹配和候选。

## 5. 科学计算规则

### 背景 pH 联动（1.4.0）

新增 `background_ph_mode`（auto/follow/manual）、`background_ph_status`、`background_ph_sources`、`background_ph_detail` 与旧项目兼容标记。`background_ph.resolved_configs` 先读取完整配置快照，再按实际盘/环绑定建立入边，去重同一样品；同一背景只有一个有效 pH。模式为 auto 且没有独立值时采用 follow；已有值按独立记录保护。已知 pH 在绝对容差 1e-9 内一致才联动，未知值不反向补样品；不同已知值使 pH 失效并标明冲突。

`invalidate()` 在清空旧结果前同步派生状态，覆盖绑定、参数应用、预设、移除与恢复；`process_trace`、`pack_project`、`parameter_record` 和 `unpack_project` 独立重新解析，防止绕过 UI 使用陈旧值。原始坐标同样阻止明确冲突；实测 RHE 总偏移/已是 RHE 仍无需为了电位换算补 pH。不同的独立 pH 保留并提示，不自动伪造同条件。

1.6.0 起元数据和逐文件编辑先暂存；候选校验在副本上处理背景绑定、调用 `activate_ph_links` 并解析 pH，不因此改写已应用配置。统一应用后同步实际派生状态。旧项目缺少模式时保留独立 pH，包括空白；主动重新确认空背景绑定或开启 follow 后可采用新规则。解绑最后一个来源仅清理派生值，独立值保留。未复制参比、温度、气氛、面积或 N。

`apply_conditions(..., background_ph_edit=...)` 区分直接编辑背景与从样品批量应用：后者不会意外将 follow 变成 manual；前者改变 pH 时显式转为独立。跟随关系字段不进入常用预设白名单。具体审核和测试记录见 `REVIEW_1.4.0.md` 与 `VALIDATION.md`。

### 条件与默认值（1.3.0 引入，1.6.0 调整交互）

`condition_ui.common_parameter_form(purpose, ids, density, channels, subtract_background)` 在导入、绘图、K–L、RRDE 页面提供已应用／待修改摘要和默认折叠的编辑区。先选择本次文件，再按任务展示所需输入。`channels="disk"` 只核对盘背景，`"ring"` 只核对环背景；完整 RRDE 核对两者。

读取来源和应用目标独立；范围为“仅此文件／当前组／自选”，默认当前组。仅切换来源或范围不复制条件。输入真正变化时，在副本上调用 `apply_conditions(overwrite=True)`，将当前整套显示条件形成字段补丁，暂存到 `conditions:{source_id}` 编辑域；“复制当前条件到所选范围”是显式整套复制到草稿的动作，不是另一套提交按钮。切换上下文的首轮只读取，避免旧输入被投向新范围。

条件控件用来源、目标 ID、用途、修订和草稿重置计数组成的上下文，保留跨页状态；隐藏方式的已存参数不清空。成功暂存后不触发额外 `st.rerun()`，保证本次点击的计算／导出事件继续使用最后输入。预设显式载入后才刷新视图；即使来源不在目标范围，载入模板仍可显示并接续手改。原配置和可复用条件来源均不受显示控件隐式覆盖。

新字段：`disk_diameter_mm`、`area_mode`（diameter/area）、`parameter_sources`。新文件盘面积为 `math.pi*(5/20)**2`，显示可舍入，计算保留精度；直接面积模式清空直径避免标签矛盾。旧项目缺少尺寸字段时保留面积（包括 None），尺寸置 None，不推定成 5 mm；来源缺失如实记录。schema 保持 1。

`experiment_conditions` 不依赖 Streamlit。`snapshot_conditions` 使用白名单排除身份、rpm、背景、扫描、平滑及确认标志；`apply_conditions` 默认由调用者明确指定覆盖行为，保留无关字段，将面积作为一组更新，保护参比信息不被不同预设部分混合。默认补全允许用户主动选用的预设替换软件初始默认，不覆盖人工值。`missing_conditions` 按用途给提示；无效面积仅省略 j 并记录原因，mA/RRDE 仍可继续，K–L 的核心检查继续拒绝无效面积。

本机预设在 `user_settings/experiment_presets.json`，schema=1，白名单参数和原始来源随快照保存；临时文件加原子替换避免中途截断。读取失败回退为空并提示，不覆盖损坏原文件。没有自动套用下一批条件，也不再通过 common_defaults 跨组隐式继承。项目仍保存实际参数，不依赖可变的本机预设名称。

新增数值预设仅为用户明确指定的 5 mm 几何尺寸；pH、N 和实测偏移没有通用假定值。K–L 只包装已有 KOH 文献参数为方案选择，不新增其他电解液常数，不自动推定 NaOH 与 KOH 相同。

历史记录：1.3.1 修正“已填 pH 仍报缺失”的诊断体验，当时用 `unapplied_changes` 区分输入和已应用配置，阻止保存旧预设，并提供局部提交按钮和加入关联背景按钮。1.6.0 已由共享草稿、明确自选范围和统一应用替换这些交互；保存预设有草稿时先统一应用，再读取来源文件的已应用条件，位置通过“当前项目／本机”选择。条件来源仍可选择背景，背景编辑不要求面积/N。`linked_backgrounds` 和 `process_trace` 的背景错误上下文继续保留。

该历史补丁完整测试 66 项通过，新增两个界面回归和一个核心错误上下文测试；`tests/browser_ph.cjs` 当时在隔离服务上验证草稿提示、项目预设防误存、关联背景加入、应用后 K–L 可用和参数导出。现行交互的验证以 1.6.0 测试和 `VALIDATION.md` 为准，旧脚本按钮文案不能作为新实现依据。

### 5.1 扫描段

读取电位差符号，检测转折点，保留原始顺序。相邻支线共享转折点。以表头 High/Low E 和 Sample Interval 判定完整性；数据中四份样例均末端缺一个 1 mV 步，因此不能要求终点浮点数严格相等。

完整循环由相邻、方向相反且完整的两支线构成。初始半圈不会自动被算成完整循环。缺少程序上下限时仅能展示数据极值，自动选择拒绝认证完整性，提示手选。

### 5.2 RHE 与 iR

理论换算：

`E_RHE = E_vs_ref + E_ref_vs_SHE(T) + 2.303RT/F × pH`。

25°C pH 系数约 0.05916 V。参比偏移自身也依赖温度与内充液。内置参比数据仅用于 25°C，并记录来源；Hg/HgO 的文献数值差异需要优先用实际标定。

实测相对 RHE 总偏移：`E_RHE=E_vs_ref+offset`，不再加 pH。已是 RHE：不再平移。

iR：`E_corr=E_raw-I_anodic_positive_raw × R_remaining`。用未经背景扣除的有符号总盘电流；文件中阴极为正时先转换为阳极为正的电流约定。不要根据 Comp R / UC R 字段自动断定电位已校正或自动二次校正。

### 5.3 背景

分别选择样品与背景各自的完整圈/支线，要求同方向。背景程序范围可不同；记录范围、扫描速度、补偿字段及实验条件差异。采用同坐标电位插值，缺覆盖点为 NaN，禁止外推。

先带符号减背景，再形成反应正幅值，禁止直接取绝对值。非单调的校正电位不能可靠插值，会提示检查 iR 或手选段。环单列背景使用其唯一电流列，需核对环电流的符号约定。

### 5.4 RRDE

令 D 为盘还原电流正幅值、R 为环氧化电流正幅值、N 为收集效率：

`peroxide%=200*(R/N)/(D+R/N)`；`n=4*D/(D+R/N)`。

`four_e%=100-peroxide%` 仅适用于两产物模型。使用实际电流 A；不分别用盘面积和环面积归一化后代入。N 是 0–1 数值，不是百分数。

默认盘阈值 1e-9 A，可修改。盘符号不符、盘过小、环符号不符、未覆盖背景点不会计算比例。大于 100% 或 n 小于 2 的结果保留但标为超出模型范围。

### 5.5 K–L

`omega=2*pi*rpm/60`，使用 rad/s。

`1/j=intercept+slope*omega^(-1/2)`，j 使用正阴极幅值 A/cm²。

`n=1/[slope*0.62*F*D^(2/3)*nu^(-1/6)*C]`。

C：mol/cm³；D、ν：cm²/s。j 已除面积，因此 B 中不能再乘面积。`two_e%=50*(4-n)`、`four_e%=50*(n-2)` 是两路径模型估算。

只在共同覆盖电位区间分析；各文件必须同参比坐标、pH、温度、电解液、面积及扫描方向。重复转速需手动选择一条。两个转速能求线，但没有足够自由度评估 R² 或斜率标准误；相应结果为 NaN。

斜率标准误按普通最小二乘计算，n 标准误只传播斜率不确定度，不含物性、面积、仪器、气压等系统误差。非正斜率、负截距、n 超出 2–4 都会显示原因。默认不裁剪。

0.1 M KOH、25°C、O₂ 饱和文献预设：C=1.2e-6、D=1.9e-5、ν=0.01。不得从样例的 `0.1MNa` 名称自动套用这组 KOH 参数。

公式出处见 README 与参数导出中的 `sources` 字段。

### 5.6 仅绘图平滑

用户明确确认：只处理极化曲线显示，默认关闭；默认叠加浅色未平滑参考线并允许隐藏；同图统一参数。算法为 SciPy Savitzky–Golay，固定 polyorder=2、deriv=0、mode=interp，窗口弱/中/强=11/21/51 点，自定义 5–1001 奇数点。奇数是产品的居中对齐约定，不是当前 SciPy API 强制要求。

`smooth_for_plot(frame, settings)` 返回深拷贝和报告，不替换 `I_disk_A` 或任何原有列，也不修改传入表。K–L/RRDE 仍直接从 `process_trace` 的未平滑数据读取，不能把平滑副本送回公共计算入口。

有限电位且有限电流组成连续有效段；NaN/无效点保留为缺口，不拼接左右数据。窗口不能跨越缺口或反向支线。段长不足窗口时保留原值，不自动缩窗。电位严格单调、无重复，并满足步长相对中位值 1% + 1e-9 V 公差才平滑；不均匀/重复/非单调时保留原值，不重采样。

报告包含算法、SciPy 版本、窗口、阶数、端部模式、容差、逐段实际步长/窗口跨度、平滑/保留/缺口计数和原因。报告段索引是当前所选处理支线中的 0 起索引。端部多项式估计会改变端点，可能过冲；不要把平滑解释为真实信号恢复或峰形不变。

盘图／环图的完整数据表分别保留独立平滑列和显示状态；`all_curves.csv` 保持未平滑公共处理数据。绘图 CSV 从同一份绘图副本的当前实线取值，开启时变量名称包含 `smoothed_plot_only`。图片页脚标明仅绘图平滑及窗口阶数。

## 6. 状态、缓存与保存

状态统一在 `ui_shared.initialize()` 初始化。`traces`、`configs`、`settings` 为已应用主状态；`revision` 是数据／科学配置修订号；`results`、`exports` 是当前有效结果。`settings_draft` 记录基础修订号和按域划分的逐文件／全局补丁；`draft_epoch` 只在应用、明确放弃或数据重置时递增，普通暂存不递增。控件值、编辑器显示快照与共享业务草稿分开，收起或跨页不等于提交。

`settings_draft.py` 的 `stage_config`／`stage_settings` 检测独立编辑域对同一叶字段的矛盾修改；同域后续编辑允许覆盖前值。`candidate` 在深拷贝上合并，核对基础修订、数值／结构、有效通道、人工段、背景图及 pH 解析；缺少任务输入或共享 pH 冲突可保留为合法待解决记录。没有草稿时普通预览可读取已应用副本，不因无关任务字段阻止原始电流预览。

`ui_shared.stage_config_updates`／`stage_settings_updates` 剪除与已应用值相同的叶字段，维护按域错误及拒绝编辑，避免另一控件成功重跑清除错误。条件本地校验失败同样登记到对应域，用户在该域修正（包括修回原值）或明确放弃后才能解除。`get_draft_configs`／`get_draft_settings` 提供编辑读取；`pending_candidate` 用于提交与任务快照。

`apply_pending_settings(preflight=None)` 统一取得合法候选，先执行需要的任务预检查，再一次提交 `configs` 和科学 `settings`，最后 `invalidate()` 递增修订并清除旧结果／导出。失败保留草稿，不提交半份文件配置或只提交全局坐标。普通“应用设置”和保存项目允许合法缺项；“应用并计算／导出”检查所选任务实际依赖，不静默剔除 K–L 转速。成功提交后发生任务生成错误时，按已应用的新修订报告失败，不恢复旧结果伪装成功。

K–L／RRDE 都保留明确计算动作，使用本次输入签名及修订保存结果。选择、物性／区间、阈值等分析输入变化时清理相应旧结果；其他未参与文件的普通缺项不作为当前文件选择的错误。图形设置独立保留，平滑等只影响对应图表。

平滑配置保存于 `settings.plot.smoothing`，逐文件处理报告于 `settings.plot.smoothing_report`。极化页更新时 `clear_polarization_exports()` 只清除旧极化图/表/参数和旧平滑报告，不递增计算修订号、不清空 K–L/RRDE 结果。科学配置变动仍用 `invalidate()` 并移除过时平滑报告。

平滑设置随 schema=1 项目原样保存；不增加逐文件 config 字段，不改变项目 schema。旧项目没有该设置时默认关闭。平滑控件 key 含当前 revision，使项目恢复后使用恢复设置而非旧控件值。

只缓存文件解析，`st.cache_data(max_entries=40)`。单批规模很小，数值处理实时计算。文件选项格式化使用不可变标签快照，避免跨线程/测试状态读取问题。

### Origin 绘图 CSV 与下载交接（1.6.0）

`origin_export.py` 只映射已有绘图／计算值，不负责插值、平滑、裁剪或重采样。极化／环图每样品一组独立 XY，RRDE 每样品一组 E／过氧化物率／n／四电子比例；K–L 结果保持共同 E，拟合图按各分析电位输出 X／Y／Yfit 列组。序列使用位置顺序横向并置，保留内部 NaN，短列尾部为空；不依赖样品索引对齐。样品名加稳定 ID 前缀区分重名，短前缀冲突时确定性延长。`csv_bytes` 使用 UTF-8 BOM、无索引、单行表头和 `%.17g` 精度。CSV 不能携带 Origin 的列指定元数据，用户导入后按独立 XY 组设置。

盘／环图的列名从明确的通道、单位、轴和平滑状态生成，Y 值直接使用 `plotted_current_value`，与实线共用变量来源；浅色未平滑参考线不替代当前实线。完整长表及分析有效性状态仍独立保留，便于核查科学数据。

`download_ui.result_downloads` 提供统一“绘图 CSV／PNG”和“更多导出”区域。无草稿的既有图像／表格可用原生下载；有草稿时这些旧字节禁用。组合导出用普通按钮在页面线程内处理最后输入、任务校验、统一提交和字节生成，然后 `send_download` 把已校验的固定字节、文件名、MIME、一次性 token 交给小型 Streamlit v2 组件。该组件只创建 Blob 下载，不读取或修改科学状态，也不承担计算／提交；生成失败时不向浏览器发送旧字节。不要改回“先把旧字节传给下载按钮，再期望回调替换”的模式，也不要在普通输入暂存后重跑而丢弃同次按钮事件。

项目 schema=1：

```text
project.json
  schema / app_version / settings
  files[]: id / name / path / sha256 / config
raw/<id>.txt
```

只在内存读取 ZIP，不向文件系统解压路径。加载时验证版本、总体大小、原字节 SHA 和 ID。项目保存通过统一应用后打包已应用原始数据和设置，不把控件草稿或本机预设名称当作真实配置；合法缺项、共享 pH 冲突可以保存，恢复后仍需解决才能分析。结果表与图片不保存在项目中，恢复后明确重新计算。结果 ZIP 与项目文件用途不同。

## 7. 验证依据

1.6.0 新增共享草稿、条件范围、下载修订和 Origin CSV 数值映射测试；本轮数量与执行结果统一记录在 `VALIDATION.md`。`tests/browser_ui_simplification.cjs` 使用独立服务和合成项目检查实际输入、点击与下载，不操作用户正在分析的浏览器会话。下列早期版本及真实样例信息保留作历史方法依据。

四份真实样例：

| 文件 | 点数 | 程序范围/V | 数据列 |
|---|---:|---|---|
| O-0.1MNa-5mv-1225.txt | 3600 | −0.8 ～ 0.1 | Potential/V, Current/A |
| O-0.1MNa-5mv-900.txt | 3600 | −0.8 ～ 0.1 | Potential/V, Current/A |
| Ar-5mv-beijing.txt | 5000 | −1.15 ～ 0.1 | Potential/V, Current/A |
| 盘环-o-CS-第二个电极.txt | 4000 | −0.9 ～ 0.1 | Potential/V, i1/A, i2/A |

全部为 CV、4 段、5 mV/s、1 mV 采样步。盘环文件第二电极设定为 0.2 V，但没有写明物理盘环接线、参比、pH、N、面积或转速。pH/N 等仍需用户提供；5 mm 几何尺寸是用户指定的软件默认，不是从文件测得。测试条件不是实际实验结论。

测试命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

1.3.0 验证基线：63 项测试通过，保留 1.2.0 的 49 项，新增 9 项条件单元测试和 5 项界面流程。最后一次完整运行中，10 个 3600 点文件解析与提取约 0.133 秒（本机单次运行，不含界面和绘图）。详细证据见 `VALIDATION.md`。

条件浏览器验证：`tests/browser_conditions.cjs` 默认连接临时服务 `http://127.0.0.1:8766/orr-workbench/`，或读取环境变量 `ORR_TEST_URL`。它使用独立浏览器会话，不操作用户当前页面；覆盖 RHE 显隐、有效 0 V 偏移、5 mm 面积、4 mm 同组修改、RRDE 不要求面积、K–L 方案与项目下载恢复。本机预设的磁盘保存和重启复用由临时目录中的单元及 AppTest 验证，不向用户的真实预设写入测试条件。

浏览器验证：`tests/browser_smoke.cjs`，使用 Codex 内置 Node/Playwright 与已安装浏览器，仅访问本地应用。验证导入、扫描预览、曲线、CSV 下载、项目下载和项目恢复。报告和截图在 `verification/`。

转速浏览器验证：先运行 `tests/create_rpm_browser_fixture.py`，再执行 `tests/browser_rpm.cjs`。使用真实 CV 字节配合合成文件名和旧版配置，验证实际上传、冲突、旧值保护、补空白、旧导出失效和新项目恢复。报告为 `verification/rpm_browser_report.json`；测试转速配置不代表真实实验结论。

## 8. 已知限制与改进顺序

1. **实验数据扩充**：先增加更多真实转速、不同内充液/参比、真正中途截断和多圈数据；用人工核验的扫描范围作回归依据。
2. **背景匹配**：当前以明确选择和人工核对为准，可增加按气氛、电解液、转速、扫描速率和电极配置评分的匹配建议，不能自动当作已确认配对。
3. **重复实验**：当前 K–L 同转速重复文件要手选，可增加显式平均/误差条和重复组，而不是静默合并。
4. **更多导入格式**：当前不解析辰华二进制，不支持任意缺表头 CSV；有真实样例后增加适配器，不依赖固定行数。
5. **项目迁移与校验**：若增加字段或重构结构，保持 schema 迁移，并扩充错误类型/字段边界校验。
6. **图形体验**：可加入鼠标缩放、分析电位点击选择、多个组一键输出各自图片，以及每文件独立命名的图形批导出。现有图形参数和矢量输出应保留。
7. **方法扩展**：可加入 RRDE 固定电位 i–t 稳态区间、环信号时滞、收集效率标定及不同温度物性，但每项都需要相应数据和方法验证。

目前同类图片用固定文件名，导出页保留当前最后生成的该类图片；要保存多个组的图，请分别下载，或后续改为按实验组命名。第一版以本机 Windows 为目标，换电脑后按 README 安装 Python 3.13 和项目依赖。

## 9. 后续会话接手清单

1.6.0 的已确认设计和完成记录见 [操作简化工作计划](tasks/UI_SIMPLIFICATION_WORK_PLAN.md)。后续修改入口应先理解 `settings_draft`、UI 暂存包装、候选任务检查及下载字节交接：同一编辑器的后续手改可以更新草稿，独立编辑域的矛盾修改必须显式解决；一次组合动作不能读到旧结果，也不能因输入暂存后无条件重跑而吞掉下载事件。项目 schema 仍为 1，草稿状态本身不序列化。

1.5.0 的环图与背景配对见 [任务及完成记录](tasks/RING_CURRENT_COMPARISON_AND_PAIRED_BACKGROUND.md)。新增 `background_pairing.py` 提供原子绑定校验，`ring_comparison.py` 只比较已知条件，不把未知判为一致；数值比较采用小容差，文本做空白与大小写规范化，不猜电解液等价。

`process_trace(..., channels="all", subtract_background=True)` 保留旧默认；环图使用 `channels="ring"`，只检查实际参与环背景，iR 仍通过 `base_curve(..., require_disk=False)` 内部的 iR 分支读取必要盘电流。环图关闭背景处理时保留绑定、输出未参与状态及 NaN 背景；`processing` 随参数记录。科学公式保持原样。

配置新增 `background_mode`：新 RRDE 为 `paired`，旧项目缺字段时迁移为 `independent`，不覆盖旧绑定。项目设置增加 `plot_channel`、`ring_plot`（unit、background_view、selection_by_group、comparison_audit、smoothing 等），原盘图继续使用 `plot`；schema 仍为 1，字段由默认配置白名单持久化。

`smooth_for_plot(..., channel="ring")` 生成独立环绘图列，旧调用默认处理盘。`clear_polarization_exports(channel)` 只清理当前图类和过期参数，不清除 K–L/RRDE；科学输入改变仍统一 `invalidate()`。背景模式、通道选择和批量提交经 `apply_background_binding` 校验后才提交，防止半更新；下拉框空值用具体 UI 哨兵后再转换为 None，避免旧值恢复。

K–L 异常结果的排查记录见 [参数审查](tasks/KL_PARAMETER_AUDIT.md)。相关修复已并入 1.5.0，增加区间/单位/实际输入提示，修复电解液批量同步与失败重算残留结果；导出 K–L 参数增加 `axis`、`units`，不改变原始字段或项目 schema。实际异常项目仍待用户提供，不应把敏感性检查使用的 KOH 物性当作其 Na 电解液实际参数。

1. 先读本文件、README 和 CHANGELOG，保留已经确认的科学口径。
2. 确认需求改动属于导入、计算、UI 还是部署；不要把未知实验参数补成默认真实值。
3. 修改核心时用独立已知答案测试验证单位、符号和模型边界。
4. 修改配置时检查 `default_config`、项目序列化、表单和结果失效四处是否同步。
5. 重跑相关测试；页面变动用真实浏览器检查图、表格和下载。
6. 更新本文件和 CHANGELOG，记录新增字段、schema 变化及未解决限制。
