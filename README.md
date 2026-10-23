# Du / Steve: trợ lý giọng nói kiểu JARVIS (Windows + Mac)

Trợ lý nghe tiếng Việt và tiếng Anh: gọi "Du ơi" hoặc "Hey Steve" rồi ra lệnh. Trợ lý mở app,
web, nhạc, tìm file và trả lời câu hỏi bằng AI có số liệu thật (giá XAUUSD, US100, BTC, lịch tin
CPI/FOMC, tin tức). Câu dễ trả lời ngay; câu khó thì tra nhiều nguồn rồi mới trả lời.
Nhắn Telegram từ điện thoại: `/capnhat` nhận bản tin (thị trường, vàng SJC, lãi suất, luật kinh
doanh, tin hot), `/note ...` ghi chú lên Google Calendar, hoặc hỏi bất cứ gì. Bot chạy 24/7
trên máy chủ Google (Apps Script, [google-cloud/bot-telegram.gs](google-cloud/bot-telegram.gs)),
máy tính tắt vẫn trả lời.

Hướng dẫn dùng đầy đủ: [HUONG-DAN.txt](HUONG-DAN.txt). Mọi tuỳ chỉnh: [config.py](config.py).

## Cài lại từ GitHub (máy mới, hoặc lỡ xoá mất thư mục)

1. Cài Python 3.11 trở lên: https://www.python.org (Windows: tick "Add python.exe to PATH").
2. Tải code về: trên trang GitHub bấm **Code → Download ZIP** rồi giải nén, hoặc:
   ```
   git clone https://github.com/truongdinhhuydu123-rgb/Du-Jarvis-.git Jarvis
   ```
3. Trong thư mục vừa tải, chép `.env.example` thành `.env` rồi dán key vào
   (Gemini: https://aistudio.google.com/apikey, Groq: https://console.groq.com/keys).
4. Bấm đúp **Start Tom.bat**. Lần đầu máy tự cài thư viện (~300 MB) và tải bộ nghe
   (~550 MB) nên mất vài phút, cần có mạng.
5. Bấm đúp **Tao lenh run.bat** một lần. Sau đó gõ `run` để bật, `turn off` để tắt.

Repo này không chứa `.env` (key riêng), `.venv` (thư viện), `models` (bộ nghe) và `.cache`
(dữ liệu tự học, hồ sơ Chrome), vì các thứ đó hoặc là riêng tư, hoặc tự tạo lại được.
