# app/bot/routers/client/bonus.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message

from app.config import BONUS_IMAGE_FILE_ID

router = Router(name="client-bonus")

BONUS_TEXT = (
    "📢 Подпишитесь на открытый канал <a href='https://t.me/+on4x8BSxxv5hZmYy'>Whale Trade</a> и получите бесплатно:\n\n"
    "▪️Тестирование автоматического советника WhaleTrade_AI — пишите в бот \"советник\".\n"
    "▪️Индикатор спроса и предложения Whale - пишите в бот \"индикатор\".\n"
    "▪️Мини-курс по трейдингу - пишите в бот \"курс\".\n"
    "▪️Консультацию по торговле - пишите в бот \"консультация\".\n"
    "▪️Информацию о проверенных брокерах - пишите в бот \"брокеры\".\n\n"

    "Напишите, что вас интересует и мы ответим в ближайшее время 🤝"
)



@router.message(F.text == "🎁 Бонус")
async def results_entry(message: Message):
    # главное меню "Отзывы" = фото+текст (если есть), иначе текст
    if BONUS_IMAGE_FILE_ID:
        await message.answer_photo(
            photo=BONUS_IMAGE_FILE_ID,
            caption=BONUS_TEXT,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            BONUS_TEXT,
            parse_mode="HTML",
        )