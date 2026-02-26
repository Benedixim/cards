#app/handlers/card.py
from aiogram import Router, F
import asyncio
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import FSInputFile
from datetime import datetime
from sqlalchemy import and_, or_
import json
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import re
import os
from gigachat import GigaChat
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
from playwright.async_api import async_playwright

from aiogram.fsm.context import FSMContext
from aiogram import Bot

from app.keyboards.start_keyboard import (
    get_top_level_actions_keyboard,
)
from app.state import BankState
from app.excel.py_xlsx import create_bank_excel_report
from app.handlers.parser import get_page_content, extract_page_text
from app.db.model import (SessionLocal, User, Log, Data, Bank, Set, Product, Characteristic,
                           migrate_products, migrate_banks, init_db, get_sets_for_user, recreate_data_table, migrate_base_characteristics, migrate_logs_add_tokens_column, migrate_data_add_pdf_urls)
from config import GIGACHAT_TOKEN, SYSTEM_USER_ID

custom = Router()

_bot_instance = None

def get_bot(token: str) -> Bot:
    """Получить глобальный экземпляр бота"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = Bot(token=token)
    return _bot_instance


FIELD_NAMES = {
    "type": "Тип карты",
    "currency": "Валюта", 
    "validity": "Срок действия",
    "maintenance_cost": "Обслуживание",
    "free_conditions": "Бесплатно при",
    "sms_notification": "СМС уведомления",
    "atm_limit_own": "Лимит ATM своего",
    "atm_limit_other": "Лимит ATM других",
    "loyalty_program": "Программа лояльности",
    "interest_rate": "% на остаток",
    "additional": "Дополнительно",
}


@custom.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    db = SessionLocal()
    try:
        tg_id = message.from_user.id
        user = db.query(User).filter(User.tg_id == tg_id).first()
        if user:
            sets = get_sets_for_user(db, user.id)
        else:
            sets = get_sets_for_user(db, None)
    finally:
        db.close()

    await message.answer(
        "👋 Добро пожаловать в бенчмаркинг‑бот!\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=get_top_level_actions_keyboard(sets)
    )

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Собрать информацию")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
    await message.answer(
        "Нажмите 💬 внизу, чтобы начать анализ по картам.",
        reply_markup=kb
    )


@custom.message(Command("actv"))
async def start_multi(message: Message, state: FSMContext):
    # init_db()
    # migrate_banks()
    migrate_products()
    # migrate_base_characteristics()
    # recreate_data_table()
    # migrate_logs_add_tokens_column()
    print("✅ Полная миграция завершена!")


@custom.message(F.text == "📊 Собрать информацию")
async def click_button_start(message: Message, state: FSMContext):
    db = SessionLocal()
    try:
        tg_id = message.from_user.id
        user = db.query(User).filter(User.tg_id == tg_id).first()
        
        if not user:
            user = User(tg_id=tg_id)
            db.add(user)
            db.commit()
            db.refresh(user)
        
        sets = get_sets_for_user(db, user.id)
    finally:
        db.close()
    
    await message.answer( 
        "Выберите **набор карт**:",
        parse_mode="Markdown",
        reply_markup=get_top_level_actions_keyboard(sets)
    )


@custom.message(Command('db'))
async def dump_data_base(message: Message):
    import shutil

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    src_path = "cards.db"
    tmp_path = os.path.join(os.path.dirname(os.path.abspath(src_path)), f"cards_{timestamp}.db")

    try:
        shutil.copy2(src_path, tmp_path)
        document = FSInputFile(tmp_path, filename=f"cards_{timestamp}.db")
        await message.answer_document(document, caption=f"🗄 База данных\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    except Exception as e:
        await message.answer(f"Ошибка при отправке файла: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except:
            pass

async def show_products_keyboard(callback: CallbackQuery, state: FSMContext, set_id: int):
    text, markup = await build_products_keyboard(state, set_id)
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=markup,
    )
    await callback.answer()



@custom.message(BankState.waiting_new_char_for_set)
async def handle_new_char_for_set(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Название не должно быть пустым!")
        return

    data = await state.get_data()
    set_id = data["editing_set_id"]

    # Показываем статус
    status_msg = await message.answer("⏳ Генерирую описание...")

    prompt = f"""
Сформулируй краткое понятное описание для характеристики финансового продукта с названием: "{name}".
Также добавь маленький текст‑подсказку о типе значения этой характеристики (например: "в BYN", "% годовых", "без ограничений" и т.п.).

