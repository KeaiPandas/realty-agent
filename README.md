# Realestate AI Agent

Windows 本地私有化的房产客服辅助系统。

它把微信聊天数据读取、客户画像解析、飞书/钉钉同步、Web 控制台、微信 Bot 自动回复整合到一个项目里，适合本机单账号运行和人工陪跑式迭代。

## 当前版本

- 项目阶段：MVP / 本地单机版
- 推荐运行环境：Windows 10/11
- 推荐微信版本：
  - `3.9.10.19`：当前 Bot 自动发送主线路，使用 `wxauto`
  - `4.x`：聊天数据提取和解密链路可用，但桌面 RPA 发送仍在继续优化
- 默认大模型：`glm-5`（OpenAI 兼容接口）

## 这版能做什么

- 读取和解密本地微信数据库
- 列出有消息的微信联系人
- 提取单联系人私聊消息
- 用 LLM 从聊天记录生成客户画像 JSON
- 同步画像到飞书多维表或钉钉 AI 表格
- 用 Web 控制台查看健康状态、联系人、任务、日志和 Bot 状态
- 让 Bot 对指定会话做：
  - `关闭`
  - `半自动待审批`
  - `全自动回复`

## 当前 Bot 支持边界

### 已验证

- `3.9.10.19 + wxauto`：
  - 已接入真实发送后端
  - `文件传输助手` 实发通过
  - Bot 发送链路可用
- `4.x + 本地数据库解密`：
  - 解密、提取、画像、同步链路可用
  - Web 控制台和健康检查可用

### 仍在完善

- `3.x` 的消息监控已切到 `wxauto` 路线，但真实用户来消息后的全链路还需要继续联调
- `4.x` 的桌面自动发送仍在做更稳的窗口聚焦和输入控件适配
- 当前仍默认面向“单账号、前台桌面可交互”的运行方式

## 项目结构

```text
api/
  server.py                  FastAPI 入口
  decrypt_coordinator.py     微信数据库解密协调
  scheduler.py               定时任务执行
  routers/
    workflow.py              解密/提取/解析/同步工作流
    bot_router.py            Bot REST API
    bot_events.py            Bot SSE 事件流
    scheduler_router.py      定时任务 CRUD
    health.py                环境健康检查
    logs.py                  日志查询和实时流
  static/                    Web 控制台

services/
  sync/
    decrypt.py               3.x / 4.x 微信数据库解密
    extract.py               联系人和聊天记录提取
    db_layout.py             微信数据库布局识别
    wechat_path.py           微信数据目录自动探测
    incremental.py           增量游标持久化
  bot/
    __init__.py              Bot 编排和状态管理
    monitor.py               消息监控
    responder.py             LLM 回复生成
    sender.py                发送调度
    wechat_backends.py       微信自动化后端
    conversation.py          会话和托管设置管理
    models.py                Bot 数据模型

agents/
  profile_parser.py          客户画像解析

config/
  llm.yaml                   LLM 配置
  wechat.yaml                微信相关配置
  sync.yaml                  飞书/钉钉 CLI 配置
  agent.yaml                 提取与解析配置
  bot.yaml                   Bot 行为配置
  paths.yaml                 路径配置

tests/
  test_bot.py                Bot 回归测试

main.py                      CLI 入口
config.py                    配置加载
models.py                    客户画像模型
prompts.yaml                 提示词配置
```

## 环境要求

- Windows 10/11
- Python `3.12+`
- 已登录的微信 PC 客户端
- GLM / OpenAI 兼容模型 API Key

可选依赖：

- `@larksuite/cli`：同步飞书
- `dws`：同步钉钉

## 安装

```powershell
git clone <your-repo-url> D:\realestate-ai-agent
cd D:\realestate-ai-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 手动配置

先复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

至少需要配置：

```env
LLM_API_KEY=your_glm_api_key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-5
```

建议补充：

```env
WECHAT_VERSION=3.x
WECHAT_DATA_DIR=
FEISHU_BASE_TOKEN=
FEISHU_TABLE_ID=
DINGTALK_BASE_ID=
DINGTALK_TABLE_ID=
```

说明：

- `WECHAT_VERSION=3.x`
  - 适合当前 `wxauto` Bot 线路
- `WECHAT_VERSION=4.x`
  - 适合当前数据库提取线路
- `WECHAT_DATA_DIR`
  - 留空时会尽量自动探测
  - 自动探测失败时再手动填写

### `config/bot.yaml` 关键项

```yaml
enabled: false
poll_interval: 5
default_mode: semi_auto
reply_debounce_seconds: 1.8
manual_conflict_guard: true
transport_backend: wxauto
```

建议当前保持：

- `transport_backend: wxauto`
- `manual_conflict_guard: true`
- `default_mode: semi_auto`

## 启动方式

### Web 控制台

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api.server:app --host 127.0.0.1 --port 8000
```

打开：

[http://127.0.0.1:8000](http://127.0.0.1:8000)

### CLI

列出联系人：

```powershell
python main.py --list-contacts
```

提取并解析某个联系人：

```powershell
python main.py --contact <wxid>
```

只解析不同步：

```powershell
python main.py --contact <wxid> --parse-only
```

直接解析聊天文本文件：

```powershell
python main.py --parse-file .\chat.txt
```

## 常用 API

- `GET /api/health`
- `GET /api/workflow/contacts`
- `POST /api/workflow/start`
- `GET /api/bot/status`
- `POST /api/bot/start`
- `POST /api/bot/stop`
- `GET /api/bot/conversations`
- `PATCH /api/bot/settings/global`
- `PATCH /api/bot/settings/{wxid}`
- `POST /api/bot/send`
- `GET /api/bot/stream`

## 测试

```powershell
python -m pytest tests\test_bot.py -q
```

当前离线 Bot 回归覆盖了：

- 自动接管模式
- 半自动审批
- 发送失败回退
- 全局设置与单会话覆写
- 调度器事件循环修复
- 画像空结果保护
- 3.x `wxauto` 监控映射逻辑

## 已知注意事项

- 这个项目默认运行在本地真实 Windows 桌面，不适合无头服务器
- 自动发送阶段依赖已登录微信和可交互桌面
- 不建议把真实生产客户会话直接一键开成全自动，建议先从 `semi_auto` 起步
- `3.x` 降级运行时，可能需要额外处理微信客户端自动升级
- `_vendor/` 仅作为本地参考代码来源，不属于项目运行必需部分

## 明天继续前建议

- 保留当前 `3.9.10.19` 环境
- 不要删 `.env`、`config/bot.yaml` 和当前微信登录态
- 如果要继续联调真实自动回复，优先用测试联系人或文件传输助手
