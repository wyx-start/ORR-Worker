# ORR Workbench 项目说明

版本：1.3.1。首次交付：2026-10-14；本次更新：2026-10-15。本文件供后续开发者或 Codex 会话继续改进。

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
| 背景 | 可一对多，盘和环分别指定；同方向、按电位对齐、不外推 |
| iR | 默认关闭；用户明确剩余电阻与已补偿情况后开启 |
| 归一化 | I 内部为 A；新文件默认直径 5 mm、面积 π/16 cm²，可改尺寸或直接填面积；旧项目面积优先 |
| 条件输入 | 根据当前页面/纵轴显示必要条件，必填标注 *；其余高级设置折叠 |
| 常用条件 | 项目内预设 + 主动保存的本机预设；主动套用，默认不覆盖人工非空值，不继承核对状态 |
| 平滑 | 默认关闭；仅极化曲线绘图 SG 二阶；11/21/51 点或自定义奇数窗口 |
| K–L | 表观 n；2e/4e 标为两路径模型估算 |
| RRDE | 过氧化物产率、n、两产物模型下的四电子比例 |
| 输出 | PNG 300 dpi、矢量 SVG、UTF-8 BOM CSV、JSON；可独立或 ZIP 下载 |
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
  condition_ui.py           按用途显示条件、默认项、必填摘要及预设界面
  ui_shared.py              扫描/背景表单、批量状态、图形、导出工具
  launch.py                 Windows 本地启动与停止
  app_pages/
    import_data.py          导入、元数据核对、实验条件、扫描/通道/背景设置
    curves.py               分组叠图、样式设置、曲线导出
    kl.py                   物性、共同电位区间、K–L 拟合和模型估算
    rrde.py                 RRDE 比值、符号/阈值检查和选择性图
    export.py               独立导出、结果 ZIP、项目保存
  examples/                 用户提供的四份 TXT 副本
  tests/test_core.py         已知答案、真实样例和异常边界数值测试
  tests/test_app.py          Streamlit AppTest 界面流程
  tests/test_launcher.py     本机健康接口与代理回归测试
  tests/test_smoothing.py    已知信号、缺口、短段、非均匀采样、关闭行为
  tests/test_rpm.py          转速写法、边界、来源、补空白与旧项目兼容
  tests/test_conditions.py   默认面积、用途校验、预设、隐藏参数及旧项目面积兼容
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
  -> scan_segments / select_segment -> 扫描段
  -> base_curve -> 可选原始总电流 iR + RHE 平移
  -> process_trace -> 背景插值、带符号相减、盘面积归一化
      -> plot_smoothing.smooth_for_plot -> 独立绘图副本（极化页）
      -> kl_calculate 或 rrde_calculate（未平滑数据）
  -> CSV / PNG / SVG / 参数 JSON / .orrproj
