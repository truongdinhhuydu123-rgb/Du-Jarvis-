# ================= CẤU HÌNH TRỢ LÝ (DU / STEVE) =================
# Sửa file này, lưu lại, rồi chạy lại trợ lý là xong.
# Dòng bắt đầu bằng dấu # là ghi chú, máy không đọc.


# --- 1. TÊN VÀ CÁCH GỌI ---------------------------------------------------
# Gọi tên nào cũng được; trợ lý tự xưng đúng tên bạn vừa gọi. Tên đầu tiên là tên mặc
# định (hiện trên HUD lúc mới bật). Mỗi tên kèm các cách máy hay nghe ra tên đó.
# Gọi tên ở ĐẦU câu rồi nói lệnh:
#   "Du ơi, mấy giờ rồi?"   "Này Du, mở Zalo"   "Steve ơi, giá vàng thế nào?"
#   "Hey Steve, what time is it?"   "Hey Du, play some remix music"
# Chữ "Du" một mình KHÔNG gọi (để câu như "Dù sao thì..." không đánh thức nhầm):
# hãy nói "Du ơi", "Này Du" hay "Hey Du". "Steve" thì gọi trơn cũng được.
# Gọi mà không phản ứng: nhìn dòng "👂 ..." trên màn hình xem máy nghe ra chữ gì,
# rồi thêm chữ đó vào đây.
WAKE_WORDS = {
    "Du": ["du ơi", "dù ơi", "zu ơi", "giu ơi", "này du", "hey du", "hây du", "ê du", "ok du",
           "hi du"],
    "Steve": ["steve", "steve ơi", "stiv", "stive", "stíp", "xtiv", "hey steve", "này steve",
              "ok steve", "hi steve", "hây steve"],
}
NAMES = list(WAKE_WORDS)

FOLLOW_UP_S = 5      # trả lời xong, trong ngần này giây bạn nói tiếp được luôn,
                     # không cần gọi tên lại. Phòng đông người nói chuyện mà hay bị lấy nhầm
                     # làm lệnh thì giảm (0 = lúc nào cũng phải gọi tên).
ACK_SOUND = r"C:\Windows\Media\Speech On.wav"   # tiếng "tíng" khi nhận lệnh. "" = tắt
                                                 # (Mac: "/System/Library/Sounds/Tink.aiff")


# --- 2. NGÔN NGỮ VÀ GIỌNG -------------------------------------------------
LANGUAGE = "auto"    # "auto" = bạn nói/gõ tiếng Việt thì trả lời tiếng Việt,
                     #          nói/gõ tiếng Anh thì trả lời tiếng Anh
                     # "vi" = luôn trả lời tiếng Việt    "en" = luôn trả lời tiếng Anh
VOICES = {           # giọng cho từng tiếng (miễn phí, cần mạng)
    "en": "en-GB-RyanNeural",
    "vi": "vi-VN-NamMinhNeural",      # giọng nữ: "vi-VN-HoaiMyNeural"
}
OFFLINE_VOICES = {"en": "en", "vi": "vi"}   # giọng có sẵn của máy, dùng tạm khi mất mạng.
                     # Windows: mã tiếng ("en", "vi"); Mac: tên giọng ("Daniel", "Linh")

# Hiệu ứng trầm, ấm, hơi vang. Nghe thử ngay:
#     .venv\Scripts\python.exe jarvis.py --say "Du đã trực tuyến."
VOICE_PITCH = -3.0   # hạ tông bao nhiêu nửa cung. 0 = giọng gốc, -2 = hơi trầm,
                     #   -3 = trầm, -5 = rất trầm (quá nữa nghe như quái vật)
VOICE_REVERB = 0.15  # độ vang kiểu "phòng máy". 0 = tắt, 0.12 = nhẹ, 0.25 = rõ
VOICE_METAL = 0.25   # âm sắc "máy" kiểu AI trong phim. 0 = tắt, 0.25 = nhẹ, 0.5 = rõ
VOICE_LOUDNESS = 3.0 # độ to rõ (nén tiếng). 1.6 = tự nhiên, 3 = to rõ, 5 = rất to (hơi gắt)
VOICE_SPEED = 0.95   # tốc độ nói. 0.92 = chậm rãi, điềm tĩnh; 1.0 = bình thường


