# Realty Agent

AI房产客服系统 — 微信聊天记录提取 → AI画像解析 → 飞书/钉钉同步

> 基于真实房地产业务场景开发的AI客户画像系统，从微信私聊记录中自动提取69字段客户画像并同步到办公平台。

## 功能

- **Web仪表盘**：单页可视化控制台，实时监控解密/提取/解析/同步全流程
- **微信聊天提取**：解密微信PC本地数据库，提取私聊(DM)消息记录
- **AI画像解析**：通过LLM从聊天记录中提取69字段客户画像（结构化JSON）
- **飞书同步**：按微信号唯一键去重，自动创建/更新飞书多维表格记录
- **钉钉同步**：自动将客户画像创建/更新到钉钉AI表格
- **批量扫描**：一键扫描所有联系人的聊天记录，逐个AI解析并同步
- **定时任务**：支持 cron 定时自动执行扫描任务
- **Agent工具层**：11个LangChain Tool，供LangGraph Agent直接调用
- **提示词可配置**：所有AI提示词存储在独立的 `prompts.yaml` 中
- **配置分离**：所有参数按域拆分到 `config/*.yaml`，敏感凭证放 `.env`

## 快速开始

> 以下步骤假设你的电脑是一台全新的 Windows 机器，没有安装过 Python 和 Git。

### 前置条件：安装 Git

如果你已经有 Git，跳过这步。

1. 打开浏览器访问 https://git-scm.com/download/win
2. 下载并安装，安装过程中全部点"下一步"即可
3. 安装完成后，在开始菜单搜索 **Git Bash** 并打开，输入 `git --version` 验证安装成功

### 第 1 步：下载项目代码

```bash
# 把代码克隆到本地（在 Git Bash 或终端中执行）
git clone <项目仓库地址>
cd realty-agent
```

> 如果你已经下载了代码压缩包并解压，直接 `cd` 进入项目目录即可。

### 第 2 步：安装 Python 3.12

> **为什么是 3.12？** 项目依赖 PyAudio（微信语音处理），只有 Python 3.12 有预编译的安装包。使用 3.13 或更高版本会要求你额外安装 C++ 编译器，非常麻烦。

**方法 A — winget（推荐，Win10/11 自带）：**

打开终端（PowerShell 或 CMD），执行：

```bash
winget install Python.Python.3.12
```

安装完成后 **关闭并重新打开终端**，然后验证：

```bash
py -3.12 --version
# 应该输出：Python 3.12.x
```

**方法 B — 手动下载：**

1. 访问 https://www.python.org/downloads/release/python-31210/
2. 滚动到底部，下载 **Windows installer (64-bit)**
3. 运行安装程序，**务必勾选 "Add python.exe to PATH"**
4. 安装完成后关闭并重新打开终端，运行 `py -3.12 --version` 验证

### 第 3 步：创建虚拟环境并安装依赖

> **什么是虚拟环境？** 它把项目的 Python 包隔离在项目目录内，不会污染系统 Python，也不会和其他项目冲突。

```bash
# 进入项目目录（如果还没进入的话）
cd realty-agent

# 创建虚拟环境（只需要执行一次）
py -3.12 -m venv .venv

# 激活虚拟环境（每次打开新终端都需要执行）
.venv\Scripts\activate

# 激活后命令行前面会出现 (.venv) 标识，说明已激活
# 安装所有依赖（锁定了版本号，确保所有人环境一致）
pip install -r requirements.lock
```

> 安装过程需要几分钟，看到 `Successfully installed ...` 就是成功了。
>
> **常见问题：** 如果 `pip install` 报错 `No module named pip`，先执行：
> ```bash
> py -3.12 -m ensurepip
> ```

> **注意：** 每次关闭终端后虚拟环境会自动退出。下次重新打开终端进入项目时，需要再次执行 `.venv\Scripts\activate`。

### 第 4 步：配置环境变量

项目需要 LLM API 密钥等敏感信息，通过 `.env` 文件配置（此文件不会提交到 Git）。

```bash
# 从模板复制一份配置文件
cp .env.example .env
```

然后用任意文本编辑器打开 `.env`，填入你的真实信息：

```env
# LLM API 配置（必填，不填无法使用 AI 解析功能）
LLM_API_KEY=你的API密钥
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-5

# 微信数据目录（留空会自动检测，一般不用改）
WECHAT_DATA_DIR=

# 飞书多维表格（如果不用飞书同步，可以留空）
FEISHU_BASE_TOKEN=你的飞书base_token
FEISHU_TABLE_ID=你的飞书table_id

# 钉钉AI表格（如果不用钉钉同步，可以留空）
DINGTALK_BASE_ID=你的钉钉base_id
DINGTALK_TABLE_ID=你的钉钉table_id
```

> 最少只需填写 `LLM_API_KEY` 即可启动服务。飞书和钉钉配置如果不使用对应同步功能可以留空。

**微信数据目录配置：**

程序通常会自动检测微信数据目录。如果仪表盘显示"无法自动检测微信数据目录"，需要手动配置：

