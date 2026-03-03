# app/bot/routers/client/robots.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.bot.keyboards.robots import get_robot_list_keyboard, get_robot_detail_keyboard, get_robot_post_apply_keyboard
from app.config import QUANT_IMAGE_FILE_ID, ROBOTS_IMAGE_FILE_ID, AI_IMAGE_FILE_ID, SAFE_IMAGE_FILE_ID
from app.integrations.bitrix.client import BitrixClient
from app.services.auto_followup_service import mark_activity
from app.services.robots_service import create_product_request
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed

bitrix_client = BitrixClient()
router = Router(name="client-robots")


# ---------- helpers ----------

async def safe_callback_answer(callback: CallbackQuery, text: str | None = None) -> None:
    try:
        await callback.answer(text=text)
    except (TelegramBadRequest, TelegramNetworkError):
        pass
    except Exception:
        pass


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
        try:
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass
    except Exception:
        try:
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass


# ---------- texts ----------

ROBOTS_LIST_TEXT = (
    "<b>Торговый советник</b> - полностью автоматическаое решение для валютного рынка.\n\n"
    "🤖 <b>Наши роботы</b> - это актуальные алгоритмы стратгеии, постоянная оптимизция, "
    "вариации настроек, прозрачная статистика с 2022 года на независимых мониторингах.\n\n"
    "<b>1.WhaleTrade AI(основной)</b> \n\n"
    "<b>2.WhaleTrade SafeTrend(новый)</b>\n\n"
    "<b>3.WhaleTrade QUANT - в разработке(золото)</b>\n\n"
    "Выберите робота который вас интересует:"
)


def _quant_text() -> str:
    return (
        "⚡ <b>WhaleTrade QUANT — импульсный робот для резких движений</b>\n\n"
        "Автоматический алгоритм, который заходит в рынок только при ускорении цены.\n"
        "Без уровней, без трендовых фильтров — только работа с импульсом.\n\n"

        "🔎 <b>Принцип работы:</b>\n"
        "Если цена за короткое время проходит заданную дистанцию —\n"
        "робот фиксирует импульс и входит в движение.\n"
        "Вверх — BUY, вниз — SELL.\n\n"

        "🥇 <b>Особенно эффективен на XAUUSD (золото)</b>\n"
        "Золото часто даёт резкие ускорения и мощные новостные выносы,\n"
        "что идеально подходит для импульсной логики.\n\n"

        "⚙️ <b>Сопровождение позиции:</b>\n"
        "🔵 Динамический трейлинг-стоп\n"
        "🔵 Возможность открытия дополнительной позиции при продолжении импульса\n"
        "🔵 Закрытие серии по общей цели прибыли\n\n"

        "🛡️ <b>Контроль риска:</b>\n"
        "🔒 Ограничение просадки в % или фиксированной суммой\n"
        "🔒 Контроль спреда\n"
        "🔒 Ограничение времени торговли\n"
        "🔒 Возможность остановки до следующего дня\n\n"

        "📌 <b>Ключевые параметры:</b>\n"
        "PipsStep — сила импульса для входа\n"
        "OpenTime — время ускорения\n"
        "TrailStart / Trail — логика защиты прибыли\n"
        "TakeProfit — цель для серии\n\n"
        "📈 Лучший инструмент — XAUUSD.\n\n"

        "✉️ Хотите протестировать или получить настройки под брокера?\n"
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
        "🥇 <b>Мониторинги с 2022:</b>https://www.myfxbook.com/members/WT_FX\n\n"
        "✉️ Хотите протестировать или получить настройки под свой депозит?\n"

    )