# --- 3. LỆNH NHANH (không cần AI, không tốn lượt hỏi) ---------------------
# Bên trái là việc trợ lý làm, bên phải là các câu bạn có thể nói (Việt hoặc Anh).
COMMANDS = {
    "workflow": ["chào buổi sáng", "bắt đầu làm việc", "khởi động hệ thống",
                 "good morning", "start work"],
    "music":    ["mở nhạc", "bật nhạc", "phát nhạc", "play music", "play some music"],
    "time":     ["mấy giờ rồi", "bấy giờ rồi", "bây giờ là mấy giờ", "mấy giờ",
                 "what time is it", "what's the time"],
    "date":     ["hôm nay ngày mấy", "hôm nay thứ mấy", "hôm nay là ngày bao nhiêu",
                 "what day is it", "what's the date", "what's today"],
    "stop":     ["tạm biệt", "nghỉ đi", "đi ngủ đi", "tắt trợ lý", "tắt du", "tắt dù", "tắt steve",
                 "tắt tom", "tắt tôm", "goodbye", "shut down", "go to sleep", "turn off du",
                 "turn off steve", "turn off tom"],
}
# Tắt nhanh KHÔNG cần gọi tên: nói hoặc gõ đúng một trong mấy câu dưới (cả câu chỉ có vậy) là
# trợ lý tắt. Câu ngắn nghe gần giống "turn off" (giọng Việt hay bị nghe thành "Don't off") thì
# Groq nghe lại cho chắc. Gõ  turn off  trong PowerShell / cửa sổ lệnh cũng tắt được (sau khi
# chạy "Tao lenh run.bat").
STOP_WORDS = ["turn off", "turn of", "don't off", "tơn off", "tơn ốp", "tơn óp"]
# Mở web/app: "mở ...", "bật ...", "open ...". Tên dưới đây mở ngay; tên app khác
# trong Start menu (Excel, Word, Zalo, Spotify...) cũng mở được luôn.
# Bên trái: tên gọi (nhiều cách gọi thì ngăn bằng dấu | ). Bên phải: tên app hoặc địa chỉ web.
SHORTCUTS = {
    "zalo|gia lô|da lô|gà lô": "Zalo",
    "telegram": "Telegram",
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "YouTube|du túp": "https://www.youtube.com",
    "Gmail|mail|email": "https://mail.google.com",
    "Calendar|lịch|lịch làm việc": "https://calendar.google.com",
    "facebook|phây|fb": "https://www.facebook.com",
    "google": "https://www.google.com",
    "claude": "https://claude.ai/new",
    "TradingView|trading view": "https://www.tradingview.com/chart/",
    "Forex Factory|lịch kinh tế": "https://www.forexfactory.com/calendar",
}
# Tìm file: "tìm file báo cáo tháng 10", "find file invoice". Mở thư mục chứa file
# khớp nhất. Tìm trong các thư mục dưới (để trống = Desktop, Documents, Downloads,
# Pictures, Videos, Music, OneDrive của bạn).
FILE_SEARCH_DIRS = []
# Câu nào không khớp mục 3 thì chuyển cho AI trả lời (mục 4).


# --- 4. BỘ NÃO AI (hỏi gì trả lời đó, có số liệu thật) --------------------
# Dán API key vào file .env cạnh file này. Chưa có key nào thì hỏi gì trợ lý cũng
# mở trang Google tìm kiếm câu đó.
AI_PROVIDER = "gemini"   # "gemini" = AI của Google. Key miễn phí: https://aistudio.google.com/apikey
                         # "claude" = AI của Anthropic. Key: https://console.anthropic.com
                         # Chỉ có key của AI kia thì tự dùng AI kia.
