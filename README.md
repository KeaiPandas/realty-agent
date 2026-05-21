# Realty Agent

AI房产客服系统 — 微信聊天记录提取 → AI画像解析 → 飞书/钉钉同步 → AI自动回复

## 功能

- **Web仪表盘**：单页可视化控制台，实时监控解密/提取/解析/同步全流程
- **微信聊天提取**：解密微信 4.x/3.x PC本地数据库，提取私聊(DM)消息记录
- **AI画像解析**：通过LLM从聊天记录中提取36字段客户画像（结构化JSON）
- **飞书同步**：按微信号唯一键去重，自动创建/更新飞书多维表格记录
- **钉钉同步**：自动将客户画像创建/更新到钉钉AI表格
- **AI自动回复**：微信消息实时监控 + LLM自动生成回复 + pywinauto发送
  - 全自动模式：AI生成后直接发送
  - 半自动模式：AI生成建议，人工审批后发送
  - 支持屏蔽词过滤和无意义消息过滤
- **定时任务**：支持 cron 定时自动执行扫描任务
- **提示词可配置**：所有AI提示词存储在 `prompts.yaml`，无需改代码

## 快速开始

### 前置条件

- Windows 10/11（微信数据库解密依赖 Windows API）
- Python 3.12+
- 微信 PC 版已登录

### 安装

```bash
git clone <项目仓库地址>
cd realty-agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
```

编辑 `.env` 填入：

```env
LLM_API_KEY=你的API密钥          # 必填
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-5

WECHAT_DATA_DIR=                 # 留空自动检测

FEISHU_BASE_TOKEN=               # 飞书同步（可选）
FEISHU_TABLE_ID=
DINGTALK_BASE_ID=                # 钉钉同步（可选）
DINGTALK_TABLE_ID=
```

非敏感参数在 `config/` 下按域拆分：`llm.yaml` / `wechat.yaml` / `sync.yaml` / `agent.yaml` / `bot.yaml`

### 启动

```bash
.venv\Scripts\activate
uvicorn api.server:app --reload --port 8000
```

浏览器打开 http://localhost:8000

### 命令行使用

```bash
python main.py --list-contacts                # 列出微信私聊联系人
python main.py --contact <wxid>               # 提取+AI解析+同步飞书
python main.py --contact <wxid> --date 2026-05-03  # 指定日期
python main.py --contact <wxid> --parse-only  # 只解析不同步
python main.py --parse-file <chat.txt>        # 直接解析聊天文件
```

## 项目结构

