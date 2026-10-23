// Cầu nối để trợ lý Du / Steve (và bot Telegram) tự thêm ghi chú, lịch hẹn vào Google Calendar.
// Chạy trên chính tài khoản Google của bạn, chỉ ghi vào lịch chính (lịch mặc định) của bạn.
//
// Cài một lần (chi tiết trong HUONG-DAN.txt):
//   1. Mở https://script.google.com/create (đăng nhập Gmail có lịch muốn dùng).
//   2. Xoá hết chữ có sẵn, dán toàn bộ file này vào. Đổi MAT_KHAU bên dưới thành GCAL_SECRET
//      trong file .env của trợ lý (hai chỗ phải giống hệt nhau). Bấm Lưu.
//   3. Triển khai (Deploy) → Tùy chọn triển khai mới (New deployment) → loại: Ứng dụng web
//      (Web app). Thực thi với tư cách: Tôi (Me). Người có quyền truy cập: Bất kỳ ai (Anyone).
//      Bấm Triển khai, cho phép quyền truy cập lịch.
//   4. Chép URL ứng dụng web (…/exec) vào .env: GCAL_WEBHOOK_URL=…
// Không có MAT_KHAU đúng thì không ai thêm được gì vào lịch của bạn, dù biết URL.

const MAT_KHAU = "DOI-THANH-GCAL_SECRET-TRONG-FILE-.env";
const MUI_GIO = "Asia/Ho_Chi_Minh";

function doPost(e) {
  let d;
  try {
    d = JSON.parse(e.postData.contents);
  } catch (err) {
    return traLoi({ ok: false, loi: "dữ liệu hỏng" });
  }
  if (!MAT_KHAU || MAT_KHAU.startsWith("DOI-THANH") || d.secret !== MAT_KHAU) {
    return traLoi({ ok: false, loi: "sai mật khẩu" });
  }
  const lich = CalendarApp.getDefaultCalendar();
  const tieuDe = String(d.title || "Ghi chú").slice(0, 200);
  const moTa = { description: String(d.details || "") };
  let suKien;
  if (d.allDay) {
    const dau = Utilities.parseDate(String(d.start).slice(0, 10), MUI_GIO, "yyyy-MM-dd");
    const cuoi = Utilities.parseDate(String(d.end || d.start).slice(0, 10), MUI_GIO, "yyyy-MM-dd");
    suKien = cuoi > dau
      ? lich.createAllDayEvent(tieuDe, dau, new Date(cuoi.getTime() + 24 * 3600 * 1000), moTa)
      : lich.createAllDayEvent(tieuDe, dau, moTa);
  } else {
    const dau = Utilities.parseDate(String(d.start).slice(0, 16), MUI_GIO, "yyyy-MM-dd'T'HH:mm");
    const cuoi = d.end
      ? Utilities.parseDate(String(d.end).slice(0, 16), MUI_GIO, "yyyy-MM-dd'T'HH:mm")
      : new Date(dau.getTime() + 60 * 60 * 1000);
    suKien = lich.createEvent(tieuDe, dau, cuoi, moTa);
    if (Number(d.remindMinutes) > 0) suKien.addPopupReminder(Number(d.remindMinutes));
  }
  return traLoi({ ok: true, id: suKien.getId() });
}

// Mở URL trên trình duyệt để thử: thấy dòng này là đã triển khai đúng.
function doGet() {
  return traLoi({ ok: true, tin: "Cầu nối Google Calendar của trợ lý đang chạy." });
}

function traLoi(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