Представь ответ в JSON‑форме одной строкой:
{{
  "description": "Описание характеристики...",
  "value_hint": "Подсказка к формату значения"
}}
"""
    
    try:
        giga = GigaChat(
            credentials=GIGACHAT_TOKEN,
            scope="GIGACHAT_API_B2B",
            verify_ssl_certs=False,
            model="GigaChat-2-Max",
        )
        result = giga.chat(prompt)
        parsed = _parse_json_safely(result.choices[0].message.content)

        desc = parsed.get("description", "Описание характеристики") if parsed else "Описание характеристики"
        hint = parsed.get("value_hint", "Формат значения") if parsed else "Формат значения"
    except:
        desc = "Описание характеристики"
        hint = "Формат значения"
    
    # Удаляем статус
    try:
        await status_msg.delete()
    except:
        pass

    await state.update_data(
        temp_char_name=name,
        temp_char_description=desc,
        temp_char_hint=hint,
    )
    await state.set_state(BankState.editing_char_for_set)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Добавить в набор",
                callback_data="confirm_char_for_set",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить описание",
                callback_data="edit_char_for_set_desc",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить подсказку",
                callback_data="edit_char_for_set_hint",
            )],
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="no_confirm_char_for_set",
            )]
        ]
    )

    await message.answer(
        f"🔑 Характеристика: *{name}*\n\n"
        f"📝 Описание:\n{desc}\n"
        f"💡 Тип значения: {hint}\n\n"
        "Вы можете отредактировать описание и подсказку перед добавлением.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@custom.callback_query(F.data == "edit_char_for_set_desc", BankState.editing_char_for_set)
async def edit_char_for_set_desc(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_char_desc_edit_for_set)
    await callback.message.edit_text("✏️ Введите новое описание характеристики:")
    await callback.answer()


@custom.message(BankState.waiting_char_desc_edit_for_set)
async def process_char_for_set_desc_edit(message: Message, state: FSMContext):
    new_desc = message.text.strip()
    if not new_desc:
        await message.answer("Описание не должно быть пустым!")
        return

    await state.update_data(temp_char_description=new_desc)
    await state.set_state(BankState.editing_char_for_set)
    
    data = await state.get_data()
    name = data.get("temp_char_name", "")
    hint = data.get("temp_char_hint", "")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Добавить в набор",
                callback_data="confirm_char_for_set",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить описание",
                callback_data="edit_char_for_set_desc",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить подсказку",
                callback_data="edit_char_for_set_hint",
            )],
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="no_confirm_char_for_set",
            )]
        ]
    )

    await message.answer(
        f"🔑 Характеристика: *{name}*\n\n"
        f"📝 Описание:\n{new_desc}\n"
        f"💡 Тип значения: {hint}\n\n"
        "Готово! Подтвердите или отредактируйте дальше.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@custom.callback_query(F.data == "edit_char_for_set_hint", BankState.editing_char_for_set)
async def edit_char_for_set_hint(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_char_hint_edit_for_set)
    await callback.message.edit_text("💡 Введите подсказку к формату значения (например: 'в BYN', '% годовых'):")
    await callback.answer()


@custom.message(BankState.waiting_char_hint_edit_for_set)
async def process_char_for_set_hint_edit(message: Message, state: FSMContext):
    new_hint = message.text.strip()
    if not new_hint:
        await message.answer("Подсказка не должна быть пустой!")
        return

    await state.update_data(temp_char_hint=new_hint)
    await state.set_state(BankState.editing_char_for_set)
    
    data = await state.get_data()
    name = data.get("temp_char_name", "")
    desc = data.get("temp_char_description", "")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Добавить в набор",
                callback_data="confirm_char_for_set",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить описание",
                callback_data="edit_char_for_set_desc",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить подсказку",
                callback_data="edit_char_for_set_hint",
            )],
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="no_confirm_char_for_set",
            )]
        ]
    )

    await message.answer(
        f"🔑 Характеристика: *{name}*\n\n"
        f"📝 Описание:\n{desc}\n"
        f"💡 Тип значения: {new_hint}\n\n"
        "Все готово! Подтвердите добавление.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@custom.callback_query(F.data == "confirm_char_for_set", BankState.editing_char_for_set)
async def confirm_char_for_set(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    if "editing_set_id" not in data:
        await callback.answer("❌ Ошибка данных. Попробуйте еще раз.", show_alert=True)
        await state.clear()
        return
    
    set_id = data["editing_set_id"]
    name = data.get("temp_char_name", "")
    desc = data.get("temp_char_description", "")
    hint = data.get("temp_char_hint", "")
    
    if not name:
        await callback.answer("❌ Название характеристики не заполнено.", show_alert=True)
        return

    user_tg_id = callback.from_user.id
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.tg_id == user_tg_id).first()
        if not user:
            user = User(tg_id=user_tg_id)
            db.add(user)
            db.commit()

        char = Characteristic(
            user_id=user.id,
            set_id=set_id,
            name=name,
            description=desc,
            value_hint=hint,
        )
        db.add(char)
        db.commit()

        await callback.message.edit_text(
            f"✅ Характеристика *{name}* добавлена в набор!",
            parse_mode="Markdown",
        )
        
        await state.update_data(current_set_id=set_id)
        await state.set_state(BankState.waiting_products)
        
        db_refresh = SessionLocal()
        try:
            set_obj = db_refresh.query(Set).filter_by(id=set_id).first()
            set_name = set_obj.name if set_obj else "Набор"
        finally:
            db_refresh.close()
        
        text = (
            f"⚙️ Настройки набора: *{set_name}*\n\n"
            "Вы можете добавить еще характеристики или продукты."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Изменить имя", callback_data="edit_set_name"),
                ],
                [
                    InlineKeyboardButton(text="➕ Добавить еще характеристику", callback_data="add_char_to_set"),
                ],
                [
                    InlineKeyboardButton(text="➕ Добавить продукт", callback_data=f"add_product_to_set_{set_id}"),
                ],
                [
                    InlineKeyboardButton(text="⬅️ Назад к главному меню", callback_data="back_to_main_menu"),
                ],
            ]
        )

        await callback.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
        
    except Exception as e:
        print(f"❌ Ошибка при добавлении характеристики: {e}")
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
    finally:
        db.close()
    
    await callback.answer()


async def show_confirmation(callback: CallbackQuery, state: FSMContext):
    """Показывает подтверждение выбора"""
    data = await state.get_data()
    selected_products = data.get("selected_products", [])
    selected_chars = data.get("selected_characteristics", [])
    
    db = SessionLocal()
    try:
        product_objects = db.query(Product).filter(Product.id.in_(selected_products)).all()
        product_names = [p.name for p in product_objects]
        
        char_objects = db.query(Characteristic).filter(Characteristic.id.in_(selected_chars)).all()
        char_names = [c.name for c in char_objects]
        display_char_names = [FIELD_NAMES.get(name, name) for name in char_names]
        
        bank_ids = set(p.bank_id for p in product_objects)
        banks = db.query(Bank).filter(Bank.id.in_(bank_ids)).all()
        bank_names = [b.name for b in banks]
        
        keyboard = [
            [InlineKeyboardButton(text="✅ Да, начать парсинг", callback_data="start_parsing")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_characteristics")]
        ]
        
        text = (
            "📋 **Подтверждение выбора**\n\n"
            f"**Продукты:** {', '.join(product_names)}\n\n"
            f"**Характеристики:** {', '.join(display_char_names)}\n\n"
            f"**Банки:** {', '.join(bank_names)}\n\n"
            "Начать парсинг?"
        )
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    finally:
        db.close()
    
    await callback.answer()



@custom.callback_query(F.data.startswith("set_"))
async def handle_set_from_main_menu(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    parts = data.split("_")
    if len(parts) != 2:
        await callback.answer()
        return

    try:
        set_id = int(parts[1])
    except ValueError:
        await callback.answer("Некорректный набор", show_alert=True)
        return

    db = SessionLocal()
    try:
        set_obj = db.query(Set).filter_by(id=set_id).first()
        if not set_obj:
            await callback.answer("Набор не найден", show_alert=True)
            return

        await state.update_data(selected_set_id=set_id,
                               selected_products=[],
                               selected_characteristics=[])

        await state.set_state(BankState.waiting_products)
        await show_products_keyboard(callback, state, set_id)
    finally:
        db.close()

    await callback.answer()

@custom.callback_query(F.data == "create_new_set")
async def create_new_set_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_new_set_name)
    await callback.message.edit_text("Введите название нового набора:")

from app.keyboards.start_keyboard import get_product_list_keyboard

@custom.callback_query(F.data.startswith("set_products_"))
async def open_set_products(callback: CallbackQuery, state: FSMContext):
    try:
        set_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка набора", show_alert=True)
        return

    db = SessionLocal()
    try:
        products = db.query(Product).filter_by(set_id=set_id).all()
        await state.update_data(current_set_id=set_id)

        if not products:
            await callback.message.edit_text(
                "В этом наборе пока нет продуктов.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="➕ добавить продукт", callback_data="add_product_to_this_set")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"set_{set_id}")],
                    ]
                )
            )
        else:
            await callback.message.edit_text(
                "Продукты набора:",
                reply_markup=get_product_list_keyboard(products)
            )
    finally:
        db.close()
    await callback.answer()



@custom.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        tg_id = callback.from_user.id
        user = db.query(User).filter(User.tg_id == tg_id).first()
        
        if not user:
            user = User(tg_id=tg_id)
            db.add(user)
            db.commit()
            db.refresh(user)
        
        sets = get_sets_for_user(db, user.id)
    finally:
        db.close()

    await state.clear()
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=get_top_level_actions_keyboard(sets)
    )
    await callback.answer()

@custom.callback_query(F.data == "go_to_sets")
async def go_to_sets(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        tg_id = callback.from_user.id
        user = db.query(User).filter(User.tg_id == tg_id).first()
        
        if not user:
            user = User(tg_id=tg_id)
            db.add(user)
            db.commit()
            db.refresh(user)
        
        sets = get_sets_for_user(db, user.id)
    finally:
        db.close()

    await callback.message.edit_text(
        "Выберите набор карт:",
        reply_markup=get_top_level_actions_keyboard(sets)
    )
    await callback.answer()

@custom.message(BankState.waiting_new_set_name)
async def create_set_process(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Название не должно быть пустым. Введите название набора:")
        return

    # Сохраняем имя в state и спрашиваем тип набора
    await state.update_data(pending_set_name=name)
    await message.answer(
        f"📁 Набор: *{name}*\n\nВыберите тип набора:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Программа лояльности", callback_data="set_type_loyalty")],
            [InlineKeyboardButton(text="💳 Обычный набор (карты, вклады...)", callback_data="set_type_regular")],
        ])
    )


@custom.callback_query(F.data.in_({"set_type_loyalty", "set_type_regular"}))
async def create_set_with_type(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data.get("pending_set_name", "Новый набор")
    is_loyalty = 1 if callback.data == "set_type_loyalty" else 0

    user_id = callback.from_user.id
    db = SessionLocal()

    try:
        user = db.query(User).filter(User.tg_id == user_id).first()
        if not user:
            user = User(tg_id=user_id)
            db.add(user)
            db.commit()

        existing = db.query(Set).filter_by(name=name, user_id=user.id).first()
        if existing:
            await callback.message.edit_text(f"Набор с таким именем уже есть: {name}")
            await state.clear()
            return

        new_set = Set(
            name=name,
            user_id=user.id,
            description="Пользовательский набор",
            is_loyalty=is_loyalty
        )
        db.add(new_set)
        db.commit()
        db.refresh(new_set)

        type_label = "🎯 Программа лояльности" if is_loyalty else "💳 Обычный набор"
        await callback.message.edit_text(f"✅ Набор '{name}' создан!\n{type_label}")

        set_id = new_set.id
        await state.update_data(current_set_id=set_id)
        await state.set_state(BankState.waiting_products)

        text = (
            f"⚙️ Настройки набора: *{name}*\n\n"
            "Добавьте продукты и характеристики для этого набора."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="➕ Добавить продукт", callback_data=f"add_product_to_set_{set_id}"),
                ],
                [
                    InlineKeyboardButton(text="➕ Добавить характеристику", callback_data="add_char_to_set"),
                ],
                [
                    InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="back_to_main_menu"),
                ],
            ]
        )

        await callback.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

    finally:
        db.close()


async def build_products_keyboard(state: FSMContext, set_id: int):

    data = await state.get_data()
    selected_products = set(data.get("selected_products", []))

    db = SessionLocal()
    try:
        products = db.query(Product).filter(
            Product.set_id == set_id
        ).all()
        
        set_obj = db.query(Set).filter_by(id=set_id).first()
        banks = db.query(Bank).all()
        bank_map = {b.id: b.name for b in banks}
    finally:
        db.close()

    keyboard = []
    for product in products:
        is_selected = product.id in selected_products
        emoji = "✅" if is_selected else ""
        bank_name = bank_map.get(product.bank_id, "Unknown")
        product_text = f"{emoji} {product.name} ({bank_name})"
        keyboard.append([
            InlineKeyboardButton(
                text=product_text,
                callback_data=f"toggle_product_{product.id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="➕ Добавить продукт", callback_data=f"add_product_to_set_{set_id}")
    ])
    keyboard.append([
        InlineKeyboardButton(text="✏️ Настройки набора", callback_data=f"edit_set_{set_id}")
    ])
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_set"),
        InlineKeyboardButton(text="➡️ Далее", callback_data="show_characteristics")
    ])

    set_name = set_obj.name if set_obj else "Набор"
    text = f"📦 **{set_name}**\n\nВыберите продукты\nВыбрано: {len(selected_products)}/{len(products)}"

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    return text, markup


@custom.callback_query(F.data == "show_characteristics", BankState.waiting_products)
async def show_characteristics(callback: CallbackQuery, state: FSMContext):

    data = await state.get_data()
    set_id = data.get("selected_set_id")
    selected_products = data.get("selected_products", [])
    
    if not selected_products:
        await callback.answer("❌ Выберите хотя бы один продукт!", show_alert=True)
        return
    
    if not set_id:
        await callback.answer("Набор не выбран", show_alert=True)
        return

    selected_chars = set(data.get("selected_characteristics", []))

    db = SessionLocal()
    try:
        chars = db.query(Characteristic).filter(
            Characteristic.set_id == set_id
        ).all()
    finally:
        db.close()

    keyboard: list[list[InlineKeyboardButton]] = []

    for char in chars:
        is_selected = char.id in selected_chars
        emoji = "✅" if is_selected else ""
        display_name = FIELD_NAMES.get(char.name, char.name)
        keyboard.append([
            InlineKeyboardButton(
                text=f"{emoji} {display_name}",
                callback_data=f"toggle_char_{char.id}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="➕ Добавить характеристику",
            callback_data="add_char_to_set",
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад к продуктам",
            callback_data="back_to_products",
        ),
        InlineKeyboardButton(
            text="➡️ Подтвердить",
            callback_data="confirm_selection",
        ),
    ])

    text = (
        "🔧 Выберите характеристики этого набора\n\n"
        f"Выбрано: {len(selected_chars)}/{len(chars)}"
    )

    await state.set_state(BankState.waiting_characteristics)
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()

@custom.callback_query(
    F.data.regexp(r"^edit_set_\d+$"),
    BankState.waiting_products
)
async def edit_set_menu(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")

    if not parts[-1].isdigit():
        await callback.answer("Ошибка данных", show_alert=True)
        return

    set_id = int(parts[-1])

    await state.update_data(current_set_id=set_id)
    db = SessionLocal()
    try:
        set_obj = db.query(Set).filter_by(id=set_id).first()
        if not set_obj:
            await callback.answer("Набор не найден", show_alert=True)
            return

        text = (
            f"⚙️ Настройки набора: *{set_obj.name}*\n\n"
            "Вы можете изменить имя и управлять характеристиками этого набора."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Изменить имя", callback_data="edit_set_name"),
                ],
                [
                    InlineKeyboardButton(text="➕ Добавить характеристику", callback_data="add_char_to_set"),
                ],
                [
                    InlineKeyboardButton(text="⬅️ Назад к продуктам", callback_data="back_to_set_products"),
                ],
            ]
        )

        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    finally:
        db.close()
    await callback.answer()


@custom.callback_query(F.data == "back_to_set_products")
async def back_to_set_products(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    set_id = data.get("current_set_id") or data.get("selected_set_id")
    await state.set_state(BankState.waiting_products)
    await show_products_keyboard(callback, state, set_id)


@custom.callback_query(F.data == "edit_set_name")
async def edit_set_name_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    set_id = data.get("current_set_id")
    if not set_id:
        await callback.answer("Набор не выбран", show_alert=True)
        return

    db = SessionLocal()
    try:
        set_obj = db.query(Set).filter_by(id=set_id).first()
        if not set_obj:
            await callback.answer("Набор не найден", show_alert=True)
            return

        await state.set_state(BankState.waiting_set_name_edit)
        await callback.message.edit_text(
            f"✏️ Текущее имя: *{set_obj.name}*\n\nВведите новое название:",
            parse_mode="Markdown",
        )
    finally:
        db.close()
    await callback.answer()


@custom.message(BankState.waiting_set_name_edit)
async def process_set_name_edit(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if not new_name:
        await message.answer("Название не должно быть пустым!")
        return

    data = await state.get_data()
    set_id = data.get("current_set_id")

    db = SessionLocal()
    try:
        set_obj = db.query(Set).filter_by(id=set_id).first()
        if not set_obj:
            await message.answer("Набор не найден")
            return

        set_obj.name = new_name
        db.commit()

        await message.answer(f"✅ Имя набора изменено на: *{new_name}*", parse_mode="Markdown")

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Изменить имя", callback_data="edit_set_name"),
                ],
                [
                    InlineKeyboardButton(text="➕ Добавить характеристику", callback_data="add_char_to_set"),
                ],
                [
                    InlineKeyboardButton(text="⬅️ Назад к продуктам", callback_data="back_to_set_products"),
                ],
            ]
        )
        await message.answer(
            f"⚙️ Настройки набора: *{new_name}*",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        await state.set_state(BankState.waiting_characteristics)
    finally:
        db.close()


@custom.callback_query(F.data == "add_char_to_set")
async def add_char_to_set_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    set_id = data.get("current_set_id") or data.get("selected_set_id")
    
    if not set_id:
        await callback.answer("❌ Набор не выбран. Пожалуйста, выберите набор сначала.", show_alert=True)
        return

    await state.update_data(editing_set_id=set_id)
    await state.set_state(BankState.waiting_new_char_for_set)
    await callback.message.edit_text("➕ Введите название новой характеристики для этого набора:")
    await callback.answer()



@custom.callback_query(F.data.startswith("toggle_product_"), BankState.waiting_products)
async def toggle_product(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_", 2)[2])
    data = await state.get_data()
    selected_products = set(data.get("selected_products", []))
    
    if product_id in selected_products:
        selected_products.remove(product_id)
    else:
        selected_products.add(product_id)
    
    set_id = data.get("selected_set_id")
    await state.update_data(selected_products=list(selected_products))
    await show_products_keyboard(callback, state, set_id)


@custom.callback_query(F.data == "back_to_set", BankState.waiting_products)
async def back_to_set(callback: CallbackQuery, state: FSMContext):
    await state.update_data(selected_products=[])

    db = SessionLocal()
    try:
        tg_id = callback.from_user.id
        user = db.query(User).filter(User.tg_id == tg_id).first()
        
        if not user:
            user = User(tg_id=tg_id)
            db.add(user)
            db.commit()
            db.refresh(user)
        
        sets = get_sets_for_user(db, user.id)
    finally:
        db.close()

    await state.clear()
    await callback.message.edit_text(
        "👋 Выберите **набор карт**:",
        parse_mode="Markdown",
        reply_markup=get_top_level_actions_keyboard(sets)
    )
    await callback.answer()



@custom.callback_query(F.data.startswith("add_product_to_set_"))
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    set_id = int(callback.data.split("_")[-1])
    await state.update_data(editing_set_id=set_id)
    await state.set_state(BankState.waiting_product_url)
    await callback.message.edit_text("Введите ссылку на страницу продукта (карты/кредита/депозита):")
    await callback.answer()


@custom.message(BankState.waiting_product_url)
async def handle_product_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("Введите корректный URL (начинается с http:// или https://)")
        return

    data = await state.get_data()
    set_id = data["editing_set_id"]
    user_id = message.from_user.id

    progress_msg = await message.answer(
        "🔄 Загружаю страницу...\n"
        "[░░░░░░░░░░] 10%"
    )

    try:
        await progress_msg.edit_text(
            "🔄 Загружаю страницу...\n"
            "[██░░░░░░░░] 20%"
        )

        page_text = await extract_page_text(url)
        if not page_text or len(page_text) < 100:
            await progress_msg.delete()
            await message.answer(
                "❌ Не удалось загрузить страницу.\n\n"
                "Возможные причины:\n"
                "• Неверный URL\n"
                "• Сайт недоступен\n"
                "• Сайт заблокирован\n\n"
                "Проверьте URL и попробуйте снова."
            )
            await state.clear()
            return

        await progress_msg.edit_text(
            "🤖 Анализирую содержимое...\n"
            "[████░░░░░░] 40%"
        )

        giga = GigaChat(
            credentials=GIGACHAT_TOKEN,
            scope="GIGACHAT_API_B2B",
            verify_ssl_certs=False,
            model="GigaChat-2-Max"
        )

        prompt = f"""
