# 小艺 Work 对话驱动运行说明

本模式由小艺 Work 完成回答和反思，Python 项目负责调度、现有 Exact Match 评分、补丁校验、卡库更新和候选选择。无需小艺 API、模型密钥或本地 OpenClaw CLI。先使用 `examples/tasks.json` 的两道 Train 和两道 Val，运行一轮，共六次回答执行；反思按成功/失败分组，可能生成多个请求。

## 环境和验证范围

用户提供的现场检查报告显示，小艺可从 GitHub 拉取代码、运行 Python、读写工作区，并能通过 `sessions_history` 获取记录。隔离子会话和文件交付仍以首次实际运行结果为准，本仓库不声称已经完成小艺线上验收。本地自动测试使用明确标注的离线夹具，不代表小艺效果。

控制主会话调度；每道 Train、每个候选下的每道 Val 使用新的回答子会话；反思使用另一个子会话。`sessions_spawn`、等待终态和 `sessions_history` 的具体参数由小艺读取其实际工具说明，不由此项目虚构。若隔离会话不可用，记录限制并交给用户在新对话中继续，不冒充隔离评测。共享文件系统没有强权限隔离；回答方不得读取私有答案、评分器、run manifest、反思材料和其他任务目录，且不能把答案或反馈写入共享记忆。子会话启动时可能加载全局技能和记忆，需要记录干扰情况。

## 拉取并启动

在 `/home/sandbox/.openclaw/workspace/repo/` 下拉取用户的 GitHub 仓库，再进入仓库根目录；仓库 URL 由用户提供。不要把访问凭据写进项目或运行记录。

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
python3 -m skill_optimizer run --config configs/xiaoyi-work.json --output runs/xiaoyi-pilot
```

配置已固定：真实回答文件交换、真实反思文件交换、`exact_match`、一轮、词汇 top-k 路由、`webshop` 排序策略。后者仅是排序规则的名称，不要求 WebShop 数据。真实请求次数未知，保持 `null`。

退出码 **3** 是正常等待，小艺应处理请求后重跑完全相同的 run 命令；其他非零退出码应检查错误，不删除锁或缓存强行重跑。代码、任务、模型、配置或提示词改变时用新的输出目录。不要在正在运行时拉取代码或修改这些输入。

```bash
python3 -m skill_optimizer pending --output runs/xiaoyi-pilot
```

命令返回 `requests` 和 `final_exists`。`awaiting_response` 需要处理；`response_supplied` 表示已提交，应恢复 run 消费回复，不再执行任务。`final_exists` 只表示冻结文件存在，不能代替查看最终成绩和运行错误。工作区中不存在请求时不要猜下一题；先运行 run。

## 处理 execution 请求

1. 控制会话读取 pending 给出的 `request.json`。只将公开的 `task`、同目录 `SKILL.md` 路径和专用产物目录交给全新回答子会话，不传父聊天记录、答案或反思。候选切换和同题重测也必须新建会话。
2. 子会话先实际读取该 Skill 文件，再执行公开题目。读取文件的路径、SHA256 和工具记录都应保存。不要求改全局 `skills/`。哈希证明文件身份，不证明模型完全遵循规则。
3. 等待真实终态。导出平台实际提供的可见消息、工具调用、参数、返回、错误与最终回答，保存为 `actual-conversation.json`（JSON 数组）。不包括隐藏推理字段。若平台返回外层对象，保留原导出，另外提取其实际消息数组，不手工补造对话。检查截断和分页；缺失证据应如实记录，不将摘要标成完整轨迹。
4. 将实际最终答案原样保存为 `actual-final.txt`。示例评分器只去掉首尾空白，额外解释文字会导致判错。独立保存实际产物；正常错误答案也应提交，不因分数不好重答。
5. 保存 `execution-metadata.json`，填写真实会话和证据情况，例如字段：`target_session_id`、`skill_load_mode`（`file-read`）、`loaded_skill_sha256`、`trace_source`、`trace_complete`、`missing_evidence`、`artifacts`。文件路径应在持久工作区中。无法确认的字段用 null 或明确描述，不填写猜测值。
6. 使用现有辅助脚本提交（将示意路径换成本次实际路径）：

```bash
python3 examples/complete_request.py --request REQUEST_DIR/request.json \
  --trace EVIDENCE_DIR/actual-conversation.json --final EVIDENCE_DIR/actual-final.txt \
  --metadata EVIDENCE_DIR/execution-metadata.json
