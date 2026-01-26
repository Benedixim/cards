from aiogram import Router, F
import asyncio
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
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

from aiogram.fsm.context import FSMContext

from app.keyboards.start_keyboard import get_multi_keyboard, ITEMS, get_info_keyboard
from app.state import BankState
from app.excel.py_xlsx import create_bank_excel_report
from app.db.model import SessionLocal, User, Log, Data, Bank, migrate_banks, init_db
from config import GIGACHAT_TOKEN

router = Router()


@router.message(Command("start"))
async def start_multi(message: Message, state: FSMContext):
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_id=message.from_user.id).first()
        if not user:
            user = User(tg_id=message.from_user.id)
            db.add(user)
            db.commit()
    finally:
        db.close()
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Выберите банки или используйте кнопки ниже:",
        reply_markup=get_info_keyboard()
    )
    await state.set_state(BankState.waiting_selection)
    await show_bank_keyboard(message, state)

@router.message(F.text == "📊 Получить информацию")
async def start_multi(message: Message, state: FSMContext):
    await state.set_state(BankState.waiting_selection)
    await show_bank_keyboard(message, state)

@router.message(Command("actv"))
async def start_multi(message: Message, state: FSMContext):
    init_db()
    migrate_banks()
    await message.answer("db migrate and active")

async def show_bank_keyboard(message_or_cb: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected_banks", []))

    builder = get_multi_keyboard(ITEMS, selected)
    text = f"Выберите банки для парсинга\nВыбрано: {len(selected)}/{len(ITEMS)}"

    if isinstance(message_or_cb, Message):
        await message_or_cb.answer(text, reply_markup=builder.as_markup())
    else:
        await message_or_cb.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("toggle_bank_"), BankState.waiting_selection)
async def toggle_bank(callback: CallbackQuery, state: FSMContext):
    bank = callback.data.split("_", 2)[2]
    data = await state.get_data()
    selected = set(data.get("selected_banks", []))

    if bank in selected:
        selected.remove(bank)
    else:
        selected.add(bank)

    await state.update_data(selected_banks=list(selected))
    await show_bank_keyboard(callback, state)
    await callback.answer()



session = requests.Session()
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com/",
}

HTML_MIN_SIZE = 500
CLEANED_MIN_SIZE = 300
TEXT_MAX = 70000
HTML_MAX = 40_000





@router.callback_query(F.data == "parse_selected", BankState.waiting_selection)
async def parse_selected_banks(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    db = SessionLocal()
    

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
    selected_banks = data.get("selected_banks", [])
    
    all_banks = ["Сбер"] + [b for b in selected_banks if b != "Сбер"]
    
    giga = GigaChat(
        credentials=GIGACHAT_TOKEN,
        scope="GIGACHAT_API_B2B",
        verify_ssl_certs=False, 
        model="GigaChat-2-Max"
    )
    
    await callback.message.edit_text(f"Парсинг банков: {', '.join(all_banks)}")
    results = []
    
    total = len(all_banks)
    
    for i, bank_name in enumerate(all_banks, 1):
        progress = int(i / total * 10)
        bar = "█" * progress + "░" * (10 - progress)

        try:
            await callback.message.edit_text(
                f"Начать сбор информации\n\n"
                f"Банк: {bank_name} ({i}/{total})\n[{bar}]"
                )
            
            config = db.query(Bank).filter_by(name=bank_name).first()
            if not config:
                print(f"-! Банк {bank_name} не найден в БД")
                results.append(_empty_schema(bank_name))
                continue

            url = config.url
        
            try:
                # для ВТБ и остальных — с браузерными заголовками
                response = requests.get(
                    url,
                    timeout=10,
                    verify=False,         
                    headers=BROWSER_HEADERS
                )
            except requests.exceptions.SSLError:
                print(f"-! {bank_name}: SSL ошибка, повторная попытка без проверки...")
                response = requests.get(
                    url,
                    timeout=10,
                    verify=False,
                    headers=BROWSER_HEADERS
                )
            
            response.encoding = 'utf-8'
            page_content = response.text
            
            print(f"- {bank_name}: статус {response.status_code}, размер HTML {len(page_content)} символов")
            
            if bank_name == "ВТБ" and len(page_content) < 500:
                print(f"-! ВТБ: HTML слишком мал, вероятно защита/редирект. Скип.")
                results.append(_empty_schema(bank_name))
                continue
            
            # Если HTML слишком мал — может быть редирект или ошибка
            if len(page_content) < 500:
                print(f"-! {bank_name}: Загруженный HTML очень мал. Проверьте URL: {config.get('url')}")
                print(f"   Status: {response.status_code}, Content-Type: {response.headers.get('content-type')}")
                results.append(_empty_schema(bank_name))
                continue
            
            # Парсим и чистим
            soup = BeautifulSoup(page_content, 'html.parser')
            
            # Удаление мусора
            for tag in soup(['script', 'style', 'meta', 'link', 'svg', 'iframe', 'noscript']):
                tag.decompose()
            
            # Берем чистый HTML как строку - увеличиваем лимит для больших сайтов
            cleaned_html = str(soup)
            if len(cleaned_html) > 120000:
                cleaned_html = cleaned_html[:120000]
            
            print(f"{bank_name}: размер очищенного HTML {len(cleaned_html)} символов")
            
            if len(cleaned_html) < 300:
                print(f"-! {bank_name}: После очистки HTML слишком мал ({len(cleaned_html)} символов)")
                results.append(_empty_schema(bank_name))
                continue
            
            cleaned_content = cleaned_html
            
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
{cleaned_content}"""
            
            result = giga.chat(prompt)
            raw_response = result.choices[0].message.content
            
            print(f"\n🔍 {bank_name} RAW: {repr(raw_response[:150])}")
            
            # 3️⃣ ПАРСИМ JSON С ОБРАБОТКОЙ ОШИБОК
            parsed_data = _parse_json_safely(raw_response)
            if not parsed_data:
                print(f"!!! {bank_name}: Не удалось распарсить JSON")
                print(f"  -> RAW: {raw_response[:200]}")
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
            
        except requests.exceptions.RequestException as e:
            print(f"{bank_name}: Ошибка загрузки {str(e)}")
            results.append(_empty_schema(bank_name))
        except Exception as e:
            print(f"{bank_name}: {type(e).__name__}: {str(e)}")
            results.append(_empty_schema(bank_name))

    try:
        characteristics = (
            "type,currency,validity,maintenance_cost,"
            "free_conditions,sms_notification,atm_limit_own,"
            "atm_limit_other,loyalty_program,interest_rate,additional"
        )
        
        data_row = Data(
            user_id=user_id,
            characteristics=characteristics,
            card_set=",".join(all_banks),
            payload=results,
        )
        db.add(data_row)
        db.commit()
        
        # Excel 
        excel_path = await asyncio.to_thread(
            create_bank_excel_report, 
            results, 
            "./reports/"
        )
        
        file = FSInputFile(excel_path)
        await callback.message.answer_document(
            file,
            caption=f"Парсинг завершен!\nСбер — первый столбец\nБанки: {', '.join(all_banks)}"
        )
        os.unlink(excel_path)
        await callback.message.edit_text("📁 Excel файл отправлен!")
        
        log.status = "ok"
        db.commit()
        
    except Exception as e:
        log.status = "error"
        log.message = str(e)
        db.commit()
        await callback.message.edit_text(f"Ошибка создания Excel: {str(e)}")
    
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
        
        # попытка исправить невалидный JSON
        try:
            # delete перевод строк внутри строк
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