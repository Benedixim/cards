from aiogram.fsm.state import State, StatesGroup

from aiogram.fsm.state import State, StatesGroup

class BankState(StatesGroup):
    waiting_set_selection = State()      # выбор набора (если нужен)
    waiting_products = State()           # выбор продуктов
    waiting_characteristics = State()    # выбор характеристик