from aiogram.fsm.state import State, StatesGroup

class BankState(StatesGroup):
    waiting_selection = State()