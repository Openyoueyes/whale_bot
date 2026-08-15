# app/bot/routers/client/robots.py
from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.bot.keyboards.robots import get_robot_list_keyboard, get_robot_detail_keyboard, get_robot_post_apply_keyboard
from app.config import BREAKOUTGOLD_IMAGE_FILE_ID, ROBOTS_IMAGE_FILE_ID, AI_IMAGE_FILE_ID
from app.integrations.bitrix.client import BitrixClient
from app.services.auto_followup_service import mark_activity
from app.services.request_service import create_product_request
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed

logger = logging.getLogger(__name__)

bitrix_client = BitrixClient()
router = Router(name="client-robots")


# ---------- helpers ----------

async def safe_callback_answer(callback: CallbackQuery, text: str | None = None) -> None:
    """
    Ответ на callback — необязательная вежливость (убрать «часики» на кнопке).
    Протухший callback или сетевой сбой не должны ронять обработчик, поэтому
    глушим любые ошибки: основная работа делается дальше по коду.
    """
    try:
        await callback.answer(text=text)
    except (TelegramBadRequest, TelegramNetworkError):
        pass
    except Exception:
        logger.debug("callback.answer не прошёл", exc_info=True)


async def safe_edit_text_or_caption(
        callback: CallbackQuery,
        *,
        text: str,
        reply_markup=None,
        parse_mode: str = "HTML",
) -> None:
    """
    Безопасно обновляет сообщение:
    - если сообщение с media/caption -> edit_caption
    - если текстовое -> edit_text
    - если редактирование невозможно -> отправляет новое сообщение
    """
    if not callback.message:
        return

    try:
        # Если это медиа-сообщение (фото/видео/док и т.д.) — правим caption
        if callback.message.photo or callback.message.video or callback.message.document or callback.message.animation or callback.message.audio:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return

        # Если это текст — правим текст
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest:
        # Частый кейс: "there is no text in the message to edit"
        await _fallback_answer(callback, text, reply_markup, parse_mode)
    except Exception:
        await _fallback_answer(callback, text, reply_markup, parse_mode)


async def _fallback_answer(callback: CallbackQuery, text: str, reply_markup, parse_mode: str) -> None:
    """
    Последний рубеж: отправляем новым сообщением.
    Молчать здесь нельзя — именно это скрывало баг с пустым текстом.
    """
    try:
        await callback.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        logger.exception(
            "Не удалось показать экран клиенту tg_id=%s (длина текста=%s)",
            callback.from_user.id if callback.from_user else None,
            len(text or ""),
        )


# ---------- texts ----------

ROBOTS_LIST_TEXT = (
    "<b>Торговый советник</b> - полностью автоматическое решение для валютного рынка.\n\n"
    "🤖 <b>Наши роботы</b> - это актуальные алгоритмы стратгеии, постоянная оптимизция, "
    "вариации настроек, прозрачная статистика с 2022 года на независимых мониторингах.\n\n"
    "<b>1.WhaleTrade AI(основной)</b> \n\n"
    "<b>2.WT_BREAKOUTGOLD(золото)</b>\n\n"
    "Выберите робота который вас интересует:"
)


def _ai_text() -> str:
    return (

        "🤖 <b>WhaleTrade AI — автоматическая система торговли на Forex</b>\n\n"
        "Робот работает по заранее заданному сетапу и строго исполняет стратегию без эмоций и отклонений.\n\n"
        "📌 <b>Как работает система:</b>\n"
        "🔵 Открывает сделки только по заданным условиям\n"
        "🔵 Контролирует объём и дистанции усреднения\n"
        "🔵 Управляет серией как единой позицией\n"
        "🔵 Пересчитывает общий TP и SL\n\n"
        "🎯 <b>Общий принцип:</b>\n"
        "Робот не торгует хаотично и не использует классический мартингейл.\n"
        "Он выстраивает структурированную серию и закрывает её по плановой прибыли.\n\n"
        "🛡️ <b>Защита капитала:</b>\n"
        "🔒 Лимиты усреднения\n"
        "🔒 Контроль дистанции и времени\n"
        "🔒 Общий SL на серию\n"
        "🔒 Фильтры от случайных входов\n\n"
        "⏱ Оптимальный таймфрейм: M15 (допустимо H1,H4)\n"
        "‼️ Рекомендуемые активы: EURUSD, GBPUSD, GBPJPY, AUDJPY\n"
        "📈 Всё полностью прозрачно — каждый вход, расчёт и закрытие фиксируются.\n"
        "🥇 <b>Мониторинги с 2022:</b>\nhttps://www.myfxbook.com/members/WT_FX\n\n"
        "✉️ Хотите протестировать бесплатно и получить настройки под свой депозит?\n"

    )


