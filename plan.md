# Realty Agent — 实施计划

## Context

AI房产客服Agent系统原型，实现：微信聊天记录采集 → AI解析生成69字段客户画像 → 自动同步钉钉AI表单。本计划覆盖前后端完整原型，运行环境为本地游戏本。

已有基础设施：
- **微信解密**：`pywxdump 3.1.46` 已安装，`wechat-summarizer/` 项目有成熟的 decrypt.py + extract.py
- **钉钉CLI**：`dws` v1.0.18 已认证，`aitable` MCP 服务可用
- **Python环境**：3.14.3，FastAPI/uvicorn/pydantic/openpyxl 已安装
- **LangGraph研究**：3个开源项目代码已深挖，State Graph/路由/工具注册模式已明确

---

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| LLM | Claude Sonnet 4.5 (langchain-anthropic) | 中文理解强，JSON结构化输出可靠，API已有 |
| Agent框架 | LangGraph StateGraph | 条件路由灵活，对话阶段控制精确（不用create_supervisor，避免handoff额外token） |
| 后端 | FastAPI + uvicorn (已安装) | 原生async + SSE StreamingResponse |
| 前端 | Vue 3 + Vite + TypeScript | 轻量适合demo，Vite秒级热重载，Node 24已就绪 |
| 持久化 | SQLite (业务表 + LangGraph checkpointer) | 本地demo无需Postgres，零配置 |
| 钉钉集成 | `dws` CLI 子进程调用 | 已认证，CLI已处理鉴权 |
| 微信数据 | 复用 wechat-summarizer decrypt.py + 改造extract.py | 代码成熟，只需增加DM私聊提取 |

---

## 项目目录结构

```
D:\realestate-ai-agent/
├── backend/
│   ├── main.py                          # FastAPI入口
│   ├── config.py                        # Pydantic Settings配置
│   ├── models.py                        # 69字段Pydantic模型 + API schema
│   ├── agents/
│   │   ├── __init__.py                  # Agent注册表
│   │   ├── state.py                     # CustomerServiceState TypedDict
│   │   ├── graph.py                     # 主StateGraph（条件路由5阶段）
│   │   ├── prompts.py                   # 各phase的system prompt模板
│   │   ├── profile_parser.py            # 独立画像解析Graph（聊天→69字段JSON）
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── wechat_tools.py          # 微信聊天记录读取
│   │       ├── profile_tools.py         # 客户画像CRUD
│   │       └── dingtalk_tools.py        # 钉钉aitable写入
│   ├── services/
│   │   ├── wechat_service.py            # 封装解密+DM提取
│   │   ├── dingtalk_service.py          # 封装dws CLI调用
│   │   └── profile_service.py           # 去重/更新策略
│   ├── routers/
│   │   ├── agent_router.py              # /api/agent/* 状态/prompt/工具
│   │   ├── chat_router.py               # /api/chat/* SSE流式对话
│   │   ├── profile_router.py            # /api/profiles/* 画像CRUD
│   │   └── wechat_router.py             # /api/wechat/* 联系人/消息
│   ├── db/
│   │   └── local_store.py              # SQLite初始化 + CRUD
│   └── adapters/                        # 复用wechat-summarizer
│       ├── decrypt.py                   # 原样复用
│       ├── extract.py                   # 改造：增加DM私聊提取
│       └── config.yaml
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.vue
│       ├── style.css                    # Apple风格全局样式
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.vue
│       │   │   └── Header.vue
│       │   ├── chat/
│       │   │   ├── ChatPanel.vue        # 对话测试（SSE流式）
│       │   │   └── MessageBubble.vue
│       │   ├── profile/
│       │   │   ├── ProfileTable.vue     # 客户画像列表
│       │   │   └── ProfileDetail.vue    # 69字段详情/编辑
│       │   ├── prompt/
│       │   │   └── PromptEditor.vue     # Agent提示词编辑
│       │   └── status/
│       │       ├── AgentStatus.vue      # 运行状态
│       │       └── ExecutionLog.vue     # 执行日志+工具调用追踪
│       ├── composables/
│       │   ├── useSSE.ts               # SSE流式接收hook
│       │   └── useApi.ts               # API封装
│       └── stores/
│           ├── chat.ts
│           └── agent.ts
├── data/                                # 运行时数据（gitignore）
│   └── app.db
├── requirements.txt
└── README.md
```

