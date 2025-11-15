# 随机表情工具设计

> 目标：让 Agent 可以调用一个“发送随机表情”的工具，访问第三方提供的随机 emoji API（API 返回 3xx 重定向到图片 URL），最终直接把表情图片发送给 Telegram 用户。

## 架构概览

```
🍀 随机表情 API  (HTTP 可重定向) 
        ↑              
        |  httpx.AsyncClient GET / retry / 302 follow
        ↓
 EmojiService.query_random()  ——>  EmojiTool (pydantic-ai tool) 
                                        ↓
                          AgentDependencies.tool_media_cb(message.answer_photo)
                                        ↓
                        Telegram 用户收到一条图片消息
```

## 实现步骤

1. **配置项**
   - 在 `ExternalToolSettings` 添加 `emoji_api_url`（默认指向随机 API），可复用 `request_timeout_seconds`。
   - 这样 `AgentDependencies.tool_settings` 自动包含配置，服务可以读取。

2. **服务层 (`EmojiService`)**
   - 放在 `app/services/external_tools.py` 内，复用 `_BaseToolService`。
   - 行为：
     ```python
     response = await self._client.get(self._settings.emoji_api_url, follow_redirects=True)
     response.raise_for_status()
     return {
         "final_url": str(response.url),
         "content": response.content,
         "content_type": response.headers.get("Content-Type")
     }
     ```
   - 出错时抛 `ToolServiceError`，例如网络失败或 API 返回非 2xx。

3. **工具输入/输出模型**
   - `SendEmojiInput(ToolInputBase)`：可选字段 `style` 或 `category`，默认 `random`。
   - `SendEmojiOutput(BaseModel)`：
     - `image_url`: str
     - `caption`: Optional[str]
     - `status`: Literal["sent", "failed"]
     - `error_message`: Optional[str]

4. **工具实现 `send_emoji_tool`**
   - 拉取 `EmojiService.query_random()`，拿到图片 URL 与二进制内容。
   - 通过新的 `tool_media_cb`（详见下一节）直接 `await tool_media_cb(content, caption)`，让 Telegram 立即收到图片。
   - 返回 `SendEmojiOutput(status="sent", image_url=..., caption=...)`，若出现异常则 `status="failed"` 并填入 `error_message`（同现在行情工具的做法）。

5. **AgentDependencies 扩展**
   - 在 `app/agents/runner.py` 中给 `AgentDependencies` 增加 `tool_media_cb: Callable[[bytes, str | None], Awaitable[None]] | None`。
   - `_process_user_prompt` 中定义：
     ```python
     async def send_tool_media(content: bytes, caption: str | None = None):
         photo = BufferedInputFile(content, filename="emoji.png")
         await message.answer_photo(photo, caption=caption)
     ```
     并将其传入 `agent.run(..., tool_media_cb=send_tool_media)`。

6. **Tool Registry 注册**
   - 在 `app/agents/toolkit.py` 中添加输入/输出模型与 `send_emoji_tool`。
   - 将工具插入 `DEFAULT_TOOLS`，名称可为 `send_emoji` 或 `random_emoji`，描述“发送随机 emoji 图片给用户”。
   - 更新 Agent instructions：“8. send_emoji (emoji) - 调用此工具可以直接发送随机表情图片”。

7. **错误处理**
   - 若 API 请求失败、回调不存在等情况，工具返回 `status="failed"` 和 `error_message`，Agent 可向用户解释。
   - `tool_media_cb` 缺失时抛出 `RuntimeError("tool_media_cb is not configured")`，避免无声失败。

## 后续可选增强

- 支持不同分类（Happy / Sad），在输入参数中传递并在服务层拼接查询字符串。
- 对图片内容做缓存（例如上传到 Telegram 获取 file_id，后续直接 sendPhoto(file_id) 节省带宽）。
- 将 `caption` 支持多语言，通过 I18nService 生成“送你一张随机表情”。

按照以上方案，实现后的工具可以被 Agent 像其他工具一样调用：当模型想给用户“发一个表情”时，调用 `send_emoji`，工具负责请求随机 API 并把图片推送到聊天，整个过程对用户透明。
