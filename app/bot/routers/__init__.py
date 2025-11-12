from aiogram import Router

from app.bot.routers import chat


def setup_routers() -> Router:
    router = Router()
    router.include_router(chat.router)
    return router


__all__ = ["setup_routers"]
