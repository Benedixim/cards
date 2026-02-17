# app/keyboards/start_keyboard.py

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import SYSTEM_USER_ID


def get_multi_keyboard(banks: list, selected: set) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for bank in banks:
        text = f"✅ {bank}" if bank in selected else bank
        builder.button(text=text, callback_data=f"toggle_bank_{bank}")

    builder.button(text="✅ Запустить парсинг", callback_data="parse_selected")
    builder.button(text="❌ Отмена", callback_data="cancel_parse")

    builder.adjust(1)
    return builder.as_markup()


def get_info_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📊 Собрать информацию")]],
        resize_keyboard=True
    )


def get_set_actions_keyboard(set_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Продукты", callback_data=f"set_products_{set_id}")],
            [InlineKeyboardButton(text="🔬 Характеристики", callback_data=f"set_chars_{set_id}")],
            [InlineKeyboardButton(text="🛠 Настроить набор", callback_data=f"edit_set_{set_id}")]
        ]
    )


def get_product_list_keyboard(products: list, set_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for product in products:
        builder.button(text=product.name, callback_data=f"product_{product.id}")

    builder.button(text="➕ Добавить продукт", callback_data=f"add_product_to_set_{set_id}")
    builder.button(text="⬅️ Назад", callback_data="back_to_set")

    builder.adjust(1)
    return builder.as_markup()


def get_characteristic_list_keyboard(chars: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for char in chars:
        builder.button(text=char.name, callback_data=f"char_{char.id}")

    builder.button(text="➕ Добавить характеристику", callback_data="add_characteristic")
    builder.button(text="⬅️ Назад", callback_data="back_to_set_menu")

    builder.adjust(1)
    return builder.as_markup()


def get_top_level_actions_keyboard(sets: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    system = [s for s in sets if s.user_id == SYSTEM_USER_ID]
    user = [s for s in sets if s.user_id != SYSTEM_USER_ID]

    for s in system:
        builder.row(
            InlineKeyboardButton(text=f"🏦 {s.name}", callback_data=f"set_{s.id}")
        )

    if system and user:
        builder.row(InlineKeyboardButton(text="──────────────", callback_data="dummy"))

    for s in user:
        builder.row(
            InlineKeyboardButton(text=f"🏦 {s.name}", callback_data=f"set_{s.id}")
        )
    builder.row(
        InlineKeyboardButton(text="➕ Создать набор", callback_data="create_new_set")
    )

    return builder.as_markup()

