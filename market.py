"""Dữ liệu thật cho trợ lý: giá thị trường, lịch tin kinh tế, tin tức, tìm web, đọc trang web.

Nguồn miễn phí, không cần key:
  giá        Yahoo Finance (vàng tương lai, Nasdaq, DXY, lợi suất...) và Binance (crypto, PAXG)
  lịch tin   Forex Factory (tuần này: giờ ra tin, dự báo, kỳ trước)
  tin tức    RSS của CNBC, InvestingLive (ForexLive), Investing.com; Google News khi tìm theo chủ đề
             Tin Việt Nam: RSS VnExpress (tin nổi bật, kinh doanh, pháp luật), Google News tiếng Việt
  vàng VN    SJC (vàng miếng, nhẫn) và PNJ
  tìm web    DuckDuckGo
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import config as cfg
from common import CACHE, log

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_FILE = CACHE / "lich_tin.json"
NEWS_FEEDS = {
    "CNBC Economy": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "InvestingLive": "https://www.forexlive.com/feed/news",
    "Investing.com": "https://www.investing.com/rss/news_25.rss",
}
VN_FEEDS = {
    "VnExpress Tin nổi bật": "https://vnexpress.net/rss/tin-noi-bat.rss",
    "VnExpress Kinh doanh": "https://vnexpress.net/rss/kinh-doanh.rss",
    "VnExpress Pháp luật": "https://vnexpress.net/rss/phap-luat.rss",
}
SJC_URL = "https://sjc.com.vn/GoldPrice/Services/PriceService.ashx"
PNJ_URL = "https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price?zone=00"
OZ_PER_LUONG = 37.5 / 31.1035   # 1 lượng = 37,5 g; 1 ounce = 31,1035 g
_cache: dict = {}
_lock = threading.Lock()


def _get(url: str, timeout: float = 10, data: bytes | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Accept-Language": "en-US,en;q=0.8", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _cached(key: str, ttl: float, fn):
    """Nhớ kết quả trong ttl giây để HUD và AI hỏi liên tục không bị nguồn chặn."""
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    try:
        value = fn()
    except Exception:
        if hit:   # nguồn lỗi tạm thời (vd bị chặn vì hỏi nhiều): dùng bản cũ còn trong máy
            return hit[1]
        raise
    with _lock:
        _cache[key] = (time.time(), value)
    return value


# --- giá -------------------------------------------------------------------
def _quote(code: str) -> dict:
    if code.startswith("binance:"):
        d = json.loads(_get("https://api.binance.com/api/v3/ticker/24hr?symbol=" + code[8:]))
        return {"price": float(d["lastPrice"]), "change_pct": float(d["priceChangePercent"]),
                "basis": "24 giờ qua", "source": "Binance", "time": time.time()}
    d = json.loads(_get("https://query1.finance.yahoo.com/v8/finance/chart/"
                        + urllib.parse.quote(code) + "?interval=5m&range=1d"))
    meta = d["chart"]["result"][0]["meta"]
    price, prev = meta["regularMarketPrice"], meta.get("chartPreviousClose") or meta.get("previousClose")
    return {"price": price, "change_pct": (price / prev - 1) * 100 if prev else None,
            "basis": "so với giá đóng cửa trước", "source": "Yahoo Finance",
            "time": meta.get("regularMarketTime", time.time())}


def quotes(names: list[str] | None = None) -> list[dict]:
    """Giá mới nhất cho các mã trong config.MARKETS (hoặc mã Yahoo bất kỳ, vd "AAPL")."""
    wanted = names or list(cfg.MARKETS)
    out = []
    for name in wanted:
        key = next((k for k in cfg.MARKETS if k.lower() == str(name).strip().lower()), None)
        code = cfg.MARKETS[key] if key else str(name).strip()
        try:
            q = _cached("q:" + code, 20, lambda: _quote(code))
        except Exception as e:
            out.append({"name": key or name, "code": code, "error": str(e)[:80]})
            continue
        out.append({"name": key or name, "code": code, **q,
                    "time_local": datetime.fromtimestamp(q["time"]).strftime("%H:%M %d/%m")})
    return out


# --- lịch tin kinh tế --------------------------------------------------------
def _load_calendar() -> list[dict]:
    """Lịch tin từ Forex Factory; nguồn chặn (hỏi nhiều quá) thì dùng bản đã lưu trong ngày."""
    try:
        events = json.loads(_get(CALENDAR_URL))
    except Exception as e:
        if CALENDAR_FILE.is_file() and time.time() - CALENDAR_FILE.stat().st_mtime < 24 * 3600:
            log(f"⚠️  Không tải được lịch tin ({e}); dùng bản đã lưu.")
            return json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))
        raise
    CALENDAR_FILE.parent.mkdir(exist_ok=True)
    CALENDAR_FILE.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
    return events


def calendar(country: str = "USD", impact: str = "High") -> list[dict]:
    """Lịch tin tuần này (giờ Việt Nam/giờ máy), lọc theo nước và mức độ ("" = tất cả)."""
    events = _cached("calendar", 15 * 60, _load_calendar)
    now = datetime.now(timezone.utc)
    out = []
    for e in events:
        if country and e.get("country", "").upper() != country.upper():
            continue
        if impact and e.get("impact", "").lower() != impact.lower():
            continue
        try:
            when = datetime.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        out.append({"title": e.get("title"), "country": e.get("country"), "impact": e.get("impact"),
                    "time_local": when.astimezone().strftime("%H:%M %a %d/%m"),
                    "ts": when.timestamp(), "status": "đã ra" if when < now else "sắp ra",
                    "forecast": e.get("forecast") or "", "previous": e.get("previous") or ""})
    return sorted(out, key=lambda x: x["ts"])


# --- tin tức ------------------------------------------------------------------
def _rss(url: str, source: str) -> list[dict]:
    root = ET.fromstring(_get(url))
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        when = it.findtext("pubDate") or ""
        try:
            ts = parsedate_to_datetime(when).timestamp()
        except (TypeError, ValueError):
            ts = 0
        if title:
            items.append({"title": html.unescape(title), "link": (it.findtext("link") or "").strip(),
                          "source": source, "ts": ts})
    return items


def news(query: str = "", limit: int = 8, lang: str = "en", days: int = 3) -> list[dict]:
    """Tin mới nhất: theo chủ đề (Google News) hoặc tin chung (kinh tế quốc tế / tin Việt Nam).

    lang="vi": Google News tiếng Việt, hoặc (không có chủ đề) RSS VnExpress.
    """
    if query:
        region = "hl=vi&gl=VN&ceid=VN:vi" if lang == "vi" else "hl=en-US&gl=US&ceid=US:en"
        url = f"https://news.google.com/rss/search?{region}&q=" + urllib.parse.quote(f"{query} when:{days}d")
        items = _cached(f"news:{lang}:{days}:{query}", 5 * 60, lambda: _rss(url, "Google News"))
    else:
        items = []
        for source in (VN_FEEDS if lang == "vi" else NEWS_FEEDS):
            items += feed(source, 50)
    return _newest(items, limit)


def feed(source: str, limit: int = 8) -> list[dict]:
    """Tin mới nhất của một nguồn RSS trong NEWS_FEEDS / VN_FEEDS (lỗi thì trả về rỗng)."""
    url = {**NEWS_FEEDS, **VN_FEEDS}[source]
    try:
        items = _cached("feed:" + source, 5 * 60, lambda: _rss(url, source))
    except Exception as e:
        log(f"⚠️  Không đọc được tin {source}: {e}")
        return []
    return _newest(items, limit)


def _newest(items: list[dict], limit: int) -> list[dict]:
    """Mới nhất trước, bỏ tin trùng tiêu đề (một tin hay có ở nhiều mục)."""
    out, seen = [], set()
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        if it["title"] in seen:
            continue
        seen.add(it["title"])
        it["time_local"] = datetime.fromtimestamp(it["ts"]).strftime("%H:%M %d/%m") if it["ts"] else ""
        out.append(it)
        if len(out) >= limit:
            break
    return out


# --- giá vàng trong nước -------------------------------------------------------------
def vn_gold() -> dict:
    """Giá vàng Việt Nam (đồng/lượng): SJC vàng miếng và nhẫn (TP.HCM), PNJ; cập nhật 5 phút/lần."""
    return _cached("vn_gold", 5 * 60, _load_vn_gold)


def _load_vn_gold() -> dict:
    out: dict = {"unit": "đồng/lượng", "prices": []}
    errors = []
    try:
        d = json.loads(_get(SJC_URL, data=b"method=GetCurrentGoldPricesByBranch&BranchId=1",
                            headers={"Content-Type": "application/x-www-form-urlencoded"}))
        out["sjc_updated"] = d.get("latestDate", "")
        for row in d.get("data", []):
            if row.get("TypeName") in ("Vàng SJC 1L, 10L, 1KG", "Vàng nhẫn SJC 99,99% 1 chỉ, 2 chỉ, 5 chỉ"):
                out["prices"].append({"name": row["TypeName"], "source": "SJC",
                                      "buy": int(row["BuyValue"]), "sell": int(row["SellValue"])})
    except Exception as e:
        errors.append(f"SJC: {e}")
    try:
        for row in json.loads(_get(PNJ_URL)).get("data", []):
            if row.get("masp") in ("SJC", "N24K"):   # PNJ tính nghìn đồng/chỉ; 1 lượng = 10 chỉ
                out["prices"].append({"name": row["tensp"], "source": "PNJ",
                                      "buy": int(row["giamua"]) * 10_000, "sell": int(row["giaban"]) * 10_000})
    except Exception as e:
        errors.append(f"PNJ: {e}")
    if not out["prices"]:
        raise OSError("; ".join(errors) or "không có giá vàng")
    return out


def world_gold_vnd() -> dict:
    """Giá vàng thế giới quy ra đồng/lượng (chưa thuế phí), để so với vàng trong nước."""
    q = {x["name"]: x for x in quotes(["XAUUSD", "VND=X"])}
    xau, usd = q["XAUUSD"].get("price"), q["VND=X"].get("price")
    if not (xau and usd):
        raise OSError("thiếu giá vàng thế giới hoặc tỷ giá")
    return {"xauusd": xau, "usd_vnd": usd, "per_luong_vnd": round(xau * OZ_PER_LUONG * usd)}


# --- tìm web và đọc trang --------------------------------------------------------
def web_search(query: str, limit: int = 5) -> list[dict]:
    """Tìm trên web (DuckDuckGo): tiêu đề, link, đoạn trích."""
    page = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)).decode("utf-8", "ignore")
    results = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)class="result__snippet"[^>]*>(.*?)</a>',
                         page, re.S):
        link = html.unescape(m.group(1))
        target = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("uddg")
        url = target[0] if target else link
        if "duckduckgo.com/" in url:   # quảng cáo (link chuyển hướng của DuckDuckGo)
            continue
        results.append({"title": _text(m.group(2)), "url": url, "snippet": _text(m.group(4))})
        if len(results) >= limit:
            break
    return results


def read_page(url: str, max_chars: int = 6000) -> str:
    """Chữ chính của một trang web (bỏ script, menu...), cắt bớt cho vừa."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("chỉ đọc được link http(s)")
    raw = _get(url, timeout=15).decode("utf-8", "ignore")
    raw = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form)\b.*?</\1>", " ", raw)
    return _text(raw)[:max_chars]


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# --- cho HUD ----------------------------------------------------------------------
def hud_snapshot() -> dict:
    """Bảng giá và vài tin Mỹ quan trọng sắp tới; lấy lại khi dữ liệu cũ quá 8 giây."""
    return _cached("hud", 8, _build_hud)


def hud_latest() -> dict:
    """Dữ liệu HUD đã có sẵn, không chờ mạng (HUD hỏi vài lần mỗi giây)."""
    with _lock:
        hit = _cache.get("hud")
    return hit[1] if hit else {"markets": [], "events": []}


def _build_hud() -> dict:
    rows = []
    for q in quotes():
        rows.append({"name": q["name"], "price": q.get("price"),
                     "change": q.get("change_pct"), "error": bool(q.get("error"))})
    try:
        upcoming = [e for e in calendar() if e["status"] == "sắp ra"][:4]
    except Exception:
        upcoming = []
    return {"markets": rows, "events": [{k: e[k] for k in ("title", "time_local", "forecast", "previous", "ts")}
                                        for e in upcoming]}


def start_background() -> None:
    """Luồng nền cập nhật dữ liệu HUD để lúc vẽ không phải chờ mạng."""
    def loop() -> None:
        while True:
            try:
                hud_snapshot()
            except Exception as e:
                log(f"⚠️  Không cập nhật được bảng giá: {e}")
            time.sleep(10)
    threading.Thread(target=loop, daemon=True).start()
