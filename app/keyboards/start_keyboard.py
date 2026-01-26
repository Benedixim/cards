from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from aiogram.utils.keyboard import InlineKeyboardBuilder 



ITEMS = ["Сбер", "Альфа Банк", "Беларусбанк", "МТБанк", "Приорбанк", "БНБ", "ВТБ", "Белгазпромбанк", "Белагропромбанк", "БелВэб", "Дабрабыт"]

def get_multi_keyboard(banks: list, selected: set) -> InlineKeyboardBuilder:
    """Клавиатура выбора банков для парсинга"""
    builder = InlineKeyboardBuilder()
    
    for bank in banks:
        text = f"✅ {bank}" if bank in selected else bank
        builder.button(text=text, callback_data=f"toggle_bank_{bank}")
    
    builder.button(text="✅ Запустить парсинг", callback_data="parse_selected")
    builder.button(text="❌ Отмена", callback_data="cancel_parse").adjust(1)
    builder.adjust(1)
    
    return builder


def get_info_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Получить информацию")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

