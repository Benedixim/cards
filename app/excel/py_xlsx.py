import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
from openpyxl.styles import Alignment
from datetime import datetime

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

FIELD_ORDER = list(FIELD_NAMES.keys())

def create_bank_excel_report(
    results: List[Dict[str, Any]], 
    output_dir: str = "./",
    selected_characteristics: Optional[List[str]] = None
) -> str:

    # Если характеристики не указаны, используем все
    if not selected_characteristics:
        field_order = FIELD_ORDER
    else:
        # Используем только выбранные, в порядке FIELD_ORDER
        field_order = [f for f in FIELD_ORDER if f in selected_characteristics]

    banks_order = ["Сбер"]
    bank_data = {}
    
    for result in results:
        bank = result.get("bank", "Unknown")
        if bank not in bank_data:
            bank_data[bank] = result
            if bank != "Сбер":
                banks_order.append(bank)
    

    num_banks = len(banks_order)
    print(f"Создаем таблицу для {num_banks} банков: {banks_order}")
    print(f"Характеристики: {field_order}")
    

    data_rows = []
    for field in field_order:
        row = [FIELD_NAMES[field]]  
        for bank in banks_order:
            bank_info = bank_data.get(bank, {})
            value = bank_info.get(field)
            row.append(value)
        data_rows.append(row)

    df = pd.DataFrame(data_rows, columns=["Параметр"] + banks_order)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ТГ_Бенчмаркинг_{timestamp}.xlsx"
    filepath = Path(output_dir) / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Карты банков', index=False)
        
        worksheet = writer.sheets['Карты банков']
        for row in worksheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value or "")) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    return str(filepath)


def get_field_name(field: str) -> str:
    return FIELD_NAMES.get(field, field)