Проанализируй текст страницы и определи:

1. название банка (кратко: просто "Сбер", "Альфа Банк", "Беларусбанк" и т.п.);
2. название продукта (карты, кредита или депозита).

Формат ответа — JSON строкой:
{{
"bank": "НАЗВАНИЕ_БАНКА",
"product": "НАЗВАНИЕ_ПРОДУКТА"
}}

ТЕКСТ:
{page_text}
"""

        result = giga.chat(prompt)
        raw = result.choices[0].message.content

        await progress_msg.edit_text(
            "✅ Анализ завершен\n"
            "[██████████] 100%"
        )

        parsed = _parse_json_safely(raw)
        if not parsed:
            bank_guess = "Банк (уточните)"
            product_guess = "Продукт (уточните)"
        else:
            bank_guess = parsed.get("bank", "Банк (уточните)")
            product_guess = parsed.get("product", "Продукт (уточните)")

        # Удаляем прогресс сообщение
        try:
            await progress_msg.delete()
        except:
            pass

        await state.update_data(
            temp_product_url=url,
            temp_bank_guess=bank_guess,
            temp_product_guess=product_guess,
        )
        await state.set_state(BankState.waiting_product_confirm)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_product"),
                    InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_product_bank_product"),
                ]
            ]
        )
        await message.answer(
            "✅ Анализ завершен:\n\n"
            f"🏦 Банк: <b>{bank_guess}</b>\n"
            f"💳 Продукт: <b>{product_guess}</b>\n\n"
            "Проверьте и подтвердите или отредактируйте.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception as e:
        print(f"❌ Ошибка при обработке URL: {e}")
        
        try:
            await progress_msg.delete()
        except:
            pass
        
        await message.answer(
            "❌ Ошибка при обработке URL.\n\n"
            "Попробуйте еще раз или проверьте URL."
        )
        await state.clear()



@custom.callback_query(F.data == "confirm_product", BankState.waiting_product_confirm)
async def confirm_product(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    url = data["temp_product_url"]
    bank_guess = data["temp_bank_guess"]
    product_guess = data["temp_product_guess"]
    set_id = data.get("editing_set_id") or data.get("selected_set_id")

    db = SessionLocal()
    try:
        bank = db.query(Bank).filter(Bank.name == bank_guess).first()
        if not bank:
            await callback.answer("Банк не найден в БД, добавь вручную.", show_alert=True)
            return

        product = Product(
            set_id=set_id,
            bank_id=bank.id,
            name=product_guess,
            url=url,
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    await state.set_state(BankState.waiting_products)
    await state.update_data(editing_set_id=None)
    await show_products_keyboard(callback, state, set_id)


@custom.callback_query(F.data == "add_characteristic")
async def add_characteristic_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_char_name)
    await callback.message.edit_text("Введите название характеристики (например, \"Обслуживание\"):")
    await callback.answer()


@custom.message(BankState.waiting_char_name)
async def handle_char_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Введите не‑пустое название характеристики:")
        return

    await state.update_data(temp_char_name=name)
    user_id = message.from_user.id

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.tg_id == user_id).first()
        if not user:
            user = User(tg_id=user_id)
            db.add(user)
            db.commit()
    finally:
        db.close()

    status_msg = await message.answer("⏳ Генерирую описание...")

    prompt = f"""
