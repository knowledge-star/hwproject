# 华为小艺 Work 接入指南

## 状态与目标

**当前选定路径：**小艺从 GitHub 拉取项目到云沙箱，主会话调度独立回答/反思会话，项目通过文件暂停与恢复；使用现有 Exact Match 和 examples 的两道 Train、两道 Val。`configs/xiaoyi-work.json` 已采用 `file_reflection`，无需模型 API，并预先采用支持未知请求计数的 `webshop` 排序策略。具体执行请优先阅读 [小艺 Work 对话驱动运行说明](XIAOYI_WORK_RUNBOOK.zh.md)。下面的能力清单保留通用适配背景；用户现场检查报告不是本工程直接完成的线上验证。

目标边界是 **Python Optimizer → Harness Adapter → 小艺 Work Main Agent**。本次没有小艺 Work 连接会话，也没有验证其内部 API、Skill 管理、批量任务或轨迹导出；不能把 `XiaoyiWorkAdapter` 或合成 worker 称为真实部署完成。

已经提供的 `adapters/xiaoyi.py` 继承可运行的文件交换协议。接手同学可先人工完成一个真实任务的请求/响应，再把已确认的接口接入 `execute`；无需修改核心反思、解析、补丁和候选选择。

## 1. 算法需要目标环境具备什么能力？

最低能力是：提交公开任务；让该任务使用指定 Skill 文本；返回真实最终交付和足够完整的执行证据；获得独立 Judge 的反馈；在下一轮更换 Skill；对固定 Val 重复同样的部署和评测过程。

| 能力 | 原算法的用途 | 小艺 Work 当前状态 / 必须验证的问题 |
|---|---|---|
| 任务提交与会话身份 | 将固定 Train/Val 与实际执行一一对应 | 待验证：API、SDK、CLI、企业工作流还是仅 UI；是否可创建独立会话/恢复会话 |
| Skill 文本加载/更新 | 本轮执行使用准确候选 | 待验证：原生 Skill 导入、工作区文件、系统指令、用户附件分别是否支持；更新生效时间/缓存/名称冲突 |
| Skill 使用证明 | 区分导入成功与真正执行使用 | 待验证：可否确认所加载内容/版本/哈希；是否有平台自带规则或其他 Skill 干扰 |
| 原生调用与结果轨迹 | 反思实际动作和失败原因 | 待验证：消息、工具名/参数/返回、错误、顺序、文件产物、压缩前记录的导出权限；不要求提供平台未公开的内部思维链 |
| 完整最终产物 | 宿主 Judge 与最终交付 | 待验证：文本/文件下载、工作目录、临时链接有效期、文件权限/哈希 |
| strict/partial/原因 | 分开成功失败、保留部分分 | 可由宿主现有 Judge 完成；不能默认平台自评分可信或存在 |
| 请求计数 | OfficeQA 排名的平均 API 请求 tie-break | 待验证：平台能否提供真实计数。未知必须 null，不能用 UI 消息数或工具数替代 |
| 超时和基础设施状态 | 避免把权限/服务故障学成错误规则 | 待验证：明确终态、取消/限流、会话恢复和幂等语义 |
| 新版 Skill 的独立 Val | 最终选择防止训练过拟合 | 待验证：候选之间隔离、任务重置、输出记录一致性 |
| 图片/音频与长轨迹 | 保留原始证据 | 待验证：多模态导出、附件访问权限和上下文上限；当前反思器是文本接口，不自动理解图片 |
| Windows 运行方式 | Python 与目标环境连接 | 待验证：可用 Python/脚本权限、进程启动、用户目录、企业网络端点、文件交换位置 |

这些能力的可用性、权限和限制应在接手环境逐项记录。无需先实现 Subagent 或内部多 Agent 学习。

## 2. 如何把 Skill 传入小艺 Work？

