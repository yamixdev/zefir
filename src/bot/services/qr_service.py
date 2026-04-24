"""Генерация QR-кода в PNG-байты.

`qrcode[pil]` использует Pillow под капотом. Рендерим в буфер,
отдаём байты — Telegram загружает как фото.
"""
import io

import qrcode


def make_qr_png(text: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,  # автоподбор по размеру
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