Сформулируй краткое понятное описание для характеристики финансового продукта с названием: "{name}".
Также добавь маленький текст‑подсказку о типе значения этой характеристики (например: "в BYN", "% годовых", "без ограничений" и т.п.).

Представь ответ в JSON‑форме одной строкой:
{{
  "description": "Описание характеристики...",
  "value_hint": "Подсказка к формату значения"
}}
"""

    try:
        giga = GigaChat(
            credentials=GIGACHAT_TOKEN,
            scope="GIGACHAT_API_B2B",
            verify_ssl_certs=False,
            model="GigaChat-2-Max"
        )

        result = giga.chat(prompt)
        raw = result.choices[0].message.content
        parsed = _parse_json_safely(raw)

        if not parsed:
            desc = "Описание характеристики."
            hint = "Заполните вручную (BYN, % и т.п.)"
        else:
            desc = parsed.get("description", "Описание характеристики.")
            hint = parsed.get("value_hint", "Подсказка не сформирована")

        await state.update_data(
            temp_char_description=desc,
            temp_char_hint=hint,
        )
        await state.set_state(BankState.editing_char_desc)

        try:
            await status_msg.delete()
        except:
            pass

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Добавить", callback_data="confirm_characteristic"),
                    InlineKeyboardButton(text="✏️ Изменить описание", callback_data="edit_characteristic_desc"),
                ]
            ]
        )

        await message.answer(
            f"🔑 Характеристика: <b>{name}</b>\n\n"
            f"📝 Описание:\n<pre>{desc}</pre>\n"
            f"💡 Тип значения: <code>{hint}</code>\n\n"
            f"<b>Проверьте и подтвердите или отредактируйте описание и подсказку.</b>",
            parse_mode="HTML",
            reply_markup=kb,
        )

    except Exception as e:
        print(f"Ошибка при генерации описания: {e}")
        await status_msg.delete()
        
        await state.update_data(
            temp_char_description="Описание характеристики.",
            temp_char_hint="Заполните вручную"
        )
        await state.set_state(BankState.editing_char_desc)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Добавить", callback_data="confirm_characteristic"),
                    InlineKeyboardButton(text="✏️ Изменить описание", callback_data="edit_characteristic_desc"),
                ]
            ]
        )

        await message.answer(
            f"🔑 Характеристика: <b>{name}</b>\n\n"
            f"⚠️ Не удалось автоматически сгенерировать описание.\n"
            f"Пожалуйста, отредактируйте вручную.",
            parse_mode="HTML",
            reply_markup=kb,
        )


@custom.callback_query(F.data == "edit_characteristic_desc", BankState.editing_char_desc)
async def edit_characteristic_desc(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_char_desc_edit)
    await callback.message.edit_text(
        "✏️ Введите новое описание характеристики:"
    )
    await callback.answer()


@custom.message(BankState.waiting_char_desc_edit)
async def process_char_desc_edit(message: Message, state: FSMContext):
    new_desc = message.text.strip()
    if not new_desc:
        await message.answer("Описание не должно быть пустым!")
        return

    await state.update_data(temp_char_description=new_desc)
    await state.set_state(BankState.editing_char_desc)
    
    data = await state.get_data()
    name = data.get("temp_char_name", "")
    hint = data.get("temp_char_hint", "")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Добавить", callback_data="confirm_characteristic"),
                InlineKeyboardButton(text="✏️ Изменить подсказку", callback_data="edit_characteristic_hint"),
            ]
        ]
    )

    await message.answer(
        f"🔑 Характеристика: <b>{name}</b>\n\n"
        f"📝 Описание:\n<pre>{new_desc}</pre>\n"
        f"💡 Тип значения: <code>{hint}</code>\n\n"
        f"<b>Подтвердите или отредактируйте дальше.</b>",
        parse_mode="HTML",
        reply_markup=kb,
    )


@custom.callback_query(F.data == "edit_characteristic_hint", BankState.editing_char_desc)
async def edit_characteristic_hint(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_char_hint_edit)
    await callback.message.edit_text(
        "💡 Введите подсказку к формату значения (например: 'в BYN', '% годовых'):"
    )
    await callback.answer()


@custom.message(BankState.waiting_char_hint_edit)
async def process_char_hint_edit(message: Message, state: FSMContext):
    new_hint = message.text.strip()
    if not new_hint:
        await message.answer("Подсказка не должна быть пустой!")
        return

    await state.update_data(temp_char_hint=new_hint)
    await state.set_state(BankState.editing_char_desc)
    
    data = await state.get_data()
    name = data.get("temp_char_name", "")
    desc = data.get("temp_char_description", "")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Добавить", callback_data="confirm_characteristic"),
                InlineKeyboardButton(text="✏️ Изменить описание", callback_data="edit_characteristic_desc"),
            ]
        ]
    )

    await message.answer(
        f"🔑 Характеристика: <b>{name}</b>\n\n"
        f"📝 Описание:\n<pre>{desc}</pre>\n"
        f"💡 Тип значения: <code>{new_hint}</code>\n\n"
        f"<b>Все готово! Подтвердите добавление.</b>",
        parse_mode="HTML",
        reply_markup=kb,
    )


@custom.callback_query(F.data == "confirm_characteristic", BankState.editing_char_desc)
async def confirm_characteristic(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data["temp_char_name"]
    desc = data["temp_char_description"]
    hint = data["temp_char_hint"]
    
    user_id = callback.from_user.id
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.tg_id == user_id).first()
        if not user:
            user = User(tg_id=user_id)
            db.add(user)
            db.commit()
        
        char = Characteristic(
            user_id=user.id,
            set_id=None,
            name=name,
            description=desc,
            value_hint=hint
        )
        db.add(char)
        db.commit()
    finally:
        db.close()
    
    await callback.message.edit_text(f"✅ Характеристика *{name}* добавлена!", parse_mode="Markdown")
    await state.clear()
    await callback.answer()


@custom.callback_query(F.data == "edit_characteristic_desc", BankState.editing_char_desc)
async def edit_characteristic_desc(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.editing_char_desc)
    await callback.message.edit_text("Введите новое описание характеристики:")
    await callback.answer()


@custom.callback_query(F.data.startswith("toggle_char_"), BankState.waiting_characteristics)
async def toggle_characteristic(callback: CallbackQuery, state: FSMContext):
    char_id = int(callback.data.split("_", 2)[2])
    data = await state.get_data()
    selected_chars = set(data.get("selected_characteristics", []))
    
    if char_id in selected_chars:
        selected_chars.remove(char_id)
    else:
        selected_chars.add(char_id)
    
    await state.update_data(selected_characteristics=list(selected_chars))
    
    set_id = data.get("selected_set_id")
    db = SessionLocal()
    try:
        chars = db.query(Characteristic).filter(
            Characteristic.set_id == set_id
        ).all()
    finally:
        db.close()

    keyboard: list[list[InlineKeyboardButton]] = []
    updated_data = await state.get_data()
    updated_selected = set(updated_data.get("selected_characteristics", []))
    
    for char in chars:
        is_selected = char.id in updated_selected
        emoji = "✅" if is_selected else ""
        display_name = FIELD_NAMES.get(char.name, char.name)
        keyboard.append([
            InlineKeyboardButton(
                text=f"{emoji} {display_name}",
                callback_data=f"toggle_char_{char.id}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="➕ Добавить характеристику",
            callback_data="add_char_to_set",
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад к продуктам",
            callback_data="back_to_products",
        ),
        InlineKeyboardButton(
            text="➡️ Подтвердить",
            callback_data="confirm_selection",
        ),
    ])

    text = (
        "🔧 Выберите характеристики этого набора\n\n"
        f"Выбрано: {len(updated_selected)}/{len(chars)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


@custom.callback_query(F.data == "back_to_products", BankState.waiting_characteristics)
async def back_to_products(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    set_id = data.get("selected_set_id")
    await state.set_state(BankState.waiting_products)
    await show_products_keyboard(callback, state, set_id)



@custom.callback_query(F.data == "confirm_selection", BankState.waiting_characteristics)
async def confirm_selection(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    if not data.get("selected_characteristics"):
        await callback.answer("❌ Выберите хотя бы одну характеристику!", show_alert=True)
        return
    
    await show_confirmation(callback, state)
    await callback.answer()


@custom.callback_query(F.data == "back_to_characteristics")
async def back_to_characteristics(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    set_id = data.get("selected_set_id")
    selected_chars = set(data.get("selected_characteristics", []))
    
    db = SessionLocal()
    try:
        chars = db.query(Characteristic).filter(
            Characteristic.set_id == set_id
        ).all()
    finally:
        db.close()

    keyboard: list[list[InlineKeyboardButton]] = []

    for char in chars:
        is_selected = char.id in selected_chars
        emoji = "✅" if is_selected else ""
        display_name = FIELD_NAMES.get(char.name, char.name)
        keyboard.append([
            InlineKeyboardButton(
                text=f"{emoji} {display_name}",
                callback_data=f"toggle_char_{char.id}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="➕ Добавить характеристику",
            callback_data="add_char_to_set",
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад к продуктам",
            callback_data="back_to_products",
        ),
        InlineKeyboardButton(
            text="➡️ Подтвердить",
            callback_data="confirm_selection",
        ),
    ])

    text = (
        "🔧 Выберите характеристики этого набора\n\n"
        f"Выбрано: {len(selected_chars)}/{len(chars)}"
    )

    await state.set_state(BankState.waiting_characteristics)
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


def _parse_json_safely(raw_response: str) -> dict | None:
    if not raw_response:
        return None

    start_idx = raw_response.find('{')
    end_idx = raw_response.rfind('}')

    if start_idx == -1 or end_idx == -1:
        print(f"  JSON не найден в ответе")
        return None

    json_str = raw_response[start_idx:end_idx+1]
    json_str = json_str.replace('```json', '').replace('```', '').strip()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"!!!! JSON ошибка парсинга: {str(e)[:100]}")

        try:
            json_str = json_str.replace("'", '"')
            return json.loads(json_str)
        except:
            pass

        try:
            json_str = re.sub(r'\\n', ' ', json_str)
            json_str = re.sub(r'\n', ' ', json_str)
            return json.loads(json_str)
        except:
            pass

        return None

@custom.callback_query(F.data == "no_confirm_char_for_set", BankState.editing_char_for_set)
async def no_confirm_char_for_set(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    set_id = data.get("editing_set_id") or data.get("current_set_id")
    
    await callback.message.edit_text("Характеристика не добавлена.")
    
    if set_id:
        await state.set_state(BankState.waiting_products)
        
        db = SessionLocal()
        try:
            set_obj = db.query(Set).filter_by(id=set_id).first()
            set_name = set_obj.name if set_obj else "Набор"
        finally:
            db.close()
        
        text = (
            f"⚙️ Настройки набора: *{set_name}*\n\n"
            "Добавьте продукты или характеристики."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Изменить имя", callback_data="edit_set_name"),
                ],
                [
                    InlineKeyboardButton(text="➕ Добавить характеристику", callback_data="add_char_to_set"),
                ],
                [
                    InlineKeyboardButton(text="➕ Добавить продукт", callback_data=f"add_product_to_set_{set_id}"),
                ],
                [
                    InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main_menu"),
                ],
            ]
        )

        await callback.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
    
    await callback.answer()


@custom.callback_query(F.data == "start_parsing")
async def start_parsing(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_products = data.get("selected_products", [])
    selected_chars = data.get("selected_characteristics", [])
    
    if not selected_products or not selected_chars:
        await callback.answer("Выберите продукты и характеристики!", show_alert=True)
        return
    
    await callback.message.edit_text("🔄 **Начинаем парсинг...**\n\nЭто может занять несколько минут.", parse_mode="Markdown")
    await callback.answer()
    
    set_id = data.get("selected_set_id")
    asyncio.create_task(parse_selected_data_with_response(
        callback.from_user.id, 
        selected_products, 
        selected_chars,
        callback.message.chat.id,
        callback.bot,
        set_id=set_id
    ))

async def parse_selected_data_with_response(
    user_id: int, 
    product_ids: list[int], 
    char_ids: list[int],
    chat_id: int,
    bot: Bot,
    set_id: int = None
):

    db = SessionLocal()
    message_id = None

    log = Log(
        user_id=user_id,
        action="parse",
        status="process",
        tokens_input=0,
        tokens_output=0,
        message=""
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    
    try:
        print(f"\nНачинаем парсинг: {len(product_ids)} продуктов × {len(char_ids)} характеристик")
        
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        chars = db.query(Characteristic).filter(Characteristic.id.in_(char_ids)).all()
        banks = db.query(Bank).all()
        
        bank_map = {b.id: b for b in banks}

        # Режим программы лояльности только для набора с id=7
        is_loyalty = (set_id == 7)
        print(f"  {'🎯 Программа лояльности' if is_loyalty else '📋 Обычный набор'} (set_id={set_id})")
        
        giga = GigaChat(
            credentials=GIGACHAT_TOKEN,
            scope="GIGACHAT_API_B2B",
            verify_ssl_certs=False,
            model="GigaChat-2-Max"
        )
        
        total_products = len(products)
        
        # Отправляем начальное сообщение
        init_msg = await bot.send_message(
            chat_id=chat_id,
            text=f"📊 Парсинг начинается...\n\n"
                 f"Продуктов: {total_products}\n"
                 f"Характеристик: {len(chars)}"
        )
        message_id = init_msg.message_id
        
        for idx, product in enumerate(products, 1):
            progress = int((idx - 1) / total_products * 20)
            bar = "█" * progress + "░" * (20 - progress)
            bank_name = bank_map.get(product.bank_id).name if product.bank_id in bank_map else "Unknown"
            
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"📊 Парсинг продуктов\n\n"
                         f"Продукт: {product.name}\n"
                         f"Банк: {bank_name}\n"
                         f"Прогресс: [{bar}] {idx}/{total_products}\n\n"
                         f"⏱️ Идет сбор данных...\n"
                )
            except Exception as e:
                print(f" Ошибка обновления: {e}")
            
            print(f"\n Парсим {product.name} ({bank_name})...")
            
            try:
                # Загружаем контент с таймаутом 90 секунд
                TIMEOUT = 90
                try:
                    page_content = await asyncio.wait_for(
                        get_page_content(product.url),
                        timeout=TIMEOUT
                    )
                except asyncio.TimeoutError:
                    print(f"  ⏱️ Таймаут {TIMEOUT}с — {bank_name} не ответил, переходим дальше")
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"⏱️ {bank_name} | {product.name} — превышено время ожидания ({TIMEOUT}с), пропускаем"
                    )
                    continue

                if not page_content or len(page_content) < 500:
                    print(f"  !!! requests не сработал, пробуем Playwright...")
                    from app.handlers.parser import get_page_content as get_page_content_playwright
                    try:
                        page_content = await asyncio.wait_for(
                            get_page_content_playwright(product.url),
                            timeout=TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        print(f"  ⏱️ Playwright таймаут {TIMEOUT}с — пропускаем")
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⏱️ {bank_name} | {product.name} — Playwright тоже не ответил ({TIMEOUT}с), пропускаем"
                        )
                        continue
                    if not page_content or len(page_content) < 500:
                        print(f"  !!! Не удалось загрузить страницу ни одним методом")
                        continue
                
                print(f" Загружено {len(page_content)} символов")
                
                # Очищаем HTML
                soup = BeautifulSoup(page_content, 'html.parser')
                for tag in soup(['script', 'style', 'meta', 'link', 'svg', 'iframe',
                                 'noscript', 'header', 'footer', 'nav']):
                    tag.decompose()
                cleaned_html = str(soup)
                # Лимит увеличен — программы лояльности часто большие страницы
                if len(cleaned_html) > 150000:
                    cleaned_html = cleaned_html[:150000]

                # PDF и доп. страницы — только для программ лояльности
                pdf_content, pdf_urls, extra_text = "", [], ""
                if is_loyalty:
                    try:
                        result = await _collect_pdf_content(page_content, product.url)
                        pdf_content, pdf_urls = result if result else ("", [])
                    except Exception as _pdf_err:
                        print(f"  ⚠️ PDF сбор упал: {_pdf_err}")
                    if pdf_urls:
                        print(f"  📄 PDF прочитано: {len(pdf_urls)} шт.: {pdf_urls}")
                    extra_text = await _fetch_extra_pages(page_content, product.url)
                    if extra_text:
                        print(f"  📑 Доп. страницы загружены: {len(extra_text)} символов")
                
                if len(cleaned_html) < 300:
                    print(f" -! HTML слишком мал, используем текстовый парсинг")
                    # Дополняем текст PDF-контентом если есть
                    raw_text = soup.get_text(separator="\n", strip=True)
                    text_content = _dedup_text(raw_text)
                    if extra_text:
                        text_content = text_content + "\n\n---ДОППСТРАНИЦЫ---\n\n" + extra_text
                    if pdf_content:
                        text_content = text_content + "\n\n---PDF---\n\n" + pdf_content
                    text_content = text_content[:80000]
                    tokens_in, tokens_out = await _parse_product_text(giga, product, chars, db, user_id, text_content, pdf_urls)
                    log.tokens_input += tokens_in
                    log.tokens_output += tokens_out
                    continue
                

                tokens_in, tokens_out = await _parse_product_html(giga, product, chars, db, user_id, cleaned_html, pdf_content, pdf_urls, extra_text)
                log.tokens_input += tokens_in
                log.tokens_output += tokens_out
                
                # tokens_in==0 означает либо ошибку, либо все поля null → пробуем текстовый парсинг
                if tokens_in == 0 and tokens_out == 0:
                    print(f"  >>> HTML не дал результата, пробуем текстовый парсинг...")
                    raw_text = soup.get_text(separator="\n", strip=True)
                    text_content = _dedup_text(raw_text)
                    print(f"  Текст: {len(raw_text)} → {len(text_content)} символов после дедупликации")
                    if extra_text:
                        text_content = text_content + "\n\n---ДОППСТРАНИЦЫ---\n\n" + extra_text
                    if pdf_content:
                        text_content = text_content + "\n\n---PDF---\n\n" + pdf_content
                    text_content = text_content[:80000]
                    tokens_in, tokens_out = await _parse_product_text(giga, product, chars, db, user_id, text_content, pdf_urls)
                    log.tokens_input += tokens_in
                    log.tokens_output += tokens_out
                
            except Exception as e:
                print(f"  !!! Ошибка парсинга: {e}")
                continue
            

            db.commit()
            await asyncio.sleep(0.5)
    
        
        excel_path = create_bank_excel_report(db, user_id, product_ids, char_ids)
        
        if excel_path:
            print(f"Excel готов: {excel_path}")
            
            try:
                document = FSInputFile(excel_path)
                await bot.send_document(
                    chat_id=chat_id,
                    document=document,
                    caption=f"📊 Готовый отчет парсинга!\n\n"
                            f"- Обработано {len(products)} продуктов\n"
                            f"- {len(chars)} характеристик\n"
                            f"Файл готов к скачиванию!"
                )
                print(f"Excel отправлен пользователю")
                
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"✅ Парсинг завершен!\n\n"
                         f"📁 Excel отправлен\n"
                )
                
                log.status = "ok"
                log.message = f"Успешно: {len(products)} продуктов, {len(chars)} характеристик, вход: {log.tokens_input} / выход: {log.tokens_output} токенов"
                db.commit()
                
            except Exception as e:
                print(f"!!! Ошибка при отправке файла: {e}")
                log.status = "error"
                log.message = f"Ошибка: {str(e)}"
                db.commit()
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"!!! Ошибка: {e}"
                    )
                except:
                    pass
        else:
            log.status = "error"
            log.message = "Не удалось создать Excel"
            db.commit()
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="!!! Ошибка при создании Excel файла"
                )
            except:
                pass
        
    except Exception as e:
        print(f"-! Ошибка: {e}")
        import traceback
        traceback.print_exc()
        
        log.status = "error"
        log.message = f"Ошибка: {str(e)}"
        db.commit()
        
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"!!! Ошибка парсинга: {str(e)}"
            )
        except:
            pass
    finally:
        db.close()


@custom.callback_query(F.data == "edit_product_bank_product", BankState.waiting_product_confirm)
async def edit_product_details(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.set_state(BankState.waiting_product_confirm)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 Изменить банк", callback_data="edit_bank")],
        [InlineKeyboardButton(text="💳 Изменить продукт", callback_data="edit_product")],
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_product")]
    ])
    
    await callback.message.edit_text(
        "Что изменить?",
        reply_markup=kb
    )
    await callback.answer()

@custom.callback_query(F.data == "edit_bank")
async def edit_bank_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_bank_edit)
    await callback.message.edit_text("Введите название банка:")
    await callback.answer()

@custom.callback_query(F.data == "edit_product")
async def edit_product_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BankState.waiting_product_edit)
    await callback.message.edit_text("Введите название продукта:")
    await callback.answer()

@custom.message(BankState.waiting_bank_edit)
async def process_bank_edit(message: Message, state: FSMContext):
    new_bank = message.text.strip()
    await state.update_data(temp_bank_guess=new_bank)
    await state.set_state(BankState.waiting_product_confirm)
    
    data = await state.get_data()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_product")],
        [InlineKeyboardButton(text="✏️ Дополнительно изменить", callback_data="edit_product_bank_product")]
    ])
    
    await message.answer(
        f"🏦 Банк: <b>{new_bank}</b>\n💳 Продукт: <b>{data['temp_product_guess']}</b>\n\nПодтвердить?",
        parse_mode="HTML",
        reply_markup=kb
    )

@custom.message(BankState.waiting_product_edit)
async def process_product_edit(message: Message, state: FSMContext):
    new_product = message.text.strip()
    await state.update_data(temp_product_guess=new_product)
    await state.set_state(BankState.waiting_product_confirm)
    
    data = await state.get_data()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_product")],
        [InlineKeyboardButton(text="✏️ Дополнительно изменить", callback_data="edit_product_bank_product")]
    ])
    
    await message.answer(
        f"🏦 Банк: <b>{data['temp_bank_guess']}</b>\n💳 Продукт: <b>{new_product}</b>\n\nПодтвердить?",
        parse_mode="HTML",
        reply_markup=kb
    )

@custom.callback_query(F.data.startswith("add_product_to_this_set"))
async def add_product_to_current_set(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    set_id = data.get("current_set_id")
    if not set_id:
        await callback.answer("Набор не выбран", show_alert=True)
        return
    
    await state.update_data(editing_set_id=set_id)
    await state.set_state(BankState.waiting_product_url)
    await callback.message.edit_text("Введите ссылку на страницу продукта:")
    await callback.answer()



# ─────────────────────────────────────────────
# PDF helpers
# ─────────────────────────────────────────────

def _extract_pdf_links(html: str, base_url: str) -> list[str]:
    """Ищет ссылки на PDF-файлы в HTML-странице (расширенный поиск)."""
    from urllib.parse import urlparse, urljoin
    soup = BeautifulSoup(html, 'html.parser')
    links = set()
    base = base_url.rstrip('/')

    def _normalize(href: str) -> str | None:
        href = href.strip().split('#')[0].split('?')[0]
        if not href:
            return None
        if href.startswith('http'):
            return href
        if href.startswith('//'):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}:{href}"
        # Relative path
        return urljoin(base_url, href)

    PDF_MARKERS = ['.pdf', '/pdf/', 'pdf/', 'documents/', 'doc/', 'files/']

    # 1. <a href>
    for tag in soup.find_all('a', href=True):
        href = tag['href']
        if any(m in href.lower() for m in PDF_MARKERS):
            url = _normalize(href)
            if url:
                links.add(url)

    # 2. data-* attributes (data-href, data-url, data-src)
    for tag in soup.find_all(True):
        for attr in ('data-href', 'data-url', 'data-src', 'data-file'):
            val = tag.get(attr, '')
            if val and any(m in val.lower() for m in PDF_MARKERS):
                url = _normalize(val)
                if url:
                    links.add(url)

    # 3. Ищем PDF-ссылки прямо в тексте (встречается в JS-блоках)
    import re
    for match in re.finditer(r'(?<=["\'])(\S+?\.pdf)(?=["\'])', html, re.IGNORECASE):
        url = _normalize(match.group(1))
        if url:
            links.add(url)

    print(f"  _extract_pdf_links: найдено {len(links)} PDF")
    return list(links)


def _download_pdf(url: str, save_dir: str = "./tmp_pdfs") -> str | None:
    """Скачивает PDF по URL, возвращает путь к временному файлу."""
    os.makedirs(save_dir, exist_ok=True)
    try:
        r = requests.get(url, timeout=15, verify=False,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        filename = os.path.join(save_dir, os.path.basename(url.split('?')[0]) or "doc.pdf")
        with open(filename, 'wb') as f:
            f.write(r.content)
        return filename
    except Exception as e:
        print(f"  PDF download error: {e}")
        return None


async def _extract_pdf_text(pdf_path: str, max_chars: int = 80000) -> str:
    """Извлекает текст из PDF через PyMuPDF (fitz)."""
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()[:max_chars]
    except Exception as e:
        print(f"  Ошибка чтения PDF {pdf_path}: {e}")
        return ""


# PDF-файлы которые точно не содержат нужных данных — фильтруем
_PDF_SKIP_KEYWORDS = [
    'polozheniye', 'politika', 'policy', 'privacy', 'personal',
    'obrabotka', 'персональн', 'soglasie', 'согласие', 'agreement',
    'cookie', 'licence', 'license', 'оферта', 'rekvizit', 'устав',
    'charter', 'reestr', 'реестр', 'lichenzia', 'лицензи', 'polit-',
    'reklam', 'реклам', 'oferta', 'anketa', 'zayavl',
]

def _is_relevant_pdf(url: str) -> bool:
    """Возвращает False если PDF явно нерелевантен (политики, соглашения и т.д.)."""
    name = url.lower().split('/')[-1].split('?')[0]
    return not any(kw in name for kw in _PDF_SKIP_KEYWORDS)


async def _collect_pdf_content(page_html: str, product_url: str,
                                max_pdfs: int = 5) -> tuple[str, list[str]]:
    """
    Ищет PDF-ссылки на странице, скачивает и читает каждый файл.
    Фильтрует нерелевантные PDF (политики, соглашения).
    Возвращает (объединённый текст, список URL найденных PDF).
    Всегда возвращает tuple — никогда не бросает исключение.
    """
    try:
        all_links = _extract_pdf_links(page_html, product_url)

        # Фильтруем мусорные PDF
        pdf_links = [u for u in all_links if _is_relevant_pdf(u)]
        skipped = len(all_links) - len(pdf_links)
        print(f"  PDF найдено: {len(all_links)}, после фильтра: {len(pdf_links)} (пропущено: {skipped})")

        pdf_texts = []
        pdf_urls_used = []

        for pdf_url in pdf_links[:max_pdfs]:
            try:
                pdf_file = _download_pdf(pdf_url)
                if not pdf_file:
                    continue
                text = await _extract_pdf_text(pdf_file)
                try:
                    os.remove(pdf_file)
                except:
                    pass
                if text:
                    pdf_urls_used.append(pdf_url)
                    pdf_texts.append(f"PDF ({os.path.basename(pdf_url.split('?')[0])}):\n{text}")
                    print(f"  ✅ PDF прочитан: {os.path.basename(pdf_url)} ({len(text)} символов)")
                else:
                    print(f"  ⚠️ PDF пустой: {os.path.basename(pdf_url)}")
            except Exception as e:
                print(f"  ⚠️ Ошибка PDF {pdf_url}: {e}")
                continue

        combined = "\n\n---\n\n".join(pdf_texts)
        return combined, pdf_urls_used

    except Exception as e:
        print(f"  !!! _collect_pdf_content критическая ошибка: {e}")
        return "", []




# Ключевые слова для поиска страниц с условиями программы
_CONDITIONS_KEYWORDS = [
    'about', 'conditions', 'rules', 'terms', 'program', 'loyalty',
    'о-программе', 'о_программе', 'usloviya', 'pravila', 'tarify',
    'условия', 'правила', 'тарифы', 'программа', 'участие',
    'nacislenie', 'начисление', 'bonusy', 'бонусы', 'info',
]

def _find_conditions_links(html: str, base_url: str, max_links: int = 3) -> list[str]:
    """Ищет ссылки на страницы с условиями программы лояльности."""
    from urllib.parse import urlparse, urljoin
    soup = BeautifulSoup(html, 'html.parser')
    base_domain = urlparse(base_url).netloc
    found = []
    seen = {base_url.rstrip('/')}

    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        text = a.get_text(strip=True).lower()

        # Проверяем текст ссылки и href на ключевые слова
        combined = (href + ' ' + text).lower()
        if not any(kw in combined for kw in _CONDITIONS_KEYWORDS):
            continue

        # Нормализуем URL
        if href.startswith('http'):
            full_url = href
        elif href.startswith('/'):
            parsed = urlparse(base_url)
            full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
        else:
            full_url = urljoin(base_url, href)

        # Только ссылки в пределах того же домена
        if urlparse(full_url).netloc != base_domain:
            continue

        clean = full_url.split('#')[0].rstrip('/')
        if clean not in seen:
            seen.add(clean)
            found.append(clean)

        if len(found) >= max_links:
            break

    print(f"  Найдено доп. страниц с условиями: {len(found)}: {found}")
    return found


async def _fetch_extra_pages(page_html: str, product_url: str) -> str:
    """
    Загружает дополнительные страницы с условиями программы и
    возвращает их объединённый очищенный текст.
    """
    extra_links = _find_conditions_links(page_html, product_url)
    if not extra_links:
        return ""

    extra_texts = []
    for url in extra_links:
        try:
            content = await asyncio.wait_for(get_page_content(url), timeout=30)
            if not content or len(content) < 300:
                continue
            soup = BeautifulSoup(content, 'html.parser')
            for tag in soup(['script', 'style', 'meta', 'link', 'svg',
                             'iframe', 'noscript', 'header', 'footer', 'nav']):
                tag.decompose()
            text = _dedup_text(soup.get_text(separator="\n", strip=True))[:30000]
            if text:
                extra_texts.append(f"--- Страница {url} ---\n{text}")
                print(f"  ✅ Доп. страница загружена: {url} ({len(text)} символов)")
        except asyncio.TimeoutError:
            print(f"  ⚠️ Таймаут доп. страницы: {url}")
        except Exception as e:
            print(f"  ⚠️ Ошибка доп. страницы {url}: {e}")

    return "\n\n".join(extra_texts)

def _dedup_text(text: str, min_len: int = 40) -> str:
    """Убирает дублированные строки (артефакт slick-слайдеров и клонированных блоков)."""
    seen = set()
    result = []
    for line in text.splitlines():
        stripped = line.strip()
        if len(stripped) < min_len:
            # Короткие строки пропускаем дедупликацию
            result.append(line)
            continue
        if stripped not in seen:
            seen.add(stripped)
            result.append(line)
    return "\n".join(result)

async def _parse_product_html(giga: GigaChat, product, chars, db, user_id: int, cleaned_html: str, pdf_content: str = "", pdf_urls: list = None, extra_text: str = "") -> tuple[int, int]:

    char_instructions = []
    for char in chars:
        char_instructions.append(
            f"- {char.name}: {char.description or 'найти значение'}"
        )
    
    pdf_section = f"""

