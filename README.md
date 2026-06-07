# Realty Agent

Windows 本地运行的房产客户画像工具。读取微信 4.x 本地数据库，用 AI 从聊天记录中提取客户画像，同步到飞书/钉钉多维表格。支持微信自动回复 Bot。

## 功能

- **消息同步**：解密微信 4.x 本地数据库 → 提取私聊消息 → AI 生成客户画像 → 同步飞书/钉钉
- **客户画像**：LLM 提炼需求/预算/意向区域/跟进策略，本地代码直写微信号/首次联系日期等强信号字段
- **自动回复 Bot**：监听微信消息，AI 生成回复，支持半自动审批 / 全自动模式
- **定时任务**：Cron 定时自动执行同步流程
- **线索情报看板**：风险预警、行动建议、每日简报
- **环境健康检测**：自动检查微信进程、数据库、LLM 接口、飞书配置

## 环境要求

- **操作系统**: Windows 10/11
- **Python**: 3.12+
- **微信**: PC 客户端 4.x 已登录
- **LLM API Key**: OpenAI 兼容接口（默认智谱 GLM）

## 快速开始

### 1. 克隆项目并创建虚拟环境

```powershell
cd D:\
git clone <your-repo-url> realestate-ai-agent
cd realestate-ai-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> 如果 PowerShell 报执行策略错误，先运行：
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

> 如果部分包安装失败，项目提供了 `setup.ps1` 一键安装脚本，会逐个重试：
> `.\setup.ps1`

### 3. 配置环境变量

```powershell
Copy-Item .env.example .env
notepad .env
```

最少需要填写 `LLM_API_KEY`，其余有默认值。完整配置说明见下方 [配置说明](#配置说明)。

### 4. 启动 Web Dashboard

```powershell
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

打开浏览器访问 http://127.0.0.1:8000

> 也可以直接双击 `start.ps1` 启动。

## Web Dashboard 使用

启动后访问 http://127.0.0.1:8000 ，包含以下功能页面：

### 线索情报看板

首页默认展示看板视图：
- **KPI 卡片**：活跃客户数、今日新消息、待回复数、沉默客户数
- **今日情报简报**：AI 生成的每日摘要
- **紧急待办**：风险引擎产出的行动建议，可勾选完成
- **高优先线索**：按风险等级排序的客户卡片
- **数据概览**：消息时段分布、客户阶段分布

### 微信消息同步

通过 API 或 Dashboard 操作同步流程：

1. **解密数据库**：`GET /api/workflow/decrypt` — 解密微信本地数据库
2. **获取联系人**：`GET /api/workflow/contacts` — 列出有私聊消息的联系人
3. **启动同步**：`POST /api/workflow/start` — 对单个联系人或全部联系人执行完整同步流程
4. **查看状态**：`GET /api/workflow/status` — 查看当前运行状态
5. **停止运行**：`POST /api/workflow/stop` — 停止正在运行的同步任务

同步流程包含四个步骤：解密数据库 → 提取私聊消息 → AI 解析画像 → 同步飞书/钉钉。

支持指定日期范围（`date_start` / `date_end`）或 `parse_only` 模式（只解析不同步）。

使用 `contact_id = "__all__"` 可批量处理所有联系人。

### 自动回复 Bot

Bot 监听微信消息，用 AI 自动生成回复。通过 API 控制：

**Bot 管理**：
- `POST /api/bot/start` — 启动 Bot
- `POST /api/bot/stop` — 停止 Bot
- `GET /api/bot/status` — 查看 Bot 运行状态（是否运行、活跃会话数、待审批回复数）

**会话管理**：
- `GET /api/bot/conversations` — 列出所有会话
- `GET /api/bot/conversations/{wxid}/messages` — 查看某个会话的消息记录

**回复审批（半自动模式）**：
- `POST /api/bot/conversations/{wxid}/approve` — 批准发送 AI 生成的回复（可编辑后发送）
- `POST /api/bot/conversations/{wxid}/reject` — 拒绝发送

**手动发送**：
- `POST /api/bot/send` — 手动给指定联系人发送消息

