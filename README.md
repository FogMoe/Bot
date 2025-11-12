# Telegram AI Bot

基于 **aiogram 3**、**pydantic-ai** 和 **MySQL 8** 构建的异步 Telegram 机器人脚手架。  
主要功能：

- 免费与专业版分层（每小时 5 条 vs 50 条消息），通过存储在 MySQL 中的卡密激活。
- 模块化的逻辑/应用层，包含仓储层、服务层和路由层。
- 通过 `pydantic-ai` 实现智能体响应，支持可插拔工具和长期记忆钩子。
- MarkdownV2 格式输出，支持换行分割，未来可集成 Redis/向量数据库。

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
   BOT_LLM__API_KEY=sk-...
   ```

4. 使用轮询模式运行机器人：

   ```bash
   python -m app.main
   ```

机器人会为每次更新管理数据库会话，持久化对话记录，执行每小时配额限制，并调用 pydantic-ai 智能体。工具日志表和向量/Redis 钩子已就位，可供未来集成使用。
