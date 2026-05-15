# Realty Agent

AI房产客服系统 — 微信聊天记录提取 → AI画像解析 → 飞书/钉钉同步

## 功能

- **微信聊天提取**：解密微信PC本地数据库，提取私聊(DM)消息记录
- **AI画像解析**：通过LLM从聊天记录中提取69字段客户画像（结构化JSON）
- **飞书同步**：按微信号唯一键去重，自动创建/更新飞书多维表格记录
- **钉钉同步**：自动将客户画像创建/更新到钉钉AI表格
- **Agent工具层**：11个LangChain Tool，供LangGraph Agent直接调用
- **提示词可配置**：所有AI提示词存储在独立的 `prompts.yaml` 中
- **配置分离**：所有参数按域拆分到 `config/*.yaml`，敏感凭证放 `.env`

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
```

编辑 `.env` 填入敏感凭证：

```env
LLM_API_KEY=你的API密钥
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-5
FEISHU_BASE_TOKEN=你的飞书base_token
FEISHU_TABLE_ID=你的飞书table_id
```

非敏感参数按需修改 `config/` 下的YAML文件：

| 文件 | 内容 |
|------|------|
| `config/llm.yaml` | LLM温度、最大token数 |
| `config/wechat.yaml` | 微信数据目录、数据库名、扫描范围 |
| `config/sync.yaml` | CLI工具路径、超时时间 |
| `config/agent.yaml` | 消息提取条数、联系人显示上限 |
| `config/paths.yaml` | 数据目录、提示词文件路径 |

### 3. 运行

```bash
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
└── requirements.txt
```

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

- **LLM**: GLM-5（智谱AI，OpenAI兼容接口）
- **LangChain**: langchain-openai + @tool
- **微信解密**: PyWxDump
- **飞书同步**: lark-cli
- **钉钉同步**: dws CLI
- **Python**: 3.11+

## License

Private