1. 打开微信 PC 版 → 左下角菜单 → 设置 → 文件管理 → 打开文件夹
2. 你会进入类似 `C:\Users\你的用户名\Documents\WeChat Files\wxid_xxxxx\` 的目录
3. 将这个路径填写到 `.env` 中的 `WECHAT_DATA_DIR`：

```env
WECHAT_DATA_DIR=C:\Users\你的用户名\Documents\WeChat Files\wxid_xxxxx
```

或者填写到 `config/wechat.yaml` 的 `data_dir` 字段（效果相同）。

非敏感参数按需修改 `config/` 下的 YAML 文件：

| 文件 | 内容 |
|------|------|
| `config/llm.yaml` | LLM温度、最大token数 |
| `config/wechat.yaml` | 数据库名、扫描范围、微信数据目录 |
| `config/sync.yaml` | CLI工具路径、超时时间 |
| `config/agent.yaml` | 消息提取条数、联系人显示上限 |
| `config/paths.yaml` | 数据目录、提示词文件路径 |

### 第 4.5 步：（可选）安装飞书同步工具

如果你需要把客户画像同步到飞书多维表格，需要安装 `lark-cli` 命令行工具。不需要飞书同步可以跳过。

> **前提：** 需要先安装 [Node.js](https://nodejs.org/)（下载 LTS 版本，安装时全部点"下一步"即可）。

```bash
# 安装飞书官方 CLI 工具
npm install -g @larksuite/cli

# 验证安装（必须看到版本号输出才算安装成功）
lark-cli --version
```

> **注意：** 包名是 `@larksuite/cli`，不是 `lark-cli`。`npm install -g lark-cli` 安装的是一个无关的第三方包，无法使用。
>
> **常见问题：** 如果 `lark-cli --version` 提示"命令未找到"，说明 npm 全局路径没加入 PATH：
> 1. 终端中运行 `npm config get prefix` 查看路径（通常是 `C:\Users\你的用户名\AppData\Roaming\npm`）
> 2. 打开 Windows 设置 → 搜索"环境变量" → 编辑用户环境变量 → 在 PATH 中添加上面的路径
> 3. 关闭并重新打开终端，再试 `lark-cli --version`
>
> 如果仍然不行，可以在 `config/sync.yaml` 中手动指定完整路径：
> ```yaml
> lark_cli_path: "C:\\Users\\你的用户名\\AppData\\Roaming\\npm\\lark-cli.cmd"
> ```

安装完成后，在 `.env` 文件中填写飞书配置：

```env
FEISHU_BASE_TOKEN=你的飞书多维表格base_token
FEISHU_TABLE_ID=你的飞书多维表格table_id
```

> **如何获取 base_token 和 table_id：** 打开飞书多维表格的网页链接，URL 格式为：
> `https://xxx.feishu.cn/base/XXXXXXXXXXXXXX?table=tblYYYYYYYYYY`
> 其中 `XXXXXXXXXXXXXX` 是 `FEISHU_BASE_TOKEN`，`tblYYYYYYYYYY` 是 `FEISHU_TABLE_ID`。

### 第 5 步：启动服务

```bash
# 确保已激活虚拟环境（命令行前面有 (.venv)）
.venv\Scripts\activate

# 启动 Web 服务
uvicorn api.server:app --reload --port 8000
```

看到类似以下输出说明启动成功：

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

然后用浏览器打开 **http://localhost:8000**，即可使用 Web 仪表盘。

> **停止服务：** 在终端中按 `Ctrl + C`
>
> **`--reload` 参数：** 开发模式下代码修改后服务会自动重启。生产环境部署时去掉这个参数。

### Web 仪表盘功能

1. **环境状态** — 自动检测微信进程、数据库、LLM接口、飞书连通性
2. **联系人选择** — 点击解密后加载联系人列表，支持搜索和备注名优先显示
3. **管道控制** — 选择联系人+日期范围，启动单次或全量扫描
4. **任务监控** — 实时显示运行中任务的步骤进度，支持中途停止
5. **工具调用日志** — 按任务筛选查看每一步的输入/输出/耗时
6. **定时任务** — 通过弹窗创建 cron 定时扫描任务

### 命令行使用

除了 Web 仪表盘，也可以直接用命令行操作（同样需要先激活虚拟环境）：

```bash
.venv\Scripts\activate

# 列出微信私聊联系人（需先登录微信PC版）
python main.py --list-contacts

# 提取指定联系人的聊天记录 + AI解析 + 同步飞书
python main.py --contact <wxid>

# 指定日期
python main.py --contact <wxid> --date 2026-05-03

# 只解析不同步
python main.py --contact <wxid> --parse-only

# 直接解析聊天文件（不提取微信）
python main.py --parse-file <chat.txt>
```

## 项目结构