先保留两个不同工件：`bank.json` 是优化器经验库，`SKILL.md` 是交给 Agent 的原生文本。不要直接上传 JSON 卡库并假设平台会解析。

优先级由**现场实际能力**决定：

1. 若支持原生 Skill：按平台已验证的目录/名称/长度规范导入 `SKILL.md`，确认当前任务实际加载版本；记录内容 SHA256 和版本号。需要现场实现 `load/update` 调用。
2. 若支持任务附件或工作区文件：上传 `SKILL.md`，在任务指令中明确要求阅读该文件。必须确认 Agent 能读取且有权限，不能只以 UI 显示“上传完成”当作使用证明。
3. 若只能提供普通提示词：把 Skill 正文和任务明确分隔后提交。这是**提示词注入部署模式**，不是已经验证的原生 Skill。必须记录这种条件，重新评估效果。
4. 若任务之间无法更新 Skill：每个候选使用独立会话/工作区，先加载固定版本后执行完整 Val。若平台始终固定不可控规则且无法提供候选指令，当前部署假设不成立，需要与平台同学确认能力。

默认算法按当前公开问题在 Python 侧做词汇 top-k，再把渲染结果提交给 Harness。若无法逐任务更新，可显式导出全部卡片后重新验证长度与效果；这不是 top-k 部署的等价替代，不应直接复用原实验结论。

接口中，`execute(public_task, skill_markdown, directory)` 传递的是当前完整快照；Adapter 在本次任务前加载它，下一次调用传入新版实现更新。`export_skill` 提供静态文件输出。接口不假设能够热更新一个正在执行的目标会话。

## 3. 如何调用小艺 Work 执行 Train？

确认有正式支持的 API/SDK 后，在 `XiaoyiWorkAdapter.execute` 中实现：创建任务 → 加载当前 Skill → 触发 Main Agent → 等待明确终态 → 导出证据。应把目标会话ID写进 `Execution.metadata`，并以本地 request 哈希做幂等映射。

在尚无接口时，使用已实现的人工流程：

```bash
python -m skill_optimizer run --config configs/xiaoyi-work.json --output runs/xiaoyi-pilot
```

当前配置无需端点或密钥。Train 执行与现有评分完成后，还会生成反思请求；由小艺读取对应 `PROMPT.md`，保存原始 JSON 回复，用 `submit-reflection` 提交，再恢复原命令。不要把 `model` 改为 synthetic 后将结果当作小艺真实学习。

缺响应时程序退出3，目录内生成：

```text
round-001/train/<task-id>/exchange/
  request.json       # 公开任务、Skill 文件名/哈希、Adapter 身份
  SKILL.md           # 本次任务应加载的精确快照
```

操作员在小艺 Work 完成这份任务，保留实际证据，然后提交响应，再执行同一个命令恢复。原已完成任务不会因为控制器重启自动重跑。脚本桥接可使用 `CommandAdapter`，通过 argv 数组调用已授权的企业脚本；无需改变请求协议。

不要把宿主目录整体挂给目标 Agent；`inputs.json`、run manifest、答案、Judge 和反思数据属于宿主。文件适配器只发送 `request.json` 和 `SKILL.md`。原生本地 CLI 不提供操作系统级沙箱，处理私有评分数据应由既有隔离执行器保证访问边界。

## 4. 如何获取轨迹、工具调用与结果？

`Execution` 的 JSON 结构：

```json
{
  "task_id":"train-total-a",
  "final_answer":"精确的真实最终交付文本",
  "conversation":[
    {"role":"user","content":"真实公开任务"},
    {"type":"tool_call","cmd":"真实工具名称与参数文本","obs":"真实返回内容"},
    {"role":"assistant","content":"精确的最终交付文本"}
  ],
  "status":"complete",
  "api_requests":null,
  "tool_feedback":[],
  "metadata":{"target_session_id":"现场实际会话ID","skill_load_mode":"待填写"}
}
```

