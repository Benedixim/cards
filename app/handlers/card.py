from aiogram import Router, F
import asyncio
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import FSInputFile
from datetime import datetime
import json
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import re
import os
from gigachat import GigaChat
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from aiogram.fsm.context import FSMContext

from app.keyboards.start_keyboard import get_multi_keyboard, ITEMS, get_info_keyboard, get_sets_keyboard
from app.state import BankState
from app.excel.py_xlsx import create_bank_excel_report
from app.db.model import (SessionLocal, User, Log, Data, Bank, Set, Product, Characteristic, migrate_products, init_db)
from config import GIGACHAT_TOKEN

router = Router()


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


async def get_page_content_playwright(url: str, timeout: int = 30000) -> str | None:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--start-maximized',
                ]
            )
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until='networkidle', timeout=timeout)
                content = await page.content()
                await browser.close()
                return content
            except Exception as e:
                print(f"Playwright ошибка для {url}: {e}")
                await browser.close()
                return None
    except Exception as e:
        print(f"Критическая ошибка Playwright: {e}")
        return None


async def get_page_content(url: str) -> str | None:

    try:
        response = requests.get(
            url,
            timeout=10,
            verify=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        
        if response.status_code == 200 and len(response.text) > 500:
            print(f"{url}: загружено через requests")
            return response.text
    except Exception as e:
        print(f"-! requests не сработал для {url}: {type(e).__name__}")
    

    print(f"- Пробуем Playwright для {url}...")
    content = await get_page_content_playwright(url)
    
    if content and len(content) > 500:
        print(f"{url}: загружено через Playwright")
        return content
    
    print(f"-!!! Не удалось загрузить {url}")
    return None


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Выберите **набор карт**:",
        parse_mode="Markdown",
        reply_markup=get_sets_keyboard()
    )
    await message.answer('кнопка "📊 Собрать информацию" добавлена')


@router.message(Command("actv"))
async def start_multi(message: Message, state: FSMContext):
    init_db()
    migrate_products()
    print("✅ Полная миграция завершена!")


@router.message(F.text == "📊 Собрать информацию")
async def click_button_start(message: Message, state: FSMContext):
    await message.answer( 
        "Выберите **набор карт**:",
        parse_mode="Markdown",
        reply_markup=get_sets_keyboard())


async def show_products_keyboard(callback: CallbackQuery, state: FSMContext, set_id: int):
    """Отображение продуктов с мультивыбором"""
    data = await state.get_data()
    selected_products = set(data.get("selected_products", []))
    
    db = SessionLocal()
    try:
        products = db.query(Product).filter_by(set_id=set_id).all()
        set_obj = db.query(Set).filter_by(id=set_id).first()
        
        keyboard = []
        for product in products:
            is_selected = product.id in selected_products
            emoji = "✅" if is_selected else ""
            keyboard.append([InlineKeyboardButton(
                text=f"{emoji} {product.name}",
                callback_data=f"toggle_product_{product.id}"
            )])
        
        # Кнопки навигации
        keyboard.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_set"),
            InlineKeyboardButton(text="➡️ Далее", callback_data="show_characteristics")
        ])
        
        set_name = set_obj.name if set_obj else "Набор"
        text = f"📦 **{set_name}**\n\nВыберите продукты\nВыбрано: {len(selected_products)}/{len(products)}"
        
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    finally:
        db.close()
    
    await callback.answer()


async def show_characteristics_keyboard(callback: CallbackQuery, state: FSMContext):
    """Отображение характеристик с мультивыбором"""
    data = await state.get_data()
    selected_chars = set(data.get("selected_characteristics", []))
    
    db = SessionLocal()
    try:
        chars = db.query(Characteristic).all()
        
        keyboard = []
        for char in chars:
            is_selected = char.id in selected_chars
            emoji = "✅" if is_selected else ""
            display_name = FIELD_NAMES.get(char.name, char.name)
            keyboard.append([InlineKeyboardButton(
                text=f"{emoji} {display_name}",
                callback_data=f"toggle_char_{char.id}"
            )])
        
        # Кнопки навигации
        keyboard.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_products"),
            InlineKeyboardButton(text="➡️ Далее", callback_data="confirm_selection")
        ])
        
        text = f"Выберите характеристики\nВыбрано: {len(selected_chars)}/{len(chars)}"
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
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
        # Получаем имена продуктов
        product_objects = db.query(Product).filter(Product.id.in_(selected_products)).all()
        product_names = [p.name for p in product_objects]
        
        # Получаем имена характеристик
        char_objects = db.query(Characteristic).filter(Characteristic.id.in_(selected_chars)).all()
        char_names = [c.name for c in char_objects]
        display_char_names = [FIELD_NAMES.get(name, name) for name in char_names]
        
        # Получаем уникальные банки
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


