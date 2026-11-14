# 来源、许可证与依赖

## 复用的算法代码

| 来源 | 本包位置 | 修改范围与许可 |
|---|---|---|
| 本地 `SkillOpt/skillopt`，上游项目声明 https://github.com/microsoft/SkillOpt | `src/skill_optimizer/_vendor/skillopt` | MIT，Copyright (c) 2026 Microsoft Corporation，原文见 `licenses/SkillOpt.LICENSE`。保留实际使用文件及导入闭包；算法文件只替换绝对导入命名空间。部分package initializer缩小、model initializer换成必须显式注入的I/O边界，没有复制完整模型后端/Trainer |
| 本地 `officeqa-skill-research/oqs/learn.py`、`method.py`，当前冻结实验代码 | `research/officeqa.py`、`research/officeqa_routing.py`，默认卡片更新/选择编排的来源 | MIT，Copyright (c) 2026 OfficeQA Skill Research contributors，见 `licenses/OfficeQA.LICENSE`。轨迹/解析/过滤按AST提取；parser操作词表改为可选实例参数；routing文件完整原样复制。核心卡片更新语义由原源码块对照测试 |
| 本地 `huawei-skill-data-research/experiments/hf_round2/learn.py` | `research/binary.py`、`examples/huawei_reflection_prompt.txt` | 项目内部研究源码，未发现该项目顶层独立LICENSE；本次按用户授权用于内部工程交接，保留来源与哈希，不将其重新声明为第三方开源MIT代码。外部发布前应由权利人确认授权 |
| 本地 `webshop-skill-research/wsr/learn.py`、`gdpevo-skill-research/optimizer.py` | `examples/webshop_reflection_prompt.txt`、`examples/gdpevo_reflection_prompt.txt`；WebShop排名策略为原选择代码逻辑的抽取 | 原项目未发现顶层独立LICENSE；仅带内部算法提示词和来源说明，不带任务/服务/数据；对外发布前确认权利归属。项目已有vendor中的OfficeQA/SkillOpt许可证不等于给整个原项目自动授予MIT |
| `officeqa-skill-research/oqs/container_entry.py`、`episode.py` 的Python native CLI/JSONL接口 | `adapters/openclaw.py` | 依照原MIT来源参数化并缩小范围，避免复制个人路径/凭据工具。新中继 `adapters/ledger.py` 只承担I/O，不声称复刻原relay的全部runtime策略 |

顶层 `LICENSE` 保留 OfficeQA MIT 通知，覆盖相应复用部分和本次同许可证工程整理；明确列出的内部片段仍依其原权利归属处理。逐文件来源、SHA256、提取符号和变化见 `PROVENANCE.json`。没有下载或再分发Benchmark第三方数据、Docker镜像、Node/OpenClaw包或官方评分器。

本地SkillOpt仓库在审查时的HEAD为 `bc0a392ef0a7f92840ec673d80204d34ced169d0`；OfficeQA为 `d3e619b1970aa7f159a1138211102069f83e3149`；WebShop为 `3525792861f0bdc556bda9bd3de15ece05d3a81c`。HEAD不代替文件身份，实际来源以PROVENANCE及冻结哈希核验为准。GDP和华为位于父Git工作区，本次不把父仓库HEAD误写成它们独立的上游版本。

## 安装时的外部依赖

- `json-repair`：反思JSON的语法恢复，项目 https://github.com/mangiucugna/json_repair，MIT。通过包管理器安装，未将其源码vendoring到本包。
- `pytest`：开发测试依赖，MIT；通过包管理器安装。
- setuptools/wheel/build：安装与构建工具，仅构建/开发使用，不是算法运行时后端。
- OpenClaw / Node：可选外部运行环境，原研究使用OpenClaw 2026.6.9和Node22.20.0；本包不再分发二进制、内部补丁或它们的依赖，安装者应保留各自随发行版提供的许可证。仅凭版本号不能重建原实验运行库。

没有将OpenAI SDK、Azure SDK、WebShop、OfficeQA、GDPevo、Windows COM或其数据作为核心Python依赖。没有把个人服务器凭据读取器带入交接包。依赖安装解析出的版本见 `requirements-tested.txt`，需在目标Python/系统上复验。