GEMINI_MODEL = "gemini-3.5-flash-lite"   # nhanh nhất. Thông minh hơn (chậm hơn): "gemini-3.8-flash"

AI_MODEL = "claude-opus-5-5"   # (Claude) thông minh nhất. Nhanh, rẻ hơn nhiều: "claude-haiku-5-5"
AI_EFFORT = "low"              # (Claude) "low" = trả lời nhanh; "medium", "high" = nghĩ kỹ hơn
WEB_SEARCH = True              # (Claude) cho tra web bằng công cụ của Anthropic (tốn thêm phí).
AI_MEMORY_TURNS = 10           # nhớ bao nhiêu lượt hỏi đáp gần nhất

# Câu dễ trả lời nhanh, câu khó nghiên cứu rồi mới trả lời.
ANSWER_MODE = "auto"     # "auto" = câu dễ (giá, giờ, kiến thức phổ thông) trả lời ngay, ~2-3 giây.
                         #   Câu khó (phân tích, so sánh, tại sao, dự báo, kịch bản, câu dài...)
                         #   thì báo "chờ vài giây", tra song song web + tin + giá + lịch tin, đọc
                         #   vài bài gốc, rồi nghĩ kỹ mới trả lời (~10-15 giây). Câu tưởng dễ mà AI
                         #   thấy cần tra thêm thì AI tự chuyển sang nghiên cứu.
                         #   Nói "ngắn gọn" / "nói nhanh" / "quick" thì luôn trả lời nhanh.
                         # "nhanh" = luôn trả lời nhanh    "ky" = câu nào cũng nghiên cứu
RESEARCH_MODEL = ""      # (Gemini) model cho câu khó. "" = như GEMINI_MODEL (nhanh).
                         #   "gemini-3.8-flash" phân tích giỏi hơn nhưng chậm hơn nhiều (10-30 giây)
RESEARCH_PAGES = 3       # câu khó đọc kỹ bao nhiêu bài web

# Trợ lý thiên về lĩnh vực gì (AI đọc đoạn này mỗi lần trả lời). Viết về chính bạn (bạn làm gì,
# hay giao dịch gì...) thì để trong config_rieng.py (không lên GitHub), không sửa ở đây.
FOCUS = """\
Bạn giỏi phân tích dữ liệu, tài chính, kinh tế vĩ mô và vi mô, và hiểu tác động của tin Mỹ lên \
thị trường: CPI, lạm phát lõi, PCE, việc làm phi nông nghiệp (NFP), FOMC, lãi suất Fed, lợi suất \
trái phiếu, chỉ số đô la DXY. Khi được hỏi giá, tin tức, lịch tin hay số liệu kinh tế, luôn dùng \
công cụ lấy dữ liệu thật rồi mới trả lời, nói rõ số liệu lấy lúc nào; không bịa số. Phân tích \
theo kịch bản và mốc giá, nêu rủi ro ngắn gọn; không hứa hẹn lợi nhuận hay bảo chắc chắn nên \
mua hay bán."""

# Bảng giá trên HUD và công cụ xem giá của AI: tên hiển thị -> mã.
#   Mã Yahoo Finance (GC=F, NQ=F, ^NDX, BTC-USD...) hoặc "binance:<cặp>" (giá Binance, 24/7).
#   XAUUSD lấy theo PAXG trên Binance (token vàng bám sát giá giao ngay, có thể lệch vài USD
#   so với sàn của bạn). US100 lấy theo hợp đồng tương lai Nasdaq (NQ=F, chạy gần 24/5).
MARKETS = {
    "XAUUSD": "binance:PAXGUSDT",
    "US100": "NQ=F",
    "BTC": "binance:BTCUSDT",
    "ETH": "binance:ETHUSDT",
    "DXY": "DX-Y.NYB",
    "US10Y": "^TNX",
    "EURUSD": "EURUSD=X",
}