上例仅说明 schema，不是可冒充真实执行的示例轨迹。`conversation` 可以保留 OpenClaw 原生 `id/timestamp/message` 行，也可使用上游支持的 `type=tool_call,cmd,obs` 或 `role/content`。必须保留原动作参数、反馈、错误与顺序，不只留最终答案摘要。若另有工具结果，放入 `tool_feedback`，优化器也会送给反思器；已在完整轨迹中存在时无需重复附加。

`status` 可为 `complete`、`normal_failure`、`infrastructure_failure`。明确有效执行的错误答案是正常失败，应该参与学习；未执行、权限故障、服务故障或证据缺失不是“得0分”。当前原生 CLI 超时不能可靠判定时停止交接流程，不擅自重试。

未公开的内部推理不作为强制接口。要求的是平台可授权导出的实际消息、工具行为和反馈。如果 UI 只能展示最终答案而完全没有执行证据，不能伪造一段轨迹来满足接口；应先解决日志/导出权限，或者明确另立“仅结果反思”方法并重新验证，不能称为当前完整轨迹算法的等价部署。

文本反思器遇到图片/音频会留下原记录哈希，并明确没有收到像素/音频语义；不能将 base64 当自然语言送入后声称已理解图片。可见文字/OCR若由目标真实工具生成，可作为真实工具反馈保留。

## 5. 如何把 Judge 反馈送回优化器？

优先把已有权威 Judge 包成 `Judge.score(task, execution) -> Score`。配置 `judge.kind` 可以是已安装模块的 `module:Class`。Judge 留在宿主，目标 Agent 不应读取标准答案、评测器或 validation reference。

当前示例配置直接使用 `ExactMatchJudge`，无需手工提供评分。只有外部人工/服务能评分时，才切换为 `ExternalFeedbackJudge`。响应包含独立的：

```json
{"hard":0,"soft":0.5,"feedback":"可迁移的真实结构化失败原因","qualified":true}
```

`hard` 是严格成功 0/1；`soft` 在0到1保留部分分；`qualified=false` 表示不能用于学习或选择。不得将解决任务的 Agent 自己宣称“完成”直接当成权威分数。请求哈希可以防串任务，不证明评分正确；评分方的身份和权限仍需现场确认。

使用辅助脚本打包真实导出：

```bash
python examples/complete_request.py --request REQUEST_DIR/request.json \
  --trace actual-conversation.json --final actual-final.txt \
  --judge actual-judge.json
```

若真实计数可获得，再加 `--api-requests N`。脚本自动写 schema、任务身份和 request SHA，避免人工计算绑定值。修改同一个 request 的响应会被拒绝；更正反馈应保留旧证据，用新评测版本/输出目录处理。

## 6. 多轮更新、Validation 与最终 Skill

先固定 Train/Val 划分、Judge 和候选选择策略。全部 Train 执行与合法评分完成后，反思器只读取 Train；旧卡保留，新卡通过来源解析和过滤后 append。随后在同一固定完整 Val 上执行 seed 与学到的候选，选中后导出并冻结。

`rounds>1` 支持显式的上一版卡库→重新 Train→追加更新链；这是工程编排开关，不能替代 GDP cross-fit、WebShop 配对残差或华为族级确认流程。不要用 Val 轨迹或 Test 反馈改写卡片。

如果平台不提供精确 API 请求数，保留 null。默认 `officeqa` 排名将拒绝选择，以免悄悄改变其“少请求优先”含义。可在**首次评测前**预登记采用已有 `webshop` 排名策略（严格成功→部分分→正文长度），在配置和报告中明确；这属于部署协议选择，不是补编请求数。

最终 `final/SKILL.md` 是全部卡的静态快照，`final/bank.json` 是精确路由部署的源。目标平台长度不足时，应预先定义整卡预算候选并独立 Validation；不应从中途截断一段卡体或未经验证就宣称部署等价。

