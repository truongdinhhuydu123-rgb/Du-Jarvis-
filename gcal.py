"""Đưa ghi chú, lịch hẹn, việc cần nhắc lên Google Calendar.

Tự động: qua một Google Apps Script nhỏ chạy trên chính tài khoản Google của bạn (file
google-calendar/lich.gs, cách cài xem HUONG-DAN.txt). Cần GCAL_WEBHOOK_URL và GCAL_SECRET trong .env.
Chưa cài thì tạo link Google Calendar điền sẵn: bấm vào rồi bấm Lưu là xong.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import config as cfg
from common import log


def connected() -> bool:
    return bool(os.environ.get("GCAL_WEBHOOK_URL") and os.environ.get("GCAL_SECRET"))


def add_event(title: str, start: str, end: str = "", all_day: bool = False,
              details: str = "") -> tuple[bool, str, str]:
    """Thêm một sự kiện. start/end: "YYYY-MM-DDTHH:MM" (giờ máy) hoặc "YYYY-MM-DD" (cả ngày).

    Trả về (đã lưu tự động?, câu báo lại, link Google Calendar điền sẵn).
    """
    title = (title or "Ghi chú").strip()[:200]
    begin = _parse(start) or datetime.now().replace(second=0, microsecond=0)
    all_day = all_day or len(start.strip()) <= 10
    finish = _parse(end) if end else None
    if all_day:
        first = begin.date()
        last = finish.date() if finish and finish.date() > first else first
        when = first.strftime("%d/%m/%Y") + ("" if last == first else last.strftime(" - %d/%m/%Y"))
        link = _link(title, first.strftime("%Y%m%d"), (last + timedelta(days=1)).strftime("%Y%m%d"), details)
    else:
        if not finish or finish <= begin:
            finish = begin + timedelta(minutes=cfg.CALENDAR_EVENT_MIN)
        when = begin.strftime("%H:%M %d/%m/%Y") + finish.strftime(" - %H:%M")
        link = _link(title, begin.strftime("%Y%m%dT%H%M%S"), finish.strftime("%Y%m%dT%H%M%S"), details)

    if not connected():
        return False, f"{title} ({when})", link
    body = {"secret": os.environ["GCAL_SECRET"], "title": title, "details": details, "allDay": all_day,
            "start": (begin.date().isoformat() if all_day else begin.strftime("%Y-%m-%dT%H:%M")),
            "end": (last.isoformat() if all_day else finish.strftime("%Y-%m-%dT%H:%M")),
            "remindMinutes": 0 if all_day else cfg.CALENDAR_REMIND_MIN}
    req = urllib.request.Request(os.environ["GCAL_WEBHOOK_URL"], data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    # Apps Script chạy xong rồi chuyển hướng sang trang kết quả; urllib tự theo.
    with urllib.request.urlopen(req, timeout=20) as r:
        result = json.loads(r.read() or b"{}")
    if not result.get("ok"):
        raise OSError(f"Google Calendar từ chối: {result.get('loi') or result}")
    log(f"📅 Đã thêm vào Google Calendar: {title} ({when})")
    return True, f"{title} ({when})", link


def _parse(value: str) -> datetime | None:
    """"2026-10-22T09:00", "2026-10-22 09:00", "2026-10-22" (có múi giờ thì đổi về giờ máy)."""
    try:
        when = datetime.fromisoformat((value or "").strip())
    except ValueError:
        return None
    return when.astimezone().replace(tzinfo=None) if when.tzinfo else when


def _link(title: str, begin: str, end: str, details: str) -> str:
    query = {"action": "TEMPLATE", "text": title, "dates": f"{begin}/{end}", "ctz": cfg.TIMEZONE}
    if details:
        query["details"] = details
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(query)
