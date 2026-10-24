from aiogram.fsm.state import State, StatesGroup


class AdminLinkStates(StatesGroup):
    waiting_link = State()


class AdminSearchStates(StatesGroup):
    waiting_query = State()


class AdminBroadcastStates(StatesGroup):
    waiting_text = State()
    confirm = State()
