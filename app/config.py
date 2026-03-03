import os

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

# --- VIDEO поля ---
WELCOME_PHOTO_FILE_ID = env.str("WELCOME_PHOTO_FILE_ID", default="")
BONUS_IMAGE_FILE_ID = env.str("BONUS_IMAGE_FILE_ID", default="")
MANAGER_CONTACT_IMAGE_FILE_ID = env.str("MANAGER_CONTACT_IMAGE_FILE_ID", default="")
PREM_IMAGE_FILE_ID = env.str("PREM_IMAGE_FILE_ID", default="")
ROBOTS_IMAGE_FILE_ID = env.str("ROBOTS_IMAGE_FILE_ID", default="")
AI_IMAGE_FILE_ID = env.str("AI_IMAGE_FILE_ID", default="")
SAFE_IMAGE_FILE_ID = env.str("SAFE_IMAGE_FILE_ID", default="")
QUANT_IMAGE_FILE_ID = env.str("QUANT_IMAGE_FILE_ID", default="")