ТЕКСТ ИЗ PDF:
ВАЖНО: если значения отсутствуют или неполные в HTML — ОБЯЗАТЕЛЬНО используй данные из PDF.

{pdf_content}""" if pdf_content else ""

    extra_section = f"""

ДОПОЛНИТЕЛЬНЫЕ СТРАНИЦЫ САЙТА (условия, правила, о программе):
{extra_text}""" if extra_text else ""

    fields_json = "{" + ", ".join(f'"{c.name}": null' for c in chars) + "}"

    prompt = f"""Ты парсер банковских данных. Извлеки КОНКРЕТНЫЕ значения для продукта "{product.name}" банка.

ПОЛЯ И ЧТО ИСКАТЬ:
{chr(10).join(char_instructions)}

ПРАВИЛА:
1. Ищи данные в <table>, <tr>, <td>, <ul>, <li>, <div class*="condition">, <span>, <p>, секциях "Условия", "Тарифы", "Как это работает"
2. Если данные разбиты на части — собери в одну строку
3. Конкретные цифры важнее общих фраз (пиши "до 10%" а не "повышенный кэшбэк")
4. Если поле реально не найдено — пиши null (не придумывай)
5. Ответ — СТРОГО только JSON, без пояснений и markdown

Шаблон ответа (замени null на найденные значения):
{fields_json}

