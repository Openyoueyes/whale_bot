# app/services/message_formatters.py


from aiogram.types import Message


def format_message_for_log(message: Message) -> str:
    text = message.text or message.caption or ""
    parts = []

    if text:
        parts.append(text)

    if message.photo:
        parts.append(f"[photo] file_id={message.photo[-1].file_id}")
    if message.video:
        parts.append(f"[video] file_id={message.video.file_id}")
    if message.document:
        parts.append(
            f"[document] {message.document.file_name or ''} "
            f"file_id={message.document.file_id}"
        )
    if message.voice:
        parts.append(f"[voice] file_id={message.voice.file_id}")
    if message.audio:
        parts.append(f"[audio] file_id={message.audio.file_id}")
    if message.sticker:
        parts.append(f"[sticker] file_id={message.sticker.file_id}")

    return "\n".join(parts) or "<без текста>"


_BITRIX_COMMENT_MAX = 3500


def _truncate(text: str, limit: int = _BITRIX_COMMENT_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 50].rstrip() + "\n...\n[обрезано]"


def format_message_for_bitrix(message: Message) -> str:
    """
    Универсально для broadcast/dialog/quiz:
    - берём html_text/text/caption
    - дописываем вложения (file_id + имена)
    """
    text = message.html_text or message.text or message.caption or ""
    parts: list[str] = []
    if text.strip():
        parts.append(text.strip())

    if message.photo:
        parts.append(f"[photo] file_id={message.photo[-1].file_id}")
    if message.video:
        parts.append(f"[video] file_id={message.video.file_id}")
    if message.document:
        parts.append(f"[document] {message.document.file_name or ''} file_id={message.document.file_id}")
    if message.voice:
        parts.append(f"[voice] file_id={message.voice.file_id}")
    if message.audio:
        parts.append(f"[audio] file_id={message.audio.file_id}")
    if message.animation:
        parts.append(f"[animation] file_id={message.animation.file_id}")
    if message.sticker:
        parts.append(f"[sticker] file_id={message.sticker.file_id}")

    out = "\n".join([p for p in parts if p]).strip() or "<без текста>"
    return _truncate(out)
