from aiogram.fsm.state import StatesGroup, State

class BankState(StatesGroup):
    waiting_products = State()
    waiting_characteristics = State()
    waiting_new_set_name = State()
    waiting_set_name_edit = State()
    waiting_new_char_for_set = State()
    editing_char_for_set = State()
    waiting_char_description = State()
    waiting_product_url = State()
    waiting_bank_edit = State()
    waiting_product_confirm = State()
    waiting_product_edit = State()
    waiting_char_name = State()
    editing_char_desc = State()