## 7. 只有普通 UI、没有内部 API 怎么办？

文件交换协议仍可运行：Python 生成请求 → 操作员在 UI 加载 Skill 并执行任务 → 下载/导出实际记录与交付 → 宿主/人工 Judge → 写响应 → 原命令恢复。程序会逐项暂停，直到所有 Train 和候选 Val 有完整证据。这一流程不需要虚构小艺 Work 的 API。

若企业允许已有 RPA/脚本，可将实际 UI 操作封装为 `CommandAdapter` worker，但以下能力必须另行实现并验证：稳定定位、登录会话/权限、文件上传下载、终态识别、会话隔离、轨迹导出、重复请求防护。现有 `exchange_worker.py` 只是合成 worker，没有任何小艺 UI 自动化实现。

无法拿到日志或原始工具反馈时，本任务的完整轨迹闭环尚不成立；应把它登记为阻塞项，而不是把截图内容、推测动作或最终结果包装成完整轨迹。仅可见聊天消息有多少就记录多少，并明确缺失范围，不能混入“完整轨迹已验证”的验收结论。

## Windows 与运行限制

Python 核心、JSON/Markdown 文件交换、脚本 argv 使用 `pathlib`、UTF-8 和独占文件锁，不依赖 `fcntl`、`/proc` 或 symlink。Windows 原生 **尚未实际测试**；应先运行 pytest 和人工单任务交换，明确 Python/企业终端的脚本权限。

原 Benchmark 调度器依赖 Linux Docker、Unix UID、tmux、特定挂载与运行库；没有随核心包移植。原实验 Linux Node 二进制不能直接复制到 Windows；需要目标平台的 Node/OpenClaw，或把已验证的 Linux 执行器部署在 WSL/远端，再通过文件/脚本协议连接。OpenClaw 本次只在 Linux 的原运行库离线检查通过，不保证 Windows 原生兼容。

终端可设置 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` 避免旧代码默认文本编码与中文路径问题。企业出网、模型端点、数据允许流转范围和 UI 自动化权限均由接手环境确认；不要将真实内部轨迹上传到未授权模型服务。本包只带合成任务，不含内部坏例数据。

## 8. 完成项和接手待办

已完成：真实算法抽取、独立导入/安装、Harness/Judge/模型边界、OpenClaw CLI参考、文件/脚本协议与恢复、Skill导出、来源核验、最小闭环和测试。完成证据见 `reports/VALIDATION.zh.md`。

接手同学优先完成：

1. 在小艺 Work 确认可行的 Skill 加载方式、Main Agent任务提交方式、轨迹/产物导出权限；用一个非敏感真实任务保存证据。
2. 填写/实现 `XiaoyiWorkAdapter.execute` 或企业脚本 worker，把实际会话ID、部署模式和真实记录绑定到 request；验证加载内容一致、无串任务。
3. 接上真实宿主 Judge，区分正常失败与基础设施无效；确认请求计数能否获得，预登记相应选择策略。
4. 固定少量 Train 与独立 Val，使用真实可授权模型完成一次优化；核验实际使用的 Skill 与 final freeze 哈希一致。
5. Windows 现场验证、文件任务暂存/产物回传、平台长度限制、登录和重置策略。先验收 Main Agent，Subagent 优化后续再设计。

验收不能仅看最终文件存在：还要看真实目标会话、完整工具证据、独立评分、Train-only 反思输入、相同完整 Val 覆盖、选中部署文件哈希和没有未经确认的重跑。

中文问题还有一个已知迁移点：现有路由按连续Unicode字母切词，**没有中文分词器**。整句中文可能形成一个长token，短触发词未必命中。现场要检查真实中文问题的 `routing.json/card_ids`；可将全卡部署登记为独立候选做Validation，不能暗自更换路由算法后仍声称与原实验等价。Task ID使用ASCII字母/数字和 `_.-` 的安全单段名称，中文内容放在prompt中。
