# POS AID/CAPK TLV Agent Skill

用于生成、校验、解释和维护 POS 终端 AID/CAPK BER-TLV 参数的 Agent Skill，支持：

- 智能设备：Android POS。
- 传统设备：RTOS/Linux POS。
- 传统设备 SDK 的 `MfSdkEmvSetAid`、`MfSdkEmvSetCapk` 参数格式。

当用户询问“应该配置哪些 AID”或提供 TSE/L3 报告时，Skill 会优先输出完整、连续且经过校验的 AID TLV，再解释 `9F06`、Kernel ID、TAC、限额等参数。CAPK 也会优先输出完整的单行 TLV。

仓库遵循开放的 Agent Skills 目录结构，可供支持 `.agents/skills/` 的 Codex、Claude Code、GitHub Copilot 等 Agent 使用。仓库不包含 POS SDK 源码。

## 主要能力

### AID

- 解析、解释、校验、构建和修改完整 AID TLV。
- 从参数截图、PDF、表格或认证配置生成 AID。
- 从 Mastercard TSE/M-TIP L3 HTML 报告生成 Mastercard、Mastercard China 和 Maestro AID。
- 区分接触与非接参数、Purchase TAC 与 Refund TAC。
- 将非接退货参数编码到 `DF8407 -> DF840A`。
- 根据设备类型自动选择 Kernel ID Tag 和嵌套结构。
- 处理 `DF8118`、`DF8119`、`DF811B`、`DF8120`、`DF8121`、`DF8122` 等 Mastercard 非接参数。
- 未明确要求时省略 `5F2A` 和 `5F36`，避免擅自加入币种及指数。
- 输出完整、连续、可直接配置的 TLV，而不是只返回 AID 名称或 `9F06`。

### CAPK

- 使用本地 CAPK 库按卡组织或 `RID + Index + environment` 查询。
- 区分测试 CAPK 与生产 CAPK，避免混用。
- 校验 RID、索引、模数、指数、有效期及 SHA-1 Checksum。
- 支持同一 RID/Index 在不同环境或处理机构下的独立记录。
- 来源未提供有效期时，按项目规则设置 `DF05=20301231` 并说明默认值。
- 生成传统设备 `MfSdkEmvSetCapk()` C 字节数组。

## 设备类型与编码差异

| 项目 | 传统设备（RTOS/Linux） | 智能设备（Android） |
|---|---|---|
| Kernel ID Tag | `DF810C` | `DF8408` |
| 接触额外参数 | `DF8A01 -> DF8406` | 顶层 `DF8406` |
| 非接额外参数 | `DF8A01 -> DF8407` | 顶层 `DF8407` |
| 非接退货参数 | `DF8A01 -> DF8407 -> DF840A` | `DF8407 -> DF840A` |
| CAPK TLV | 相同 | 相同 |

以下机型默认识别为智能设备，不再重复询问设备类型：

- `MF919`
- `MF360`
- `MF960`
- `M90`
- `SR800`

型号匹配不区分大小写。如果用户明确指定设备类型，则明确指定的类型优先于机型默认值。

## 安装

克隆仓库：

```bash
git clone https://github.com/lizeyi7170-afk/pos-aid-tlv.git
```

把下面的 Skill 目录保留在项目中，或复制到目标项目的 `.agents/skills/`、用户级 `~/.agents/skills/`：

```text
.agents/skills/pos-aid-tlv
```

不支持自动扫描 Agent Skills 的工具，可以直接让 Agent 读取：

```text
.agents/skills/pos-aid-tlv/SKILL.md
```

## 对 Agent 的示例请求

```text
分析 L3.html，告诉我 MF919 应该配置哪些 AID。
```

```text
根据这张参数表生成完整的智能设备 AID TLV。
```

```text
给我 A000000003 索引 94 的生产 CAPK。
```

```text
把这条传统设备 AID 转换为智能设备格式。
```

## 命令行工具

要求 Python 3.8 或更高版本。Windows 可将 `python3` 替换为 `py -3`。

### AID TLV

```bash
python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py inspect "<TLV_HEX>"

python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py validate "<TLV_HEX>" --device MF919 --strict

python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py set-auto "<TLV_HEX>" DF20 000000200000 --device smart

python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py convert-device "<TLV_HEX>" --device smart

python3 .agents/skills/pos-aid-tlv/scripts/aid_tlv.py format-c "<TLV_HEX>" --name aid_tlv
```

`--device` 支持 `traditional`、`rtos`、`linux`、`smart`、`android`，也支持 `MF919`、`MF360`、`MF960`、`M90`、`SR800`。

### Mastercard TSE/M-TIP L3

```bash
python3 .agents/skills/pos-aid-tlv/scripts/mastercard_tse_aid.py inspect "<REPORT.html>"

python3 .agents/skills/pos-aid-tlv/scripts/mastercard_tse_aid.py build "<REPORT.html>" --device smart

python3 .agents/skills/pos-aid-tlv/scripts/mastercard_tse_aid.py validate "<REPORT.html>" --device MF919
```

### CAPK

```bash
python3 .agents/skills/pos-aid-tlv/scripts/capk_catalog.py lookup --rid A000000003 --index 09 --environment production

python3 .agents/skills/pos-aid-tlv/scripts/capk_catalog.py lookup --scheme unionpay --index 0B --environment test

python3 .agents/skills/pos-aid-tlv/scripts/capk_catalog.py validate

python3 .agents/skills/pos-aid-tlv/scripts/capk_tlv.py validate "<CAPK_TLV_HEX>" --strict
```

## 验证

```bash
python3 -m unittest discover -s .agents/skills/pos-aid-tlv/scripts -p "test_*.py"
```

## 使用原则

AID、TAC、TTQ、限额、应用版本、Kernel ID、币种和 CAPK 必须来自收单机构、卡组织或认证报告，不能由 Agent 猜测。修改已有记录时应从完整原始 TLV 开始，不应只提交发生变化的 Tag。测试 CAPK 不能替代生产 CAPK。

本 Skill 会按项目规则执行确定性转换和明确记录的默认值，但最终参数仍需结合实际地区、收单机构和认证要求确认。

## 风险与免责

本项目只提供参数解析、校验和编辑辅助，不提供或替代收单机构、卡组织、EMV 实验室及终端认证要求。使用者必须核对认证参数，并在部署到生产 POS 终端前完成代码审查、实验室测试和交易验证。

本项目按“现状”提供，不提供任何明示或默示保证。使用本项目及其生成结果所产生的风险由使用者承担，详细条款见 [MIT License](LICENSE)。

## License

Copyright (c) 2026 lizeyi7170-afk. Released under the [MIT License](LICENSE).