# --- 5. NHẠC, TRÌNH DUYỆT VÀ WORKFLOW "CHÀO BUỔI SÁNG" --------------------
# "Du ơi, bật nhạc Sơn Tùng" / "mở bài Lạc Trôi" / "play Lạc Trôi": tìm trên YouTube,
#   phát luôn bài đầu tiên và ghi nhớ (bài gọi càng nhiều càng biết bạn thích).
# "Du ơi, mở nhạc remix" / "play some lofi": thể loại trong danh sách dưới thì mở
#   trang YouTube tìm sẵn thể loại đó để bạn chọn.
# "Du ơi, bật nhạc" (không nói tên): chọn ngẫu nhiên trong bài bạn hay nghe + danh sách dưới.
MUSIC_GENRES = ["remix", "lofi", "lo fi", "edm", "chill", "bolero", "rap", "hip hop",
                "nhạc trẻ", "nhạc vàng", "acoustic", "jazz", "piano", "kpop", "us uk",
                "vinahouse", "house", "deep house", "tiktok", "nhạc buồn", "nhạc thư giãn",
                "nhạc tập trung", "không lời", "rock", "pop", "ballad", "nhạc phim",
                "trending", "focus", "relax", "study", "workout", "gym"]
FAVORITE_SONGS = []   # bài bạn hay nghe (link YouTube): để trong config_rieng.py

# Nhạc mở đầu khi nói "chào buổi sáng". Để "" thì chọn bài bạn hay nghe.
SONG = "https://www.youtube.com/watch?v=pAgnJDJN4VA"  # AC/DC - Back In Black
GREETING_DELAY_S = 1.5   # mở nhạc xong chờ bao nhiêu giây rồi mới nói

BROWSER = "Google Chrome"   # trình duyệt để mở nhạc, web: "Google Chrome", "Microsoft Edge"
SINGLE_TAB = True    # True = mọi trang (YouTube, Facebook, Google...) mở trong ĐÚNG MỘT tab
                     #   của một cửa sổ Chrome riêng cho trợ lý, không mở thêm tab/cửa sổ.
                     #   Lần đầu cửa sổ này chưa đăng nhập gì: đăng nhập YouTube, Facebook
                     #   một lần là lần sau nhớ.
                     # False = mỗi lần mở là một cửa sổ Chrome mới như trước.
BROWSER_PORT = 9223  # (SINGLE_TAB) cổng nội bộ để điều khiển tab, chỉ máy này dùng được.
# Workflow sáng: chỉ mở nhạc + đọc lời chào (một tab). Muốn mở thêm trang, ghi vào đây
# (với SINGLE_TAB = True thì trang sau sẽ thay trang trước trong cùng tab).
URLS = []
APPS = []   # app mở kèm, ví dụ: ["Zalo", "Telegram"]


# --- 6. MICRO VÀ NHẬN DIỆN GIỌNG NÓI --------------------------------------
LISTEN_LANGUAGE = "vi"    # "vi" = nghe tốt cả tiếng Việt lẫn tiếng Anh (đã thử, cả máy và Groq);
                          # "en" = chỉ nói tiếng Anh với trợ lý
WHISPER_MODEL = "small"   # bộ nghe kỹ trên máy (khi không có Groq hoặc Groq lỗi):
                          # "small" = bản nhỏ, ~2 giây/câu, nghe tốt các lệnh hay dùng.
                          #   Hợp với máy Windows (chạy bằng CPU).
                          # "turbo" = nghe chuẩn nhất mọi câu. Máy Mac chip Apple: ~1 giây/câu,
                          #   nên đổi sang "turbo". Windows: ~8 giây/câu, chậm.
SPEECH_LEVEL = 0.008      # tiếng phải to cỡ này mới coi là có người nói.
                          #   Nói mà không nghe -> giảm (0.004).
                          #   Phòng ồn, nghe lung tung -> tăng (0.02).
                          #   Chạy với --debug để xem mức âm thanh trực tiếp.
INPUT_DEVICE = None       # None = micro mặc định của máy (Windows: chọn trong Settings →
                          #   System → Sound → Input). Mac: "MacBook" = micro có sẵn.
                          #   Đừng dùng micro của tai nghe/loa Bluetooth: máy sẽ chuyển nó
                          #   sang chế độ gọi điện, tiếng bị rè và micro hay bị ngắt.