```
├── api/                          # Web层（FastAPI + SSE）
│   ├── server.py                 # 应用入口
│   ├── event_bus.py              # 统一事件总线（SSE广播）
│   ├── scheduler.py              # APScheduler 定时任务引擎
│   ├── tool_logger.py            # 工具调用日志（环形缓冲区）
│   ├── decrypt_coordinator.py    # 解密协调（内存+磁盘缓存）
│   ├── routers/
│   │   ├── workflow.py           # 管道控制（解密→提取→解析→同步）
│   │   ├── scheduler_router.py   # 定时任务 CRUD
│   │   ├── health.py             # 环境健康检测
│   │   ├── logs.py               # 日志历史 + SSE 实时流
│   │   ├── bot_router.py         # Bot REST API
│   │   └── bot_events.py         # Bot SSE 事件流
│   └── static/                   # 前端（vanilla JS + ES Modules）
│       ├── index.html
│       ├── style.css
│       └── js/
│           ├── api.js            # 后端API调用
│           ├── bot.js            # Bot面板（会话/消息/审批/模式切换）
│           ├── state.js          # 共享状态
│           ├── sse.js            # SSE连接
│           ├── pipeline.js       # 管道控制
│           ├── scheduler.js      # 定时任务
│           ├── health.js         # 健康检测
│           ├── logs.js           # 日志查看
│           ├── tasks.js          # 任务列表
│           └── contacts.js       # 联系人选择
├── services/
│   ├── bot/                      # AI自动回复机器人
│   │   ├── __init__.py           # WeChatBot 编排器 + 全局单例
│   │   ├── models.py             # 数据模型（BotMessage/Conversation/Settings）
│   │   ├── monitor.py            # 消息监控（mtime轮询 + 增量解密）
│   │   ├── responder.py          # LLM回复生成（含屏蔽词/无意义消息过滤）
│   │   ├── sender.py             # 消息发送（pywinauto UI自动化 + Transport接口）
│   │   ├── conversation.py       # 会话管理
│   │   └── events.py             # Bot事件广播
│   ├── sync/                     # 数据提取 + 同步
│   │   ├── decrypt.py            # 微信数据库解密（3.x + 4.x）
│   │   ├── extract.py            # 聊天记录提取（兼容3.x/4.x）
│   │   ├── db_layout.py          # 数据库布局 + 版本检测
│   │   ├── wechat_path.py        # 微信数据目录自动检测
│   │   └── incremental.py        # 增量同步游标（持久化）
│   ├── feishu_service.py         # 飞书多维表格同步
│   └── dingtalk_service.py       # 钉钉AI表格同步
├── agents/
│   └── profile_parser.py         # AI画像解析（聊天记录 → 36字段JSON）
├── config/                       # 配置文件
│   ├── llm.yaml                  # LLM参数
│   ├── wechat.yaml               # 微信数据库配置
│   ├── sync.yaml                 # 飞书/钉钉CLI配置
│   ├── agent.yaml                # Agent行为参数
│   ├── bot.yaml                  # Bot配置（轮询间隔/模式/屏蔽词）
│   └── paths.yaml                # 文件路径
├── tests/
│   └── test_bot.py               # Bot单元测试（15个）
├── config.py                     # 配置加载器
├── models.py                     # 客户画像 Pydantic 模型
├── prompts.yaml                  # AI提示词配置
├── main.py                       # CLI入口
└── requirements.txt              # 依赖
```

## API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/health` | 环境健康检测 |
| `POST` | `/api/workflow/start` | 启动管道 |
| `POST` | `/api/workflow/stop` | 停止管道 |
| `GET` | `/api/workflow/runs` | 运行记录 |
| `GET` | `/api/workflow/contacts` | 联系人列表 |
| `GET` | `/api/workflow/decrypt` | 触发解密 |
| `GET` | `/api/logs/stream` | SSE 实时日志 |
| `GET` | `/api/logs` | 历史日志 |
| `POST` | `/api/scheduler/tasks` | 创建定时任务 |
| `GET` | `/api/scheduler/tasks` | 列出定时任务 |
| `PATCH` | `/api/scheduler/tasks/:id` | 更新任务 |
| `DELETE` | `/api/scheduler/tasks/:id` | 删除任务 |
| `GET` | `/api/bot/status` | Bot运行状态 |
| `POST` | `/api/bot/start` | 启动Bot |
| `POST` | `/api/bot/stop` | 停止Bot |
| `GET` | `/api/bot/conversations` | 会话列表 |
| `GET` | `/api/bot/conversations/{wxid}/messages` | 消息历史 |
| `POST` | `/api/bot/conversations/{wxid}/approve` | 审批回复 |
| `POST` | `/api/bot/conversations/{wxid}/reject` | 拒绝回复 |
| `GET` | `/api/bot/settings` | 联系人模式配置 |
| `PATCH` | `/api/bot/settings/{wxid}` | 更新模式 |
| `POST` | `/api/bot/send` | 手动发消息 |
| `GET` | `/api/bot/stream` | Bot SSE事件流 |

## 技术栈

- **LLM**: GLM-5（OpenAI兼容接口） via LangChain
- **Web**: FastAPI + Uvicorn + SSE
- **微信解密**: SQLCipher 4（4.x）/ PyWxDump（3.x）+ Windows API 内存密钥提取
- **消息发送**: pywinauto UI自动化
- **飞书**: @larksuite/cli
- **钉钉**: dws CLI
- **定时任务**: APScheduler

## 配置优先级

```
.env 环境变量 > config/*.yaml > 代码默认值
```

## License

MIT
