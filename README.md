# Skill Optimizer 工程交接

这是从实际实验源码整理的 Python Skill 优化工程，交接目标是华为小艺 Work 的 **Main Agent**。默认采用 OfficeQA 已冻结的经验卡主线：SkillOpt 分批反思 → 来源核验解析 → 实例过滤/正文去重 → 原版 append 补丁 → 问题词汇路由 → 完整 Validation 选择。不是将全部 Benchmark 打包，也不是重新实现 SkillOpt Trainer。

**已验证：**原源码一致性、核心测试、合成运行环境中的完整闭环、真实 OpenClaw CLI 的离线 Skill 发现。**未验证：**付费模型下的新 Agent rollout、小艺 Work 的 API、轨迹导出和原生 Skill 更新。Mock 响应不代表模型学习效果。

## 小艺 Work 对话驱动试跑

当前小艺接入采用 **GitHub 拉取项目 → 小艺在云沙箱运行 Python → 对话处理回答/反思请求 → 原命令恢复**。无需小艺模型 API。已配置现有 Exact Match 评分器、`examples/tasks.json` 的两道 Train 和两道 Val、一轮优化；正式数据随后从 GitHub 更新并使用新的运行目录。

```bash
python -m skill_optimizer run --config configs/xiaoyi-work.json --output runs/xiaoyi-pilot
python -m skill_optimizer pending --output runs/xiaoyi-pilot
```

退出码 3 表示等待小艺处理文件，不是运行失败。回答用 `examples/complete_request.py` 提交，反思用 `submit-reflection` 提交，然后恢复原 run 命令。完整操作、证据要求、部署和可粘贴指令见 [小艺运行说明](XIAOYI_WORK_RUNBOOK.zh.md)。自动测试使用离线夹具，小艺现场试跑尚待完成；简单示例不保证优化后成绩提高。

## 安装与最小闭环

Python ≥3.10；本次实际使用 Linux / Python 3.12.16。核心只有 `json-repair` 外部依赖，不要求 GPU、Docker、Office 软件或任何 Benchmark 数据。

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell 改用：.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python -m pytest -q
python -m skill_optimizer run --config configs/mock.json --output runs/demo
```

此命令使用**合成 Harness 和固定反思响应**，但调用真实的上游反思调度、解析、补丁、路由和选择代码。两道 Train、两道独立 Val；seed 的 Val 成功数为 0，学到一张计算卡后为 2，最终选中 `round-001`。数字只是接口测试结果，不是算法效果评测。

输出：

- `runs/demo/round-001/learning/`：输入清单、完整原轨迹、文本轨迹、原响应缓存、解析审计、补丁、经验卡和更新审计。
- `runs/demo/{seed,round-001}/validation.json`：相同完整 Val 上的评分。
- `runs/demo/selection.json`：候选排名及选择规则。
- `runs/demo/final/bank.json`：最终完整卡库，保留逐任务路由能力。
- `runs/demo/final/SKILL.md`：**全部卡片的静态导出**，便于人工交接；不是任意问题下的 top-k 部署等价物。
- `runs/demo/final/freeze.json`：最终文件哈希和选择依据。

原命令可恢复相同输入。若修改代码、模型、任务、Judge、提示词或配置，使用新输出目录；未完成的付费调用不会自动重发。`run.lock` 是跨平台的独占文件；只有确认所属进程已经退出后才可人工清理遗留锁。

## 切换 Harness

| 配置 | 用途 | 是否代表真实 Agent 部署 |
|---|---|---|
| `configs/mock.json` | 本地合成闭环 | 否 |
| `configs/script.json` | 真正启动外部 Python 进程交换 JSON；worker 仍是合成环境 | 否 |
| `configs/file-exchange.json` | 请求文件/人工响应/恢复原命令 | 取决于响应是否来自真实目标环境 |
| `configs/openclaw.json` | 本地 OpenClaw 原生 CLI + 原生 JSONL + 请求计数中继 | 本次仅离线发现检查通过，真实推理待验证 |
| `configs/xiaoyi-work.json` | 小艺回答/反思文件交换 + 现有 Exact Match；示例数据 | 对话驱动流程已实现，真实小艺会话待现场验收 |

```bash
python -m skill_optimizer run --config configs/script.json --output runs/script-demo
python -m skill_optimizer run --config configs/file-exchange.json --output runs/manual-demo
```

文件交换缺少响应时返回退出码 **3**，打印 `request.json` 路径。请求只含公开任务和 Skill；私有答案留在宿主。将真实任务与 `SKILL.md` 交给目标环境，取得原始轨迹和最终结果后：

```bash
python examples/complete_request.py --request REQUEST_DIR/request.json \
  --trace actual-conversation.json --final actual-final.txt --api-requests 3
# 若配置 external Judge，另加 --judge actual-judge.json
# 然后恢复原 run 命令，依次完成 Train 与每个候选的 Val。
```

`--api-requests` 只能填写实际计数；不知道则不填，保存为 null。OfficeQA 的原选择规则要求精确请求数，未知时会拒绝最终选择。可在评测前明确选择现有 `webshop` 策略（hard → soft → 正文长度），不能事后为了更换胜者改变策略。

`examples/exchange_worker.py` 仅示范脚本契约。配置中的 `command` 是 argv 数组，支持 `{python}`、`{project}`、`{request}`、`{response}`、`{directory}`，不通过 shell 执行。

## OpenClaw 参考实现

先准备 Node 和 OpenClaw。原实验使用经补丁的 OpenClaw 2026.6.9 / Node 22.20.0；版本号不能代替完整运行库的文件身份。本包不包含运行库、Docker 镜像或认证配置。任意新版本的兼容性需要重新检查。

离线检查不调用 Agent、不发模型请求：

```bash
python -m skill_optimizer probe-openclaw --output runs/openclaw-probe
# 若没有 PATH 中的 openclaw：
python -m skill_optimizer probe-openclaw --output runs/openclaw-probe \
  --command /path/to/node /path/to/openclaw.mjs