**配置**：
- `GET /api/bot/settings` — 查看所有联系人配置
- `PATCH /api/bot/settings/{wxid}` — 修改单个联系人的 Bot 配置（mode / enabled）
- `GET /api/bot/settings/global` — 查看全局配置
- `PATCH /api/bot/settings/global` — 修改全局配置（mode / enabled）

**Bot 回复模式**：
- `semi_auto`（默认）：AI 生成回复后等待人工审批，适合初期使用
- `auto`：AI 生成回复后自动发送，模拟真人回复节奏
- `disabled`：对该联系人禁用 Bot

**Bot 行为参数**（在 `config/bot.yaml` 中配置）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | `false` | Bot 默认是否开启 |
| `poll_interval` | `5` | 消息轮询间隔（秒） |
| `context_messages` | `10` | 上下文消息条数 |
| `default_mode` | `semi_auto` | 默认回复模式 |
| `reply_debounce_seconds` | `1.8` | 回复防抖等待（等客户说完） |
| `think_delay_min/max` | `0.8 / 2.4` | 模拟思考延迟（秒） |
| `segment_count_min/max` | `1 / 3` | 分段发送条数 |
| `segment_delay_min/max` | `0.15 / 0.45` | 分段发送间隔（秒） |
| `manual_conflict_guard` | `true` | 检测到人工回复时阻止自动发送 |
| `block_words` | `["测试", "test"]` | 触发这些词的消息不自动回复 |

### 定时任务

通过 API 设置 Cron 定时自动执行同步：

- `GET /api/scheduler/tasks` — 列出所有定时任务
- `POST /api/scheduler/tasks` — 创建定时任务
- `PATCH /api/scheduler/tasks/{task_id}` — 更新任务
- `DELETE /api/scheduler/tasks/{task_id}` — 删除任务

任务参数：`task_id`（任务名）、`cron`（Cron 表达式）、`contact_id`（联系人 wxid）、`date` / `date_start` / `date_end`（日期范围）、`scan_mode`、`enabled`。

### 环境健康检测

`GET /api/health` — 一键检测四项环境状态：

1. **微信进程**：是否检测到 WeChat/Weixin 进程
2. **微信数据库**：数据目录是否存在、数据库文件是否找到
3. **飞书配置**：lark-cli 是否安装、Base Token 和 Table ID 是否配置
4. **LLM 接口**：API Key 是否配置、接口是否可达

## CLI 命令行

```powershell
# 列出微信私聊联系人
python main.py --list-contacts

# 解析某个联系人（只生成画像，不同步）
python main.py --contact <wxid> --parse-only

# 解析并同步到飞书
python main.py --contact <wxid>

# 直接解析聊天文本文件
python main.py --parse-file .\chat.txt

# 指定日期范围
python main.py --contact <wxid> --date 2025-06-01
```

## 配置说明

所有配置通过 `.env` 文件管理（从 `.env.example` 复制）。运行时参数通过 `config/*.yaml` 调整。

### .env 环境变量

**LLM 配置**：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_API_KEY` | ✅ | — | 模型 API Key |
| `LLM_BASE_URL` | 否 | `https://open.bigmodel.cn/api/paas/v4` | OpenAI 兼容接口地址 |
| `LLM_MODEL` | 否 | `glm-5` | 模型名称 |

**微信配置**：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `WECHAT_VERSION` | 否 | `auto` | 微信版本，当前主链路用 `4.x` |
| `WECHAT_DATA_DIR` | 否 | 自动检测 | 微信数据目录路径，留空则自动从进程探测 |

**飞书同步（可选）**：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `FEISHU_BASE_TOKEN` | 否 | — | 飞书多维表格 Base Token |
| `FEISHU_TABLE_ID` | 否 | — | 飞书多维表格 Table ID |

