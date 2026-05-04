# RealEstate AI Agent

西双版纳21世纪房地产 AI客服A岗系统原型 — 端到端管道：微信聊天记录提取 → AI画像解析 → 钉钉同步

## 功能

- **微信聊天提取**：解密微信PC本地数据库，提取私聊(DM)消息记录
- **AI画像解析**：通过LLM从聊天记录中提取69字段客户画像（结构化JSON）
- **钉钉同步**：自动将客户画像创建/更新到钉钉AI表格
- **提示词可配置**：所有AI提示词存储在独立的 `prompts.yaml` 中，修改无需动代码

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 填入：
- `LLM_API_KEY` — 智谱API Key
- `WECHAT_DATA_DIR` — 微信数据目录路径（如 `C:\Users\你的用户名\Documents\WeChat Files\wxid_xxxxx`）
- `DINGTALK_BASE_ID` / `DINGTALK_TABLE_ID` — 钉钉AI表格ID（可选，不填则跳过同步）

同时修改 `adapters/config.yaml` 中的微信数据路径。

### 3. 运行

```bash
# 列出微信私聊联系人（需先登录微信PC版）
python main.py --list-contacts

# 提取指定联系人的聊天记录 + AI解析 + 同步钉钉
python main.py --contact <wxid>

# 指定日期
python main.py --contact <wxid> --date 2026-05-03

# 只解析不同步钉钉
python main.py --contact <wxid> --parse-only

# 直接解析聊天文件（不提取微信）
python main.py --parse-file <chat.txt>
python main.py --parse-file <chat.txt> --parse-only
```

## 项目结构

```
├── adapters/
│   ├── decrypt.py          # 微信数据库解密（基于PyWxDump）
│   ├── extract.py          # 聊天记录提取（群聊 + 私聊DM）
│   └── config.yaml         # 微信路径配置
├── agents/
│   └── profile_parser.py   # AI解析：聊天记录 → 69字段客户画像
├── services/
│   └── dingtalk_service.py # 钉钉同步（dws CLI）
├── config.py               # 全局配置
├── models.py               # 69字段Pydantic模型
├── prompts.yaml            # 提示词配置（独立文件，方便修改）
├── main.py                 # 管道入口
└── requirements.txt
```

## 自定义提示词

编辑 `prompts.yaml` 即可调整AI行为，无需修改代码：

- `profile_parser.system` — 画像解析的系统提示词
- `profile_parser.user_template` — 用户消息模板
- `chat_agent.*` — 对话Agent各阶段提示词（后续版本使用）

## 69字段客户画像

客户画像包含9大模块：

| 模块 | 字段数 | 示例字段 |
|------|--------|----------|
| 系统字段 | 2 | 用户ID、手机号 |
| 基本信息 | 12 | 姓名、性别、年龄、籍贯 |
| 客户来源 | 4 | 渠道、引流入口、首次留资时间 |
| 旅居信息 | 7 | 是否来过版纳、来版纳时间、目的 |
| 核心购房需求 | 12 | 目的、区域、户型、预算、计划时间 |
| 个人偏好 | 10 | 朝向、景观、配套、装修风格 |
| 预算资质 | 6 | 付款方式、首付、月供、征信 |
| 跟进沟通 | 8 | 跟进时间、内容、顾虑点 |
| 画像总结 | 7 | 标签、性格、成交概率、跟进策略 |

## 技术栈

- **LLM**: GLM-5（智谱AI，OpenAI兼容接口）
- **LangChain**: langchain-openai + structured output
- **微信解密**: PyWxDump
- **钉钉**: dws CLI（dingtalk-workspace-cli）
- **Python**: 3.11+

## 依赖工具

- [PyWxDump](https://github.com/xaoyaoo/PyWxDump) — 微信数据库解密
- [dws CLI](https://www.npmjs.com/package/dingtalk-workspace-cli) — 钉钉工作台命令行工具

## License

Private — 仅供内部使用