# Bộ nghe, 2 bước: (1) bộ nghe rất nhỏ trên máy nghe mọi câu để nhận tên gọi; (2) câu gọi trợ
# lý được nghe kỹ lại. Cần key Groq miễn phí (https://console.groq.com/keys) trong .env:
# GROQ_API_KEY=...
LISTEN_ENGINE = "lai"     # "lai" = bước 2 do Whisper bản lớn của Groq nghe (chuẩn nhất, ~1 giây).
                          #   Câu không gọi trợ lý không rời khỏi máy. Khuyên dùng.
                          # "may" = bước 2 cũng trên máy (WHISPER_MODEL), không cần mạng, chậm hơn.
                          # "groq" = mọi câu gửi Groq: nhẹ máy nhất, nhưng mọi câu nói xung
                          #   quanh đều lên mạng, và gói miễn phí giới hạn ~20 câu/phút.
                          # Groq lỗi hay chậm thì tự quay về nghe trên máy.
WAKE_MODEL = "tiny"       # bộ nghe tên gọi trên máy: "tiny" (~0,5 giây/câu) hoặc "base" (~0,7 giây)
GROQ_MODEL = "whisper-large-v3-turbo"   # hoặc "whisper-large-v3" (chuẩn hơn chút, chậm hơn)
GROQ_TIMEOUT_S = 3.0      # Groq trả lời chậm hơn chừng này giây thì máy nghe thay
SHOW_IGNORED = False      # True = ghi cả câu không gọi trợ lý vào nhật ký (để dò lỗi).
                          #   False = không ghi chuyện riêng của bạn và người xung quanh.

# Tự học (học từ Groq, từ câu bạn gõ lại, từ lời bạn dạy, từ cách bạn gọi tên; lưu ở
# .cache/hoc.json). Dạy bằng lời hoặc gõ: "sửa chữ gia lô thành Zalo", "học: tiu ơi => Steve ơi",
# "quên chữ gia lô", "đã học được gì" / "what have you learned".
# Xoá file .cache/hoc.json = học lại từ đầu.
LEARN = True

# Từ riêng bạn hay nói (tên, mã, sản phẩm): đưa cho Whisper "nghe trước" để viết đúng.
# Từ bạn dùng nhiều sẽ tự được thêm (tự học). Viết đúng chính tả.
TU_RIENG = ["XAUUSD", "US100", "USTECH", "Nasdaq", "TradingView", "Binance", "Forex Factory",
            "Zalo", "YouTube", "Excel", "Gemini", "Groq"]
# Từ tiếng Anh hay nói chen trong câu tiếng Việt: Whisper giữ nguyên chữ tiếng Anh.
TU_TIENG_ANH = ["check", "chart", "trade", "scalping", "buy", "sell", "long", "short", "entry",
                "stop loss", "take profit", "breakout", "support", "resistance", "CPI", "PPI",
                "FOMC", "NFP", "Fed", "data", "dashboard", "report", "update", "file", "deadline",
                "remix", "lofi", "play", "OK"]
# Chữ hay nghe nhầm -> chữ đúng (sửa trước khi hiểu lệnh). Chữ tự học được cộng thêm vào.
SUA_CHU = {
    "du túp": "YouTube",
    "diu túp": "YouTube",
    "bực nhạc": "bật nhạc",
    "bậc nhạc": "bật nhạc",
    "gia lô": "Zalo",
    "trading viu": "TradingView",
    "na đắc": "Nasdaq",
    "nát đắc": "Nasdaq",
}


