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
