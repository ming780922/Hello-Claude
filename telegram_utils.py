import io

import requests

TELEGRAM_MAX_LENGTH = 4096


def send_message(token, chat_id, text, *, parse_mode=None,
                 disable_web_page_preview=False, timeout=15,
                 raise_on_error=False):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if disable_web_page_preview:
        payload["disable_web_page_preview"] = True
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=timeout,
    )
    if raise_on_error:
        r.raise_for_status()
    return r


def send_photo_bytes(token, chat_id, data, filename="photo.jpg", *,
                     caption=None, parse_mode=None, timeout=30, raise_on_error=False):
    fields = {"chat_id": chat_id}
    if caption:
        fields["caption"] = caption
    if parse_mode:
        fields["parse_mode"] = parse_mode
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=fields,
        files={"photo": (filename, io.BytesIO(data), "image/jpeg")},
        timeout=timeout,
    )
    if raise_on_error:
        r.raise_for_status()
    return r


def send_batched(token, chat_id, header, items, *,
                 separator="\n\n", parse_mode="HTML",
                 disable_web_page_preview=True):
    """Send items as few messages as possible, splitting only when exceeding Telegram's limit."""
    current = header
    for item in items:
        candidate = current + separator + item
        if len(candidate) > TELEGRAM_MAX_LENGTH:
            send_message(token, chat_id, current,
                         parse_mode=parse_mode,
                         disable_web_page_preview=disable_web_page_preview)
            current = item
        else:
            current = candidate
    send_message(token, chat_id, current,
                 parse_mode=parse_mode,
                 disable_web_page_preview=disable_web_page_preview)


# 向後相容別名（供 notify_telegram.py 不改呼叫端使用）
send_telegram = send_message
