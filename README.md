# Realty Agent

Windows 本地运行的地产客服与客户画像工具。

当前已经打通的主链路：
- 读取微信 `4.x` 本地数据库
- 解密并提取私聊消息
- 用单个画像总结 Agent 提炼客户需求字段
- 用本地代码直接补齐 `wechat_id`、`wechat_name`、时间等强信号字段
- 同步到飞书多维表

## 当前实现

### 画像链路

当前画像链路已经简化为两层：
1. 本地代码提取强信号字段
2. 单个 LLM Agent 只负责聊天理解和客户画像总结

本地字段不会再发送给“飞书整理 Agent”，因为该 Agent 已删除。

### 本地优先字段

下面这些字段优先由代码直接提取并写入最终画像：
- `phone`
- `wechat_id`
- `wechat_name`
- `first_contact_date`
- `first_followup_date`
- `latest_followup_date`

注意：
- `wxid` 是微信内部 ID
- `wechat_id` 是微信号
- 两者不能混用

### 安全处理

发送给 LLM 前会先做脱敏：
- `FEISHU_BASE_TOKEN`
- `FEISHU_TABLE_ID`
- `LLM_API_KEY`
- 其他匹配到的 `token/key/secret` 类字段

CLI 里的聊天预览也会显示脱敏后的内容。

## 环境要求

- Windows 10/11
- Python `3.12+`
- 已登录的微信 PC 客户端
- OpenAI 兼容接口的模型 Key
- 可选：`lark-cli` 用于飞书同步

## 安装

```powershell
git clone <your-repo-url> D:\realty-agent
cd D:\realty-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置

先复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

最少需要配置：

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-5
WECHAT_VERSION=4.x
WECHAT_DATA_DIR=
```

如果要同步飞书：

```env
FEISHU_BASE_TOKEN=
FEISHU_TABLE_ID=
```

## 启动方式

### CLI

列出联系人：

```powershell
python main.py --list-contacts
```

解析并同步某个联系人：

```powershell
python main.py --contact <wxid>
```

只解析不同步：

```powershell
python main.py --contact <wxid> --parse-only
```

直接解析聊天文本：

```powershell
python main.py --parse-file .\chat.txt
```

### Web

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api.server:app --host 127.0.0.1 --port 8000
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)

## 微信 3.9 登录辅助脚本

仓库里保留了两个 3.9 登录辅助脚本，便于参考或兼容旧链路：
- `scripts/start_wechat_39.ps1`
- `scripts/wechat_39_login_patch.py`

当前主推荐链路仍然是微信 `4.x` 数据提取与飞书同步。

## 飞书同步说明

当前飞书同步逻辑：
- 优先按 `wechat_id` 查重
- 如果没有 `wechat_id`，再按 `phone` 查重
- 如果两者都没有命中，则创建新记录

如果飞书里已存在旧脏数据，可能出现重复记录，建议人工清理后再做 UAT。

## 当前已验证能力

已经实际验证通过：
- 微信 `4.x` 数据库解密
- 私聊联系人提取
- 单联系人画像生成
- 飞书记录创建与更新
- `微信号` / `微信名称` 字段更新

## 主要文件

```text
main.py                      CLI 入口
config.py                    配置加载
models.py                    客户画像模型与飞书字段映射
prompts.yaml                 LLM 提示词配置

agents/
  profile_parser.py          本地字段提取 + 单 Agent 画像总结

services/
  feishu_service.py          飞书同步
  sync/
    decrypt.py               微信数据库解密
    extract.py               联系人与消息提取
    db_layout.py             数据库结构识别
    wechat_path.py           微信目录探测

api/
  server.py                  FastAPI 入口
```

## 已知限制

- LLM 接口偶发超时或限流时，整条画像链路会变慢
- 已加入重试，但模型侧不稳定时仍可能失败
- `phone`、`family_members`、`current_visit_date` 等字段仍可继续增强本地规则
- 当前飞书表若已有重复客户，需要结合业务规则进一步去重
