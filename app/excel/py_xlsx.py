#app/excel/py_xlsx.py
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.model import Data, Product, Characteristic, Bank


RUSSIAN_CHAR_NAMES = {
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


def _get_russian_char_name(char_name: str) -> str:
    if char_name in RUSSIAN_CHAR_NAMES:
        return RUSSIAN_CHAR_NAMES[char_name]
    
    return char_name


def create_bank_excel_report(
    db: Session,
    user_id: int,
    product_ids: List[int],
    char_ids: List[int],
    output_dir: str = "./reports/"
) -> str:

    
    try:

        data_records = db.query(Data).filter(
            Data.user_id == user_id,
            Data.product_id.in_(product_ids)
        ).all()
        
        print(f"📊 Найдено {len(data_records)} записей в БД")
        
        if not data_records:
            print("⚠️ Нет данных для создания отчета")
            return None
        
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        chars = db.query(Characteristic).filter(Characteristic.id.in_(char_ids)).all()
        banks = db.query(Bank).all()
        
        print(f"📋 Характеристик: {len(chars)}, Продуктов: {len(products)}")
        
        # Словари для быстрого доступа
        product_map = {p.id: p for p in products}
        char_map = {c.id: c for c in chars}
        bank_map = {b.id: b for b in banks}
        
        structured_data = {}
        for record in data_records:
            if record.product_id not in structured_data:
                structured_data[record.product_id] = {}
            structured_data[record.product_id][record.characteristic_id] = record.value
        
        table_data = []
        
        for char in chars:
            char_display_name = _get_russian_char_name(char.name)
            
            row = {
                "Характеристика": char_display_name  # ← На русском!
            }
            
            # Добавляем значения для каждого продукта
            for product in products:
                value = structured_data.get(product.id, {}).get(char.id, "—")
                
                # Название колонки: "Банк - Продукт"
                bank_name = bank_map.get(product.bank_id, None)
                bank_name = bank_name.name if bank_name else "Unknown"
                col_name = f"{bank_name}\n{product.name}"
                
                row[col_name] = value
            
            table_data.append(row)
        
        # Создаем DataFrame
        df = pd.DataFrame(table_data)
        
        # Генерируем имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Парсинг_Карт_{timestamp}.xlsx"
        
        # Создаем директорию если её нет
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        filepath = output_path / filename
        
        # Сохраняем в Excel с форматированием
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Сравнение', index=False)
            
            worksheet = writer.sheets['Сравнение']
            
            # Заголовки жирным и синим фоном
            header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            header_font = Font(bold=True, color="FFFFFF", size=11)
            
            for col in range(1, len(df.columns) + 1):
                cell = worksheet.cell(row=1, column=col)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(wrap_text=True, vertical='center', horizontal='center')
            
            # Форматирование данных
            for row in worksheet.iter_rows(min_row=2):
                for idx, cell in enumerate(row):
                    cell.alignment = Alignment(wrap_text=True, vertical='top', horizontal='left')
                    
                    # Чередуем цвета строк
                    if cell.row % 2 == 0:
                        cell.fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
                    
                    # Выделяем пустые ячейки
                    if cell.value is None or cell.value == "—":
                        cell.fill = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
            
            # Автоматическая ширина колонок
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                
                for cell in column:
                    try:
                        cell_length = len(str(cell.value or ""))
                        if cell_length > max_length:
                            max_length = cell_length
                    except:
                        pass
                
                # Минимум 15, максимум 50
                adjusted_width = min(max(max_length + 2, 15), 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
            
            # Высота строк для многострочного текста
            for row in worksheet.iter_rows():
                worksheet.row_dimensions[row[0].row].height = 30
            
        
        print(f"✅ Excel создан: {filepath}")
        print(f"✅ Характеристики на русском: {', '.join([_get_russian_char_name(c.name) for c in chars[:3]])}...")
        return str(filepath)
        
    except Exception as e:
        print(f"!!! Ошибка при создании Excel: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_field_display_name(field: str) -> str:
    return RUSSIAN_CHAR_NAMES.get(field, field)


def create_comparison_table(results: List[Dict[str, Any]]) -> pd.DataFrame:
    banks = {}
    for result in results:
        bank = result.get("bank", "Unknown")
        banks[bank] = result
    
    # Все возможные поля
    all_fields = set()
    for data in banks.values():
        all_fields.update(data.keys())
    all_fields.discard("bank")
    
    field_list = sorted(list(all_fields))
    
    data = []
    for field in field_list:
        row = [get_field_display_name(field)]
        for bank_name in sorted(banks.keys()):
            value = banks[bank_name].get(field, "")
            row.append(value)
        data.append(row)
    
    return pd.DataFrame(data, columns=["Характеристика"] + sorted(banks.keys()))