**钉钉同步（可选）**：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DINGTALK_BASE_ID` | 否 | — | 钉钉 AI 表格 Base ID |
| `DINGTALK_TABLE_ID` | 否 | — | 钉钉 AI 表格 Table ID |

### config/ 目录

| 文件 | 说明 |
|------|------|
| `agent.yaml` | Agent 参数（消息提取条数、联系人列表上限） |
| `bot.yaml` | Bot 行为参数（回复模式、防抖、分段发送、屏蔽词等） |
| `sync.yaml` | 同步 CLI 配置（lark-cli/dws 路径、超时） |
| `paths.yaml` | 数据目录和提示词文件路径 |
| `llm.yaml` | LLM 参数（temperature、max_tokens），通常由 .env 覆盖 |
| `wechat.yaml` | 微信版本和数据目录，通常由 .env 覆盖 |

## 项目结构

```
main.py                    CLI 入口
config.py                  配置加载（.env + config/*.yaml）
models.py                  客户画像数据模型
prompts.yaml               LLM 提示词（画像总结 / 客服回复 / 每日简报 / 行动建议）

agents/
  profile_parser.py        画像解析 Agent（本地字段提取 + LLM 总结）

services/
  feishu_service.py        飞书多维表格同步（按微信号/手机号查重）
  dingtalk_service.py      钉钉 AI 表格同步
  db.py                    本地数据库
  bot/
    __init__.py            WeChatBot 主类（监听、回复、审批）
    monitor.py             微信消息监控
    responder.py           AI 回复生成
    sender.py              消息发送（pywinauto 驱动微信窗口）
    conversation.py        会话与联系人配置管理
    models.py              Bot 数据模型
    events.py              SSE 事件广播
    wechat_backends.py     微信窗口操作封装
  leads/
    risk_engine.py         客户风险评级
    action_extractor.py    行动建议提取
    briefing.py            AI 每日简报生成
    stats.py               统计数据
  sync/
    decrypt.py             微信数据库解密（3.x / 4.x）
    extract.py             联系人与消息提取
    db_layout.py           数据库结构识别
    wechat_path.py         微信目录自动探测
    incremental.py         增量同步

api/
  server.py                FastAPI 应用入口
  scheduler.py             定时任务管理（APScheduler）
  pipeline_state.py        同步管道运行状态
  decrypt_coordinator.py   解密协调器
  event_bus.py             事件总线
  tool_logger.py           日志记录
  routers/
    workflow.py            同步工作流 API
    scheduler_router.py    定时任务 CRUD API
    bot_router.py          Bot 管理 API
    bot_events.py          Bot SSE 事件流
    health.py              环境健康检测 API
    leads_router.py        线索情报 API
    logs.py                日志流 API

config/
  agent.yaml / bot.yaml / sync.yaml / paths.yaml / llm.yaml / wechat.yaml
```

## 常见问题

### `uvicorn` 不是可识别的命令

不要直接用 `uvicorn`，改用：

```powershell
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

如果仍然报错，说明依赖未安装，先运行 `pip install -r requirements.txt`。

### 微信数据目录自动检测失败

确保微信 PC 客户端正在运行且已登录，程序通过进程探测数据目录。如果仍然检测不到，手动在 `.env` 中设置 `WECHAT_DATA_DIR`：

```env
WECHAT_DATA_DIR=C:\Users\<你的用户名>\Documents\WeChat Files\<wxid_xxx>\
```

### LLM 接口超时或限流

模型接口偶发不稳定时会自动重试。如果持续失败，检查：

1. `LLM_API_KEY` 是否正确
2. `LLM_BASE_URL` 是否可达
3. 账户余额是否充足

### 飞书同步出现重复记录

飞书表按 `wechat_id` 或 `phone` 查重。如果历史数据中有脏数据（如同一个人多条记录），需先在飞书表中人工清理。

### Bot 无法发送消息

1. 确保微信 PC 客户端在前台运行且已登录
2. Bot 通过 pywinauto 驱动微信窗口操作，不能最小化到托盘
3. 检查 `config/bot.yaml` 中 `transport_backend` 是否正确
4. 如果是半自动模式，需要在 Dashboard 中审批后才会发送

### Python 版本不对

项目需要 Python 3.12+。检查版本：

```powershell
python --version
```

如果系统有多个 Python 版本，创建虚拟环境时指定完整路径：

```powershell
py -3.12 -m venv .venv
```