```

本次检查报告见 `reports/openclaw-offline/openclaw-probe.json`：真实 CLI 仅启用 `portable-skill`，模型调用数为 0。

真实运行前，修改 `configs/openclaw.json` 与 `configs/openclaw-native.example.json` 中的模型、端点和 CLI。通过环境变量提供 `${AGENT_API_KEY}` 和 `SKILL_OPTIMIZER_API_KEY`，不将密钥写入配置。配置参考 `experiment` provider；Agent 请求经本地中继精确计数，失败请求不冒充可训练结果。之后运行：

```bash
python -m skill_optimizer run --config configs/openclaw.json --output runs/openclaw-live
```

此命令会实际请求所配置模型，**本次未执行**。Adapter 每次使用临时隔离状态和工作区，不修改现有 OpenClaw 配置。它是本地 CLI 参考适配，不包含原研究 Docker 文件沙箱、进度拦截和完整运行库补丁。需要文件附件/产物的任务，应在 Adapter 中补充输入暂存和产物导出，或通过 `CommandAdapter` 接入已有隔离执行器。

## 接入新任务、Judge、模型

任务是 `examples/tasks.json` 中的结构：`id/prompt/split` 必填，`answer/reference_text` 是宿主私有字段，`public_metadata` 只能放公开输入。Train 与 Val 的 ID 必须互斥。CLI 中的 Test 任务不参与优化；本包不自动运行最终 Test。

`Task.public()` 是提供给 Harness 的唯一任务对象。Adapter 实现 `execute(public_task, skill_markdown, directory) -> Execution` 和 `identity()`；无需重写核心算法。完整字段见 [接口契约](src/skill_optimizer/contracts.py) 和 [适配指南](XIAOYI_WORK_ADAPTATION.zh.md)。

生产 Judge 使用已有权威评分器，返回 `Score(hard, soft, feedback, qualified)`。`hard` 是严格成功 0/1，`soft` 保留部分分；基础设施问题不能标为正常失败用于学习。新增 Judge 示例见 `examples/new_judge.py`。配置 `kind` 支持已安装包中的 `your_package.module:Class`，同样可扩展 Harness 与反思模型。

反思模型接口沿用上游 `(system, user, **kwargs) -> (text, usage)`。Mock 示例使用固定响应；小艺配置使用 `file_reflection`，由对话中的小艺处理文件请求，无需模型 API。也可切换 `openai_compatible`，或注入现有模型客户端。客户端不自动重试含糊失败，以免重复付费。

领域提示词独立配置。`examples/officeqa_reflection_prompt.txt` 等四份是原源码中的提示词；`portable_reflection_prompt.txt` 是迁移示例，**更换提示词需要重新验证效果**。默认过滤规则仍来自 OfficeQA，业务领域若允许年份/阈值，不能直接宣称此过滤与 GDP 原分支等价。

## 导出与交付

```bash
# 保留原词汇路由，针对下一道公开任务导出：
python -m skill_optimizer export --bank runs/demo/final/bank.json \
  --question 'Return the total of the current operands.' --output runs/deploy/SKILL.md
# 无逐任务更新能力时，显式导出全库（需目标长度预算验证）：
python -m skill_optimizer export --bank runs/demo/final/bank.json \
  --all-cards --output runs/deploy-all/SKILL.md
```

不要将没有触发词的问题空路由结果当成完整经验库，也不要将 JSON 卡库直接当作 Harness 原生 Skill 文件上传。

## 工程目录与进一步阅读

```text
src/skill_optimizer/
  core.py                 # 经验卡学习、词汇路由、候选排名
  pipeline.py             # Train → 执行/Judge → 学习 → 全 Val → 最终冻结
  contracts.py            # 复用上游类型 + Harness/Judge 边界
  adapters/               # OpenClaw、文件/脚本交换、小艺骨架、合成环境
  research/               # 当前 OfficeQA 解析/轨迹/路由 + 华为二进制索引
  _vendor/skillopt/       # 实际使用的反思器/补丁/数据类型及必要导入闭包
configs/ examples/ tests/ tools/ reports/ licenses/
```

- [ARCHITECTURE.zh.md](ARCHITECTURE.zh.md)：实际算法、分支差异、源码入口及迁移边界。
- [XIAOYI_WORK_ADAPTATION.zh.md](XIAOYI_WORK_ADAPTATION.zh.md)：八项接入问题、接口契约、Windows 与 UI 限制。
- [HANDOFF.zh.md](HANDOFF.zh.md)：交接顺序、验证清单、未完成工作和历史复现位置。
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、`PROVENANCE.json`：许可证、来源及逐文件哈希。
- `reports/VALIDATION.zh.md`：本次实际通过的验证及未执行内容。

验证来源无需旧项目：`python tools/verify_provenance.py`。如果仍可访问原源码，可执行 `python tools/check_source_equivalence.py --source-root /path/to/research-parent`，它只读取算法源码和合成输入，不读取原任务/凭据、不导入旧中继。

重新打包可运行 `python tools/package_handoff.py`，默认在父目录生成 `skill-optimizer-handoff.zip` 与 `.zip.sha256`。工具仅打包列明的源码/配置/合成示例/测试/文档/验证报告/wheel，排除本地venv、runs、构建缓存和原研究数据；`FILE_MANIFEST.json` 提供逐文件校验。不要手工将真实运行目录或用户配置追加到交接包。