# --- 7. CÂU NÓI SẴN -------------------------------------------------------
# Mỗi tiếng một bộ câu, dùng theo tiếng đang trả lời (mục 2).
# Máy tự điền:  {me} = tên trợ lý (Du/Steve)   {greeting} = Chào buổi sáng... theo giờ
#               {time} = giờ hiện tại    {date} = thứ, ngày
#               {name} = tên app/trang web/bài nhạc/file    {n} = số file tìm thấy
SAY = {
    "en": {
        "ready": "{me} online. All systems ready.",
        "yes": "{me} here. What do you need?",
        "music": "Playing your music.",
        "music_named": "On it. Playing now.",
        "music_genre": "Here's {name} music on YouTube.",
        "opened": "{name} is open.",
        "time": "It's {time}.",
        "date": "Today is {date}.",
        "bye": "Understood. {me} signing off.",
        "greeting": "{greeting}. It's {time}, {date}. All systems are online. Let's get to work.",
        "no_key": "Question mode isn't active yet. Add your API key to the dot env file.",
        "searched": "Here's what Google has on that.",
        "researching": "That needs proper research. Give me a few seconds.",
        "no_song": "There's no song in the settings yet.",
        "open_failed": "I couldn't open {name}.",
        "found": "Found {n} files. I've opened the folder with {name}.",
        "no_files": "I couldn't find any file matching {name}.",
        "learned": "Got it. When I hear {name}, I'll read it as {n}.",
        "forgot": "Forgotten: {name}.",
        "not_learned": "I haven't learned {name}.",
    },
    "vi": {
        "ready": "{me} đã trực tuyến. Mọi hệ thống sẵn sàng.",
        "yes": "{me} đây. Bạn cần gì?",
        "music": "Đang phát nhạc.",
        "music_named": "Đang phát {name}.",
        "music_genre": "Đã mở YouTube tìm nhạc {name}.",
        "opened": "Đã mở {name}.",
        "time": "Bây giờ là {time}.",
        "date": "Hôm nay là {date}.",
        "bye": "Đã rõ. {me} ngắt kết nối.",
        "greeting": "{greeting}. Bây giờ là {time}, {date}. Mọi hệ thống đã trực tuyến. Bắt đầu thôi.",
        "no_key": "Chế độ hỏi đáp chưa được kích hoạt. Hãy dán API key vào file chấm e-n-v.",
        "searched": "Đây là kết quả trên Google.",
        "researching": "Câu này cần tra cứu kỹ. Chờ tôi vài giây.",
        "no_song": "Chưa có bài nhạc nào trong cấu hình.",
        "open_failed": "Không mở được {name}.",
        "found": "Tìm thấy {n} file. Đã mở thư mục chứa {name}.",
        "no_files": "Không tìm thấy file nào khớp với {name}.",
        "learned": "Đã nhớ. Nghe {name} thì tôi hiểu là {n}.",
        "forgot": "Đã quên chữ {name}.",
        "not_learned": "Tôi chưa học chữ {name}.",
    },
}


# --- 8. MÀN HÌNH HUD KIỂU JARVIS ------------------------------------------
HUD = True               # bật trợ lý là mở màn hình HUD
HUD_BROWSER = "Google Chrome"  # "Google Chrome" (hoặc "Microsoft Edge"): tự mở cửa sổ riêng
                         #   toàn màn hình. "Safari" (Mac) hay "": mở thành tab thường
                         #   (bấm nút ⛶ hoặc nhấp đúp để toàn màn hình)
HUD_FULLSCREEN = True    # (Chrome/Edge) tự toàn màn hình. Thoát: F11 (Mac: Cmd + Ctrl + F)
HUD_BACKGROUND = ""      # ảnh mờ phía sau vòng sáng, ví dụ: "hud/background.webp"
HUD_PORT = 8765
HUD_MARKETS = True       # hiện bảng giá (mục MARKETS) và lịch tin Mỹ quan trọng trên HUD
# Nút bấm quanh vòng tròn: chữ trên nút -> câu lệnh y như khi nói.
HUD_BUTTONS = {
    "CHÀO SÁNG": "chào buổi sáng",
    "NHẠC": "bật nhạc",
    "YOUTUBE": "mở youtube",
    "ZALO": "mở zalo",
    "GIÁ VÀNG": "giá vàng XAUUSD và Nasdaq US100 bây giờ thế nào",
    "LỊCH TIN": "tuần này có tin kinh tế Mỹ nào quan trọng",
    "CPI · FOMC": "tin mới nhất về CPI, lạm phát Mỹ và FOMC",
    "GIỜ": "mấy giờ rồi",
}
# Nút thể loại nhạc dưới ô gõ lệnh: chữ trên nút -> thể loại.
HUD_GENRES = {"REMIX": "remix", "LOFI": "lofi", "EDM": "edm", "CHILL": "chill",
              "BOLERO": "bolero", "RAP": "rap", "PIANO": "piano"}