HTML СТРАНИЦЫ:
{cleaned_html}{pdf_section}{extra_section}"""

    try:
        result = giga.chat(prompt)
        raw_response = result.choices[0].message.content
        
        usage = result.usage if hasattr(result, 'usage') else None
        tokens_input = 0
        tokens_output = 0
        if usage:
            tokens_input = getattr(usage, 'prompt_tokens', 0) or 0
            tokens_output = getattr(usage, 'completion_tokens', 0) or 0
        
        parsed_data = _parse_json_safely(raw_response)
        if not parsed_data:
            print(f"  !!! JSON парсинг не удался")
            return tokens_input, tokens_output
        
        has_data = any(v for v in parsed_data.values() if v and v != "null" and v is not None)
        if not has_data:
            print(f"  -! HTML парсинг: все поля null, передаём в текстовый fallback")
            # Возвращаем (0, 0) чтобы основной цикл запустил текстовый парсинг
            return 0, 0
        
        # Сохраняем в БД
        for char in chars:
            value = parsed_data.get(char.name) or "Не указано"
            if value == "null":
                value = "Не указано"
            
            data_record = Data(
                user_id=user_id,
                product_id=product.id,
                characteristic_id=char.id,
                card_set="Автопарсинг",
                value=str(value),
                pdf_urls="\n".join(pdf_urls) if pdf_urls else None
            )
            db.add(data_record)
        
        print(f"  ✅ Сохранено {len(chars)} характеристик")
        return tokens_input, tokens_output
        
    except Exception as e:
        print(f"  !!! Ошибка: {e}")
        return 0, 0


async def _parse_product_text(giga: GigaChat, product, chars, db, user_id: int, text_content: str, pdf_urls: list = None) -> tuple[int, int]:
    
    char_instructions = []
    for char in chars:
        char_instructions.append(
            f"- {char.name}: {char.description or 'найти значение'}"
        )
    
    fields_json = "{" + ", ".join(f'"{c.name}": null' for c in chars) + "}"

    prompt = f"""Ты парсер банковских данных. Извлеки КОНКРЕТНЫЕ значения для "{product.name}" из текста страницы.

