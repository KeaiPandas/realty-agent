# README.agent

给后续接手这个项目的 Agent 的最小说明。

## 当前推荐主链路

优先使用微信 `4.x`：
- 解密微信本地数据库
- 提取私聊消息
- 用单个画像总结 Agent 提炼业务字段
- 用本地代码直写 `wechat_id`、`wechat_name`、时间字段
- 同步飞书

不要再把本地强信号字段交给第二个“飞书整理 Agent”，因为这个 Agent 已删除。

## 关键实现约定

### 1. 字段职责

本地代码负责：
- `phone`
- `wechat_id`
- `wechat_name`
- `first_contact_date`
- `first_followup_date`
- `latest_followup_date`

LLM 只负责聊天理解字段，例如：
- `purchase_purpose`
- `purchase_reason`
- `preferred_area`
- `concern_points`
- `followup_stage`
- `followup_strategy`

### 2. 微信字段区分

必须区分：
- `wxid`: 微信内部 ID
- `wechat_id`: 微信号

绝不能把 `wxid` 写进飞书的 `微信号` 列。

### 3. 安全

送 LLM 前会对聊天内容脱敏。
CLI 预览也显示脱敏内容。

## 重要文件

- [main.py](D:\realty-agent\main.py)
- [agents/profile_parser.py](D:\realty-agent\agents\profile_parser.py)
- [services/feishu_service.py](D:\realty-agent\services\feishu_service.py)
- [services/sync/extract.py](D:\realty-agent\services\sync\extract.py)
- [prompts.yaml](D:\realty-agent\prompts.yaml)
- [models.py](D:\realty-agent\models.py)

## 接手时先做什么

1. 看 `git status`
2. 看 [README.md](D:\realty-agent\README.md)
3. 跑一次：

```powershell
python main.py --list-contacts
python main.py --contact <wxid> --parse-only
```

4. 如果要联调飞书，再跑：

```powershell
python main.py --contact <wxid>
```

## 当前已知问题

- 模型接口偶发超时或限流
- 飞书表可能已有重复客户脏数据
- `phone`、`family_members` 等字段还有继续本地规则化的空间
