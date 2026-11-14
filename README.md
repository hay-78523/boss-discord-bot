# 🤖 Discord AI Bot (Groq & Ollama + Vision + Team Memory)

Bot chat AI dành cho Discord viết bằng Python (`discord.py`), hỗ trợ song song **Groq** (miễn phí, tốc độ phản hồi cực nhanh) và **Ollama** (chạy model offline ngay trên máy).

## ✨ Tính năng chính
1. **Tag `@bot` hoặc Reply tin nhắn của thành viên trong team:**
   - Gọi trực tiếp `@TênBot câu hỏi...` ở bất kỳ kênh nào.
   - Reply trực tiếp vào tin nhắn của Bot để nói chuyện tiếp mà không cần tag lại.
   - **Reply vào tin nhắn của một thành viên khác trong team kèm tag `@TênBot`**: Bot sẽ tự động đọc nội dung chữ và cả hình ảnh trong tin nhắn gốc của thành viên đó để giải thích, tóm tắt, sửa lỗi code hoặc phân tích giúp bạn.
2. **Nhớ lịch sử hội thoại theo từng kênh:**
   - Lưu lịch sử cuộc trò chuyện kèm tên hiển thị của từng thành viên (`[Tên thành viên]: ...`) để nắm rõ mạch chuyện của cả nhóm.
3. **Đọc và phân tích hình ảnh (Vision):**
   - Gửi ảnh kèm tag `@TênBot` hoặc reply vào ảnh của thành viên trong nhóm kèm `@TênBot`, bot sẽ tự động chuyển sang model Vision để đọc và phân tích chi tiết ảnh.
4. **Slash Commands tiện lợi:**
   - `/reset`: Xoá bộ nhớ hội thoại của kênh hiện tại.
   - `/provider`: Đổi nhanh giữa `groq` và `ollama` (hoặc đổi model) ngay trên Discord.
   - `/persona`: Đổi tính cách / vai trò (System Prompt) cho bot.
   - `/status`: Kiểm tra model đang dùng và số tin nhắn đang nhớ.
   - `/tasks`: Xem task đang chạy (cả team hoặc từng người), task quá hạn được đánh dấu 🔴.
   - `/memory`: Xem / thêm / xoá trí nhớ dài hạn của team.
5. **Trợ lý công việc:**
   - Biết giờ hiện tại (giờ Việt Nam) nên hiểu đúng "mai", "thứ 6", "2 tiếng nữa".
   - Trí nhớ dài hạn: nói *"Boss nhớ giùm: deadline dự án X là 30/11"* — bot ghi lại và dùng cho các câu trả lời sau.
   - Nắm danh sách task đang chạy: hỏi *"ai đang trễ deadline?"*, *"task của @A còn gì?"*, *"đóng task landing page"*.
   - Nhắc việc và cảnh báo deadline (trước 1 tiếng và khi quá hạn) được lưu ra file, bot restart vẫn còn.
   - Tự retry và chuyển model dự phòng khi Groq bị giới hạn tốc độ.

---

## 🚀 Hướng dẫn cài đặt và chạy

### Bước 1: Tạo Bot trên Discord Developer Portal
1. Truy cập [Discord Developer Portal](https://discord.com/developers/applications) -> bấm **New Application**.
2. Vào mục **Bot** ở menu bên trái:
   - Bấm **Reset Token** để lấy `DISCORD_TOKEN`.
   - Kéo xuống phần **Privileged Gateway Intents**, **BẬT (ON)** các mục:
     - ✅ **Server Members Intent**
     - ✅ **Message Content Intent** *(Quan trọng để bot đọc được tin nhắn và hình ảnh)*
   - Bấm **Save Changes**.
3. Vào mục **OAuth2** -> **URL Generator**:
   - Phần **Scopes**: tích chọn `bot` và `applications.commands`.
   - Phần **Bot Permissions**: tích chọn `View Channels`, `Send Messages`, `Read Message History`, `Attach Files`, `Embed Links`.
   - Copy đường link ở dưới cùng dán vào trình duyệt để mời bot vào Server của bạn.

### Bước 2: Điền cấu hình vào file `.env`
Mở file `.env` và điền thông tin:
- **Nếu dùng Groq (Khuyên dùng - miễn phí & cực nhanh):**
  - Lấy API key miễn phí tại [https://console.groq.com/keys](https://console.groq.com/keys)
  - Điền vào `GROQ_API_KEY=...` và để `AI_PROVIDER=groq`.
- **Nếu dùng Ollama (Chạy local trên máy của bạn):**
  - Đổi `AI_PROVIDER=ollama`
  - Tải model về máy:
    ```bash
    ollama pull llama3.2
    ollama pull llama3.2-vision
    ```

### Bước 3: Cài đặt thư viện và chạy Bot
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

---

## 📊 Lưu dữ liệu lên Google Sheet

Bot lưu dữ liệu vào một Google Sheet gồm 4 tab (tự tạo nếu chưa có):

| Tab | Nội dung | Sửa tay được gì |
|---|---|---|
| **Tasks** | Toàn bộ task | Đổi *Hạn chót*, *Trạng thái* (`Đang làm` / `Hoàn thành` / `Huỷ`), *Giai đoạn*. **Thêm task mới**: chỉ cần điền *Giai đoạn*, *Nội dung*, *Người nhận* (gõ tên, không cần dấu), *Hạn chót* (`20/11/2026` hoặc `20/11/2026 17:00`) → bot tự tìm thành viên, đăng task lên kênh `#task` và tag người nhận |
| **Trí nhớ** | Những điều Boss ghi nhớ về team | Thêm/xoá dòng |
| **Nhắc việc** | Lời nhắc hẹn giờ | Thêm dòng: *Thời gian nhắc*, *Nội dung*, *Người nhận* |
| **Cài đặt** | Giai đoạn hiện tại, mốc gửi báo cáo | Thường không cần sửa |

Bot đọc lại Sheet mỗi ~3 phút. Không nên sửa các cột ID.

### Cài đặt
1. Vào [Google Cloud Console](https://console.cloud.google.com/) → tạo project → bật **Google Sheets API**.
2. **IAM & Admin → Service Accounts** → tạo service account → tab **Keys** → *Add key* → JSON (tải file key về).
3. Tạo một Google Sheet trống → bấm **Share** → dán email của service account (dạng `...@...iam.gserviceaccount.com`) → quyền **Editor**.
4. Trên Render (hoặc `.env`) thêm:
   - `TASK_SHEET_ID` = link Google Sheet
   - `GOOGLE_SERVICE_ACCOUNT_JSON` = toàn bộ nội dung file JSON key

## 📈 Giai đoạn & Báo cáo
- `/giaidoan ten:GĐ1 - Ra mắt` — đặt giai đoạn hiện tại; task giao từ đó được gắn nhãn giai đoạn. Lọc: `/tasks giai_doan:GĐ1`.
- Báo cáo sáng (Thứ 2 → Thứ 7, `DAILY_REPORT_TIME`, mặc định 08:30) vào `#task`: task quá hạn, hạn hôm nay, 3 ngày tới, khối lượng việc từng người.
- Tổng kết tuần (Thứ 6, `WEEKLY_REPORT_TIME`, mặc định 17:30): đã xong, tỉ lệ đúng hạn, tồn đọng theo từng người.
- Xem ngay: `/baocao` hoặc nói *"Boss báo cáo tình hình task"*.
