from aiogram.fsm.state import State, StatesGroup


class AdminLinkStates(StatesGroup):
    waiting_link = State()