```
├── api/                       # Web仪表盘（FastAPI + SSE）
│   ├── server.py              # 应用入口 + 静态文件挂载
│   ├── scheduler.py           # APScheduler 定时任务引擎
│   ├── tool_logger.py         # 工具调用日志（环形缓冲区 + SSE广播）
│   ├── routers/
│   │   ├── workflow.py        # 管道控制（启动/停止/联系人/解密/运行记录）
│   │   ├── scheduler_router.py# 定时任务 CRUD
│   │   ├── health.py          # 环境健康检测
│   │   └── logs.py            # 日志历史 + SSE 实时流
│   └── static/
│       └── index.html         # 单页仪表盘（HTML/CSS/JS）
├── config/                    # 配置文件（按域拆分）
│   ├── llm.yaml               # LLM参数
│   ├── wechat.yaml            # 微信数据库配置
│   ├── sync.yaml              # 飞书/钉钉CLI配置
│   ├── agent.yaml             # Agent行为参数
│   └── paths.yaml             # 文件路径配置
├── adapters/
│   ├── decrypt.py             # 微信数据库解密（基于PyWxDump）
│   └── extract.py             # 聊天记录提取（群聊 + 私聊DM）
├── agents/
│   ├── profile_parser.py      # AI解析：聊天记录 → 69字段客户画像
│   └── tools/                 # LangChain Tool封装（11个工具）
│       ├── wechat_tools.py    # 微信：解密、搜索联系人、提取消息
│       ├── profile_tools.py   # 画像：AI解析、保存、加载
│       └── sync_tools.py      # 同步：飞书/钉钉CRUD
├── services/
│   ├── feishu_service.py      # 飞书多维表格同步（lark-cli）
│   └── dingtalk_service.py    # 钉钉AI表格同步（dws CLI）
├── config.py                  # 配置加载器（YAML + .env）
├── models.py                  # 客户画像Pydantic模型 + 字段映射
├── prompts.yaml               # 提示词配置
├── main.py                    # 管道入口
├── requirements.txt           # 依赖声明（宽松版本范围）
└── requirements.lock          # 依赖锁定（精确版本号，部署用这个）
```

## API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/health` | 环境健康检测（微信/数据库/LLM/飞书） |
| `POST` | `/api/workflow/start` | 启动管道（单联系人或全部） |
| `POST` | `/api/workflow/stop` | 停止运行中的管道 |
| `GET` | `/api/workflow/runs` | 获取所有运行记录（支持页面刷新恢复） |
| `GET` | `/api/workflow/contacts` | 获取有消息的联系人列表 |
| `GET` | `/api/workflow/decrypt` | 触发数据库解密 |
| `GET` | `/api/logs/stream` | SSE 实时日志流 |
| `GET` | `/api/logs` | 历史日志查询 |
| `POST` | `/api/scheduler/tasks` | 创建定时任务 |
| `GET` | `/api/scheduler/tasks` | 列出定时任务 |
| `PATCH` | `/api/scheduler/tasks/:id` | 更新定时任务 |
| `DELETE` | `/api/scheduler/tasks/:id` | 删除定时任务 |

## Agent工具列表

| 工具名 | 功能 |
|--------|------|
| `get_wechat_info` | 获取当前微信账号信息 |
| `decrypt_wechat_db` | 解密微信本地数据库 |
| `search_wechat_contact` | 按姓名/昵称/备注搜索联系人 |
| `extract_dm_messages` | 提取私聊消息 |
| `parse_chat_to_profile` | AI解析聊天记录为客户画像 |
| `save_profile` / `load_profile` | 保存/加载画像JSON |
| `sync_profile_to_feishu` | 同步画像到飞书（微信号去重） |
| `query_feishu_by_wechat` | 按微信号查询飞书记录 |
| `query_feishu_by_phone` | 按手机号查询飞书记录 |
| `sync_profile_to_dingtalk` | 同步画像到钉钉 |

## 客户画像字段

画像包含9大模块、69个字段，涵盖：

- **基本信息**：姓名、性别、年龄、籍贯、婚姻状况
- **客户来源**：获客渠道、引流入口、关键词
- **旅居信息**：来版纳时间、停留天数、居住月数
- **核心购房需求**：目的、区域、户型、预算、计划时间
- **个人偏好**：朝向、景观、配套、出行方式
- **预算资质**：付款方式、首付、月供、征信
- **跟进沟通**：跟进时间、内容、顾虑点、意向房源
- **跟进阶段**：初步咨询 → 意向筛选 → 带看洽谈 → 成交
- **画像总结**：标签、性格、决策人、成交概率、跟进策略

## 配置优先级

```
.env 环境变量 > config/*.yaml > 代码默认值
```

敏感凭证（API Key、Token）放 `.env`，可调参数放 YAML。

## 技术栈

- **LLM**: GLM-5（OpenAI兼容接口）
- **LangChain**: langchain-openai + @tool
- **Web**: FastAPI + Uvicorn + SSE
- **微信解密**: PyWxDump
- **飞书同步**: @larksuite/cli（飞书官方 CLI）
- **钉钉同步**: dws CLI
- **定时任务**: APScheduler
- **Python**: 3.12

## License

MIT