def _safe_text() -> str:
    return (
        "🤖 <b>WT_SAFETREND — трендовый робот с жёсткой фильтрацией флета</b>\n\n"
        "Автоматическая система для Forex и металлов, "
        "которая зарабатывает только в реальном тренде и не торгует в боковике.\n\n"
        "🔎 <b>Основная идея:</b>\n"
        "Зарабатывать в тренде — и не терять во флете.\n\n"
        "⚙️ <b>Как работает логика:</b>\n"
        "🔵 Определяет направление по EMA\n"
        "🔵 Блокирует торговлю при слабом рынке (ADX-фильтр)\n"
        "🔵 Делает паузу при смене тренда\n"
        "🔵 Проверяет обновление экстремумов перед входом\n\n"
        "🎯 <b>SL и TP рассчитываются от рынка</b>\n"
        "Без раздувания целей при росте депозита.\n"
        "Используются ограничения минимальных и максимальных значений.\n\n"
        "🛡️ <b>Контроль риска:</b>\n"
        "🔒 Лимит сделок в день\n"
        "🔒 Пауза после серии убытков\n"
        "🔒 Защита от переторговки\n"
        "🔒 Настройка риска в % от депозита\n\n"
        "📈 Рекомендуемые активы: XAUUSD, GBPJPY, AUDJPY, USDCAD\n"
        "⏱ Оптимальный таймфрейм: H1 (допустимо H4)\n"
        "💰 Рекомендуемый риск: 0.4–0.5% на сделку\n\n"
        "WT_SAFETREND — это не агрессивная стратегия.\n"
        "Это системная, спокойная торговля с акцентом на защиту капитала.\n\n"
        "✉️ Хотите получить пресеты под свой депозит или протестировать робота?\n"
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
                caption=ROBOTS_IMAGE_FILE_ID,
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
                caption=ROBOTS_IMAGE_FILE_ID,
                reply_markup=get_robot_list_keyboard(),
                parse_mode="HTML",
            )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=ROBOTS_IMAGE_FILE_ID,
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


@router.callback_query(F.data == "robots:wt_safe")
async def robots_safe(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    if SAFE_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=SAFE_IMAGE_FILE_ID,
            caption=_safe_text(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_robot_detail_keyboard("wt_safe"),
        )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=_safe_text(),
            reply_markup=get_robot_detail_keyboard("wt_safe"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "robots:wt_quant")
async def robots_quant(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    if QUANT_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=QUANT_IMAGE_FILE_ID,
            caption=_quant_text(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_robot_detail_keyboard("wt_quant"),
        )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=_quant_text(),
            reply_markup=get_robot_detail_keyboard("wt_quant"),
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
        pass
    # ✅ реакция на заявку: если клиент был в “плохих” стадиях — перекидываем в “1 касание”
    try:
        await move_to_first_touch_if_needed(bitrix_client, callback.from_user.id)
    except Exception:
        pass

    await safe_edit_text_or_caption(
        callback,
        text=(

            "✅✅✅ <b>Заявка принята</b>\n\n"
            "📩 Менеджер свяжется с вами в ближайшее время.\n\n"

        ),
        reply_markup=get_robot_post_apply_keyboard(),  # ✅ только “Назад”
        parse_mode="HTML",
    )


@router.callback_query(F.data == "robots:wt_safe:apply")
async def robots_safe_apply(callback: CallbackQuery):
    await safe_callback_answer(callback)

    await create_product_request(
        bot=callback.bot,
        tg_user=callback.from_user,
        source="Роботы / WT SAFE / Получить доступ",
    )
    try:
        await mark_activity(callback.from_user.id)
    except Exception:
        pass
    # ✅ реакция на заявку: если клиент был в “плохих” стадиях — перекидываем в “1 касание”
    try:
        await move_to_first_touch_if_needed(bitrix_client, callback.from_user.id)
    except Exception:
        pass
    await safe_edit_text_or_caption(
        callback,
        text=(
            "✅✅✅ <b>Заявка принята</b>\n\n"
            "📩 Менеджер свяжется с вами в ближайшее время для консультации.\n\n"

        ),
        reply_markup=get_robot_post_apply_keyboard(),  # ✅ только “Назад”
        parse_mode="HTML",
    )
