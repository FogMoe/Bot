# Bot Project Overview

## 当前能力概览

- **Telegram 交互**：基于 aiogram 3，包含数据库会话中间件、用户上下文、按小时限流。
- **订阅/配额**：支持卡密激活，`user_subscriptions` 记录每次订阅。小时额度随计划自动调整，过期后回退到免费额度。
- **Agent 架构**：
  - 主 Agent (`AgentOrchestrator`) 负责与用户对话，使用 pydantic-ai，并可调用工具。
  - 工具通过 `ToolTemplate` 注册，实际业务逻辑放在 service 层（如 `SearchService`）。工具调用历史由 pydantic-ai 原生机制管理，并写入 `messages` 以供上下文参考。
  - 短期上下文：`messages` 表按会话保存 `result.all_messages()` 的完整 JSON 轨迹（含工具调用），Agent 直接复用该快照作为下一轮的 `message_history`。
  - 长期记忆：表结构和 `MemoryService` 已就绪，但尚未实现自动提取/压缩。
- **i18n**：使用 `app/i18n/locales/<locale>.json` 的结构化文案。`I18nService` 负责加载与缓存，默认语言 en，可按用户 `language_code` 切换。
- **数据库**：MySQL 8，`db/schema.sql` 与 SQLAlchemy 模型同步。已清理未使用的 `tool_catalog`、`tool_invocations`、`i18n_strings`。

## MVP 流程

1. 用户 `/start` → 自动建会话，返回当前订阅信息。
2. 用户 `/activate <card>` → `SubscriptionService` 校验卡密，写入订阅并更新配额。
3. 发送消息 → 中间件扣减小时额度。`AgentOrchestrator` 载入上一次的 `all_messages()` 快照与记忆摘要，调用 pydantic-ai，如果需要会触发工具。
4. 模型回复/工具输出由 `result.all_messages()` 覆盖式写回 `messages`，从而保证连续对话与工具轨迹。

## 代码结构

- `app/config.py`：环境配置（数据库、LLM、订阅、代理等）。
- `app/db/models`：SQLAlchemy ORM；`db/schema.sql` 为对应 DDL。
- `app/services/*`：业务逻辑（订阅、额度、会话、搜索等）。
- `app/agents/*`：Agent orchestrator、历史转换、工具注册。
- `app/bot/*`：aiogram routers/middlewares/格式化处理。
- `app/i18n/`：JSON 文案 + 读取服务。
- `docs/`：文档（本文件）。

## 运行指南（摘要）

1. Python 3.11+，`pip install -e .`
2. 导入 `db/schema.sql` 至 MySQL。
3. 复制 `.env.example` → `.env`，设置：
   - `BOT_TELEGRAM_TOKEN`
   - `BOT_DATABASE__DSN`
   - `BOT_LLM__PROVIDER/MODEL/API_KEY/...`
   - 可选 `BOT_TELEGRAM_PROXY`
4. 运行 `python -m app.main`（轮询模式）。

## 维护建议

- **工具扩展**：在 service 层实现业务逻辑，使用 `ToolTemplate` 注册，提供清晰的 `name/description`。pydantic-ai 会负责历史记录，无需另写日志表。
- **记忆体系**：长期记忆触发尚未实现，可在 `MemoryService` 上扩展（如监听 `context_tokens` 超限或特定关键词时写入）。
- **订阅续费/通知**：如需严格到期处理，可添加定时任务将过期订阅 `status` 改为 `expired` 并通知用户。
- **i18n**：要新增语言，只需在 `app/i18n/locales/` 添加 `<locale>.json`，注意键名统一。若需在线更新，可再扩展文件热加载或后台接口。
- **测试**：建议为 service 层（订阅、额度、记忆、搜索）和新的 `all_messages` 序列化/持久化逻辑补充单元测试，确保后续 refactor 时行为稳定。
- **非文本消息处理**：目前仅做占位记录（回复“暂不支持”），后续若要真正处理图片/语音等，应完善持久化结构与业务逻辑。
- **系统消息/错误写入**：可根据需要在异常处写入 `role="system"` 的消息，供下一轮 Agent 读取；当前实现尚未自动记录错误。
- **消息压缩/清理**：`messages` 会无限增长。利用 `memory_chunks`/`memory_compressions` 压缩旧对话并删除原记录，是后续必须实现的 TODO。
- **订阅过期任务**：当前仅在查询时降级到免费额度。如需更严格的过期处理（状态置为 `expired`、提醒用户等），需要额外的定时任务或后台流程。

> 若要引入新的依赖/模块，请更新 `pyproject.toml` 并记录在本文件，以便后续维护。