---

## API端点设计

### 对话 (核心)

```
POST /api/chat/stream        SSE流式对话
  Body: { thread_id, message, customer_id? }
  SSE:  data: {type: "token"|"message"|"tool_call"|"done", content}

POST /api/chat/invoke        同步对话（一次性返回）
```

### 客户画像

```
GET    /api/profiles                     列表（分页/搜索）
GET    /api/profiles/{id}                详情（69字段）
POST   /api/profiles                     手动创建
PATCH  /api/profiles/{id}                手动更新
POST   /api/profiles/parse-chat          AI解析聊天→画像
POST   /api/profiles/{id}/sync-dingtalk  手动同步钉钉
```

### 微信数据

```
POST /api/wechat/decrypt                 触发数据库解密
GET  /api/wechat/contacts                非群聊联系人列表
GET  /api/wechat/dm-messages             私聊消息 (query: contact_id, date?)
```

### Agent管理

```
GET    /api/agent/status                 运行状态
GET    /api/agent/prompts                提示词列表
PUT    /api/agent/prompts/{id}           更新提示词
GET    /api/agent/logs                   执行日志
```

---

## Agent架构

### State Schema

```python
class CustomerServiceState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    customer_id: str
    wechat_contact_id: str
    chat_round: int
    phase: Literal["greeting", "probing", "qualifying", "closing", "handoff"]
    intent_level: Optional[Literal["高", "中", "低"]]
    profile_updates: dict       # 本轮提取的画像字段
    tool_trace: list[dict]      # 工具调用追踪
```

### Graph结构

```
START → [route_by_phase] ─┬─ greeting → [greet_node]
                          ├─ probing  → [probe_node]
                          ├─ qualifying → [qualify_node]
                          ├─ closing  → [close_node]
                          └─ handoff  → [handoff_node]
                                       ↓
                              [update_profile] (ToolNode)
                                       ↓
                              [check_phase_transition]
                                       ↓
                              继续对话 or END
```

路由逻辑：`greeting`(1轮) → `probing`(2-3轮) → `qualifying`(4-5轮) → `closing`/`handoff`

### 画像解析管道 (独立Graph)

```
START → [parse_chat] → [validate_fields] → [output_profile] → END
```
输入：聊天记录文本 → 输出：69字段结构化JSON

### Tools

| 工具 | 功能 | 实现方式 |
|------|------|----------|
| `get_dm_messages` | 读取微信私聊记录 | 改造extract.py的DM函数 |
| `query_customer_profile` | 查询客户画像 | SQLite查询 |
| `update_customer_profile` | 更新客户画像 | SQLite写入 |
| `sync_to_dingtalk` | 同步到钉钉AI表 | `dws aitable record` CLI |

---

## 数据库设计 (SQLite)

- **customer_profiles** — 69字段客户画像主表
- **agent_logs** — Agent执行日志（node、tool_calls、token_usage、status）
- **prompt_templates** — Agent提示词模板（可前端编辑）
- **chat_history** — 对话历史（补充LangGraph checkpointer）

---

## 前端设计 (Apple风格)

**布局**：左侧导航 + 右侧内容区，4个视图

**设计要点**：
- 字体：SF Pro Display / system-ui
- 主色调：`#1d1d1f` 文字、`#f5f5f7` 背景、`#0071e3` 强调蓝
- 圆角12px卡片，轻阴影
- AI消息左对齐白底，用户消息右对齐蓝底
- 工具调用显示为可折叠灰色卡片

