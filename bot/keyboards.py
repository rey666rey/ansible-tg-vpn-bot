from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


ROLLOUT_BUTTON = "раскатать сервер"
GET_SUBSCRIPTION_BUTTON = "добавить пользователя"
SERVERS_BUTTON = "серверы"
CHECK_SERVERS_BUTTON = "проверить серверы"
CLIENTS_BUTTON = "клиенты"
BACKUP_BUTTON = "бэкап"
BACK_BUTTON = "назад"


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ROLLOUT_BUTTON)],
            [KeyboardButton(text=GET_SUBSCRIPTION_BUTTON)],
            [KeyboardButton(text=SERVERS_BUTTON), KeyboardButton(text=CHECK_SERVERS_BUTTON)],
            [KeyboardButton(text=CLIENTS_BUTTON), KeyboardButton(text=BACKUP_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="выбери блестящее действие",
    )


def rollout_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BACK_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="пришли ip и домен",
    )


def subscription_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BACK_BUTTON)]],
        resize_keyboard=True,
        input_field_placeholder="пришли имя клиента",
    )