def _breakoutgold_text() -> str:
    return (
        "🥇 <b>WT_BREAKOUTGOLD — советник пробоя сессии для XAUUSD</b>\n\n"
        "Профессиональный робот для MetaTrader 5, созданный специально под золото. "
        "Он измеряет диапазон азиатской сессии и торгует пробой на импульсе открытия Лондона.\n\n"
        "⚙️ <b>Как работает:</b>\n"
        "🔵 Фиксирует High/Low азиатского диапазона\n"
        "🔵 Ставит BuyStop и SellStop по OCO-логике\n"
        "🔵 После срабатывания одного ордера второй удаляется\n"
        "🔵 Закрывает позиции и удаляет ордера к концу дня\n\n"
        "🛡️ <b>Контроль риска:</b>\n"
        "🔒 Stop Loss на противоположной границе диапазона\n"
        "🔒 Фиксированный лот или риск % от баланса\n"
        "🔒 Фильтр минимального диапазона и отступ входа\n"
        "🔒 Работа только по своему символу и magic number\n\n"
        "📈 Инструмент: XAUUSD\n"
        "⏱ Логика: азиатский диапазон → пробой → сопровождение до закрытия дня\n"
        "📊 Тесты 2024-2026: 611 сделок, winrate около 56%, Profit Factor до 2.09 на out-of-sample.\n\n"
        "✉️ Получить мониринг вместе с роботом и подробное видео + методичку описания ⬇️⬇️⬇️⬇️\n"
    )


# ---------- handlers ----------

@router.message(F.text == "🤖 Торговые роботы")
async def products_entry(message: Message):
    if ROBOTS_IMAGE_FILE_ID:
        await message.answer_photo(
            photo=ROBOTS_IMAGE_FILE_ID,
            caption=ROBOTS_LIST_TEXT,
            reply_markup=get_robot_list_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            ROBOTS_LIST_TEXT,
            reply_markup=get_robot_list_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "robots:back")
async def products_back(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    # Возвращаемся в список: желательно всегда с фото (если есть file_id)
    if ROBOTS_IMAGE_FILE_ID:
        try:
            media = InputMediaPhoto(
                media=ROBOTS_IMAGE_FILE_ID,
                caption=ROBOTS_LIST_TEXT,
                parse_mode="HTML",
            )
            await callback.message.edit_media(
                media=media,
                reply_markup=get_robot_list_keyboard(),
            )
        except TelegramBadRequest:
            # если вдруг текущее сообщение не позволяет edit_media — отправим новое
            await callback.message.answer_photo(
                photo=ROBOTS_IMAGE_FILE_ID,
                caption=ROBOTS_LIST_TEXT,
                reply_markup=get_robot_list_keyboard(),
                parse_mode="HTML",
            )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=ROBOTS_LIST_TEXT,
            reply_markup=get_robot_list_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "robots:wt_ai")
async def robots_ai(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    if AI_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=AI_IMAGE_FILE_ID,
            caption=_ai_text(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_robot_detail_keyboard("wt_ai"),
        )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=_ai_text(),
            reply_markup=get_robot_detail_keyboard("wt_ai"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "robots:wt_breakoutgold")
async def robots_breakoutgold(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    if BREAKOUTGOLD_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=BREAKOUTGOLD_IMAGE_FILE_ID,
            caption=_breakoutgold_text(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_robot_detail_keyboard("wt_breakoutgold"),
        )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=_breakoutgold_text(),
            reply_markup=get_robot_detail_keyboard("wt_breakoutgold"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "robots:wt_ai:apply")
async def robots_ai_apply(callback: CallbackQuery):
    await safe_callback_answer(callback)

    await create_product_request(
        bot=callback.bot,
        tg_user=callback.from_user,
        source="Роботы / WT AI / Получить доступ",
    )
    try:
        await mark_activity(callback.from_user.id)
    except Exception:
        logger.warning("Не удалось отметить активность tg_id=%s", callback.from_user.id)

    # Заявка — это активность: возвращаем «мёртвую» сделку в работу.
    try:
        await move_to_first_touch_if_needed(bitrix_client, callback.from_user.id)
    except Exception:
        logger.warning("Stage guard не отработал для tg_id=%s", callback.from_user.id)

    await safe_edit_text_or_caption(
        callback,
        text=(

            "✅✅✅ <b>Заявка принята</b>\n\n"
            "📩 Менеджер свяжется с вами в ближайшее время.\n\n"

        ),
        reply_markup=get_robot_post_apply_keyboard(),  # ✅ только “Назад”
        parse_mode="HTML",
    )


@router.callback_query(F.data == "robots:wt_breakoutgold:apply")
async def robots_breakoutgold_apply(callback: CallbackQuery):
    await safe_callback_answer(callback)

    await create_product_request(
        bot=callback.bot,
        tg_user=callback.from_user,
        source="Роботы / WT BREAKOUTGOLD / Получить доступ",
    )
    try:
        await mark_activity(callback.from_user.id)
    except Exception:
        logger.warning("Не удалось отметить активность tg_id=%s", callback.from_user.id)

    # Заявка — это активность: возвращаем «мёртвую» сделку в работу.
    try:
        await move_to_first_touch_if_needed(bitrix_client, callback.from_user.id)
    except Exception:
        logger.warning("Stage guard не отработал для tg_id=%s", callback.from_user.id)
    await safe_edit_text_or_caption(
        callback,
        text=(
            "✅✅✅ <b>Заявка принята</b>\n\n"
            "📩 Менеджер свяжется с вами в ближайшее время для консультации.\n\n"

        ),
        reply_markup=get_robot_post_apply_keyboard(),  # ✅ только “Назад”
        parse_mode="HTML",
    )