**4个视图**：
1. **对话测试** — ChatPanel（SSE流式）+ 右侧实时画像提取预览
2. **客户画像** — ProfileTable列表 + ProfileDetail（69字段分组编辑）
3. **Agent管理** — PromptEditor（提示词编辑）+ ToolConfig
4. **运行日志** — 时间线日志 + 工具调用链 + 状态标签

---

## 实施阶段 (7个Phase)

### Phase 1: 后端骨架 + 数据模型 (1-2天)

1. 创建项目目录，安装依赖：`langgraph langchain-anthropic langgraph-checkpoint-sqlite`
2. `config.py` — Pydantic Settings（ANTHROPIC_API_KEY、微信路径等）
3. `models.py` — 69字段Pydantic模型 + API request/response
4. `db/local_store.py` — SQLite初始化 + CRUD
5. `main.py` — FastAPI app + lifespan + 健康检查

### Phase 2: Agent核心 (3-5天)

1. `agents/state.py` — CustomerServiceState
2. `agents/prompts.py` — 5个phase的system prompt + 画像解析prompt
3. `agents/tools/profile_tools.py` — 画像CRUD工具
4. `agents/graph.py` — StateGraph构建（5节点 + 条件路由 + checkpointer）
5. `routers/chat_router.py` — SSE流式 + 同步端点

### Phase 3: 微信集成 (6-7天)

1. 复制decrypt.py/extract.py到adapters/
2. **改造extract.py** — 新增`get_dm_contacts()`和`extract_dm_messages()`
   - DM判断：`StrTalker`不以`@chatroom`结尾
   - DM的`StrContent`直接是消息内容（无需群消息的`":\n"`分割）
3. `services/wechat_service.py` — 封装解密+提取流程
4. `routers/wechat_router.py` + `agents/tools/wechat_tools.py`

### Phase 4: 钉钉同步 (第8天)

1. `services/dingtalk_service.py` — `subprocess.run`调用`dws aitable record`
2. 去重逻辑：手机号查询 → 存在则update，不存在则create
3. `agents/tools/dingtalk_tools.py`
4. 手动同步端点

### Phase 5: 画像解析管道 (第9天)

1. `agents/profile_parser.py` — 独立Graph（聊天文本→结构化JSON）
2. `POST /api/profiles/parse-chat` 端点
3. `routers/profile_router.py` — 完整CRUD + 搜索

### Phase 6: 前端 (10-13天)

1. Vue 3 + Vite 初始化
2. Apple风格全局CSS
3. Sidebar + Header布局
4. ChatPanel（SSE对话）
5. ProfileTable + ProfileDetail
6. PromptEditor
7. AgentStatus + ExecutionLog

### Phase 7: 联调打磨 (第14天)

1. 端到端：微信解密→聊天提取→AI解析→画像生成→钉钉同步
2. 错误处理完善
3. 前端响应式
4. README

---

## 验证方式

| 阶段 | 验证方法 |
|------|----------|
| Phase 1 | `uvicorn backend.main:app --reload` → Swagger UI |
| Phase 2 | curl测试SSE端点，确认token逐个到达 |
| Phase 3 | `GET /api/wechat/contacts` 联系人列表 + DM消息验证 |
| Phase 4 | 调用同步API → 钉钉AI表单确认新记录 |
| Phase 5 | 准备真实聊天样本 → 验证69字段JSON提取准确率 |
| Phase 6 | 浏览器端到端：对话→画像→编辑→同步 |
| Phase 7 | 全流程手动测试 |

---

## 风险

| 风险 | 缓解 |
|------|------|
| Python 3.14与langgraph兼容性 | 安装时测试`import langgraph`，不行则创建3.12 venv |
| 微信数据库格式变化 | decrypt.py双层降级（pywxdump + AES fallback） |
| LLM JSON输出不符合schema | validate_fields节点pydantic验证，失败重试（最多2次） |
| dws CLI超时/认证过期 | 30秒超时 + try/except + 认证刷新提示 |
