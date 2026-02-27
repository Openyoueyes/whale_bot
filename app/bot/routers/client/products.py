# app/bot/routers/client/product.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.bot.keyboards.products import (
    get_products_list_keyboard,
    get_product_detail_keyboard, get_product_post_apply_keyboard,
)
from app.config import (
    SNIPER_SAP_IMAGE_FILE_ID,
    ONLINE_IMAGE_FILE_ID,
    INDI_IMAGE_FILE_ID,
    PRODUCTS_IMAGE_FILE_ID,
)
from app.integrations.bitrix.client import BitrixClient
from app.services.auto_followup_service import mark_activity
from app.services.products_service import create_product_request
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed

bitrix_client = BitrixClient()
router = Router(name="client-products")


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

PRODUCTS_LIST_TEXT = (
    "🛍 <b>Наши продукты</b>\n\n"
    "Только практические решения для реального рынка:\n\n"
    "<b>1.Торговля в прямом эфире</b> 📡\n\n"
    "<b>2.SNIPER SAP</b>(платформа сценарного анализа) 🧩\n\n"
    "<b>3.Индивидуальное обучение с сопровождением</b> до результата 🎓\n\n"
    "Выберите интересующий продукт:"
)


def _sap_text() -> str:
    return (
        "🎯 <b>SNIPER SAP — сценарный навигатор на рынке</b>\n\n"
        "<i>Scenario Analytic Platform</i> — платформа анализа сценариев.\n"
        "Подходит для любых рынков: <b>Forex, индексы, крипто, сырьё</b>.\n\n"

        "📌 <b>Что делает?</b>\n"
        "✅ Автоматическая разметка графика\n"
        "✅ Построение ключевых уровней каждой сессии\n"
        "✅ Поиск разворотных зон и триггеров входа\n"
        "✅ Определение типовых рыночных движений\n\n"

        "💡 <b>Что даёт?</b>\n"
        "→ Предварительный сигнал по системе «Снайпер»\n"
        "→ Убирает субъективизм: не «я думаю», а «система показывает»\n"
        "→ Экономит время — готовые сценарии вместо ручной разметки\n"
        "→ Фокус на ТВХ (точке входа), а не на догадках\n"
        "→ Выбор наиболее вероятного сценария движения цены\n"
        "→ Высокая точность и короткий стоп (несколько пунктов)\n"
        "→ Возможность отслеживать больше активов одновременно\n\n"

        "⚠️ <b>Важно:</b>\n"
        "ПО не продаётся отдельно.\n"
        "Доступно <b>только</b> в рамках Онлайн-торговли или Индивидуального обучения.\n\n"

        "🚀 <i>Это не индикатор. Это инструмент принятия решений —\n"
        "без эмоций, без шума и без лишних движений.</i>"
    )


def _online_text() -> str:
    return (
        "📈 <b>Онлайн-торговля</b>\n\n"
        "<b>Что это?</b>\n\n"
        "1️⃣Прямые эфиры с торговлей на реальном рынке:\n\n"
        "✅Обычно 3–5 дней в неделю, ориентировочно с 11:00–18:00 🕒\n"
        "✅Объясняем логику входа/выхода и ведение позиции 🎥\n\n"

        "2️⃣Возможность копировать сделки нашего трейдера\n\n"
        "3️⃣Доступ к базе знаний(комлекс обучающих материалов для новичков и опытных)\n\n"
        "4️⃣Доступ в закрытую группу Telegram с обсуждениями(более 1000+ активных трейдеров)\n\n"
        "Нажмите <b>«Принять участие»</b>, чтобы оставить заявку."
    )


def _training_text() -> str:
    return (
        "🎓 <b>Индивидуальное обучение</b>\n\n"
        "<b>Что это?</b>\n\n"
        "1️⃣Разбор системы, структур рынка и паттернов 📚\n"
        "2️⃣Отработка навыков → перенос на реальную торговлю с сопровождением 🧪\n"
        "3️⃣Поддержка в течение 12 месяцев под ваши задачи 🗓\n"
        "4️⃣Дополнительно входит:\n\n"
        "❗Подписка SNIPER SAP и необходимые материалы 🎁\n"
        "❗Доступ к базе знаний(комлекс обучающих материалов для новичков и опытных трейдеров)\n"
        "❗Доступ в закрытую группу ТГ с обсуждениями(более 1000+ активных трейдеров)\n\n"
        "* Места ограничены, потому что обучение проводится <b>до результата</b>\n\n"
        "Нажмите <b>«Получить консультацию»</b>, чтобы оставить заявку."
    )


# ---------- handlers ----------

@router.message(F.text == "🛍 Продукты")
async def products_entry(message: Message):
    if PRODUCTS_IMAGE_FILE_ID:
        await message.answer_photo(
            photo=PRODUCTS_IMAGE_FILE_ID,
            caption=PRODUCTS_LIST_TEXT,
            reply_markup=get_products_list_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            PRODUCTS_LIST_TEXT,
            reply_markup=get_products_list_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "products:back")
