# README.agent

给后续 Agent 的最小接手说明。目标是：在一台 Windows 桌面机器上，把项目拉起并进入可调试状态。

## 1. 项目目标

这是一个本地运行的房产客服 Agent：

- 从微信本地数据库或微信桌面端读取聊天
- 用 `glm-5` 生成客户画像和微信回复
- 把画像同步到飞书/钉钉
- 提供 FastAPI + Web 控制台
- 提供微信 Bot 托管能力

## 2. 当前推荐运行矩阵

### 推荐

- OS: Windows 10/11
- Python: `3.12+`
- 微信: `3.9.10.19`
- Bot 发送后端: `wxauto`
- LLM: `glm-5`

### 兼容

- 微信 `4.x`
  - 数据提取链路可用
  - Bot 自动发送链路仍在继续适配

## 3. 一键部署

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_agent.ps1
```

这个脚本会：

- 创建 `.venv`
- 安装 `requirements.txt`
- 安装 `wxauto`
- 自动补齐 `.env`
- 创建 `data/`、`decrypted/`、`logs/`
- 可选执行测试
- 可选启动 Web 服务

## 4. 必填配置

编辑 `.env`：

```env
LLM_API_KEY=your_key
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-5
WECHAT_VERSION=3.x
WECHAT_DATA_DIR=
```

如果要同步飞书或钉钉，再填：

```env
FEISHU_BASE_TOKEN=
FEISHU_TABLE_ID=
DINGTALK_BASE_ID=
DINGTALK_TABLE_ID=
```

## 5. 启动

### Web

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api.server:app --host 127.0.0.1 --port 8000
```

### CLI

```powershell
python main.py --list-contacts
python main.py --contact <wxid> --parse-only
```

## 6. 接手时先做的检查

```powershell
python -m pytest tests\test_bot.py -q
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8000/api/bot/status | ConvertTo-Json -Depth 8
```

确认点：

- 微信进程存在
- `transport_mode` 为 `desktop_rpa/wxauto`
- `LLM_API_KEY` 已配置
- `tests/test_bot.py` 通过

## 7. 当前实现边界

### 已经稳定的部分

- FastAPI 控制台
- 调度器基础能力
- 数据提取与画像解析
- 飞书/钉钉同步骨架
- Bot 的策略模型
- Bot 的 `wxauto` 发送后端

### 继续开发时重点看这里

- [D:\realestate-ai-agent\services\bot\monitor.py](D:/realestate-ai-agent/services/bot/monitor.py)
- [D:\realestate-ai-agent\services\bot\sender.py](D:/realestate-ai-agent/services/bot/sender.py)
- [D:\realestate-ai-agent\services\bot\wechat_backends.py](D:/realestate-ai-agent/services/bot/wechat_backends.py)
- [D:\realestate-ai-agent\tests\test_bot.py](D:/realestate-ai-agent/tests/test_bot.py)

## 8. 建议的接手顺序

1. 跑测试，确认当前代码状态。
2. 启动 API，确认 `/api/health` 和 `/api/bot/status` 正常。
3. 用 `/api/bot/send` 对 `文件传输助手` 做实发。
4. 再做真实联系人联调。
5. 如果是 `3.x`，优先沿 `wxauto` 线路继续。
6. 如果是 `4.x`，优先继续完善 `wechat_backends.py` 的 Windows 主窗后端。

## 9. 不要做的事

- 不要把 `_vendor/` 当成运行依赖
- 不要默认开启全局 `auto`
- 不要假设 `wxid` 一定等于微信搜索可见名称
- 不要在没有可交互桌面的情况下做真实 RPA 联调

## 10. 明天继续时的建议入口

- 先看 `git status`
- 再看 `README.md`
- 然后从 `services/bot/monitor.py` 和 `services/bot/wechat_backends.py` 接着调真机链路
