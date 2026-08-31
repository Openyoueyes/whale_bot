# app/bot/keyboards/products.py
"""
Продукты из поста в канале (кнопка «ПОЛУЧИТЬ»).

Один список — источник правды и для текста сообщения, и для клавиатуры,
и для названия заявки в CRM: добавить продукт = добавить строку сюда.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_PREFIX = "product:"


@dataclass(frozen=True)
class Product:
    code: str
    emoji: str
    name: str
    short: str        # короткая подпись на кнопке
    description: str  # строка в списке продуктов

    @property
    def button_text(self) -> str:
        return f"{self.emoji} {self.name} — {self.short}"

    @property
    def menu_line(self) -> str:
        return f"{self.emoji} <b>{self.name}</b> — {self.description}"

    @property
    def callback_data(self) -> str:
        return f"{CALLBACK_PREFIX}{self.code}"


PRODUCTS: tuple[Product, ...] = (
    Product(
        code="prem",
        emoji="1️⃣",
        name="ПРЕМ",
        short="аналитика",
        description="доступ в закрытую группу с аналитикой",
    ),
    Product(
        code="course",
        emoji="2️⃣",
        name="КУРС",
        short="обучение",
        description="бесплатный авторский курс в записи (4 урока)",
    ),
    Product(
        code="indi",
        emoji="3️⃣",
        name="ИНДИ",
        short="индикатор",
        description=(
            "лучший на рынке индикатор спроса и предложения, "
            "с системой Smart Money и методом Wyckoff"
        ),
    ),
    Product(
        code="test",
        emoji="4️⃣",
        name="ТЕСТ",
        short="демо роботов",
        description="бесплатное тестирование роботов",
    ),
    Product(
        code="robo",
        emoji="5️⃣",
        name="РОБО",
        short="роботы",
        description=(
            "доступ в закрытую группу с роботами: "
            "#WT, #WhaleGoldBreakout, #QUANT, #ST"
        ),
    ),
)

PRODUCTS_BY_CODE: dict[str, Product] = {p.code: p for p in PRODUCTS}


def get_products_keyboard() -> InlineKeyboardMarkup:
    """По кнопке на продукт, каждая — отдельной строкой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=p.button_text, callback_data=p.callback_data)]
            for p in PRODUCTS
        ]
    )
