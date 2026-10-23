# ORR Worker 1.7.0-dev 本轮实施与验证

日期：2026-10-23。状态：本机实现与集成验收完成，本次按用户授权同步 GitHub 源码，保留 1.7.0-dev 标识；稳定版记录仍为 1.6.0。

## 2026-10-23 后续补充

新导入文件现在默认 pH 13、SCE（饱和 KCl，25 °C，0.241 V vs SHE），标为软件默认且可修改。旧项目原人工值、显式空值及缺字段历史状态保留，不会被新默认补写。删除“转速识别依据与需要核对的记录”展示区；识别依据与候选仍进入参数和项目，转速表格可手动编辑。

新增 test_default_reference 的 5 项验证；旧缺条件测试改为显式缺项夹具，继续验证缺项阻断。原批量与背景继承阶段为 272 项通过，本次全量为 277 项通过。

## 已完成的需求

- 集成 Qoder 交付的背景条件 UI 与测试；跟随、独立、旧版 pH 策略及 schema=2 保持既定契约。
- 新导入 RRDE 的 N 默认 0.369，明确软件来源；可手改，旧非空 N 不覆盖。旧空值载入不补写，仅在 RRDE 编辑中提供待应用默认。
- 移除四个指定区块：补充实验记录、重复盘环条件表、低电流阈值控件、常用条件保存／复用。旧电解液、来源、项目预设、本机预设文件和有效旧阈值保留。
- 批量扫描／背景支持当前组、全部样品、自选；用中文预览目标、修改内容及人工段清除，加入统一草稿后一次应用。非法批次无部分暂存，跨域矛盾不以覆盖解决。
- 未识别、冲突、已识别转速均可手改；全空列仍为可编辑数值列。人工来源与识别依据保留，完整 CSV 新增实际 rpm、rpm_source。
- K–L 条件差异列出文件和字段，旧电解液差异按需修正；符号、阈值、模型范围和未平滑科学计算规则不变。

## 修复的集成问题

1. 背景模式切换原来会清掉其他条件编辑域中的整份背景补丁。现只撤回该背景的条件策略相关字段及其来源，保留面积、电解液和其他目标的草稿；失败恢复原草稿。
2. 空 N 的默认草稿在后续渲染中可能被误认为新的整组修改，覆盖同组已有 N。现区分默认补空、明确修改和复制意图，并验证默认应用后再改 pH 不覆盖已有 N。
3. 转速整列为空时，表格可能推断为非数值列。现固定浮点类型，捕获非法输入并整次拒绝。
4. 批量明确选择与已应用值相同时，仍保留该意图以检测其他域的反向修改；此类拒绝不自动重放。全“保持”操作不会撤回已有批量草稿。

## 自动回归

环境：Windows、Python 3.13、Streamlit 1.61.0，依赖沿用 requirements.txt。

| 检查 | 结果 | 证据 |
|---|---|---|
| Qoder 交付独立复核 | 247 项通过，失败 0，错误 0，约 47.54 秒 | verification/background_conditions_lyg40n7v/result.json |
| 最终全量回归 | **277 项通过，失败 0，错误 0**，约 55.61 秒 | verification/background_conditions_ff_r8o87/result.json |

新增／更新测试覆盖默认 N 独立正确答案、旧 N／空值往返、阈值恢复与非法阈值、批量扫描／绑定、单通道混选整次拒绝、模式切换保留无关草稿、范围替换和冲突、空转速列与人工改值、完整 CSV 来源、隐藏记录保护及 K–L 按需纠正。旧控件断言改测新的行为，仍保留后台预设兼容和科学结果验证。

回归使用 tools/verify_background_conditions.py 创建独立源码副本；仅使用程序生成的合成示例或内存生成数据，预设路径隔离。中间开发检查有失败并已修正，最终结果以上表为准。

## 真实浏览器验证

对同一最终源码副本运行四组 Playwright 流程，**4/4 通过**，各流程未捕获页面异常。

| 脚本 | 覆盖 |
|---|---|
| browser_conditions.cjs | 默认 SCE／pH 13、转速详情区移除、按方法显隐、实测零偏移、默认 5 mm／面积精度、组内修改、N=0.369、K–L 文献参数显隐、项目往返 |
| browser_background_conditions.cjs | 共享冲突只读、有效条件复制门控、独立缓存编辑、跟随／独立往返、持久化与有效投影分离 |
| browser_background_ph.cjs | 旧版 pH 策略冲突、独立值保留、恢复跟随、参比独立及项目往返 |
| browser_batch_controls.cjs | 全空转速列连续手填两行、冲突／已识别值修改、10 文件批次（9 RRDE＋1 背景）、逐文件选完整段、盘环配对、旧 N／阈值保留、四区块移除、RRDE 计算和项目往返 |

总报告：verification/background_conditions_ff_r8o87/verification/simplified_browser_report.json。四份逐项报告、日志与截图位于同一目录。代表截图：batch_scan_background_preview.png、rrde_simplified_results.png、background_conditions_conflict.png。

表格为画布渲染，浏览器脚本等待单元格编辑器实际出现后输入；最终以下载的参数和项目恢复记录核对，不能只凭画布截图认定数据已保存。合成背景与样品使用匹配方向，未绕过背景手选段方向检查。

tools/verify_simplified_browser.py 在 **8766 自有隔离服务**上运行，完成后报告 owned_service_stopped=true；user_service_touched=false、real_samples_read=false。未操作用户 8765 会话、真实实验文件或本机预设，未安装新依赖。

## 范围与后续

- 本轮未重新验证所有仪器导出格式、Windows 安装流程或性能极限；浏览器未单独走新版等待／未绑定状态，这些由 AppTest 和纯业务回归覆盖。
- 本轮保留原科学公式；N=0.369 是用户指定的软件默认，不能代替实际标定，环检测确认仍需按实验判断。
- schema=2 项目需要新版读取，旧版 1.6.0 会拒绝。更新后应先下载当前分析项目，再停止并重新启动应用以载入新代码；本轮未重启用户服务。
- 当前工作区为 1.7.0-dev；用户已授权本次追加 GitHub 源码提交，不创建 Release 或标签。发布范围见 PUBLICATION.md。

## 复现

在项目目录使用安装了固定依赖的 Python：

```powershell
python -X utf8 tools/verify_background_conditions.py
python -X utf8 tools/verify_simplified_browser.py verification/<上一步生成的隔离目录>
```

浏览器验证需要 Node 与 Playwright／Edge，为可选开发工具，不是普通使用依赖。测试会检查 8766 空闲，不能借用或停止其他服务。源码匹配摘要见 verification/default_reference_final_manifest.json。
