from environs import Env

env = Env()
env.read_env()

BOT_TOKEN: str = env.str("BOT_TOKEN")

# Превращаем строку "1,2,3" → [1, 2, 3]
ADMIN_IDS = env.list("ADMIN_IDS", subcast=int)
CHANNEL_URL: str = env.str("CHANNEL_URL", "https://t.me/your_channel_here")
DATABASE_URL: str = env.str("DATABASE_URL")

# Bitrix24
BITRIX_WEBHOOK_URL: str = env.str("BITRIX_WEBHOOK_URL")  # CRM_HOOK, типа https://domain.bitrix24.ru/rest/1/xxx/
BITRIX_PORTAL_URL: str = env.str("BITRIX_PORTAL_URL")  # CRM_URL, типа https://domain.bitrix24.ru/

# ID чата, куда шлём уведомления о новых лидах/сделках
GROUP_CHAT_MESSAGES_ID: int = env.int("GROUP_CHAT_MESSAGES_ID", 0)
GROUP_CHAT_MESSAGES_BOT_ID: int = env.int("GROUP_CHAT_MESSAGES_BOT_ID", 0)
GROUP__B_CHAT_MESSAGES_BOT_ID: int = env.int("GROUP__B_CHAT_MESSAGES_BOT_ID", 0)
MAIN_CHANNEL_ID: int = env.int("MAIN_CHANNEL_ID", 0)

# --- LEAD поля ---
BITRIX_FIELD_TG_ID_LEAD: str = env.str("BITRIX_FIELD_TG_ID_LEAD")
BITRIX_FIELD_TG_USERNAME_LEAD: str = env.str("BITRIX_FIELD_TG_USERNAME_LEAD")
BITRIX_FIELD_TG_LINK_LEAD: str = env.str("BITRIX_FIELD_TG_LINK_LEAD")
BITRIX_FIELD_TAG_LEAD: str = env.str("BITRIX_FIELD_TAG_LEAD")

# --- DEAL поля ---
BITRIX_FIELD_TG_ID_DEAL: str = env.str("BITRIX_FIELD_TG_ID_DEAL")
BITRIX_FIELD_TG_USERNAME_DEAL: str = env.str("BITRIX_FIELD_TG_USERNAME_DEAL")
BITRIX_FIELD_TG_LINK_DEAL: str = env.str("BITRIX_FIELD_TG_LINK_DEAL")
BITRIX_FIELD_TAG_DEAL: str = env.str("BITRIX_FIELD_TAG_DEAL")
BITRIX_FIELD_PHONE_DEAL: str = env.str("BITRIX_FIELD_PHONE_DEAL", "UF_CRM_1770809839968")

# --- Bitrix: сеть и лимиты ---
# У входящего вебхука Bitrix лимит порядка 2 запросов в секунду.
BITRIX_MAX_RPS: float = env.float("BITRIX_MAX_RPS", 2.0)
BITRIX_TIMEOUT_SECONDS: float = env.float("BITRIX_TIMEOUT_SECONDS", 20.0)
# Отключать проверку TLS-сертификата можно только осознанно и временно:
# в URL вебхука лежит секрет, который даёт полный доступ к CRM.
BITRIX_VERIFY_SSL: bool = env.bool("BITRIX_VERIFY_SSL", True)

# --- Рассылка ---
# Пауза между получателями: защита от 429 со стороны Telegram.
BROADCAST_DELAY_SECONDS: float = env.float("BROADCAST_DELAY_SECONDS", 0.05)

# --- Антифлуд на клиентских хендлерах ---
# Сообщения дорогие (Bitrix + уведомления менеджерам), нажатия кнопок дешёвые —
# у них окно короче, иначе ломается быстрое прохождение квиза.
# 0.5 с — сознательно мягко: отброшенное сообщение клиента не попадёт ни в CRM,
# ни менеджерам, а это дороже лишнего запроса. От Bitrix и так защищает лимитер.
# 0 полностью отключает антифлуд.
CLIENT_THROTTLE_SECONDS: float = env.float("CLIENT_THROTTLE_SECONDS", 0.5)
CLIENT_CALLBACK_THROTTLE_SECONDS: float = env.float("CLIENT_CALLBACK_THROTTLE_SECONDS", 0.3)

# --- Отладка ---
# Логирование каждого входящего сообщения целиком (включая текст переписки).
DEBUG_LOG_INCOMING: bool = env.bool("DEBUG_LOG_INCOMING", False)

# --- VIDEO поля ---
WELCOME_PHOTO_FILE_ID = env.str("WELCOME_PHOTO_FILE_ID", default="")
SUBSCRIPTION_GATE_PHOTO_PATH = env.str("SUBSCRIPTION_GATE_PHOTO_PATH", default="app/bot/assets/subscription_gate.png")
BONUS_IMAGE_FILE_ID = env.str("BONUS_IMAGE_FILE_ID", default="")
MANAGER_CONTACT_IMAGE_FILE_ID = env.str("MANAGER_CONTACT_IMAGE_FILE_ID", default="")
PREM_IMAGE_FILE_ID = env.str("PREM_IMAGE_FILE_ID", default="")
ROBOTS_IMAGE_FILE_ID = env.str("ROBOTS_IMAGE_FILE_ID", default="")
AI_IMAGE_FILE_ID = env.str("AI_IMAGE_FILE_ID", default="")
BREAKOUTGOLD_IMAGE_FILE_ID = env.str("BREAKOUTGOLD_IMAGE_FILE_ID", default="")
