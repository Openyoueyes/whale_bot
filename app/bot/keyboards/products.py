# app/bot/keyboards/products.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_products_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Онлайн-торговля", callback_data="products:online")],
            [InlineKeyboardButton(text="🧩 SNIPER SAP (ПО)", callback_data="products:sap")],
            [InlineKeyboardButton(text="🎓 Индивидуальное обучение", callback_data="products:training")],
        ]
    )


def get_product_detail_keyboard(product_key: str) -> InlineKeyboardMarkup:
    rows = []

    if product_key == "online":
        rows.append([InlineKeyboardButton(text="✅ Принять участие", callback_data="products:online:apply")])

    if product_key == "training":
        rows.append([InlineKeyboardButton(text="✅ Получить консультацию", callback_data="products:training:apply")])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="products:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_product_post_apply_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура после отправки заявки: только 'Назад'
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="products:back")],
        ]
    )
