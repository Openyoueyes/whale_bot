# app/bot/routers/client/products.py
"""
Выбор продукта после перехода по кнопке «ПОЛУЧИТЬ» из Telegram-канала.

Сценарий: клиент жмёт кнопку в канале -> попадает в бота -> видит благодарность
и меню из пяти продуктов -> выбирает один -> выбор уходит в CRM и менеджерам.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.client import get_main_menu_keyboard
from app.bot.keyboards.products import (
    CALLBACK_PREFIX,
    PRODUCTS,
    PRODUCTS_BY_CODE,
    get_products_keyboard,
)
from app.bot.routers.client.robots import safe_callback_answer, safe_edit_text_or_caption
from app.integrations.bitrix.client import BitrixClient
from app.services.auto_followup_service import mark_activity
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed
from app.services.request_service import create_product_choice_request

logger = logging.getLogger(__name__)

router = Router(name="client-products")
bitrix_client = BitrixClient()

PRODUCTS_MENU_TEXT = (
    "🐋 <b>Спасибо за интерес к Whale Trade!</b>\n\n"
    "Выберите направление, которое вам интересно — "
    "менеджер свяжется с вами и вышлет всю информацию 👇\n\n"
    + "\n\n".join(p.menu_line for p in PRODUCTS)
)


def _confirmation_text(product_name: str) -> str:
    return (
        f"✅ <b>Заявка принята: {product_name}</b>\n\n"
        "📩 Менеджер свяжется с вами в ближайшее время "
        "и вышлет всю информацию по выбранному направлению.\n\n"
        "Спасибо, что выбрали <b>Whale Trade</b> 🐋"
    )


async def send_products_menu(message: Message) -> None:
    """Меню продуктов в ответ на сообщение клиента."""
    await message.answer(
        PRODUCTS_MENU_TEXT,
        reply_markup=get_products_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def send_products_menu_to_chat(bot, chat_id: int) -> None:
    """То же меню, когда исходного сообщения под рукой нет (после проверки подписки)."""
    await bot.send_message(
        chat_id=chat_id,
        text=PRODUCTS_MENU_TEXT,
        reply_markup=get_products_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith(CALLBACK_PREFIX))
async def product_chosen(callback: CallbackQuery):
    product = PRODUCTS_BY_CODE.get((callback.data or "").removeprefix(CALLBACK_PREFIX))

    if product is None:
        await safe_callback_answer(callback, "Этот вариант больше недоступен")
        return

    await safe_callback_answer(callback)

    tg_id = callback.from_user.id

    # 1) Сначала отвечаем клиенту: он не должен ждать похода в Bitrix.
    #    Клавиатуру убираем, чтобы нельзя было нажать второй раз.
    await safe_edit_text_or_caption(
        callback,
        text=_confirmation_text(product.name),
        parse_mode="HTML",
    )

    try:
        await callback.message.answer(
            "А пока ждёте — загляните в разделы бота 👇",
            reply_markup=get_main_menu_keyboard(),
        )
    except Exception:
        logger.warning("Не удалось показать главное меню tg_id=%s", tg_id)

    # 2) Выбор продукта — активность: авто-прозвон такому клиенту не нужен.
    try:
        await mark_activity(tg_id)
    except Exception:
        logger.warning("Не удалось отметить активность tg_id=%s", tg_id)

    try:
        await move_to_first_touch_if_needed(bitrix_client, tg_id)
    except Exception:
        logger.warning("Stage guard не отработал для tg_id=%s", tg_id)

    # 3) Заявка в CRM + уведомление менеджерам.
    try:
        await create_product_choice_request(
            bot=callback.bot,
            tg_user=callback.from_user,
            product_name=product.name,
            source=f"Telegram-канал / Выбор продукта: {product.name}",
        )
    except Exception:
        logger.exception("Не удалось оформить заявку на продукт tg_id=%s", tg_id)
