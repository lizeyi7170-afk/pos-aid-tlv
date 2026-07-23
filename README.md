# POS AID TLV Agent Skill

面向 SR600 POS SDK `MfSdkEmvSetAid` 接口的共享 Agent Skill，用于解析、校验、构建和修改 AID BER-TLV 参数。

技能遵循开放的 Agent Skills 目录结构，可供支持 `.agents/skills/` 的 Codex、Claude Code、GitHub Copilot 等 Agent 使用。仓库不包含 POS SDK 源码。

## 安装

将本仓库克隆到项目根目录：

```bash
git clone https://github.com/lizeyi7170-afk/pos-aid-tlv.git
```

也可以把以下目录复制到目标项目的 `.agents/skills/` 或用户级 `~/.agents/skills/`：

```text
.agents/skills/pos-aid-tlv
```

不支持自动扫描 Agent Skills 的工具，可以直接让 Agent 读取：

```text
.agents/skills/pos-aid-tlv/SKILL.md
```

## 能力

- 解析并解释 AID TLV
- 按 SDK 实际支持的标签和长度校验
- 修改、添加或删除指定标签
- 检查嵌套的 other-TLV
- 输出完整 TLV Hex
- 生成 `MfSdkEmvSetAid()` C 字节数组
- 识别 SDK 的静默忽略、截断、字段归零及 getter 非无损回读问题

## TLV 工具

要求 Python 3.8 或更高版本。

```bash
python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py inspect "<TLV_HEX>"

python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py validate "<TLV_HEX>" --strict

python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py set "<TLV_HEX>" DF20 000000200000

python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py format-c "<TLV_HEX>" --name visa_aid_tlv
```

Windows 可将 `python3` 替换为 `py -3`。

## 使用原则

AID、TAC、TTQ、币种、限额、应用版本和 Kernel ID 必须来自收单机构或卡组织的认证参数，不能由 Agent 猜测。修改已有 AID 时应从完整的原始 TLV 开始，不应只提交发生变化的标签。