async def products_back(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    # Возвращаемся в список: желательно всегда с фото (если есть file_id)
    if PRODUCTS_IMAGE_FILE_ID:
        try:
            media = InputMediaPhoto(
                media=PRODUCTS_IMAGE_FILE_ID,
                caption=PRODUCTS_LIST_TEXT,
                parse_mode="HTML",
            )
            await callback.message.edit_media(
                media=media,
                reply_markup=get_products_list_keyboard(),
            )
        except TelegramBadRequest:
            # если вдруг текущее сообщение не позволяет edit_media — отправим новое
            await callback.message.answer_photo(
                photo=PRODUCTS_IMAGE_FILE_ID,
                caption=PRODUCTS_LIST_TEXT,
                reply_markup=get_products_list_keyboard(),
                parse_mode="HTML",
            )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=PRODUCTS_LIST_TEXT,
            reply_markup=get_products_list_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "products:online")
async def products_online(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    if ONLINE_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=ONLINE_IMAGE_FILE_ID,
            caption=_online_text(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_product_detail_keyboard("online"),
        )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=_online_text(),
            reply_markup=get_product_detail_keyboard("online"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "products:sap")
async def products_sap(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    if SNIPER_SAP_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=SNIPER_SAP_IMAGE_FILE_ID,
            caption=_sap_text(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_product_detail_keyboard("sap"),
        )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=_sap_text(),
            reply_markup=get_product_detail_keyboard("sap"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "products:training")
async def products_training(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    if INDI_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=INDI_IMAGE_FILE_ID,
            caption=_training_text(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_product_detail_keyboard("training"),
        )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=_training_text(),
            reply_markup=get_product_detail_keyboard("training"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "products:online:apply")
async def products_online_apply(callback: CallbackQuery):
    await safe_callback_answer(callback)

    await create_product_request(
        bot=callback.bot,
        tg_user=callback.from_user,
        source="Продукты / Онлайн-торговля / Получить участие",
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
            "🔥Единственный в своём роде проект в русскоязычном пространстве, "
            "где опытный трейдер торгует на реальном рынке — <b>в прямом эфире</b>.\n\n"
            "🧠Торгуем по системе <b>«Снайпер» Андрея Миклушевского + SNIPER SAP</b>\n\n"
            "💎 <b>Вы получаете:?</b>\n"
            "▶️ Реальную практику, а не теорию\n"
            "▶️ Прозрачность и честность\n"
            "▶️ Понимание логики входов и выходов\n"
            "▶️ Дисциплину и эмоциональную устойчивость\n"
            "▶️ Доступ к мышлению профессионала\n"
            "▶️ Базу для формирования собственного стиля\n\n"
            "──────────────\n\n"
            "✅✅✅ <b>Заявка принята</b>\n\n"
            "📩 Менеджер свяжется с вами в ближайшее время.\n\n"

        ),
        reply_markup=get_product_post_apply_keyboard(),  # ✅ только “Назад”
        parse_mode="HTML",
    )


@router.callback_query(F.data == "products:training:apply")
async def products_training_apply(callback: CallbackQuery):
    await safe_callback_answer(callback)

    await create_product_request(
        bot=callback.bot,
        tg_user=callback.from_user,
        source="Продукты / Индивидуальное обучение / Получить консультацию",
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
            "🎓 <b>ИНДИВИДУАЛЬНОЕ ОБУЧЕНИЕ | SNIPER CLUB</b>\n"
            "<i>Твой путь от хаоса к системе — с профессионалом рядом.</i>\n\n"

            "Хватит учиться на ошибках.\n"
            "Пора учиться по системе — <b>той, что работает в реальном рынке</b>.\n\n"

            "🔍 <b>Что изучаем?</b>\n"
            "• Логику и основы торговой системы «Снайпер»\n"
            "• Структуру рынка: каскады, расширения, продолженные движения\n"
            "• Паттерны: на разворот и на продолжение\n"
            "• ТВХ — как ловить момент через свечные модели\n"
            "• Защиту позиции по правилу «Сейф»\n"
            "• Управление капиталом и рисками — фундамент стабильности 💪\n\n"

            "🎯 <b>Как проходит обучение?</b>\n"
            "• Индивидуальные консультации с опытным трейдером в удобное время\n"
            "• Разбор ваших сделок, ситуаций и ошибок\n"
            "• Сначала — тренажёр до стабильной кривой доходности\n"
            "• Затем — переход на реальный счёт под сопровождением наставника\n"
            "• 12 месяцев гибкого обучения под ваш темп и цели\n\n"

            "🎁 <b>В комплекте ученик получает:</b>\n"
            "▶️ Подписку <b>SNIPER SAP</b> на 12 месяцев\n"
            "▶️ Программное обеспечение + все обновления\n"
            "▶️ Активированную лицензию MT4 / MT5\n"
            "▶️ Подробную инструкцию по установке\n\n"

            "🔒 <b>И бонус:</b>\n"
            "Доступ к закрытым мероприятиям, вебинарам, материалам "
            "и личному чату с поддержкой наставника.\n\n"
            
            "──────────────\n\n"
            "✅✅✅ <b>Заявка принята</b>\n\n"
            "📩 Менеджер свяжется с вами в ближайшее время для консультации.\n\n"


        ),
        reply_markup=get_product_post_apply_keyboard(),  # ✅ только “Назад”
        parse_mode="HTML",
    )
