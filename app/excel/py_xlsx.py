#app/excel/py_xlsx.py 

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
import pandas as pd
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.model import Data, Product, Characteristic, Bank


RUSSIAN_CHAR_NAMES = {
    "payment system": "Платежная система",
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
    product_ids: list[int],
    char_ids: list[int],
    output_dir: str = "./reports/"
) -> str:
    
    try:
        # Получаем данные
        data_records = db.query(Data).filter(
            Data.user_id == user_id,
            Data.product_id.in_(product_ids)
        ).all()
        
        print(f"Найдено {len(data_records)} записей в БД")
        
        if not data_records:
            print("Нет данных для создания отчета")
            return None
        
        # Получаем метаданные
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        chars = db.query(Characteristic).filter(Characteristic.id.in_(char_ids)).all()
        banks = db.query(Bank).all()
        
        print(f"Характеристик: {len(chars)}, Продуктов: {len(products)}")
        
        bank_map = {b.id: b for b in banks}
        
        # Структурируем основные данные
        structured_data = {}
        for record in data_records:
            if record.product_id not in structured_data:
                structured_data[record.product_id] = {}
            structured_data[record.product_id][record.characteristic_id] = record.value

        # Собираем PDF-ссылки из поля pdf_urls в записях Data
        pdf_by_product = {}
        for record in data_records:
            if record.pdf_urls and record.product_id not in pdf_by_product:
                urls = [u.strip() for u in record.pdf_urls.split("\n") if u.strip()]
                if urls:
                    pdf_by_product[record.product_id] = urls
        
        has_pdf = any(pdf_by_product.values())
        print(f"PDF найдено для {len(pdf_by_product)} продуктов")

        # Строим таблицу характеристик
        table_data = []
        product_urls = {}

        for char in chars:
            char_display_name = _get_russian_char_name(char.name)
            row = {"Характеристика": char_display_name}
            
            for product in products:
                value = structured_data.get(product.id, {}).get(char.id, "—")
                bank_name = bank_map.get(product.bank_id)
                bank_name = bank_name.name if bank_name else "Unknown"
                col_name = f"{bank_name}\n{product.name}"
                row[col_name] = value
                
                if product.id not in product_urls:
                    product_urls[product.id] = {
                        "url": product.url,
                        "name": product.name,
                        "bank": bank_name,
                        "col_name": col_name,
                    }
            
            table_data.append(row)

        # Создаём DataFrame
        df = pd.DataFrame(table_data)
        
        # Генерируем имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Парсинг_Карт_{timestamp}.xlsx"
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        filepath = output_path / filename

        # ─── Стили ───────────────────────────────────────────────────────────
        BLUE_FILL   = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        LBLUE_FILL  = PatternFill(start_color="E7F0FF", end_color="E7F0FF", fill_type="solid")
        LGRAY_FILL  = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
        RED_FILL    = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
        GREEN_FILL  = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")

        WHITE_BOLD  = Font(bold=True, color="FFFFFF", size=11)
        LINK_FONT   = Font(color="0563C1", underline="single", size=10, bold=True)
        LABEL_FONT  = Font(bold=True, size=10, color="0563C1")
        PDF_HEADER_FONT = Font(bold=True, size=10, color="1A5276")

        CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")
        TOP_LEFT = Alignment(wrap_text=True, vertical="top", horizontal="left")

        PDF_ROW    = 3 if has_pdf else None
        DATA_START = 4 if has_pdf else 3

        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(
                writer,
                sheet_name='Сравнение',
                index=False,
                startrow=DATA_START - 1,
                header=False,
            )
            ws = writer.sheets['Сравнение']

            # ──Шапка ──────────────────────────────────────────────
            for col in range(1, len(df.columns) + 1):
                cell = ws.cell(row=1, column=col)
                cell.value = df.columns[col - 1]
                cell.fill = BLUE_FILL
                cell.font = WHITE_BOLD
                cell.alignment = CENTER

            # ──Ссылки на страницы продуктов ───────────────────────
            ws.cell(row=2, column=1).value = "🔗 Страница продукта"
            ws.cell(row=2, column=1).font = LABEL_FONT
            ws.cell(row=2, column=1).alignment = CENTER
            ws.cell(row=2, column=1).fill = LBLUE_FILL

            for col_idx, product in enumerate(products, 1):
                info = product_urls.get(product.id, {})
                cell = ws.cell(row=2, column=col_idx + 1)
                cell.alignment = CENTER
                cell.fill = LBLUE_FILL
                if info.get("url"):
                    cell.hyperlink = info["url"]
                    cell.value = f"🔗 {info['bank']}\n{info['name']}"
                    cell.font = LINK_FONT
                else:
                    cell.value = f"{info.get('bank', '')}\n{info.get('name', '')}"
                    cell.font = Font(bold=True, size=10)

            # ── PDF-файлы ────────────────────────────
            if has_pdf and PDF_ROW:
                ws.cell(row=PDF_ROW, column=1).value = "📄 PDF документы"
                ws.cell(row=PDF_ROW, column=1).font = PDF_HEADER_FONT
                ws.cell(row=PDF_ROW, column=1).alignment = CENTER
                ws.cell(row=PDF_ROW, column=1).fill = GREEN_FILL

                for col_idx, product in enumerate(products, 1):
                    urls = pdf_by_product.get(product.id, [])
                    cell = ws.cell(row=PDF_ROW, column=col_idx + 1)
                    cell.fill = GREEN_FILL
                    cell.alignment = TOP_LEFT

                    if urls:
                        if len(urls) == 1:
                            # Одна ссылка — делаем гиперссылку прямо на ячейку
                            cell.hyperlink = urls[0]
                            cell.value = f"📄 {_pdf_short_name(urls[0])}"
                            cell.font = Font(color="1A5276", underline="single", size=9)
                        else:
                            # Несколько — перечисляем названия (кликабельность через текст)
                            lines = [f"📄 {_pdf_short_name(u)}" for u in urls]
                            cell.value = "\n".join(lines)
                            cell.font = Font(color="1A5276", size=9)
                            # Гиперссылку ставим на первый файл
                            cell.hyperlink = urls[0]
                    else:
                        cell.value = "—"
                        cell.font = Font(color="999999", size=9)

            # ── Строки данных ─────────────────────────────────────────────────
            for row_idx, row in enumerate(ws.iter_rows(min_row=DATA_START), 1):
                for cell in row:
                    cell.alignment = TOP_LEFT
                    if row_idx % 2 == 0:
                        cell.fill = LGRAY_FILL
                    if cell.value is None or cell.value == "—":
                        cell.fill = RED_FILL

            # ── Размеры ───────────────────────────────────────────────────────
            ws.column_dimensions['A'].width = 30
            for col_idx in range(2, len(df.columns) + 1):
                ws.column_dimensions[get_column_letter(col_idx)].width = 28

            ws.row_dimensions[1].height = 35
            ws.row_dimensions[2].height = 40
            if has_pdf and PDF_ROW:
                ws.row_dimensions[PDF_ROW].height = 45
            for row in range(DATA_START, DATA_START + len(df)):
                ws.row_dimensions[row].height = 30

        print(f"Excel создан: {filepath}")
        return str(filepath)
        
    except Exception as e:
        print(f"!!! Ошибка при создании Excel: {e}")
        import traceback
        traceback.print_exc()
        return None


def _pdf_short_name(url: str) -> str:
    """Возвращает короткое имя PDF из URL."""
    name = url.split("?")[0].split("/")[-1]
    if not name.lower().endswith(".pdf"):
        name = name[:30] + "…" if len(name) > 30 else name
    return name.replace(".pdf", "").replace("_", " ").replace("-", " ")