```

`Trace.values[:,0]` 始终为 V，后续电流列始终为 A。`disk_channel` 和 `ring_channel` 是**电流列的 0 起索引**，不含电位列。CSV 的 `row_1based` 是**原始数据区中 1 起的数据行编号**，不是含表头的文件总行号。

主要处理结果：

- `E_original_V`：原始电位；`E_V`：选定坐标、可选 iR 后的电位。
- `I_disk_raw_A`、`I_ring_raw_A`：原始盘环电流。
- `I_disk_background_A`、`I_ring_background_A`：对齐后的背景。无背景时为 0，但处理记录明确标记未扣背景。
- `I_disk_A`、`I_ring_A`：带符号扣背景后的电流。
- `I_disk_mA`、可选 `j_disk_mA_cm2`：显示与输出用列。
- RRDE：`peroxide_pct`、`n_RRDE`、`four_e_pct_model`、`valid_two_product_model`、`status`。
- K–L：`n_KL`、两条模型比例、斜率/截距/R²、斜率标准误和 n 标准误、状态。
- 仅极化页的平滑副本：`I_disk_smoothed_plot_only_A`、`I_disk_smoothed_plot_only_mA`、可选 `j_disk_smoothed_plot_only_mA_cm2`、`smoothing_plot_status`。所有原有列逐值保留。

文件 ID 为 SHA-256(name + NUL + raw) 的前 16 个十六进制字符；完整 SHA-256 用于原始字节校验。相同内容不同文件名可作为不同记录，便于重复实验。

### 文件名转速与来源（1.2.0）

`infer_rpm_from_name(name)` 是纯函数，只取 basename 的去扩展名部分，不读取目录、正文或用户后来修改的图例。返回 rpm、来源、状态、匹配片段及位置、候选和默认分组。

明确标记支持 `1600转`、`1600 转`、`1600转每分钟`、`1600rpm`、`1600 RPM`、`RPM1600`、`rpm=1600`、`转速1600`、`转速=1600`。英文不分大小写，匹配可位于名称中间。没有明确标记时兼容末尾分隔符后的 2–5 位整数，标为推测。

多个相同明确候选去重，不同候选冲突留空且不退回末尾数字。带小数、负号等无效标记不会拆取局部数字；rps 不转换。0 可以作为最终记录，但 K–L 使用原有大于零检查。明确标记预填仍需用户确认，不等于实验认证。

`RPM_FIELDS` 定义持久化字段：`rpm`、`rpm_source`、`rpm_status`、`rpm_matches`、`rpm_candidates`、`rpm_note`。来源为 filename_explicit、filename_legacy、manual、saved_project 或 none；状态独立区分 recognized、inferred、ambiguous、invalid、unsupported 等。`rpm_source_label()` 把冲突/无效情况优先显示为待填写。

`set_manual_rpm()` 验证非负有限值或空白，只有实际改值才记为 manual，单纯确认不会丢掉自动来源。`fill_missing_rpms()` 只补空白，0 和任何非空值都保留，不改现有分组。手改表格需先提交表单；补全按钮读取的是已应用配置。数值变动后调用 `invalidate()`；没有填入任何值时只更新识别说明和参数导出，不使有效计算失效。

默认分组移除明确匹配片段或旧式末尾数字，清理多余分隔符和空括号；不删除浓度、日期、扫描速度、重复编号等信息。冲突或无效时不盲目合并。人工分组和项目分组保留。

项目仍是 schema=1。恢复缺少完整 RPM 来源字段的旧项目时，用保存的 rpm（包括 None）覆盖新默认值，来源记为 saved_project，清空新推测依据；不能将旧人工值冒充新算法识别。新项目完整保留来源、匹配和候选。

## 5. 科学计算规则

### 条件与默认值（1.3.0）

`condition_ui.common_parameter_form(purpose, ids, density)` 在导入、绘图、K–L、RRDE 页面提供条件摘要和折叠编辑区。方式选择在表单批处理外触发显隐，数值暂存为 widget 草稿，只有点击“应用实验参数”才写入 configs。条件 widget 使用文件 ID、revision 和 session 持久化键；隐藏的方式参数不会被空值覆盖。页面标题与来源摘要是核对入口，最终计算仍在核心层校验。

新字段：`disk_diameter_mm`、`area_mode`（diameter/area）、`parameter_sources`。新文件盘面积为 `math.pi*(5/20)**2`，显示可舍入，计算保留精度；直接面积模式清空直径避免标签矛盾。旧项目缺少尺寸字段时保留面积（包括 None），尺寸置 None，不推定成 5 mm；来源缺失如实记录。schema 保持 1。

`experiment_conditions` 不依赖 Streamlit。`snapshot_conditions` 使用白名单排除身份、rpm、背景、扫描、平滑及确认标志；`apply_conditions` 默认由调用者明确指定覆盖行为，保留无关字段，将面积作为一组更新，保护参比信息不被不同预设部分混合。默认补全允许用户主动选用的预设替换软件初始默认，不覆盖人工值。`missing_conditions` 按用途给提示；无效面积仅省略 j 并记录原因，mA/RRDE 仍可继续，K–L 的核心检查继续拒绝无效面积。

本机预设在 `user_settings/experiment_presets.json`，schema=1，白名单参数和原始来源随快照保存；临时文件加原子替换避免中途截断。读取失败回退为空并提示，不覆盖损坏原文件。没有自动套用下一批条件，也不再通过 common_defaults 跨组隐式继承。项目仍保存实际参数，不依赖可变的本机预设名称。

新增数值预设仅为用户明确指定的 5 mm 几何尺寸；pH、N 和实测偏移没有通用假定值。K–L 只包装已有 KOH 文献参数为方案选择，不新增其他电解液常数，不自动推定 NaOH 与 KOH 相同。

1.3.1 修正“已填 pH 仍报缺失”的诊断体验：`unapplied_changes` 区分编辑草稿和已应用配置，未应用时阻止把旧配置保存为常用条件。`linked_backgrounds` 检查样品实际依赖的背景，摘要显示背景的换算缺失；`process_trace` 捕获背景基础处理错误并附背景名称和通道。条件来源可选择背景，背景编辑不要求面积/N。用户主动点击加入关联背景时，回调仅更新目标控件，不覆盖参数；仍由“应用实验参数”提交并使旧结果失效。

本补丁完整测试 66 项通过，新增两个界面回归和一个核心错误上下文测试；`tests/browser_ph.cjs` 在隔离服务上验证草稿提示、项目预设防误存、关联背景加入、应用后 K–L 可用和参数导出。未修改用户实际会话或本机常用配置。

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

只在 `polarization_data.csv` 中增加平滑列；`all_curves.csv` 保持未平滑处理数据。图片页脚标明仅绘图平滑及窗口阶数。

## 6. 状态、缓存与保存

状态统一在 `ui_shared.initialize()` 初始化。`traces`、`configs`、`settings` 为主状态；`revision` 是数据/实验配置修订号；`results`、`exports` 是当前结果。

修改导入数据、分组、实验条件、扫描、背景或电位坐标后，调用 `invalidate()`：递增修订号，并清空旧结果和旧导出，避免下载过时计算。图形设置单独保留在 `settings.plot`。K–L 是提交表单后计算，显示“上次计算”参数含义；RRDE 与当前阈值一起计算。

平滑配置保存于 `settings.plot.smoothing`，逐文件处理报告于 `settings.plot.smoothing_report`。极化页更新时 `clear_polarization_exports()` 只清除旧极化图/表/参数和旧平滑报告，不递增计算修订号、不清空 K–L/RRDE 结果。科学配置变动仍用 `invalidate()` 并移除过时平滑报告。

平滑设置随 schema=1 项目原样保存；不增加逐文件 config 字段，不改变项目 schema。旧项目没有该设置时默认关闭。平滑控件 key 含当前 revision，使项目恢复后使用恢复设置而非旧控件值。

只缓存文件解析，`st.cache_data(max_entries=40)`。单批规模很小，数值处理实时计算。文件选项格式化使用不可变标签快照，避免跨线程/测试状态读取问题。

项目 schema=1：

```text
project.json
  schema / app_version / settings
  files[]: id / name / path / sha256 / config
