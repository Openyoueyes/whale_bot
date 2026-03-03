# app/bot/routers/__init__.py

from aiogram import Dispatcher

from app.bot.middlewares.bitrix_first_touch import BitrixStageGuardMiddleware
from app.bot.routers.client.base import router as client_base_router
from app.bot.routers.client.prem import router as client_prem_router
from app.bot.routers.client.robots import router as client_robots_router

from app.bot.routers.admin.broadcast import router as admin_broadcast_router
from app.bot.routers.admin.dialog import router as admin_dialog_router

from app.bot.routers.common.cancel import router as common_cancel_router
from app.bot.routers.client.bonus import router as client_bonus_router
from app.bot.routers.client.manager import router as client_manager_router
from app.bot.routers.business.dialog import router as business_dialog_router
from app.bot.routers.admin.triggers import router as admin_triggers_router
from app.bot.routers.admin.getmedia import router as admin_getmedia_router
from app.bot.routers.admin.change_manager import router as admin_change_router
from app.bot.routers.common.cancel_inline import router as common_cancel_inline_router
from app.bot.routers.admin.help import router as admin_help_router
from app.bot.routers.client.quiz import router as quiz_router

def setup_routers(dp: Dispatcher) -> None:
    # Общая отмена — одной из первых
    dp.include_router(common_cancel_router)
    dp.include_router(common_cancel_inline_router)

    # Админские роутеры
    dp.include_router(admin_broadcast_router)
    dp.include_router(admin_dialog_router)
    dp.include_router(admin_triggers_router)
    dp.include_router(admin_getmedia_router)
    dp.include_router(admin_help_router)
    dp.include_router(admin_change_router)

    # Клиентские
    client_base_router.message.middleware(BitrixStageGuardMiddleware())
    dp.include_router(client_base_router)


    dp.include_router(client_prem_router)
    dp.include_router(client_robots_router)

    dp.include_router(client_bonus_router)
    dp.include_router(client_manager_router)

    dp.include_router(business_dialog_router)
    dp.include_router(quiz_router)