@router.callback_query(F.data == "set_standard")
async def show_standard_products(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        set_obj = db.query(Set).filter_by(name="Стандарт").first()
        if set_obj:
            await state.update_data(selected_set_id=set_obj.id)
            await state.set_state(BankState.waiting_products)
            await show_products_keyboard(callback, state, set_obj.id)
        else:
            await callback.answer("❌ Набор 'Стандарт' не найден")
    finally:
        db.close()


@router.callback_query(F.data == "set_premium")
async def show_premium_products(callback: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        set_obj = db.query(Set).filter_by(name="Премиум").first()
        if set_obj:
            await state.update_data(selected_set_id=set_obj.id)
            await state.set_state(BankState.waiting_products)
            await show_products_keyboard(callback, state, set_obj.id)
        else:
            await callback.answer("❌ Набор 'Премиум' не найден")
    finally:
        db.close()


@router.callback_query(F.data.startswith("toggle_product_"), BankState.waiting_products)
async def toggle_product(callback: CallbackQuery, state: FSMContext):
    """Переключение выбора продукта"""
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


@router.callback_query(F.data == "back_to_set", BankState.waiting_products)
async def back_to_set(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору набора"""
    await state.update_data(selected_products=[])
    await callback.message.edit_text(
        "👋 Выберите **набор карт**:",
        parse_mode="Markdown",
        reply_markup=get_sets_keyboard()
    )
    await state.set_state(BankState.waiting_set_selection)
    await callback.answer()


@router.callback_query(F.data == "show_characteristics", BankState.waiting_products)
async def show_characteristics(callback: CallbackQuery, state: FSMContext):
    """Переход к выбору характеристик"""
    data = await state.get_data()
    if not data.get("selected_products"):
        await callback.answer("❌ Выберите хотя бы один продукт!", show_alert=True)
        return
    
    await state.set_state(BankState.waiting_characteristics)
    await show_characteristics_keyboard(callback, state)


@router.callback_query(F.data.startswith("toggle_char_"), BankState.waiting_characteristics)
async def toggle_characteristic(callback: CallbackQuery, state: FSMContext):
    """Переключение выбора характеристики"""
    char_id = int(callback.data.split("_", 2)[2])
    data = await state.get_data()
    selected_chars = set(data.get("selected_characteristics", []))
    
    if char_id in selected_chars:
        selected_chars.remove(char_id)
    else:
        selected_chars.add(char_id)
    
    await state.update_data(selected_characteristics=list(selected_chars))
    await show_characteristics_keyboard(callback, state)


@router.callback_query(F.data == "back_to_products", BankState.waiting_characteristics)
async def back_to_products(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору продуктов"""
    data = await state.get_data()
    set_id = data.get("selected_set_id")
    await state.set_state(BankState.waiting_products)
    await show_products_keyboard(callback, state, set_id)


@router.callback_query(F.data == "confirm_selection", BankState.waiting_characteristics)
async def confirm_selection(callback: CallbackQuery, state: FSMContext):
    """Показывает подтверждение перед парсингом"""
    data = await state.get_data()
    
    if not data.get("selected_characteristics"):
        await callback.answer("❌ Выберите хотя бы одну характеристику!", show_alert=True)
        return
    
    await show_confirmation(callback, state)
    await callback.answer()


@router.callback_query(F.data == "back_to_characteristics")
async def back_to_characteristics(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору характеристик из подтверждения"""
    await state.set_state(BankState.waiting_characteristics)
    await show_characteristics_keyboard(callback, state)


@router.callback_query(F.data == "start_parsing")
async def parse_selected_banks(callback: CallbackQuery, state: FSMContext):
    """Запуск парсинга"""
    user_id = callback.from_user.id
    db = SessionLocal()

    try:
        log = Log(
            user_id=user_id,
            action="parse",
            status="new",
            created_at=datetime.utcnow(),
        )
        db.add(log)
        db.commit()

        log.status = "process"
        db.commit()

        data = await state.get_data()
        selected_products = data.get("selected_products", [])
        selected_chars = data.get("selected_characteristics", [])

        # Получаем данные из БД
        selected_char_names = []
        selected_product_data = []
        
        if selected_chars:
            char_objects = db.query(Characteristic).filter(
                Characteristic.id.in_(selected_chars)
            ).all()
            selected_char_names = [c.name for c in char_objects]
            print(f"DEBUG: Выбранные характеристики: {selected_char_names}")
        
        if selected_products:
            selected_product_data = db.query(Product).filter(
                Product.id.in_(selected_products)
            ).all()
            selected_product_names = [p.name for p in selected_product_data]
        else:
            await callback.message.edit_text("❌ Выберите хотя бы один продукт")
            db.close()
            return

        # Получаем уникальные банки из выбранных продуктов
        bank_ids = set(p.bank_id for p in selected_product_data)
        banks = db.query(Bank).filter(Bank.id.in_(bank_ids)).all()
        all_banks = [b.name for b in banks]
        
        if not all_banks:
            await callback.message.edit_text("❌ Не найдены банки для выбранных продуктов")
            db.close()
            return

        giga = GigaChat(
            credentials=GIGACHAT_TOKEN,
            scope="GIGACHAT_API_B2B",
            verify_ssl_certs=False,
            model="GigaChat-2-Max"
        )

        # Преобразуем имена характеристик для вывода
        display_char_names = [FIELD_NAMES.get(name, name) for name in selected_char_names]

        await callback.message.edit_text(
            f"🔄 Запуск парсинга...\n\n"
            f"Продукты: {', '.join(selected_product_names)}\n"
            f"Характеристики: {', '.join(display_char_names) if display_char_names else 'Все'}\n"
            f"Банки: {', '.join(all_banks)}"
        )
        results = []

        total = len(all_banks)

        for i, bank_name in enumerate(all_banks, 1):
            progress = int(i / total * 10)
            bar = "█" * progress + "░" * (10 - progress)

            try:
                await callback.message.edit_text(
                    f"Запуск сбора информации\n\n"
                    f"Банк: {bank_name} ({i}/{total})\n[{bar}]"
                )

                config = db.query(Bank).filter_by(name=bank_name).first()
                if not config:
                    print(f"-! Банк {bank_name} не найден в БД")
                    results.append(_empty_schema(bank_name))
                    continue

                url = config.url

                # Загружаем контент с fallback на Playwright
                page_content = await get_page_content(url)
                
                if not page_content or len(page_content) < 500:
                    print(f"-! {bank_name}: не удалось загрузить страницу")
                    results.append(_empty_schema(bank_name))
                    continue

                print(f"- {bank_name}: размер HTML {len(page_content)} символов")

                soup = BeautifulSoup(page_content, 'html.parser')

                for tag in soup(['script', 'style', 'meta', 'link', 'svg', 'iframe', 'noscript']):
                    tag.decompose()

                cleaned_html = str(soup)
                if len(cleaned_html) > 120000:
                    cleaned_html = cleaned_html[:120000]

                if len(cleaned_html) < 300:
                    print(f"-! {bank_name}: После очистки HTML слишком мал ({len(cleaned_html)} символов)")
                    results.append(_empty_schema(bank_name))
                    continue

                prompt = f"""Извлеки данные по карте "{bank_name}" из HTML. ВСЕ поля искать везде - в таблицах, списках, divs, spans.

ИНСТРУКЦИИ:
1. Ищи в <table>, <tr>, <td>, <ul>, <li>, <div>, <span>, <p> - везде
2. Комбинируй информацию если она разделена на части
3. Если значение не найдено - напиши null (только null, не "не найдено")
4. Ответ - ТОЛЬКО JSON в одну строку

ПОЛЯ (примеры в скобках):
- type: "Mastercard", "Виза", "Мир", "Белкарта" (ищи в заголовках, названиях)
- currency: "BYN", "USD", "EUR" (ищи "Валюта счета", "currency")
- validity: "3 года", "4 года", "5 лет" (ищи "Срок", "действия")
- maintenance_cost: "3 BYN", "бесплатно", "29 BYN" (ищи "обслуживание", "плата", "вознаграждение")
- free_conditions: "если операции > 600 BYN в месяц", "при выполнении условий" (ищи "условиях", "если")
- sms_notification: "4.5 BYN", "бесплатно" (ищи "SMS", "информирование", "оповещение")
- atm_limit_own: "без ограничений", "1000 BYN" (ищи "банкоматы", "свои", "собственные")
- atm_limit_other: "3.5%", "500 BYN" (ищи "иные банки", "комиссия", "других")
- loyalty_program: "0.75%", "мани-бэк 3%", "бонусная программа" (ищи "%", "бонус", "кэшбэк")
- interest_rate: "0.01%", "3%", "проценты" (ищи "% годовых", "на остаток", "ставка")
- additional: минимальный остаток, условия открытия, льготы, особенности (важное)

ВЫВОД - JSON в одну строку:
{{"type":"...","currency":"...","validity":"...","maintenance_cost":"...","free_conditions":"...","sms_notification":"...","atm_limit_own":"...","atm_limit_other":"...","loyalty_program":"...","interest_rate":"...","additional":"..."}}

HTML:
{cleaned_html}"""

                result = giga.chat(prompt)
                raw_response = result.choices[0].message.content

                print(f"\n🔍 {bank_name} RAW: {repr(raw_response[:150])}")

                parsed_data = _parse_json_safely(raw_response)
                if not parsed_data:
                    print(f"!!! {bank_name}: Не удалось распарсить JSON")
                    results.append(_empty_schema(bank_name))
                    continue

                has_data = any(v for v in parsed_data.values() if v and v != "null")
                if not has_data:
                    print(f"!!!!!{bank_name}: JSON распарсен но все поля null/пусто")
                    print(f"  >>> Пробуем текстовый парсинг HTML...")

                    text_content = soup.get_text(separator=" ", strip=True)[:70000]

                    prompt_fallback = f"""Извлеки данные карты "{bank_name}" из текста ниже. Очень важно найти ВСЕ значения.

{prompt.split('HTML:')[0]}

ТЕКСТ:
{text_content}"""

                    try:
                        result_fallback = giga.chat(prompt_fallback)
                        raw_response_fallback = result_fallback.choices[0].message.content
                        parsed_data = _parse_json_safely(raw_response_fallback)

                        if parsed_data and any(v for v in parsed_data.values() if v and v != "null"):
                            print(f"Текстовый парсинг сработал!")
                        else:
                            print(f"Даже текстовый парсинг не помог")
                            results.append(_empty_schema(bank_name))
                            continue
                    except Exception as e:
                        print(f"Ошибка fallback: {str(e)}")
                        results.append(_empty_schema(bank_name))
                        continue

                parsed_data["bank"] = bank_name
                print(f"{bank_name}: type={parsed_data.get('type')}")
                results.append(parsed_data)

                await asyncio.sleep(1.0)

            except Exception as e:
                print(f"{bank_name}: Ошибка {str(e)}")
                results.append(_empty_schema(bank_name))

        try:
            # Сохраняем выбранные характеристики
            if selected_char_names:
                characteristics = ",".join(selected_char_names)
            else:
                characteristics = (
                    "type,currency,validity,maintenance_cost,"
                    "free_conditions,sms_notification,atm_limit_own,"
                    "atm_limit_other,loyalty_program,interest_rate,additional"
                )

            data_row = Data(
                user_id=user_id,
                characteristics=characteristics,
                card_set=",".join(selected_product_names),
                payload=results,
            )
            db.add(data_row)
            db.commit()

            excel_path = await asyncio.to_thread(
                create_bank_excel_report,
                results,
                "./reports/",
                selected_char_names if selected_char_names else None
            )

            file = FSInputFile(excel_path)
            await callback.message.answer_document(
                file,
                caption=f"✅ Парсинг завершен!\n\n"
                       f"Продукты: {', '.join(selected_product_names)}\n"
                       f"Банки: {', '.join(all_banks)}"
            )
            os.unlink(excel_path)
            await callback.message.edit_text("📁 Excel файл отправлен!")

            log.status = "ok"
            db.commit()

        except Exception as e:
            log.status = "error"
            log.message = str(e)
            db.commit()
            await callback.message.edit_text(f"❌ Ошибка создания Excel: {str(e)}")

    except Exception as e:
        print(f"Критическая ошибка: {e}")
        await callback.message.edit_text(f"❌ Критическая ошибка: {str(e)}")
    finally:
        db.close()
        await state.clear()


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


def _empty_schema(bank_name: str) -> dict:
    return {
        "type": None,
        "currency": None,
        "validity": None,
        "maintenance_cost": None,
        "free_conditions": None,
        "sms_notification": None,
        "atm_limit_own": None,
        "atm_limit_other": None,
        "loyalty_program": None,
        "interest_rate": None,
        "additional": None,
        "bank": bank_name
    }