```

不传 `--judge`，Python 会自动运行现有评分器；不传 `--api-requests`，保持未知。脚本记录输入轨迹、最终答案文件哈希和请求中的 Skill 哈希；`requested_skill_sha256` 不能当作实际加载证明。元数据是现场证据记录，不是平台签名认证。

权限故障、任务未执行或服务不可用，提交真实现有证据并使用 `--status infrastructure_failure`；优化器会停止，不把它学成错误规则。证据无法导出时停止并说明缺失，不能虚构轨迹。提交后再次运行原 run 命令。

## 处理 reflection 请求

1. 将 pending 给出的 `PROMPT.md` 交给独立反思子会话。其内容是项目原有反思器生成的准确 system/user 文本，仅使用 Train 材料；作为该子会话的任务说明，不宣称替换平台系统规则。
2. 小艺依据实际材料反思，将原始补丁 JSON 回复保存为 `reflection-reply.txt`。遵循请求里的 edit budget 和卡片 schema；没有可迁移改进时 `edits: []` 完全有效。不要为了得到更高分添加伪造规则，不手改最终 bank。
3. 保存实际反思会话 ID、可见执行记录路径/哈希、完整性情况到 `reflection-metadata.json`，保留实际记录文件。
4. 提交并恢复：

```bash
python3 -m skill_optimizer submit-reflection --request REQUEST_DIR/request.json \
  --reply EVIDENCE_DIR/reflection-reply.txt --metadata EVIDENCE_DIR/reflection-metadata.json
python3 -m skill_optimizer run --config configs/xiaoyi-work.json --output runs/xiaoyi-pilot
```

回复按精确请求哈希绑定，重复提交相同内容可以恢复；改写已有回复会被拒绝。解析和过滤仍由原算法完成。真正未解决的 API 调用仍不自动重试，文件等待与 API 失败分别处理。

## 完成、安装和正式数据

检查 `selection.json`、seed 和 round-001 的 `validation.json`、`final/freeze.json`。示例是简单加法，小艺可能在 seed 阶段已经全对，最终选中 seed 或没有新增卡均属合理结果。跑通标准是六次实际任务、合法反思、独立评分、固定 Val 覆盖和冻结工件完整，不要求强行学出卡片或提高分数。

`final/bank.json` 保留逐问题路由，`final/SKILL.md` 是全卡静态导出，二者部署条件不同。继续相同 top-k 部署时：

```bash
python3 -m skill_optimizer export --bank runs/xiaoyi-pilot/final/bank.json \
  --question '下一道公开任务的准确问题' --output runs/xiaoyi-deploy/SKILL.md
```

让小艺读取该文件并完成新任务。若要安装全卡技能到 `workspace/skills/`，先在新实验目录把 seed bank 的 `config.routing` 设为 `all`，按同条件验证后再复制最终文件、新建会话检查加载；不要覆盖已有技能。当前词汇路由没有中文分词器，中文正式数据应核查命中结果。

将运行记录、外部产物和最终 Skill 打包交付，实际测试 `send_file_to_user` 是否可用。不要把真实运行数据自动提交到 GitHub。之后用户上传正式数据时，先结束/归档当前运行，再拉取更新、修改任务路径并使用新的运行目录。正式答案应与评分器相匹配；CLI 中的 test 数据不参与优化，本项目不会自动执行最终 Test。

## 给小艺的总控指令

> 请从我提供的 GitHub 仓库拉取项目，阅读 `XIAOYI_WORK_RUNBOOK.zh.md`，按 `configs/xiaoyi-work.json` 使用 examples 中现有两道 Train、两道 Val 跑通一轮。由你担任回答者和反思者，评分使用现有 Exact Match。你在主会话调度，每次回答和反思使用新的隔离子会话。运行命令退出 3 时用 pending 查请求，按请求类型处理并提交真实响应，再运行原命令，直到最终选择完成或遇到需要说明的真实障碍。不要使用 synthetic 响应或伪造工具记录；不要为让新 Skill 胜出而故意答错、重答或改评分器；未知请求数保持 null。子会话功能先随首次任务实际验证，不改全局配置或共享记忆。最后报告各候选成绩、选择结果、隔离/证据限制，并交付最终 Skill 和运行记录。本次不跑 100 条，正式数据随后再从 GitHub 拉取。
