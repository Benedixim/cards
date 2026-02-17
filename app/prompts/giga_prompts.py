# app/prompts/giga_prompt.py 

from app.db.model import Characteristic

def build_card_parsing_prompt(
    bank_name: str,
    product_name: str,
    characteristics: list[Characteristic],
    html: str
) -> str:
    fields_lines = []
    for char in characteristics:
        fields_lines.append(f"- {char.name}: {char.description} (пример: '{char.value_hint}')")

    fields_str = "\n".join(fields_lines)

    return f"""
Проанализируй HTML страницы продукта "{product_name}" банка {bank_name} и извлеки по следующим характеристикам:

{fields_str}

ВЫВОД - ТОЛЬКО один JSON в строку:
{{ ... }}

HTML:
{html}
"""