ПОЛЯ И ЧТО ИСКАТЬ:
{chr(10).join(char_instructions)}

ПРАВИЛА:
1. Ищи секции "Условия", "Тарифы", "Как начислить", "Как потратить", таблицы с процентами
2. Конкретные цифры важнее общих фраз
3. Если поле реально не найдено — пиши null
4. Ответ — СТРОГО только JSON без пояснений

Шаблон ответа:
{fields_json}

ТЕКСТ:
{text_content}"""

    try:
        result = giga.chat(prompt)
        raw_response = result.choices[0].message.content
        
        usage = result.usage if hasattr(result, 'usage') else None
        tokens_input = 0
        tokens_output = 0
        if usage:
            tokens_input = getattr(usage, 'prompt_tokens', 0) or 0
            tokens_output = getattr(usage, 'completion_tokens', 0) or 0
        
        
        parsed_data = _parse_json_safely(raw_response)
        if not parsed_data:
            print(f"  !!! JSON парсинг не удался")
            return tokens_input, tokens_output
        
        has_data = any(v for v in parsed_data.values() if v and v != "null" and v is not None)
        if not has_data:
            print(f"  -! Текстовый парсинг: все поля null — сохраняем как 'Не найдено'")
        
        # Сохраняем в БД всегда — даже null, чтобы строка в Excel не была пустой
        for char in chars:
            raw = parsed_data.get(char.name)
            if not raw or raw == "null":
                value = "Не найдено"
            else:
                value = str(raw)
            
            data_record = Data(
                user_id=user_id,
                product_id=product.id,
                characteristic_id=char.id,
                card_set="Автопарсинг",
                value=value,
                pdf_urls="\n".join(pdf_urls) if pdf_urls else None
            )
            db.add(data_record)
        
        if has_data:
            print(f"  ✅ Сохранено {len(chars)} характеристик (текстовый парсинг)")
        return tokens_input, tokens_output
        
    except Exception as e:
        print(f"  !!! Ошибка: {e}")
        return 0, 0


def _parse_json_safely(raw_response: str) -> dict | None:
    if not raw_response:
        return None

    start_idx = raw_response.find('{')
    end_idx = raw_response.rfind('}')

    if start_idx == -1 or end_idx == -1:
        return None

    json_str = raw_response[start_idx:end_idx+1]
    json_str = json_str.replace('```json', '').replace('```', '').strip()

    try:
        return json.loads(json_str)
    except:
        try:
            json_str = json_str.replace("'", '"')
            return json.loads(json_str)
        except:
            try:
                json_str = re.sub(r'\\n', ' ', json_str)
                json_str = re.sub(r'\n', ' ', json_str)
                return json.loads(json_str)
            except:
                return None