raw/<id>.txt
```

只在内存读取 ZIP，不向文件系统解压路径。加载时验证版本、总体大小、原字节 SHA 和 ID。结果表与图片不保存在项目中，而是在恢复参数后重新计算。结果 ZIP 与项目文件用途不同。

## 7. 验证依据

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
2. **背景匹配**：当前只有单背景的候选预填与人工核对，可增加按气氛、电解液、转速、扫描速率和电極配置评分的匹配建议，不能自动当作已确认配对。
3. **重复实验**：当前 K–L 同转速重复文件要手选，可增加显式平均/误差条和重复组，而不是静默合并。
4. **更多导入格式**：当前不解析辰华二进制，不支持任意缺表头 CSV；有真实样例后增加适配器，不依赖固定行数。
5. **项目迁移与校验**：若增加字段或重构结构，保持 schema 迁移，并扩充错误类型/字段边界校验。
6. **图形体验**：可加入鼠标缩放、分析电位点击选择、多个组一键输出各自图片，以及每文件独立命名的图形批导出。现有图形参数和矢量输出应保留。
7. **方法扩展**：可加入 RRDE 固定电位 i–t 稳态区间、环信号时滞、收集效率标定及不同温度物性，但每项都需要相应数据和方法验证。

目前同类图片用固定文件名，导出页保留当前最后生成的该类图片；要保存多个组的图，请分别下载，或后续改为按实验组命名。第一版以本机 Windows 为目标，换电脑后按 README 安装 Python 3.13 和项目依赖。

## 9. 后续会话接手清单

1. 先读本文件、README 和 CHANGELOG，保留已经确认的科学口径。
2. 确认需求改动属于导入、计算、UI 还是部署；不要把未知实验参数补成默认真实值。
3. 修改核心时用独立已知答案测试验证单位、符号和模型边界。
4. 修改配置时检查 `default_config`、项目序列化、表单和结果失效四处是否同步。
5. 重跑相关测试；页面变动用真实浏览器检查图、表格和下载。
6. 更新本文件和 CHANGELOG，记录新增字段、schema 变化及未解决限制。
