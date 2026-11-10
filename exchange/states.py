from aiogram.fsm.state import State, StatesGroup


class ClientCreateOrder(StatesGroup):
    amount = State()
    address = State()


class ClientUploadReceipt(StatesGroup):
    waiting_file = State()


class SetUsdtAddress(StatesGroup):
    waiting = State()


class SupportAssignRequisites(StatesGroup):
    bank = State()
    detail = State()
    holder = State()


class SupportSetRate(StatesGroup):
    waiting = State()


class SupportNote(StatesGroup):
    waiting = State()


class AdminPayout(StatesGroup):
    waiting_txid = State()