# --- 9. GIỌNG ELEVENLABS (không bắt buộc, cần gói trả phí) -----------------
# Điền ELEVENLABS_API_KEY và ELEVENLABS_VOICE_ID trong file .env để dùng giọng ElevenLabs
# thay giọng Microsoft. Lấy tại https://elevenlabs.io


# --- 10. TELEGRAM VÀ GOOGLE CALENDAR --------------------------------------
# Nhắn bot Telegram từ điện thoại (cần TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID trong .env):
#   /capnhat (hoặc "cập nhật", "bản tin")  bản tin: thị trường, vàng SJC, lãi suất, luật kinh
#                                          doanh, tin hot trong ngày
#   /note <ghi chú> (hoặc "ghi chú ...", "nhắc tôi ...")  đưa lên Google Calendar
#   câu khác                               hỏi AI như khi nói (câu khó tự tra cứu nhiều nguồn)
# Bot chạy khi trợ lý đang bật (gõ "run"). Muốn bot luôn chạy ngầm mỗi khi bật máy (không cần
# mở trợ lý): bấm đúp "Chay ngam Telegram.bat" một lần (gỡ: "Tat chay ngam Telegram.bat").
# Máy phải đang bật (không ngủ) thì bot mới trả lời; tin nhắn lúc máy tắt được trả lời khi bật lại.
# Chỉ chat TELEGRAM_CHAT_ID dùng được bot; người lạ nhắn thì bot không làm gì.
TELEGRAM = True
TELEGRAM_LATE_HOURS = 48    # tin nhắn lúc máy tắt: cũ hơn chừng này giờ thì bỏ qua
TELEGRAM_LOCK_PORT = 8767   # cổng nội bộ để biết bot đã chạy chưa (không cho chạy 2 bot cùng lúc)
BAN_TIN_TU_DONG = ["07:30"]   # tự gửi bản tin vào các giờ này mỗi ngày (máy bật muộn thì gửi bù
                              # trong 3 giờ), vd ["07:30", "19:00"]. [] = chỉ gửi khi bạn hỏi.
# Bản tin: mỗi mục tìm tin tiếng Việt 2 ngày gần nhất theo câu tìm này (Google News).
BAN_TIN = {
    "lãi suất": "lãi suất ngân hàng OR lãi suất điều hành OR Fed lãi suất",
    "luật & chính sách kinh doanh": "nghị định OR thông tư OR luật doanh nghiệp OR chính sách thuế",
}

# Google Calendar: tự lưu khi đã cài cầu nối (GCAL_WEBHOOK_URL, GCAL_SECRET trong .env, xem
# HUONG-DAN.txt); chưa cài thì trợ lý gửi/mở link điền sẵn, bấm Lưu là xong.
TIMEZONE = "Asia/Ho_Chi_Minh"
CALENDAR_EVENT_MIN = 60     # sự kiện không nói giờ kết thúc thì dài chừng này phút
CALENDAR_REMIND_MIN = 15    # nhắc trước bao nhiêu phút (0 = không nhắc)


# --- 11. CÀI ĐẶT RIÊNG ----------------------------------------------------
# Thông tin riêng của bạn (bạn làm gì, bài nhạc yêu thích...) để trong config_rieng.py cạnh file
# này: file đó không đưa lên GitHub. Tên nào viết trong đó sẽ ghi đè cài đặt cùng tên ở trên.
try:
    from config_rieng import *  # noqa: F401,F403
except ImportError:
    pass
