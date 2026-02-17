import os
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

GIGACHAT_TOKEN = os.getenv("GIGA_TOKEN")

PROXY_RU = os.getenv("PROXY_URL")

SYSTEM_USER_ID = 1


BASE_CHARACTERISTICS = [
    ("type", "Тип карты", "Например: Mastercard, Visa, МИР"),
    ("currency", "Валюта", "Например: BYN, USD, EUR"),
    ("validity", "Срок действия", "Например: 3 года, 5 лет"),
    ("maintenance_cost", "Обслуживание", "Например: 3 BYN/мес, бесплатно"),
    ("free_conditions", "Бесплатно при", "Например: при обороте от 600 BYN"),
    ("sms_notification", "СМС уведомления", "Например: 4.5 BYN/мес, бесплатно"),
    ("atm_limit_own", "Лимит ATM своего", "Например: 1000 BYN, без ограничений"),
    ("atm_limit_other", "Лимит ATM других", "Например: 500 BYN, 3.5 %"),
    ("loyalty_program", "Программа лояльности", "Например: кэшбэк 3 %, бонусы"),
    ("interest_rate", "% на остаток", "Например: 0.01 %, 3 % годовых"),
    ("additional", "Дополнительно", "Особенности, льготы, требования"),
]