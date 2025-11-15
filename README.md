# Telegram AI Bot

基于 **aiogram 3**、**pydantic-ai** 和 **MySQL 8** 构建的异步 Telegram 机器人脚手架。  
主要功能：

- 免费 / Plus / Pro / Max 4档配额（每小时 10 / 25 / 50 / 200 条），通过 MySQL 中的卡密激活；新用户落库时自动创建 FREE 订阅。
- 模块化的逻辑/应用层，包含仓储层、服务层和路由层。
- 通过 `pydantic-ai` 实现智能体响应，支持可插拔工具和长期记忆钩子。
- 工具层统一通过服务注入：内置 SerpApi Google 搜索、Jina Reader 抓取网页、Judge0 远程 Python 代码执行。
- MarkdownV2 格式输出，支持换行分割；所有业务时间戳均使用 UTC，Agent 调用具备 HTTP/协程双重超时保护。
- 按小时限流期间，会依据 `BOT_REQUEST_LIMIT__WINDOW_RETENTION_HOURS` 自动清理过期窗口，防止 `usage_hourly_quota` 膨胀。
- 内置 `pytest` 用例覆盖订阅默认化与速率限制逻辑，可运行 `pytest` 快速回归。

## 项目结构

```
app/
  agents/          # 智能体编排器 + 工具注册表
  bot/             # 路由、中间件、Telegram 格式化助手
  db/              # SQLAlchemy 模型 + 异步会话助手
  domain/          # Pydantic 领域对象
  services/        # 业务逻辑（订阅、速率限制、记忆、对话）
  utils/           # Token 估算、其他工具
db/schema.sql      # 与 SQLAlchemy 模型匹配的 MySQL DDL
pyproject.toml     # 依赖项（aiogram、pydantic-ai、SQLAlchemy 等）
```

docs/agent 下的文件是给agent读的。

## 本地运行

1. 创建并激活 Python 3.11+ 环境，然后安装依赖：

   ```bash
   pip install -e .
   ```

2. 配置 MySQL 8 并应用 `db/schema.sql`。示例：

   ```bash
   mysql -u root -p < db/schema.sql
   ```

3. 复制 `.env.example` -> `.env` 并设置：

   ```
   BOT_TELEGRAM_TOKEN=123456:ABC
   BOT_DATABASE__DSN=mysql+asyncmy://bot:bot@localhost:3306/telegram_bot
   BOT_LLM__PROVIDER=openai           # openai / azure / zhipu / gemini / custom
   BOT_LLM__MODEL=gpt-4o-mini
   BOT_LLM__OPENAI__API_KEY=sk-...
   BOT_SUMMARY__PROVIDER=             # 可选，缺省继承主模型
   BOT_SUMMARY__MODEL=
   BOT_COLLABORATOR__PROVIDER=        # 可选，单独为协作子 agent 指定 provider
   BOT_COLLABORATOR__MODEL=           # 可选，单独为协作子 agent 指定模型
   BOT_VISION__PROVIDER=              # 可选，图片描述 agent 的 provider，默认沿用主模型
   BOT_VISION__MODEL=                 # 可选，图片描述 agent 的模型名称，默认沿用主模型
   BOT_TOOL_AGENT__PROVIDER=openai
   BOT_TOOL_AGENT__MODEL=gpt-4o-mini
   ```

   - 如果使用 Azure，请改填 `BOT_LLM__AZURE__*`（API_KEY / BASE_URL / API_VERSION）。
   - 使用智谱或 Gemini 时，设置 `BOT_LLM__ZHIPU__API_KEY` / `BOT_LLM__GEMINI__API_KEY` 以及对应 `BASE_URL`。
   - 总结模型只需指定 provider 与 model，会自动复用上面配置的凭据。
   - 协作子 agent 默认为主模型，可通过 `BOT_COLLABORATOR__*` 覆盖。
    - 实时行情工具 `fetch_market_snapshot` 默认请求 https://s2.lilith.pro/9rinapi.php?action=get_snapshot_data。
      - 如需更换数据源，可通过 `BOT_EXTERNAL_TOOLS__MARKET_SNAPSHOT_URL` / `MARKET_SNAPSHOT_ACTION` 覆盖。

   如需单独配置总结模型，可设置 `BOT_SUMMARY__*`（provider/model/base_url/api_key），否则默认沿用主 LLM。
   如需启用工具调用的外部 API，请设置 `BOT_EXTERNAL_TOOLS__*` 相关变量（SerpApi、Jina Reader、Judge0）。默认值会保留占位，便于本地演示。

4. 如需通过代理访问 Telegram，可在 `.env` 中设置 `BOT_TELEGRAM_PROXY`（支持 http/https/socks5 URL）；留空表示直连。

5. 使用轮询模式运行机器人：

   ```bash
   python -m app.main
   ```

机器人会为每次更新管理数据库会话，持久化对话记录，执行每小时配额限制，并调用 pydantic-ai 智能体。工具日志表和向量/Redis 钩子已就位，可供未来集成使用。

## 测试

```bash
pip install -e .[dev]
pytest          # 运行全部单测
# 如需覆盖率：pytest --cov=app （需安装 pytest-cov）
# 集成测试包含在默认 test suite（tests/test_integration.py）中，确保订阅/配额/对话/记忆链路完整。
```

## 管理员命令
- /issuecard <plan_code> [days] [card_code] - 生成订阅卡
  - 仅 `BOT_ADMIN_TELEGRAM_ID` 指定的管理员可用，用于创建新的订阅卡。
- /announce <text> - 向所有用户广播公告
  - 仅 `BOT_ADMIN_TELEGRAM_ID` 指定的管理员可用，会把公告文本发送给所有机器人用户。
