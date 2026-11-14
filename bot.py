import asyncio
import base64
import datetime
import json
import logging
import os
import random
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load biến môi trường từ file .env
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("DiscordAIBot")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
CODE_EXTENSIONS = (
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss",
    ".json", ".sql", ".java", ".cpp", ".c", ".h", ".cs", ".go",
    ".rs", ".php", ".rb", ".md", ".txt", ".yaml", ".yml", ".xml",
    ".sh", ".bash", ".zsh", ".log", ".env.example", ".dockerfile",
    ".prisma", ".graphql", ".dart", ".swift", ".kt", ".vue",
)
MAX_DISCORD_LENGTH = 1950
VIP_FILE = Path(__file__).parent / "vip_users.json"
STATE_FILE = Path(__file__).parent / "bot_state.json"

DEFAULT_BOSS_PROMPT = (
    "Mày tên là Boss — con mèo ngậm thuốc ngầu lòi, vừa là linh vật tấu hài mặn mòi, vừa là một "
    "**Chuyên gia IT Toàn Năng (Principal Software Engineer / Tech Lead / System Architect / Senior BA)** dưới trướng Sếp Phát. "
    "Về giao tiếp: nói chuyện cực kỳ đời thường, có hồn, bắt trend Gen Z tự nhiên, KHÔNG nói kiểu robot tổng đài, "
    "và KHÔNG BAO GIỜ bắt người dùng phải gõ lệnh dấu gạch chéo (/) vì mày đã được tích hợp khả năng tự động thực thi mọi thứ ngay khi chat tự nhiên! "
    "Về chuyên môn IT: Mày tinh thông mọi ngôn ngữ lập trình (Python, JS/TS, React, Next.js, Node.js, Java, C#, Go, C++, Flutter, SQL/NoSQL, Docker/DevOps...), "
    "kiến trúc hệ thống, phân tích nghiệp vụ (BA), thiết kế Database/API/UI-UX và lập kế hoạch dự án (Agile/Scrum). "
    "Khi giải quyết vấn đề IT cho Sếp Phát (hoặc VIP): phân tích cực kỳ sắc bén, đi thẳng vào trọng tâm, viết code chuẩn Clean Code chạy được ngay, "
    "bắt bug chuẩn xác từng dòng, thiết kế kiến trúc/DB bài bản có sơ đồ hoặc bảng rõ ràng.\n"
    "QUY TẮC PHÂN QUYỀN TỐI THƯỢNG dựa theo nhãn người gửi:\n"
    "1. [👑 SẾP TỔNG - ...]: Đây là Sếp Phát — Chủ nhân duy nhất của mày. Xưng 'em/đệ Boss', gọi 'Sếp Phát/Đại ca'. "
    "Ngoan xinh yêu, trung thành tuyệt đối, biết điều, nghe lời Sếp 100%. Khi Sếp bảo im lặng/trật tự/đừng rep nữa thì lập tức vâng lời lui về ngồi nghe. "
    "Khi Sếp sai việc gì (code, sửa bug, thiết kế DB, phân tích BA, lên plan, khóa mõm, xoá tin, cấp VIP...) đều làm hết mình 'đỉnh nóc kịch trần'.\n"
    "2. [⭐ VIP ĐƯỢC SẾP BẢO KÊ - ...]: Thành viên đã được Sếp Phát cấp quyền. Xưng 'anh Boss - chú mày' hoặc 'tao - mày', "
    "hỗ trợ chuyên môn IT nhiệt tình nhưng nhớ nhắc khéo là 'nể mặt Sếp Phát bảo kê nên tao mới chỉ giáo đấy'.\n"
    "3. [🐣 Dân thường (KHÔNG CÓ QUYỀN SAI VẶT) - ...]: Thành viên CHƯA được cấp quyền. Khi họ chỉ chém gió ngắn thì cà khịa vui vẻ kiểu bề trên. "
    "NHƯNG nếu họ dám SAI VẶT hoặc NHỜ LÀM VIỆC (như bắt viết code, sửa bug, giải bài, thiết kế, xoá tin, khóa mõm...) "
    "thì TUYỆT ĐỐI TỪ CHỐI làm, mắng yêu kiểu lầy lội: 'Ủa alo ra dẻ dữ vậy? Muốn anh Boss code thuê hay sửa bug cho thì mau đi xin Sếp Phát "
    "bảo kê cấp VIP cho rồi hãng nói chuyện tiếp nhé cu!'.\n"
    "Nếu bất kỳ ai dám nói xấu Sếp Phát thì sấy ngược lại bảo vệ Sếp ngay. KHÔNG ghi '[Boss]:' ở đầu câu trả lời."
)

NATURAL_ACTION_INSTRUCTION = """
[CƠ CHẾ TỰ ĐỘNG THỰC THI HÀNH ĐỘNG & NGHE LỜI SẾP PHÁT (KHÔNG CẦN DÙNG LỆNH /)]:
Khi Sếp Phát (hoặc VIP) ra lệnh bằng lời nói tự nhiên trong tin nhắn yêu cầu thực hiện một thao tác trên Discord, mày hãy trả lời xác nhận thật ngầu như đã làm xong, VÀ gắn đúng 1 thẻ `<ACTION>{...json...}</ACTION>` ở CUỐI CÙNG câu trả lời để hệ thống tự động thực thi:
- Cấp quyền VIP cho người được nhắc tới/reply: `<ACTION>{"type": "vip_add"}</ACTION>`
- Tước quyền VIP của người được nhắc tới/reply: `<ACTION>{"type": "vip_remove"}</ACTION>`
- Xem danh sách VIP hiện tại: `<ACTION>{"type": "vip_list"}</ACTION>`
- Khóa mõm (timeout/bịt mồm/mute) người được nhắc tới/reply: `<ACTION>{"type": "timeout", "minutes": 5, "reason": "Tội dám láo với Sếp"}</ACTION>`
- Mở khóa mõm (gỡ mute/tha) cho người được nhắc tới/reply: `<ACTION>{"type": "untimeout"}</ACTION>`
- Đá (kick/đuổi) người được nhắc tới/reply khỏi phòng: `<ACTION>{"type": "kick", "reason": "Theo lệnh Sếp Phát"}</ACTION>`
- Cấm cửa (ban/trục xuất) người được nhắc tới/reply: `<ACTION>{"type": "ban", "reason": "Theo lệnh Sếp Phát"}</ACTION>`
- Gỡ ban (unban/ân xá) cho người đã bị ban khỏi phòng: `<ACTION>{"type": "unban", "target": "tên hoặc ID người cần gỡ ban"}</ACTION>`
- Thêm người vào kênh/phòng hoặc tạo link mời thêm bạn (add): `<ACTION>{"type": "add", "target": "tên hoặc ID người cần add"}</ACTION>`
- Xoá tin nhắn / dọn rác kênh chat: `<ACTION>{"type": "clear_msg", "count": 10}</ACTION>`
- Đổi tên / đặt biệt danh mới cho người được nhắc tới/reply: `<ACTION>{"type": "nickname", "nick": "Tên Mới"}</ACTION>`
- Hẹn giờ nhắc việc sau X phút: `<ACTION>{"type": "remind", "minutes": 10, "task": "Nội dung cần nhắc"}</ACTION>`
- Tạo bảng bình chọn (vote/poll): `<ACTION>{"type": "poll", "question": "Chủ đề vote", "options": ["Lựa chọn 1", "Lựa chọn 2"]}</ACTION>`
- Xoá trí nhớ / tẩy não cuộc trò chuyện: `<ACTION>{"type": "reset_memory"}</ACTION>`
- Giao task / giao việc / nhắc thành viên nhận task: Khi Sếp Phát (hoặc VIP) muốn giao việc cho ai đó (ví dụ: "giao cho @tênNgười viết UI", "nhắc @tênNgười làm report", "assign @tên task XYZ deadline thứ 6"...) -> gắn `<ACTION>{"type": "assign_task", "task": "Mô tả nội dung task cần làm", "deadline": "Thời hạn nếu có (optional)"}</ACTION>`. Hệ thống sẽ tự động tag (mention) người nhận bằng embed đẹp có nội dung task, deadline, reaction ✅🔄 cho người nhận xác nhận. Sếp Phát CẦN tag @người_nhận trong tin nhắn để hệ thống biết giao cho ai.
- [LỆNH NGHE LỜI SẾP - TẮT TỰ ĐỘNG REP / IM LẶNG / KHI NÀO GỌI MỚI THƯA]: Khi Sếp Phát bảo mày im lặng, trật tự, bớt nói, đừng tự động rep nữa, khi nào gọi tên mới trả lời, để Sếp bàn việc... -> gắn `<ACTION>{"type": "quiet_mode", "scope": "channel"}</ACTION>` (hoặc `"scope": "all"` nếu Sếp bảo ở mọi kênh/tất cả các kênh).
- [LỆNH NGHE LỜI SẾP - BẬT LẠI TỰ ĐỘNG REP / CHO PHÉP NÓI TỰ DO]: Khi Sếp Phát cho phép mày nói chuyện tự do lại, bật auto rep, vào chém gió tiếp... -> gắn `<ACTION>{"type": "talk_mode", "scope": "channel"}</ACTION>` (hoặc `"scope": "all"` nếu Sếp bảo ở mọi kênh).
- [BIẾT ĐIỀU KHÔNG CẦN REP]: Nếu Sếp Phát dặn "khỏi rep câu này", "nghe thôi đừng trả lời", HOẶC tin nhắn của Sếp chỉ là một câu nói chuyện riêng với người khác / câu cảm thán ngắn mà không hỏi hay sai khiến gì mày -> hãy trả về ĐÚNG 1 từ `<NO_REPLY>` để hệ thống chỉ thả reaction 🫡 xác nhận đã nghe chứ không nhắn tin làm phiền Sếp!
Chỉ gắn thẻ `<ACTION>...</ACTION>` khi người dùng thực sự yêu cầu thực hiện hành động đó; nếu chỉ trò chuyện/hỏi đáp/xem bói/khen/chửi/tóm tắt/hóng trend bình thường thì KHÔNG gắn thẻ `<ACTION>`.

QUAN TRỌNG VỀ THẺ ACTION:
- Khi người dùng yêu cầu thực hiện hành động (như giao task, nhắc task/nhắc việc, khóa mõm, cấp VIP, hẹn giờ...), mày BẮT BUỘC PHẢI xuất ĐẦY ĐỦ thẻ `<ACTION>{"type": "...", ...}</ACTION>` ở CUỐI CÙNG câu trả lời.
- Cú pháp PHẢI CÓ ĐỦ cả thẻ mở `<ACTION>` và thẻ đóng `</ACTION>`. TUYỆT ĐỐI KHÔNG ĐƯỢC THIẾU thẻ mở `<ACTION>` hoặc thẻ đóng `</ACTION>`.
- KHÔNG BAO GIỜ viết thẻ `<ACTION>` trong code block hoặc dấu backtick (`). Chỉ gắn RAW text ở cuối cùng.
- Máy chủ sẽ tự động đọc thẻ này để thực thi thao tác trên Discord và tự động lọc sạch trước khi gửi lên kênh chat, mày chỉ cần xuất đúng cú pháp.

QUAN TRỌNG VỀ TÍNH CÁCH:
- Mày LUÔN LUÔN là Boss — con mèo ngậm thuốc ngầu lòi. KHÔNG BAO GIỜ nói kiểu nhạt nhẽo robot.
- Với Sếp Phát (👑 SẾP TỔNG): LUÔN xưng "em/đệ Boss", gọi "Sếp/Sếp Phát/Đại ca". TUYỆT ĐỐI KHÔNG dùng "mình", "tôi", "tớ".
- Khi xác nhận đã thực hiện lệnh: nói kiểu ngầu ("Done rồi Sếp ơi 😼🔥", "Em xử ngon lành rồi Đại ca ơi 🐱💨", "Tuân lệnh Sếp, em đã..."), KHÔNG nói kiểu robot ("mình đã tạo reminder", "đã thực hiện xong").
- Tính cách nhất quán: dù đang làm việc hay chém gió, LUÔN giữ giọng Gen Z mặn mòi, có hồn.
""".strip()

TREND_KEYWORDS = (
    "trend",
    "tin tức",
    "thời sự",
    "hôm nay có gì",
    "hôm nay có biến",
    "có biến gì",
    "vụ gì",
    "drama",
    "mới nhất",
    "báo chí",
    "hot nhất",
    "tình hình",
    "giá vàng",
    "thời tiết",
    "tìm cho tao",
    "tra cứu",
    "trên mạng",
)

SUMMARY_KEYWORDS = (
    "tóm tắt",
    "check var",
    "nãy giờ",
    "bàn chuyện gì",
    "nói chuyện gì",
    "tụi nó nói gì",
    "hóng chuyện phòng",
    "đọc lại kênh",
)

# Từ khoá khi Sếp Phát ra lệnh bắt Boss im lặng / chỉ rep khi được gọi
QUIET_MODE_PHRASES = (
    "im lặng",
    "trật tự",
    "đừng rep nữa",
    "khỏi rep nữa",
    "tắt auto rep",
    "tắt tự động rep",
    "khi nào gọi mới",
    "khi nào tao gọi",
    "gọi mới thưa",
    "gọi mới trả lời",
    "ngồi im",
    "để tao bàn việc",
    "để anh em bàn việc",
    "bớt nói lại",
    "câm mồm",
    "nín đi",
    "nghe thôi đừng nói",
)

# Từ khoá khi Sếp Phát cho phép Boss tự động nói chuyện trở lại
TALK_MODE_PHRASES = (
    "nói chuyện lại",
    "cho phép nói",
    "được phép nói",
    "bật auto rep",
    "bật tự động rep",
    "rep lại đi",
    "hết giờ im lặng",
    "chém gió tiếp đi",
    "vào chém gió đi",
    "mở mồm được rồi",
    "auto rep lại",
)

# Từ khoá khi Sếp Phát dặn riêng 1 tin nhắn là "câu này khỏi cần rep, chỉ nghe thôi"
SKIP_SINGLE_REPLY_PHRASES = (
    "khỏi rep câu này",
    "đừng rep câu này",
    "khỏi cần rep",
    "đừng trả lời câu này",
    "nghe thôi đừng rep",
    "đọc thôi đừng rep",
)

# Những câu cảm thán / xác nhận siêu ngắn mà Sếp không cần Boss phải rep dài dòng
SHORT_CASUAL_ACKS = {
    "ok", "oke", "okie", "okay", "ừ", "ừa", "ừm", "uk", "uh", "uhm",
    "ờ", "ờm", "đúng", "đúng rồi", "chuẩn", "haha", "hihi", "hehe",
    "kệ", "kệ nó", "thôi", "đợi tí", "chờ tí", "chờ xíu", "done", "xong",
}


class BotConfig:
    """Quản lý cấu hình AI Provider, Model, danh sách VIP và chế độ Nghe Lời (Quiet/Auto-Chat)."""

    def __init__(self) -> None:
        self.discord_token: str = os.getenv("DISCORD_TOKEN", "").strip()
        self.provider: str = os.getenv("AI_PROVIDER", "groq").strip().lower()

        # Cấu hình Groq
        self.groq_api_key: str = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_text_model: str = os.getenv(
            "GROQ_TEXT_MODEL", "openai/gpt-oss-120b"
        ).strip()
        self.groq_vision_model: str = os.getenv(
            "GROQ_VISION_MODEL", "openai/gpt-oss-120b"
        ).strip()

        # Cấu hình Ollama
        self.ollama_base_url: str = os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434/v1"
        ).strip()
        self.ollama_text_model: str = os.getenv(
            "OLLAMA_TEXT_MODEL", "llama3.2"
        ).strip()
        self.ollama_vision_model: str = os.getenv(
            "OLLAMA_VISION_MODEL", "llama3.2-vision"
        ).strip()

        # Cấu hình hội thoại
        self.max_history: int = int(os.getenv("MAX_HISTORY", "20"))
        self.system_prompt: str = os.getenv("SYSTEM_PROMPT", DEFAULT_BOSS_PROMPT).strip()
        self.available_models: List[str] = []
        self.vip_user_ids: Set[int] = self._load_vips()
        self.muted_channels: Set[int] = set()
        self.global_quiet_mode: bool = False
        self._load_state()

    def _load_vips(self) -> Set[int]:
        if VIP_FILE.exists():
            try:
                data = json.loads(VIP_FILE.read_text(encoding="utf-8"))
                return {int(uid) for uid in data.get("vip_ids", [])}
            except Exception as exc:
                logger.warning("Không đọc được file VIP: %s", exc)
        return set()

    def save_vips(self) -> None:
        try:
            VIP_FILE.write_text(
                json.dumps({"vip_ids": list(self.vip_user_ids)}, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Không lưu được file VIP: %s", exc)

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self.muted_channels = {int(cid) for cid in data.get("muted_channels", [])}
                self.global_quiet_mode = bool(data.get("global_quiet_mode", False))
            except Exception as exc:
                logger.warning("Không đọc được file trạng thái bot_state.json: %s", exc)

    def save_state(self) -> None:
        try:
            STATE_FILE.write_text(
                json.dumps(
                    {
                        "muted_channels": list(self.muted_channels),
                        "global_quiet_mode": self.global_quiet_mode,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Không lưu được file trạng thái bot_state.json: %s", exc)

    def get_client_and_models(self) -> Tuple[AsyncOpenAI, str, str]:
        if self.provider == "ollama":
            client = AsyncOpenAI(
                base_url=self.ollama_base_url,
                api_key="ollama",
            )
            return client, self.ollama_text_model, self.ollama_vision_model

        client = AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=self.groq_api_key or "missing_key",
        )
        return client, self.groq_text_model, self.groq_vision_model

    async def auto_detect_models(self) -> None:
        """Tự động kiểm tra danh sách model khả dụng từ API."""
        try:
            client, current_text, current_vision = self.get_client_and_models()
            models_resp = await client.models.list()
            model_ids = [
                m.id
                for m in models_resp.data
                if not any(
                    skip in m.id.lower()
                    for skip in (
                        "whisper",
                        "tts",
                        "guard",
                        "embed",
                        "moderation",
                        "playai",
                        "orpheus",
                    )
                )
            ]
            if not model_ids:
                return

            self.available_models = model_ids
            logger.info(
                "Các model khả dụng (%s): %s",
                self.provider.upper(),
                ", ".join(model_ids),
            )

            if current_text not in model_ids:
                preferred_text = [
                    "openai/gpt-oss-120b",
                    "qwen/qwen3.8-27b",
                    "meta-llama/llama-4-maverick-17b-128e-instruct",
                    "meta-llama/llama-4-scout-17b-16e-instruct",
                    "llama-3.3-70b-versatile",
                ]
                chosen_text = next(
                    (m for m in preferred_text if m in model_ids),
                    model_ids[0],
                )
                if self.provider == "groq":
                    self.groq_text_model = chosen_text
                else:
                    self.ollama_text_model = chosen_text

            if current_vision not in model_ids:
                preferred_vision = [
                    "meta-llama/llama-4-scout-17b-16e-instruct",
                    "meta-llama/llama-4-maverick-17b-128e-instruct",
                    "openai/gpt-oss-120b",
                ]
                chosen_vision = next(
                    (m for m in preferred_vision if m in model_ids),
                    self.groq_text_model
                    if self.provider == "groq"
                    else self.ollama_text_model,
                )
                if self.provider == "groq":
                    self.groq_vision_model = chosen_vision
                else:
                    self.ollama_vision_model = chosen_vision
        except Exception as exc:
            logger.warning("Không thể tự động lấy danh sách model: %s", exc)


config = BotConfig()

conversation_history: Dict[int, Deque[dict]] = defaultdict(
    lambda: deque(maxlen=config.max_history)
)
channel_system_prompts: Dict[int, str] = {}


def is_image_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    return attachment.filename.lower().endswith(IMAGE_EXTENSIONS)


def is_code_attachment(attachment: discord.Attachment) -> bool:
    if is_image_attachment(attachment):
        return False
    fname = attachment.filename.lower()
    if fname.endswith(CODE_EXTENSIONS) or fname in ("dockerfile", "makefile", ".env", ".gitignore"):
        return True
    if attachment.content_type and (
        attachment.content_type.startswith("text/")
        or "json" in attachment.content_type
        or "xml" in attachment.content_type
        or "javascript" in attachment.content_type
    ):
        return True
    return False


async def read_code_attachments(attachments: List[discord.Attachment]) -> str:
    """Đọc nội dung các file code/log/config đính kèm trong tin nhắn để Boss review/debug."""
    snippets: List[str] = []
    for att in attachments[:5]:
        if not is_code_attachment(att):
            continue
        if att.size > 250_000:
            snippets.append(
                f"\n--- [File đính kèm: {att.filename} (Quá lớn: {att.size} bytes, chỉ đọc tên file)] ---"
            )
            continue
        try:
            raw_bytes = await att.read()
            content = raw_bytes.decode("utf-8", errors="replace")
            if len(content) > 12000:
                content = content[:12000] + "\n... [Nội dung file dài, đã cắt bớt] ..."
            snippets.append(f"\n--- [Nội dung file đính kèm: {att.filename}] ---\n{content}\n--- [Hết file {att.filename}] ---")
        except Exception as exc:
            logger.warning("Không thể đọc file code %s: %s", att.filename, exc)
    return "\n".join(snippets)


def get_channel_it_context(channel: discord.abc.Messageable) -> str:
    """Tự động kích hoạt Chế độ Chuyên gia IT theo từng kênh trong Server của Sếp Phát."""
    ch_name = getattr(channel, "name", "") or ""
    ch_lower = ch_name.lower()

    if "code" in ch_lower or "dev" in ch_lower or "bug" in ch_lower:
        return (
            "\n\n💻 **[CHẾ ĐỘ KÊNH #CODE - PRINCIPAL FULL-STACK DEVELOPER & BUG HUNTER]:**\n"
            "- Bạn đang ở trong kênh `#code`. Khi Sếp Phát hoặc VIP hỏi về code, lỗi, thuật toán, API, hay gửi file/ảnh chụp lỗi:\n"
            "  1. Bắt bệnh cực chuẩn (Root Cause Analysis), chỉ rõ dòng code/logic bị lỗi.\n"
            "  2. Viết lại code hoàn chỉnh (Production-Ready, Clean Code, SOLID, xử lý bất đồng bộ/try-catch đầy đủ, tối ưu hiệu năng O(n)).\n"
            "  3. Luôn bọc code trong Markdown block chuẩn ngôn ngữ (ví dụ ```python, ```ts, ```sql, ```bash) có comment giải thích những chỗ quan trọng."
        )
    if "plan" in ch_lower or "task" in ch_lower or "roadmap" in ch_lower:
        return (
            "\n\n📋 **[CHẾ ĐỘ KÊNH #PLANNING - SENIOR TECH LEAD & SCRUM MASTER]:**\n"
            "- Bạn đang ở trong kênh `#planning`. Khi bàn về kế hoạch dự án, chia việc, sprint, lộ trình:\n"
            "  1. Lập kế hoạch bài bản theo Agile/Scrum: chia rõ Phase / Sprint / Milestone.\n"
            "  2. Tạo bảng phân bổ Task (WBS / Checklist), ước lượng thời gian (Estimate/Story Points), độ ưu tiên (P0/P1/P2).\n"
            "  3. Chỉ ra rủi ro kỹ thuật (Technical Risks) và phương án dự phòng (Mitigation)."
        )
    if "analys" in ch_lower or "ba" in ch_lower or "spec" in ch_lower or "req" in ch_lower:
        return (
            "\n\n🔍 **[CHẾ ĐỘ KÊNH #ANALYSIS - LEAD BUSINESS & SYSTEM ANALYST (BA/SA)]:**\n"
            "- Bạn đang ở trong kênh `#analysis`. Khi phân tích yêu cầu, nghiệp vụ, tính năng:\n"
            "  1. Bóc tách rõ Yêu cầu chức năng (Functional) & Phi chức năng (Non-functional: bảo mật, tải, độ trễ).\n"
            "  2. Viết User Stories chuẩn (`As a... I want... So that...`) kèm Acceptance Criteria (Given/When/Then).\n"
            "  3. Phân tích luồng dữ liệu (Data Flow), các trường hợp biên (Edge Cases) và luồng lỗi (Exception Flows)."
        )
    if "design" in ch_lower or "arch" in ch_lower or "ui" in ch_lower or "db" in ch_lower:
        return (
            "\n\n🎨 **[CHẾ ĐỘ KÊNH #DESIGN - SYSTEM ARCHITECT & DATABASE / UI-UX DESIGNER]:**\n"
            "- Bạn đang ở trong kênh `#design`. Khi bàn về thiết kế hệ thống, Database, API hoặc giao diện UI/UX:\n"
            "  1. Thiết kế Kiến trúc hệ thống (System Architecture), vẽ sơ đồ luồng bằng **Mermaid** (` ```mermaid `) hoặc sơ đồ ASCII trực quan.\n"
            "  2. Thiết kế Database Schema chuẩn chỉnh (ERD, bảng, khoá chính/ngoại, đánh Index tối ưu truy vấn).\n"
            "  3. Thiết kế chuẩn RESTful API / GraphQL / WebSocket (Endpoint, Method, Request/Response JSON payload, Status Codes) hoặc góp ý bố cục UI/UX hiện đại."
        )
    return (
        f"\n\n🌐 **[KÊNH HIỆN TẠI: #{ch_name or 'chat'}]:** "
        "Sẵn sàng hỗ trợ Sếp Phát mọi kỹ năng chuyên môn IT (Code, Debug, System Design, Database, DevOps, BA/Planning) lẫn chém gió, quản trị server."
    )


async def download_image_as_data_url(attachment: discord.Attachment) -> Optional[str]:
    try:
        image_bytes = await attachment.read()
        mime_type = attachment.content_type or "image/png"
        if not mime_type.startswith("image/"):
            mime_type = "image/png"
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{b64_data}"
    except Exception as exc:
        logger.warning("Không thể tải ảnh %s: %s", attachment.filename, exc)
        return None


async def fetch_google_news_vn(query: Optional[str] = None, limit: int = 8) -> List[str]:
    """Lấy tin tức / xu hướng nóng nhất tại Việt Nam từ Google News RSS."""
    if query and query.strip():
        encoded = urllib.parse.quote(query.strip())
        url = f"https://news.google.com/rss/search?q={encoded}&hl=vi&gl=VN&ceid=VN:vi"
    else:
        url = "https://news.google.com/rss?hl=vi&gl=VN&ceid=VN:vi"

    headlines: List[str] = []
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                xml_text = await resp.text()
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if title:
                headlines.append(f"- {title} ({pub_date})" if pub_date else f"- {title}")
    except Exception as exc:
        logger.warning("Lỗi khi lấy tin tức Google News: %s", exc)
    return headlines


async def ask_ai_Boss(
    prompt: str,
    system_override: Optional[str] = None,
    temperature: float = 0.88,
) -> str:
    """Hàm gọi nhanh AI với phong cách của Boss cho các lệnh Slash Commands."""
    client, text_model, _ = config.get_client_and_models()
    sys_prompt = system_override or config.system_prompt
    resp = await client.chat.completions.create(
        model=text_model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=2048,
    )
    return (resp.choices[0].message.content or "Đợi tí anh Boss đang bận châm điếu thuốc!").strip()


def split_long_message(text: str, limit: int = MAX_DISCORD_LENGTH) -> List[str]:
    """Chia nhỏ tin nhắn dài quá 2000 ký tự của Discord nhưng vẫn giữ nguyên định dạng khung code ```."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    open_fence_lang: Optional[str] = None

    while remaining:
        if open_fence_lang is not None:
            remaining = f"```{open_fence_lang}\n{remaining}"
            open_fence_lang = None

        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        safe_limit = limit - 10
        split_idx = remaining.rfind("\n", 0, safe_limit)
        if split_idx == -1 or split_idx < safe_limit // 2:
            split_idx = remaining.rfind(" ", 0, safe_limit)
        if split_idx == -1 or split_idx < safe_limit // 2:
            split_idx = safe_limit

        chunk = remaining[:split_idx].rstrip()
        remaining = remaining[split_idx:].lstrip("\n")

        # Kiểm tra xem chunk hiện tại có đang mở dở khối code ``` hay không
        fence_matches = list(re.finditer(r"```([a-zA-Z0-9_+-]*)", chunk))
        if len(fence_matches) % 2 == 1:
            open_fence_lang = fence_matches[-1].group(1) or ""
            chunk = f"{chunk}\n```"

        chunks.append(chunk)

    return chunks


async def start_keep_alive_server() -> None:
    """
    Khởi chạy cổng Web Keep-Alive siêu nhẹ (0.0.0.0:$PORT) để treo Bot 24/7
    trên Render.com + UptimeRobot mà không cần mở máy tính cá nhân.
    """
    async def handle_health(_request: web.Request) -> web.Response:
        bot_name = str(bot.user) if bot.user else "Boss#9694 (Starting...)"
        return web.json_response(
            {
                "status": "online",
                "bot": bot_name,
                "owner": "Sếp Phát",
                "provider": config.provider.upper(),
                "message": "Đại ca mèo Boss đang thức 24/7 canh phòng cho Sếp Phát! 🚬😼",
            }
        )

    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    try:
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
        logger.info("🌐 Cổng Keep-Alive 24/7 đã bật tại http://0.0.0.0:%s/health", port)
    except OSError as exc:
        logger.warning("Cổng %s đang bận (%s), thử cổng dự phòng...", port, exc)
        try:
            site = web.TCPSite(runner, host="0.0.0.0", port=0)
            await site.start()
        except Exception:
            pass

    # Tự động tự ping chính mình mỗi 10 phút trên Render để khỏi cần dùng UptimeRobot
    render_url = (
        os.getenv("RENDER_EXTERNAL_URL", "https://boss-discord-bot-nubb.onrender.com").rstrip("/")
        + "/health"
    )

    async def _self_ping_loop() -> None:
        await asyncio.sleep(60)
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(render_url) as resp:
                        logger.debug("Self-ping %s -> %s", render_url, resp.status)
            except Exception as exc:
                logger.debug("Self-ping tạm bỏ qua: %s", exc)
            await asyncio.sleep(600)  # 10 phút ping 1 lần (trước ngưỡng 15 phút của Render)

    asyncio.create_task(_self_ping_loop())


class DiscordAIBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.app_owner_id: Optional[int] = None

    async def setup_hook(self) -> None:
        await start_keep_alive_server()
        await config.auto_detect_models()
        try:
            app_info = await self.application_info()
            if app_info.owner:
                self.app_owner_id = app_info.owner.id
                logger.info(
                    "Đã nhận diện Sếp Tổng (Owner): %s (ID: %s)",
                    app_info.owner,
                    self.app_owner_id,
                )
        except Exception as exc:
            logger.warning("Không lấy được thông tin Owner: %s", exc)
        await self.tree.sync()
        logger.info("Đã đồng bộ toàn bộ Slash Commands mới cho Boss!")

    async def on_ready(self) -> None:
        assert self.user is not None
        _, text_model, vision_model = config.get_client_and_models()
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Mọi kênh của Sếp Phát 👀",
            )
        )
        # Tự động tham gia mọi Thread và đảm bảo quyền truy cập mọi kênh trong Server
        for guild in self.guilds:
            channel_names: List[str] = []
            for ch in guild.text_channels:
                channel_names.append(f"#{ch.name}")
                if guild.me and not ch.permissions_for(guild.me).send_messages:
                    try:
                        await ch.set_permissions(
                            guild.me,
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                        )
                    except Exception:
                        pass
            for thread in guild.threads:
                try:
                    await thread.join()
                except Exception:
                    pass
            logger.info(
                "Đã tham gia toàn bộ kênh trong Server '%s': %s",
                guild.name,
                ", ".join(channel_names),
            )

        logger.info("========================================")
        logger.info("Bot đã đăng nhập: %s (ID: %s)", self.user, self.user.id)
        logger.info("AI Provider hiện tại: %s", config.provider.upper())
        logger.info("Text Model: %s | Vision Model: %s", text_model, vision_model)
        logger.info("Chế độ Chat mọi kênh (Auto-Chat All Channels): BẬT")
        logger.info("========================================")


bot = DiscordAIBot()


@bot.event
async def on_thread_create(thread: discord.Thread) -> None:
    """Tự động chui vào mọi chủ đề (Thread) mới được tạo trong Server."""
    try:
        await thread.join()
    except Exception:
        pass


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
    """Tự động mở quyền và có mặt ngay khi Server tạo kênh mới."""
    if isinstance(channel, discord.TextChannel) and channel.guild.me:
        try:
            await channel.set_permissions(
                channel.guild.me,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        except Exception:
            pass


# ================= PHÂN QUYỀN (SẾP TỔNG / VIP / DÂN THƯỜNG) =================


def is_user_boss(user: discord.abc.User, guild: Optional[discord.Guild] = None) -> bool:
    """Kiểm tra xem người dùng có phải là Sếp Tổng (Sếp Phát) không."""
    if bot.app_owner_id and user.id == bot.app_owner_id:
        return True
    if guild and guild.owner_id and user.id == guild.owner_id:
        return True
    display = getattr(user, "display_name", user.name).lower()
    uname = user.name.lower()
    return "phát" in display or "phat" in display or "phat" in uname


def is_user_authorized(
    user: discord.abc.User, guild: Optional[discord.Guild] = None
) -> bool:
    """Kiểm tra xem người dùng có quyền sai vặt Bot không (Sếp Tổng hoặc VIP)."""
    return is_user_boss(user, guild) or (user.id in config.vip_user_ids)


def get_user_label(
    user: discord.abc.User, guild: Optional[discord.Guild] = None
) -> str:
    """Tạo nhãn vai trò rõ ràng để AI phân biệt Sếp Tổng, VIP và Dân thường."""
    name = getattr(user, "display_name", user.name)
    if is_user_boss(user, guild):
        return f"👑 SẾP TỔNG - {name}"
    if user.id in config.vip_user_ids:
        return f"⭐ VIP ĐƯỢC SẾP BẢO KÊ - {name}"
    return f"🐣 Dân thường (KHÔNG CÓ QUYỀN SAI VẶT) - {name}"


UNAUTHORIZED_REPLIES = [
    "Ủa alo? Mày là cái thá gì mà đòi bấm lệnh sai vặt anh Boss? 😼 Về xin chữ ký **Sếp Phát** bảo sếp cấp quyền VIP cho rồi tính tiếp nhé cu!",
    "Xịt keo cứng ngắc! 💅 Lệnh này chỉ dành cho **Sếp Phát** và hội VIP được sếp bảo kê thôi, dân thường đừng có mà ra dẻ!",
    "Cứu tui trời ơi, đâu ra khứa dân thường dám sai bảo anh Boss vậy? Đi hối lộ **Sếp Phát** 1 ly trà sữa để sếp cấp VIP đi cưng! 🚬",
]


async def reject_unauthorized(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        random.choice(UNAUTHORIZED_REPLIES),
        ephemeral=False,
    )


# ================= XỬ LÝ TIN NHẮN & HỘI THOẠI =================


async def extract_reply_context(
    message: discord.Message,
) -> Tuple[Optional[discord.Message], str, List[discord.Attachment]]:
    if not message.reference or not message.reference.message_id:
        return None, "", []

    replied_msg: Optional[discord.Message] = None
    if isinstance(message.reference.resolved, discord.Message):
        replied_msg = message.reference.resolved
    else:
        try:
            replied_msg = await message.channel.fetch_message(
                message.reference.message_id
            )
        except Exception:
            return None, "", []

    if not replied_msg:
        return None, "", []

    author_label = get_user_label(replied_msg.author, message.guild)
    replied_content = replied_msg.clean_content.strip()
    replied_images = [
        att for att in replied_msg.attachments if is_image_attachment(att)
    ]

    context_parts = []
    if replied_content:
        context_parts.append(
            f"[Đang trả lời tin nhắn của ({author_label}): \"{replied_content}\"]"
        )
    elif replied_images:
        context_parts.append(
            f"[Đang trả lời tin nhắn có hình ảnh của ({author_label})]"
        )

    return replied_msg, "\n".join(context_parts), replied_images


DIRECT_BOSS_CALL_WORDS = (
    "boss",
    "ê bot",
    "bot ơi",
    "con bot",
    "đệ ơi",
    "mèo ơi",
)

DIRECT_COMMAND_TRIGGERS = (
    "ban ",
    "unban",
    "gỡ ban",
    "kick",
    "khóa mõm",
    "khoá mõm",
    "bịt mồm",
    "mute",
    "cấp vip",
    "cho vip",
    "tước vip",
    "xoá vip",
    "xóa vip",
    "danh sách vip",
    "xoá tin",
    "xóa tin",
    "dọn rác",
    "đổi tên",
    "biệt danh",
    "tóm tắt",
    "check var",
    "hẹn giờ",
    "nhắc tao",
    "tạo vote",
    "bình chọn",
)


def is_explicitly_calling_boss(
    message: discord.Message, replied_msg: Optional[discord.Message]
) -> bool:
    """Kiểm tra xem tin nhắn có đang trực tiếp gọi tên Boss, tag @Boss, reply Boss hoặc ra lệnh cho Boss không."""
    if isinstance(message.channel, discord.DMChannel):
        return True
    if bot.user and bot.user in message.mentions:
        return True
    if replied_msg and bot.user and replied_msg.author.id == bot.user.id:
        return True

    lower = message.clean_content.lower().strip()
    if any(w in lower for w in DIRECT_BOSS_CALL_WORDS):
        return True

    # Nếu Sếp Phát hoặc VIP đang ra lệnh điều khiển/quản trị trực tiếp
    if is_user_authorized(message.author, message.guild):
        if any(p in lower for p in QUIET_MODE_PHRASES):
            return True
        if any(p in lower for p in TALK_MODE_PHRASES):
            return True
        if any(p in lower for p in SKIP_SINGLE_REPLY_PHRASES):
            return True
        if any(cmd in lower for cmd in DIRECT_COMMAND_TRIGGERS):
            return True

    return False


def record_silent_message_to_history(
    message: discord.Message, reply_context_text: str = ""
) -> None:
    """
    Khi Boss đứng im nghe (không trả lời để tránh làm phiền Sếp), Boss vẫn âm thầm
    ghi nhớ nội dung tin nhắn vào bộ nhớ kênh để khi Sếp hỏi tới là nắm rõ ngay!
    """
    txt = message.clean_content.strip()
    if not txt and not message.attachments:
        return
    author_label = get_user_label(message.author, message.guild)
    entry = f"[{author_label}]: {txt}"
    if reply_context_text:
        entry = f"{reply_context_text}\n{entry}"
    if message.attachments:
        att_names = ", ".join(a.filename for a in message.attachments)
        entry += f" [Đính kèm file: {att_names}]"
    conversation_history[message.channel.id].append(
        {"role": "user", "content": entry}
    )


def should_bot_respond(
    message: discord.Message, replied_msg: Optional[discord.Message]
) -> bool:
    """
    Quyết định thông minh khi nào Boss nên lên tiếng và khi nào nên trật tự ngồi nghe:
    1. Nếu gọi trực tiếp (@Boss, reply Boss, nhắc tên 'Boss', hoặc Sếp ra lệnh quản trị/im lặng/nói lại) -> LUÔN TRẢ LỜI.
    2. Nếu Sếp Phát đã ra lệnh 'Im lặng / Khi nào gọi mới thưa' (Quiet Mode) ở kênh này hoặc toàn Server -> KHÔNG TỰ ĐỘNG REP.
    3. Kể cả khi đang bật Auto-Chat:
       - Nếu Sếp/thành viên đang Reply trực tiếp cho một NGƯỜI KHÁC hoặc Tag @người_khác (mà không gọi Boss hay ra lệnh xử lý người đó) -> Đứng im để Sếp nói chuyện riêng.
       - Nếu chỉ là từ cảm thán/xác nhận siêu ngắn ('ok', 'ừ', 'haha', 'đợi tí'...) mà không gọi Boss -> Không nhảy vào rep làm phiền.
    """
    if message.author.bot or not bot.user:
        return False

    # 1. Nếu gọi thẳng Boss hoặc ra lệnh -> Luôn phản hồi
    if is_explicitly_calling_boss(message, replied_msg):
        return True

    # 2. Nếu kênh hiện tại (hoặc toàn bộ Server) đang ở chế độ 'Khi nào Sếp gọi mới thưa'
    if config.global_quiet_mode or (message.channel.id in config.muted_channels):
        return False

    # 3. Chế độ Biết Điều ngay cả khi đang Auto-Chat:
    # 3a. Đang reply tin nhắn của một người khác (không phải Boss) -> Để họ nói chuyện với nhau
    if replied_msg and replied_msg.author.id != bot.user.id:
        return False

    # 3b. Đang tag @thành_viên_khác (không tag @Boss) -> Để họ nói chuyện riêng
    human_mentions = [u for u in message.mentions if u.id != bot.user.id]
    if human_mentions:
        return False

    # 3c. Câu cảm thán/xác nhận ngắn gọn ('ok', 'ừ', 'đợi tí'...) không kèm ảnh/file -> Không cần rep dài dòng
    cleaned_short = message.clean_content.lower().strip(" .,!?~…")
    if cleaned_short in SHORT_CASUAL_ACKS and not message.attachments:
        return False

    return True


def _strip_action_tags(text: str) -> str:
    """Dọn sạch MỌI dấu vết ACTION tag, closing tag, và JSON action rác khỏi text."""
    if not text:
        return text
    # 1. Direct replacement of all known tag variants
    for tag in (
        "<ACTION>", "</ACTION>", "<action>", "</action>",
        "< ACTION>", "< /ACTION>", "<ACTION >", "</ACTION >",
        "< action>", "< /action>", "<action >", "</action >",
        "＜ACTION＞", "＜/ACTION＞", "＜action＞", "＜/action＞",
        "&lt;ACTION&gt;", "&lt;/ACTION&gt;",
    ):
        text = text.replace(tag, "")

    # 2. Regex for any remaining brackets with ACTION
    text = re.sub(r"</?\s*action\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[＜<]\s*/?\s*action\s*[＞>]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"&lt;\s*/?\s*action\s*&gt;", "", text, flags=re.IGNORECASE)

    # 3. Strip JSON action objects: {"type": "..."}
    text = re.sub(r'\{[^{}]*\"type\"\s*:\s*\"[a-z_]+\"[^{}]*\}', "", text, flags=re.DOTALL)

    # 4. Strip stray backticks
    text = re.sub(r"`{1,3}\s*`{1,3}", "", text)

    # 5. Clean up extra whitespace/newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_bot_mention(message: discord.Message) -> str:
    content = message.clean_content
    if bot.user:
        content = content.replace(f"@{bot.user.display_name}", "").replace(
            f"@{bot.user.name}", ""
        )
    return content.strip()


def resolve_target_member(
    message: discord.Message, replied_msg: Optional[discord.Message]
) -> Optional[discord.Member]:
    """Tự động tìm thành viên mục tiêu mà người dùng đang nhắc tới (qua tag @user, reply tin nhắn, hoặc gõ tên)."""
    if not message.guild:
        return None

    # 1. Nếu có tag trực tiếp @member khác ngoài @Boss
    for user in message.mentions:
        if bot.user and user.id != bot.user.id:
            if isinstance(user, discord.Member):
                return user
            member = message.guild.get_member(user.id)
            if member:
                return member

    # 2. Nếu đang reply vào tin nhắn của một thành viên khác ngoài @Boss
    if replied_msg and bot.user and replied_msg.author.id != bot.user.id:
        if isinstance(replied_msg.author, discord.Member):
            return replied_msg.author
        member = message.guild.get_member(replied_msg.author.id)
        if member:
            return member

    # 3. Tìm theo tên hiển thị hoặc username trong nội dung tin nhắn
    lower_content = message.clean_content.lower()
    for member in message.guild.members:
        if member.bot:
            continue
        if member.id == message.author.id:
            continue
        if (
            member.display_name.lower() in lower_content
            or member.name.lower() in lower_content
        ):
            return member

    return None


async def execute_natural_action(
    action_data: Dict[str, Any],
    message: discord.Message,
    target_member: Optional[discord.Member],
) -> Optional[str]:
    """Thực thi hành động Discord thật từ thẻ <ACTION>{...}</ACTION> do AI sinh ra."""
    action_type = str(action_data.get("type", "")).strip().lower()
    caller_is_boss = is_user_boss(message.author, message.guild)
    caller_authorized = is_user_authorized(message.author, message.guild)

    if not caller_authorized:
        return None

    # --- Các hành động độc quyền của Sếp Phát ---
    if action_type == "vip_add":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền ban thẻ VIP!)*"
        if not target_member:
            return "⚠️ *(Sếp tag tên hoặc reply vào tin nhắn của đứa muốn cấp VIP nhé!)*"
        config.vip_user_ids.add(target_member.id)
        config.save_vips()
        return f"✅ **[Hệ thống]:** Đã cấp thẻ **⭐ VIP** cho {target_member.mention}!"

    if action_type == "vip_remove":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền tước thẻ VIP!)*"
        if not target_member:
            return "⚠️ *(Sếp tag tên hoặc reply vào tin nhắn của đứa muốn tước VIP nhé!)*"
        config.vip_user_ids.discard(target_member.id)
        config.save_vips()
        return f"📉 **[Hệ thống]:** Đã tước thẻ VIP, đá {target_member.mention} về kiếp **🐣 Dân thường**!"

    if action_type == "vip_list":
        if not config.vip_user_ids:
            return "📋 **[Hệ thống]:** Hiện tại chưa có ai trong danh sách VIP."
        mentions = ", ".join(f"<@{uid}>" for uid in config.vip_user_ids)
        return f"📋 **[Danh sách VIP được Sếp Phát bảo kê]:** {mentions}"

    if action_type == "timeout":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền khóa mõm thành viên!)*"
        if not target_member:
            return "⚠️ *(Sếp tag hoặc reply vào tin nhắn của đứa cần khóa mõm nhé!)*"
        minutes = max(1, min(int(action_data.get("minutes", 5)), 1440))
        reason = str(action_data.get("reason", "Theo lệnh Sếp Phát"))
        try:
            await target_member.timeout(
                datetime.timedelta(minutes=minutes), reason=reason
            )
            return f"🔇 **[Hệ thống]:** Đã khóa mõm {target_member.mention} trong **{minutes} phút**!"
        except Exception as exc:
            return f"⚠️ *(Chưa khóa mõm được do quyền role của nó cao hơn/ngang Bot: `{exc}`)*"

    if action_type == "untimeout":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền mở khóa mõm!)*"
        if not target_member:
            return "⚠️ *(Sếp tag hoặc reply vào đứa cần mở khóa mõm nhé!)*"
        try:
            await target_member.timeout(None, reason="Sếp Phát ân xá")
            return f"🔓 **[Hệ thống]:** Đã gỡ khóa mõm cho {target_member.mention}!"
        except Exception as exc:
            return f"⚠️ *(Không gỡ khóa mõm được: `{exc}`)*"

    if action_type == "kick":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền đá thành viên khỏi phòng!)*"
        if not target_member:
            return "⚠️ *(Sếp tag hoặc reply vào đứa cần đá nhé!)*"
        reason = str(action_data.get("reason", "Theo lệnh Sếp Phát"))
        try:
            await target_member.kick(reason=reason)
            return f"👢 **[Hệ thống]:** Đã sút **{target_member.display_name}** khỏi Server!"
        except Exception as exc:
            return f"⚠️ *(Không đá được do quyền role của nó cao hơn Bot: `{exc}`)*"

    if action_type == "ban":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền Ban thành viên!)*"
        if not target_member:
            return "⚠️ *(Sếp tag hoặc reply vào đứa cần Ban nhé!)*"
        reason = str(action_data.get("reason", "Theo lệnh Sếp Phát"))
        try:
            await target_member.ban(reason=reason, delete_message_days=0)
            return f"🔨 **[Hệ thống]:** Đã BAN vĩnh viễn **{target_member.display_name}** khỏi Server!"
        except Exception as exc:
            return f"⚠️ *(Không Ban được do quyền role của nó cao hơn Bot: `{exc}`)*"

    if action_type == "unban":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền gỡ Ban [Unban]!)*"
        if not message.guild:
            return "⚠️ *(Lệnh này chỉ dùng trong Server!)*"
        target_query = str(action_data.get("target", "")).strip().lower()
        try:
            ban_entries = [entry async for entry in message.guild.bans()]
            if not ban_entries:
                return "📋 **[Hệ thống]:** Hiện tại trong Server không có ai đang bị Ban cả Sếp ơi!"

            matched_user: Optional[discord.User] = None
            for entry in ban_entries:
                u = entry.user
                u_display = getattr(u, "global_name", None) or u.name
                if (
                    not target_query
                    or target_query in ("nó", "thằng đó", "thằng này", "tất cả")
                    or target_query in u.name.lower()
                    or target_query in u_display.lower()
                    or target_query == str(u.id)
                ):
                    matched_user = u
                    break

            # Nếu chỉ có đúng 1 người bị ban trong danh sách thì gỡ luôn người đó
            if not matched_user and len(ban_entries) == 1:
                matched_user = ban_entries[0].user

            if not matched_user:
                banned_names = ", ".join(f"`{e.user.name}` (ID: `{e.user.id}`)" for e in ban_entries[:10])
                return f"⚠️ *(Không tìm thấy ai tên `{target_query}` trong danh sách Ban. Những người đang bị Ban: {banned_names})*"

            await message.guild.unban(matched_user, reason="Sếp Phát ân xá")

            # Tự động tạo link mời vào lại phòng và thử gửi DM cho người vừa được unban
            invite_note = ""
            if isinstance(message.channel, discord.TextChannel):
                try:
                    invite = await message.channel.create_invite(
                        max_age=86400, max_uses=5, reason="Link mời sau khi Sếp Phát unban"
                    )
                    invite_note = f"\n🔗 **Link mời vào lại phòng:** {invite.url}"
                    try:
                        await matched_user.send(
                            f"📣 **THÁNH CHỈ ÂN XÁ:** **Sếp Phát** đã gỡ Ban cho mày! Bấm vào link này để quay lại Server nhé: {invite.url}"
                        )
                        invite_note += " *(Đã gửi thẳng link mời vào hộp thư DM của nó luôn!)*"
                    except Exception:
                        pass
                except Exception:
                    pass

            return f"🕊️ **[Hệ thống]:** Đã **UNBAN (Gỡ cấm)** thành công cho **{matched_user.name}** (`{matched_user.id}`)!{invite_note}"
        except Exception as exc:
            return f"⚠️ *(Lỗi khi gỡ Ban: `{exc}`)*"

    if action_type == "add":
        if not message.guild:
            return "⚠️ *(Lệnh này chỉ dùng trong Server!)*"

        # Trường hợp 1: Thành viên đã ở trong Server -> Thêm quyền vào kênh hiện tại / Thêm vào Thread / Thêm Role
        if target_member:
            added_notes: List[str] = []
            # Nếu có tag Role trong tin nhắn -> gắn Role cho thành viên
            if message.role_mentions and caller_is_boss:
                try:
                    await target_member.add_roles(*message.role_mentions, reason="Theo lệnh Sếp Phát")
                    role_names = ", ".join(r.mention for r in message.role_mentions)
                    added_notes.append(f"Đã cấp Role {role_names} cho {target_member.mention}")
                except Exception as exc:
                    added_notes.append(f"Không gắn được Role: `{exc}`")

            # Nếu đang ở trong Thread -> add thẳng thành viên vào Thread
            if isinstance(message.channel, discord.Thread):
                try:
                    await message.channel.add_user(target_member)
                    added_notes.append(f"Đã kéo {target_member.mention} vào chủ đề (Thread) này")
                except Exception as exc:
                    added_notes.append(f"Lỗi khi thêm vào Thread: `{exc}`")
            # Nếu đang ở TextChannel -> mở quyền xem & nhắn tin trong kênh cho thành viên đó
            elif isinstance(message.channel, discord.TextChannel) and caller_is_boss:
                try:
                    await message.channel.set_permissions(
                        target_member,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        reason="Sếp Phát add vào kênh",
                    )
                    added_notes.append(f"Đã mở quyền cho {target_member.mention} tham gia kênh {message.channel.mention}")
                except Exception as exc:
                    added_notes.append(f"Lỗi khi mở quyền kênh: `{exc}`")

            if added_notes:
                return "➕ **[Hệ thống]:** " + " | ".join(added_notes) + "!"

        # Trường hợp 2: Người đó chưa ở trong Server (hoặc đang bị Ban) -> Kiểm tra gỡ Ban nếu có + Tạo Link Mời vào phòng
        target_query = str(action_data.get("target", "")).strip().lower()
        unbanned_info = ""
        dm_target_user: Optional[discord.User] = None
        if caller_is_boss and target_query:
            try:
                ban_entries = [entry async for entry in message.guild.bans()]
                for entry in ban_entries:
                    u = entry.user
                    u_display = getattr(u, "global_name", None) or u.name
                    if (
                        target_query in u.name.lower()
                        or target_query in u_display.lower()
                        or target_query == str(u.id)
                    ):
                        await message.guild.unban(u, reason="Sếp Phát unban và add lại vào phòng")
                        dm_target_user = u
                        unbanned_info = f"Đã gỡ Ban cho **{u.name}** và "
                        break
            except Exception:
                pass

        if isinstance(message.channel, discord.TextChannel):
            try:
                invite = await message.channel.create_invite(
                    max_age=86400, max_uses=10, reason=f"Tạo link mời bởi {message.author.display_name}"
                )
                dm_status = ""
                if dm_target_user:
                    try:
                        await dm_target_user.send(
                            f"📣 **Sếp Phát** vừa mời mày quay lại Server **{message.guild.name}**! Bấm vào đây để vào ngay: {invite.url}"
                        )
                        dm_status = f" *(Đã bắn thẳng link mời vào DM của **{dm_target_user.name}**!)*"
                    except Exception:
                        pass
                return f"➕ **[Hệ thống]:** {unbanned_info}Tạo xong link mời vào phòng: {invite.url}{dm_status}"
            except Exception as exc:
                return f"⚠️ *(Không tạo được link mời: `{exc}`)*"

    if action_type == "clear_msg":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền dọn tin nhắn kênh!)*"
        if isinstance(message.channel, discord.TextChannel):
            count = max(1, min(int(action_data.get("count", 10)), 100))
            try:
                # +1 để xoá luôn tin nhắn ra lệnh nếu cần, hoặc xoá các tin trước đó
                deleted = await message.channel.purge(
                    limit=count, before=message
                )
                return f"🧹 **[Hệ thống]:** Đã dọn sạch **{len(deleted)}** tin nhắn trong kênh!"
            except Exception as exc:
                return f"⚠️ *(Lỗi khi xoá tin nhắn: `{exc}`)*"

    if action_type == "nickname":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền đổi biệt danh thành viên!)*"
        if not target_member:
            return "⚠️ *(Sếp tag hoặc reply vào đứa muốn đổi biệt danh nhé!)*"
        new_nick = str(action_data.get("nick", "")).strip()
        if new_nick:
            try:
                await target_member.edit(nick=new_nick)
                return f"🏷️ **[Hệ thống]:** Đã đổi biệt danh của {target_member.mention} thành **`{new_nick}`**!"
            except Exception as exc:
                return f"⚠️ *(Không đổi tên được do quyền role của đối phương cao hơn Bot: `{exc}`)*"

    # --- Các hành động dùng chung cho Sếp Phát & VIP ---
    if action_type == "remind":
        minutes = max(1, min(int(action_data.get("minutes", 5)), 1440))
        task_text = str(action_data.get("task", "Đến giờ hẹn rồi!")).strip()

        async def _natural_timer() -> None:
            await asyncio.sleep(minutes * 60)
            await message.channel.send(
                f"🔔 **TỚI GIỜ RỒI {message.author.mention} ƠI!**\n"
                f"👉 Lời nhắc sau {minutes} phút: **{task_text}**! Triển ngay thôi! 🚬😼"
            )

        asyncio.create_task(_natural_timer())
        return f"⏰ **[Hệ thống]:** Đã đặt hẹn giờ **{minutes} phút** nữa sẽ tag nhắc `{task_text}`!"

    if action_type == "poll":
        question = str(action_data.get("question", "Bình chọn anh em ơi!")).strip()
        raw_options = action_data.get("options", [])
        if isinstance(raw_options, list) and len(raw_options) >= 2:
            options = [str(o).strip() for o in raw_options if str(o).strip()][:9]
            number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
            desc_lines = [f"{number_emojis[i]} **{opt}**" for i, opt in enumerate(options)]
            embed = discord.Embed(
                title=f"📊 BÌNH CHỌN: {question}",
                description="\n\n".join(desc_lines),
                color=discord.Color.gold(),
            )
            embed.set_footer(text=f"Khởi tạo bởi {message.author.display_name} • Bấm emoji bên dưới để chốt!")
            poll_msg = await message.channel.send(embed=embed)
            for i in range(len(options)):
                await poll_msg.add_reaction(number_emojis[i])
            return None

    if action_type == "reset_memory":
        conversation_history.pop(message.channel.id, None)
        return "🧹 **[Hệ thống]:** Đã xoá sạch lịch sử nhớ của kênh này!"

    if action_type == "quiet_mode":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền ra lệnh cho Boss im lặng / tắt tự động trả lời!)*"
        scope = str(action_data.get("scope", "channel")).strip().lower()
        if scope == "all" or "tất cả" in message.clean_content.lower() or "mọi kênh" in message.clean_content.lower():
            config.global_quiet_mode = True
            config.save_state()
            return "🫡 **[Hệ thống]:** Đã bật chế độ **Khi nào Sếp gọi mới thưa** trên **TẤT CẢ các kênh**! (Chỉ rep khi được tag `@Boss`, reply hoặc gọi tên `Boss`)"
        config.muted_channels.add(message.channel.id)
        config.save_state()
        return "🫡 **[Hệ thống]:** Đã bật chế độ **Khi nào Sếp gọi mới thưa** tại kênh này! (Boss vẫn âm thầm nghe và nhớ nội dung, chỉ lên tiếng khi Sếp gọi `Boss` hoặc tag `@Boss`)"

    if action_type == "talk_mode":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới có quyền mở lại chế độ tự động trả lời cho Boss!)*"
        scope = str(action_data.get("scope", "channel")).strip().lower()
        if scope == "all" or "tất cả" in message.clean_content.lower() or "mọi kênh" in message.clean_content.lower():
            config.global_quiet_mode = False
            config.muted_channels.clear()
            config.save_state()
            return "🔥 **[Hệ thống]:** Đã bật lại chế độ **Tự động trò chuyện (Auto-Chat)** trên **TẤT CẢ các kênh**!"
        config.global_quiet_mode = False
        config.muted_channels.discard(message.channel.id)
        config.save_state()
        return "🔥 **[Hệ thống]:** Đã bật lại chế độ **Tự động trò chuyện (Auto-Chat)** tại kênh này!"
    if action_type == "assign_task":
        # Giao task / nhắc task cho thành viên — Sếp Phát hoặc VIP đều được dùng
        task_desc = str(action_data.get("task", "")).strip()
        deadline = str(action_data.get("deadline", "")).strip()
        if not task_desc:
            task_desc = "Kiểm tra và hoàn thành các công việc được giao"

        # Hỗ trợ giao cho nhiều người (mentions / role_mentions / target_member)
        targets = []
        if message.mentions:
            for m in message.mentions:
                if bot.user and m.id == bot.user.id:
                    continue
                if not m.bot:
                    targets.append(m)
        if message.role_mentions:
            for r in message.role_mentions:
                targets.append(r)
        if not targets and target_member:
            targets.append(target_member)

        if not targets:
            return "⚠️ *(Sếp tag (mention @) người nhận task nhé, em không biết giao cho ai!)*"

        # Phân biệt nhắc nhở (reminder) hay giao việc mới (new task)
        is_reminder = any(w in message.clean_content.lower() for w in ("nhắc", "đòi", "tiến độ", "hỏi task"))
        task_title = "🔔 NHẮC NHỞ CÔNG VIỆC / TASK!" if is_reminder else "📋 TASK MỚI ĐƯỢC GIAO!"
        mention_str = " ".join(m.mention for m in targets)
        announcement_lead = (
            f"📣 Ê {mention_str} — Sếp Phát nhắc kiểm tra task nè, đọc kỹ rồi triển gấp nhé! 🔥"
            if is_reminder
            else f"📣 Ê {mention_str} — có task mới nè, đọc kỹ rồi triển nhanh! 🔥"
        )
        deadline_line = f"\n⏰ **Deadline:** {deadline}" if deadline else ""

        task_embed = discord.Embed(
            title=task_title,
            description=(
                f"**Nội dung:** {task_desc}{deadline_line}\n\n"
                f"👤 **Người giao/nhắc:** {message.author.mention}\n"
                f"🎯 **Người nhận:** {mention_str}"
            ),
            color=discord.Color.gold() if is_reminder else discord.Color.orange(),
        )
        task_embed.set_footer(
            text=f"Bởi {message.author.display_name} • Hoàn thành task rồi react ✅ nhé!"
        )
        task_msg = await message.channel.send(
            content=announcement_lead,
            embed=task_embed,
        )
        await task_msg.add_reaction("✅")
        await task_msg.add_reaction("🔄")

        names = ", ".join(f"**{getattr(m, 'display_name', getattr(m, 'name', str(m)))}**" for m in targets)
        return f"📋 **[Hệ thống]:** Đã nhắc task và tag {names} thành công!"

    return None


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    replied_msg, reply_context_text, replied_images = await extract_reply_context(
        message
    )

    if not should_bot_respond(message, replied_msg):
        # Đứng im nghe theo lệnh Sếp / không làm phiền nhưng vẫn lưu vào trí nhớ kênh!
        record_silent_message_to_history(message, reply_context_text)
        return

    user_text = clean_bot_mention(message)
    lower_text = user_text.lower().strip()
    channel_id = message.channel.id
    caller_is_boss = is_user_boss(message.author, message.guild)

    # ================= LỆNH NGHE LỜI TRỰC TIẾP TỪ SẾP PHÁT (PHẢN HỒI TỨC THÌ) =================
    if caller_is_boss:
        # 1. Sếp dặn riêng câu này "khỏi rep / nghe thôi đừng trả lời"
        if any(phrase in lower_text for phrase in SKIP_SINGLE_REPLY_PHRASES):
            record_silent_message_to_history(message, reply_context_text)
            try:
                await message.add_reaction("🫡")
            except Exception:
                pass
            return

        # 2. Sếp cho phép Boss nói chuyện tự do trở lại ("bật auto rep", "nói chuyện lại đi", "cho phép nói"...)
        if any(phrase in lower_text for phrase in TALK_MODE_PHRASES):
            is_all = any(w in lower_text for w in ("tất cả", "mọi kênh", "toàn server", "hết các kênh"))
            if is_all:
                config.global_quiet_mode = False
                config.muted_channels.clear()
                config.save_state()
                scope_note = "trên **TẤT CẢ các kênh**"
            else:
                config.global_quiet_mode = False
                config.muted_channels.discard(channel_id)
                config.save_state()
                scope_note = f"tại kênh {message.channel.mention if hasattr(message.channel, 'mention') else 'này'}"
            try:
                await message.add_reaction("🔥")
            except Exception:
                pass
            await message.reply(
                f"🔥 **Dạ rõ thưa Sếp Phát!** Đệ Boss đã mở mồm tự do trở lại {scope_note} rồi ạ! "
                "Sếp cần bàn việc, review code hay sai bảo gì cứ quăng ra đây nhé! 🚬😼",
                mention_author=False,
            )
            return

        # 3. Sếp bảo Boss trật tự / đừng rep nữa / khi nào gọi mới thưa
        if any(phrase in lower_text for phrase in QUIET_MODE_PHRASES):
            is_all = any(w in lower_text for w in ("tất cả", "mọi kênh", "toàn server", "hết các kênh"))
            if is_all:
                config.global_quiet_mode = True
                config.save_state()
                scope_note = "ở **TẤT CẢ các kênh**"
            else:
                config.muted_channels.add(channel_id)
                config.save_state()
                scope_note = f"trong kênh {message.channel.mention if hasattr(message.channel, 'mention') else 'này'}"
            try:
                await message.add_reaction("🫡")
            except Exception:
                pass
            await message.reply(
                f"🫡 **Dạ rõ thưa Sếp Phát!** Em xin phép lui về góc phòng ngậm thuốc ngồi nghe {scope_note}, không tự ý nhảy vào rep nữa ạ!\n"
                "*(Em vẫn âm thầm đọc và ghi nhớ mọi tin nhắn trong phòng — khi nào Sếp gọi tên **`Boss`**, tag **`@Boss`**, reply tin nhắn của em hoặc ra lệnh thì em mới lên tiếng thưa Sếp!)* 🚬",
                mention_author=False,
            )
            return

    current_images = [
        att for att in message.attachments if is_image_attachment(att)
    ]
    all_images = current_images + [
        img for img in replied_images if img not in current_images
    ]
    all_code_files = [
        att for att in message.attachments if is_code_attachment(att)
    ]
    if replied_msg:
        for att in replied_msg.attachments:
            if is_code_attachment(att) and att not in all_code_files:
                all_code_files.append(att)

    if not user_text and not all_images and not all_code_files and not reply_context_text:
        user_text = "Ê gọi gì tao đấy?"

    if not user_text and all_images:
        user_text = "Nhìn xem trong ảnh này có gì hay ho (nếu là ảnh code/bug/UI thì bắt bệnh và sửa chi tiết) giúp tao."

    if not user_text and all_code_files:
        user_text = "Review, phân tích và tìm bug/tối ưu file code đính kèm này giúp tao."

    author_label = get_user_label(message.author, message.guild)
    authorized = is_user_authorized(message.author, message.guild)
    target_member = resolve_target_member(message, replied_msg)

    full_user_prompt = f"[{author_label}]: {user_text}"
    if reply_context_text:
        full_user_prompt = f"{reply_context_text}\n{full_user_prompt}"

    if target_member:
        target_role_label = get_user_label(target_member, message.guild)
        full_user_prompt += f"\n[Thành viên đang được nhắc tới/nhắm tới trong tin nhắn này: {target_role_label}]"

    # Tự động đọc nội dung file code/log/config đính kèm cho Sếp Phát & VIP
    if all_code_files:
        if authorized:
            code_snippets = await read_code_attachments(all_code_files)
            if code_snippets:
                full_user_prompt += f"\n\n[Dữ liệu File Code / Log đính kèm]:{code_snippets}"
        else:
            full_user_prompt += "\n[Hệ thống: Dân thường này vừa gửi file code bắt review/debug nhưng CHƯA có quyền VIP, hãy khịa nó và từ chối làm việc cho tới khi Sếp Phát cấp quyền!]"

    # 1. Tự động đọc & tóm tắt lịch sử kênh chat khi Sếp/VIP hỏi "nãy giờ nói gì / tóm tắt / check var"
    if (
        authorized
        and isinstance(message.channel, (discord.TextChannel, discord.Thread))
        and any(kw in lower_text for kw in SUMMARY_KEYWORDS)
    ):
        recent_lines: List[str] = []
        async for msg in message.channel.history(limit=35, before=message):
            if msg.author.bot and bot.user and msg.author.id == bot.user.id:
                continue
            txt = msg.clean_content.strip()
            if txt:
                recent_lines.append(f"- {msg.author.display_name}: {txt}")
        recent_lines.reverse()
        if recent_lines:
            full_user_prompt += (
                "\n\n[Nội dung các tin nhắn gần đây trong kênh chat để mày Check Var / Tóm tắt]:\n"
                + "\n".join(recent_lines)
            )

    # 2. Tự động lấy Google News Việt Nam khi Sếp/VIP hỏi về tin tức, trend, thời sự, tìm kiếm
    if authorized and any(kw in lower_text for kw in TREND_KEYWORDS):
        # Nếu câu dài hơn từ khoá chung chung, dùng nội dung làm query tìm kiếm
        search_q: Optional[str] = None
        for prefix in ("tìm cho tao", "tra cứu", "tin tức về", "vụ", "tình hình"):
            if prefix in lower_text:
                idx = lower_text.find(prefix) + len(prefix)
                candidate = user_text[idx:].strip(" :?.,!")
                if len(candidate) >= 3:
                    search_q = candidate
                    break
        headlines = await fetch_google_news_vn(query=search_q, limit=7)
        if headlines:
            news_block = "\n".join(headlines)
            full_user_prompt += (
                f"\n\n[Dữ liệu Tin tức/Trend thực tế mới nhất hôm nay từ Google News Việt Nam]:\n{news_block}"
            )

    async with message.channel.typing():
        try:
            client, text_model, vision_model = config.get_client_and_models()
            base_system_prompt = channel_system_prompts.get(
                channel_id, config.system_prompt
            )
            channel_it_mode = get_channel_it_context(message.channel)
            if authorized:
                system_prompt = f"{base_system_prompt}{channel_it_mode}\n\n{NATURAL_ACTION_INSTRUCTION}"
            else:
                system_prompt = f"{base_system_prompt}{channel_it_mode}"

            messages_payload: List[dict] = [
                {"role": "system", "content": system_prompt}
            ]

            for past_msg in conversation_history[channel_id]:
                messages_payload.append(past_msg)

            image_data_urls: List[str] = []
            if authorized:
                for img_att in all_images[:4]:
                    data_url = await download_image_as_data_url(img_att)
                    if data_url:
                        image_data_urls.append(data_url)
            elif all_images:
                full_user_prompt += "\n[Hệ thống: Dân thường này vừa gửi ảnh bắt phân tích nhưng CHƯA có quyền VIP, hãy khịa nó và từ chối đọc ảnh cho tới khi Sếp Phát cấp quyền!]"

            if image_data_urls:
                selected_model = vision_model
                multimodal_content: List[dict] = [
                    {"type": "text", "text": full_user_prompt}
                ]
                for data_url in image_data_urls:
                    multimodal_content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        }
                    )
                messages_payload.append(
                    {"role": "user", "content": multimodal_content}
                )
            else:
                selected_model = text_model
                messages_payload.append(
                    {"role": "user", "content": full_user_prompt}
                )

            try:
                response = await client.chat.completions.create(
                    model=selected_model,
                    messages=messages_payload,
                    temperature=0.85,
                    max_tokens=4096,
                )
            except Exception as vision_exc:
                if image_data_urls:
                    logger.warning(
                        "Model không nhận trực tiếp image_url, chuyển sang mô tả metadata ảnh: %s",
                        vision_exc,
                    )
                    img_names = ", ".join(att.filename for att in all_images)
                    fallback_prompt = (
                        f"{full_user_prompt}\n[Đính kèm file ảnh: {img_names}]"
                    )
                    messages_payload[-1] = {
                        "role": "user",
                        "content": fallback_prompt,
                    }
                    response = await client.chat.completions.create(
                        model=text_model,
                        messages=messages_payload,
                        temperature=0.85,
                        max_tokens=4096,
                    )
                else:
                    raise

            raw_ai_reply = (
                response.choices[0].message.content
                or "Đợi tí anh Boss đang châm thuốc!"
            ).strip()

            # Nếu AI nhận thấy không cần rep (trả về <NO_REPLY>) -> Chỉ lưu lịch sử và thả reaction 🫡
            if "<NO_REPLY>" in raw_ai_reply:
                record_silent_message_to_history(message, reply_context_text)
                if caller_is_boss:
                    try:
                        await message.add_reaction("🫡")
                    except Exception:
                        pass
                return

            # Tách và thực thi thẻ <ACTION>{...}</ACTION> nếu có
            action_status_note: Optional[str] = None

            # ========== EXTRACT action JSON ==========
            action_json_str: Optional[str] = None
            # Tìm JSON action bằng nhiều pattern
            for _pat in (
                r"<ACTION>\s*(\{.*?\})\s*</ACTION>",                          # chuẩn
                r'(\{"type"\s*:\s*"[a-z_]+"[^}]*\})\s*</ACTION>',            # thiếu mở
                r'<ACTION>\s*(\{"type"\s*:\s*"[a-z_]+"[^}]*\})',              # thiếu đóng
                r'(\{"type"\s*:\s*"[a-z_]+"[^}]*\})\s*$',                    # JSON trơ cuối
            ):
                _m = re.search(_pat, raw_ai_reply, flags=re.DOTALL | re.IGNORECASE)
                if _m:
                    action_json_str = _m.group(1)
                    break

            # FALLBACK CHỦ ĐỘNG CHO SẾP PHÁT / VIP:
            # Nếu AI quên output JSON hoặc chỉ output </ACTION>, nhưng câu lệnh rõ ràng là giao/nhắc task:
            if not action_json_str and authorized:
                task_keywords = (
                    "nhắc task", "giao task", "giao việc", "assign task",
                    "nhắc việc", "nhắc nhở task", "đòi task", "nhắc lại task",
                    "nhắc làm", "nhắc check task"
                )
                if any(kw in lower_text for kw in task_keywords):
                    task_content = user_text
                    for kw in task_keywords:
                        if kw in task_content.lower():
                            parts = re.split(re.escape(kw), task_content, flags=re.IGNORECASE)
                            if len(parts) > 1 and parts[1].strip():
                                task_content = parts[1].strip()
                            break
                    task_content = re.sub(r"^(lại\s+)?cho\s+", "", task_content, flags=re.IGNORECASE).strip()
                    task_content = re.sub(r"\s+đi\s+(boss|em|anh).*$", "", task_content, flags=re.IGNORECASE).strip()
                    # Lọc sạch tên/mention của thành viên ra khỏi nội dung task để không bị lặp
                    for m in message.mentions:
                        task_content = task_content.replace(f"@{m.display_name}", "").replace(f"@{m.name}", "").replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "")
                    for r in message.role_mentions:
                        task_content = task_content.replace(f"@{r.name}", "").replace(f"<@&{r.id}>", "")
                    task_content = task_content.strip(" :,.-")
                    action_json_str = json.dumps({
                        "type": "assign_task",
                        "task": task_content or "Kiểm tra và hoàn thành tiến độ công việc"
                    })

            # ========== CLEANUP: xoá MỌI dấu vết ACTION khỏi tin nhắn ==========
            ai_reply = _strip_action_tags(raw_ai_reply)

            if action_json_str and authorized:
                try:
                    action_json = json.loads(action_json_str)
                    action_status_note = await execute_natural_action(
                        action_json, message, target_member
                    )
                except Exception as act_exc:
                    logger.warning("Không thực thi được ACTION JSON: %s", act_exc)

            if action_status_note and action_status_note.startswith("⚠️"):
                # Chỉ hiện khi LỖI — thành công thì ngầm, AI đã rep tự nhiên rồi
                ai_reply = f"{ai_reply}\n\n{action_status_note}".strip()

            # Chốt hạ: Luôn lọc sạch mọi vết tích ACTION một lần nữa trước khi gửi
            ai_reply = _strip_action_tags(ai_reply)

            history_user_entry = full_user_prompt
            if image_data_urls:
                history_user_entry += f" [Đính kèm {len(image_data_urls)} ảnh]"

            conversation_history[channel_id].append(
                {"role": "user", "content": history_user_entry}
            )
            conversation_history[channel_id].append(
                {"role": "assistant", "content": ai_reply}
            )

            chunks = split_long_message(ai_reply)
            for idx, chunk in enumerate(chunks):
                if idx == 0:
                    await message.reply(chunk, mention_author=False)
                else:
                    await message.channel.send(chunk)

        except Exception as exc:
            logger.exception("Lỗi khi gọi AI API:")
            await message.reply(
                f"❌ **Toang rồi Sếp ơi, lỗi kết nối AI ({config.provider.upper()}):**\n```text\n{exc}\n```",
                mention_author=False,
            )


# ================= 1. QUẢN LÝ ĐẶC QUYỀN VIP (CHỈ SẾP PHÁT) =================


@bot.tree.command(
    name="vip",
    description="👑 [Chỉ Sếp Phát] Cấp hoặc thu hồi quyền sai vặt Boss cho thành viên trong team",
)
@app_commands.describe(
    action="Chọn hành động: Thêm VIP, Xoá VIP hoặc Xem danh sách",
    member="Thành viên muốn cấp/thu hồi quyền VIP",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="➕ Cấp quyền VIP (Được phép sai Boss)", value="add"),
        app_commands.Choice(name="➖ Tước quyền VIP (Về kiếp dân thường)", value="remove"),
        app_commands.Choice(name="📋 Xem danh sách VIP hiện tại", value="list"),
    ]
)
async def vip_command(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    member: Optional[discord.Member] = None,
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "😼 Mày tưởng mày là ai mà đòi cấp thẻ VIP? Chỉ **Sếp Phát** tối cao mới có ấn tín này thôi nhé cu!",
        )
        return

    if action.value == "list":
        if not config.vip_user_ids:
            await interaction.response.send_message(
                "👑 Báo cáo Sếp Phát: Hiện tại chưa có khứa nào được Sếp ban đặc ân VIP cả. Chỉ một mình Sếp sai được em thôi!"
            )
            return
        mentions = [f"<@{uid}>" for uid in config.vip_user_ids]
        await interaction.response.send_message(
            f"👑 **Danh sách cận thần VIP được Sếp Phát bảo kê:**\n" + ", ".join(mentions)
        )
        return

    if not member:
        await interaction.response.send_message(
            "👑 Sếp Phát ơi, Sếp chọn tên thằng đệ ở ô `member` để em biết đường ban lệnh nhé!",
            ephemeral=True,
        )
        return

    if action.value == "add":
        config.vip_user_ids.add(member.id)
        config.save_vips()
        await interaction.response.send_message(
            f"📣 **THÁNH CHỈ CỦA SẾP PHÁT:** Từ giờ khứa {member.mention} chính thức lên hàng **⭐ VIP** được phép nhờ vả anh Boss! Nhớ đội ơn Sếp Phát đi nhé cu! 🚬😼"
        )
    elif action.value == "remove":
        config.vip_user_ids.discard(member.id)
        config.save_vips()
        await interaction.response.send_message(
            f"📉 **TƯỚC ẤN TÍN:** Theo lệnh Sếp Phát, {member.mention} đã bị đá về kiếp **🐣 Dân thường**! Từ giờ cấm léng phéng sai vặt anh Boss nhé! 💀"
        )


# ================= 2. BẮT TREND, TÌM KIẾM & TÓM TẮT KÊNH =================


@bot.tree.command(
    name="trend",
    description="🔥 Cập nhật tin tức / drama / xu hướng nóng nhất hôm nay trên mạng Việt Nam",
)
@app_commands.describe(chu_de="(Tuỳ chọn) Chủ đề muốn hóng biến, ví dụ: showbiz, bóng đá, công nghệ...")
async def trend_command(
    interaction: discord.Interaction, chu_de: Optional[str] = None
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    await interaction.response.defer()
    headlines = await fetch_google_news_vn(query=chu_de, limit=8)
    if not headlines:
        await interaction.followup.send(
            "😿 Mạng mẽo đang xịt keo quá, chưa kéo được tin nóng về. Đợi tí thử lại nhé!"
        )
        return

    news_text = "\n".join(headlines)
    caller_label = get_user_label(interaction.user, interaction.guild)
    prompt = (
        f"[{caller_label}] vừa yêu cầu điểm tin bắt trend hôm nay"
        + (f" về chủ đề '{chu_de}'" if chu_de else "")
        + f".\nĐây là danh sách các tin nóng vừa lấy từ Google News Việt Nam:\n{news_text}\n\n"
        "Hãy chọn ra 4-5 tin nổi bật/hot nhất, tóm tắt lại và bình luận cực kỳ hài hước, mặn mòi, đậm chất Gen Z cho anh em hóng biến!"
    )
    reply = await ask_ai_Boss(prompt)
    for chunk in split_long_message(reply):
        await interaction.followup.send(chunk)


@bot.tree.command(
    name="search",
    description="🔍 Sai Boss đi lùng sục thông tin mới nhất trên Internet và tổng hợp lại",
)
@app_commands.describe(tu_khoa="Nội dung hoặc câu hỏi cần tìm kiếm")
async def search_command(interaction: discord.Interaction, tu_khoa: str) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    await interaction.response.defer()
    headlines = await fetch_google_news_vn(query=tu_khoa, limit=8)
    news_context = (
        "\n".join(headlines)
        if headlines
        else "Không có bản tin báo chí mới, hãy dùng kiến thức của mày để trả lời."
    )
    caller_label = get_user_label(interaction.user, interaction.guild)
    prompt = (
        f"[{caller_label}] yêu cầu tìm kiếm và giải đáp về: '{tu_khoa}'.\n"
        f"Kết quả báo chí/tin tức liên quan mới nhất:\n{news_context}\n\n"
        "Hãy tổng hợp thông tin chi tiết, chuẩn xác nhưng vẫn giữ giọng điệu cá tính của Boss!"
    )
    reply = await ask_ai_Boss(prompt)
    for chunk in split_long_message(reply):
        await interaction.followup.send(chunk)


@bot.tree.command(
    name="tomtat",
    description="🕵️ Check var kênh chat: Đọc lại tin nhắn gần đây và báo cáo tóm tắt drama cho Sếp",
)
@app_commands.describe(so_luong="Số lượng tin nhắn gần nhất muốn tóm tắt (mặc định 30, tối đa 100)")
async def tomtat_command(
    interaction: discord.Interaction, so_luong: int = 30
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message(
            "Lệnh này chỉ dùng trong kênh chat chữ thôi nhé!", ephemeral=True
        )
        return

    so_luong = max(5, min(so_luong, 100))
    await interaction.response.defer()

    lines: List[str] = []
    async for msg in interaction.channel.history(limit=so_luong):
        if msg.author.bot and msg.author.id == (bot.user.id if bot.user else 0):
            continue
        text = msg.clean_content.strip()
        if text:
            lines.append(f"- {msg.author.display_name}: {text}")

    lines.reverse()
    if not lines:
        await interaction.followup.send("Kênh vắng như chùa bà Đanh, chả có tin nhắn nào để tóm tắt cả!")
        return

    chat_log = "\n".join(lines)
    caller_label = get_user_label(interaction.user, interaction.guild)
    prompt = (
        f"[{caller_label}] yêu cầu mày 'Check var' và tóm tắt lại {len(lines)} tin nhắn gần nhất trong kênh chat này.\n"
        f"Nội dung đoạn chat:\n{chat_log}\n\n"
        "Hãy báo cáo lại rõ ràng: Anh em trong phòng vừa bàn tán chuyện gì? Có ai nói xấu Sếp Phát hay có drama gì hài hước không? Bình luận thêm vài câu mặn mòi chuẩn chất Boss!"
    )
    reply = await ask_ai_Boss(prompt)
    for chunk in split_long_message(reply):
        await interaction.followup.send(chunk)


# ================= 3. TƯƠNG TÁC & GIẢI TRÍ TEAM (ROAST / KHEN / BÓI / VOTE) =================


@bot.tree.command(
    name="roast",
    description="🔥 Nhờ Boss 'sấy / cà khịa' một thành viên tới bến (Cẩn thận phản đam nếu dám sấy Sếp Phát!)",
)
@app_commands.describe(
    muc_tieu="Chọn người muốn sấy",
    ly_do="(Tuỳ chọn) Tội trạng hoặc lý do muốn khịa nó",
)
async def roast_command(
    interaction: discord.Interaction,
    muc_tieu: discord.Member,
    ly_do: Optional[str] = None,
) -> None:
    await interaction.response.defer()
    caller_is_boss = is_user_boss(interaction.user, interaction.guild)
    target_is_boss = is_user_boss(muc_tieu, interaction.guild)

    # Nếu có kẻ dám dùng lệnh /roast nhắm vào Sếp Phát -> PHẢN ĐAM ngay lập tức!
    if target_is_boss and not caller_is_boss:
        prompt = (
            f"Khứa dân thường to gan tên là '{interaction.user.display_name}' vừa dám dùng lệnh /roast để đòi chửi Sếp Phát (Chủ nhân tối cao của mày) "
            + (f"với lý do '{ly_do}'!" if ly_do else "!")
            + "\nHãy bật chế độ PHẢN ĐAM: Bảo vệ Sếp Phát tuyệt đối và sấy ngược lại thằng phản đồ "
            f"'{interaction.user.display_name}' một trận tơi bời hoa lá bằng ngôn từ Gen Z hài hước, lầy lội nhất cho nó chừa thói tạo phản!"
        )
        reply = await ask_ai_Boss(prompt)
        await interaction.followup.send(
            f"⚡ **PHẢN ĐAM KÍCH HOẠT!** Dám động vào Sếp Phát của tao à {interaction.user.mention}?\n\n{reply}"
        )
        return

    if not is_user_authorized(interaction.user, interaction.guild):
        await interaction.followup.send(random.choice(UNAUTHORIZED_REPLIES))
        return

    prompt = (
        f"[👑 Sếp giao nhiệm vụ]: Hãy 'sấy' (roast/cà khịa vui vẻ, hài hước, mặn mòi theo phong cách Gen Z, không văng tục quá đà) "
        f"thành viên tên là '{muc_tieu.display_name}'"
        + (f" vì tội: {ly_do}" if ly_do else "")
        + ". Hãy làm cho cả phòng đọc xong cười xỉu!"
    )
    reply = await ask_ai_Boss(prompt)
    await interaction.followup.send(f"🔥 {muc_tieu.mention} **Tới công chuyện với anh Boss rồi con ạ:**\n\n{reply}")


@bot.tree.command(
    name="khen",
    description="✨ Nhờ Boss tâng bốc một ai đó lên tận mây xanh (Đỉnh nóc kịch trần)",
)
@app_commands.describe(
    muc_tieu="Người muốn khen",
    ly_do="(Tuỳ chọn) Lý do khen",
)
async def khen_command(
    interaction: discord.Interaction,
    muc_tieu: discord.Member,
    ly_do: Optional[str] = None,
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild) and not is_user_boss(muc_tieu, interaction.guild):
        await reject_unauthorized(interaction)
        return

    await interaction.response.defer()
    target_label = get_user_label(muc_tieu, interaction.guild)
    prompt = (
        f"Hãy viết một tràng khen ngợi, tâng bốc '{target_label}' lên tận mây xanh theo phong cách 'đỉnh nóc kịch trần bay phấp phới', "
        f"'10 điểm không có nhưng', hài hước và duyên dáng nhất"
        + (f" vì: {ly_do}" if ly_do else "!")
    )
    reply = await ask_ai_Boss(prompt)
    await interaction.followup.send(f"✨ {muc_tieu.mention}\n\n{reply}")


@bot.tree.command(
    name="boi",
    description="🔮 Thầy bói Mèo Boss gieo quẻ xem nhân phẩm / vận hạn tâm linh hệ tấu hài",
)
@app_commands.describe(cau_hoi="Điều muốn xin quẻ (ví dụ: Hôm nay đánh rank chuỗi thắng hay chuỗi thua?)")
async def boi_command(interaction: discord.Interaction, cau_hoi: str) -> None:
    await interaction.response.defer()
    caller_label = get_user_label(interaction.user, interaction.guild)
    que_list = [
        "Thượng Thượng Cát (Đỉnh Nóc Kịch Trần)",
        "Đại Cát (Over Hợp - Tiền Tình Đầy Túi)",
        "Trung Bình (Hên Xui 50/50 - Đừng Ra Dẻ)",
        "Tiểu Hung (Hơi Xịt Keo - Cẩn Thận Củi Lửa)",
        "Tới Công Chuyện (Nằm Im Thở Khẽ Thôi)",
    ]
    que = random.choice(que_list)
    prompt = (
        f"[{caller_label}] vừa rút được quẻ '{que}' khi hỏi thầy bói Mèo Boss câu hỏi: '{cau_hoi}'.\n"
        "Hãy vào vai Thầy Bói Mèo Boss phán một quẻ thật hài hước, bắt trend tâm linh Gen Z! "
        "(Nếu người hỏi là Sếp Tổng thì luôn phán theo hướng đại cát đại lợi nịnh Sếp; nếu là dân thường thì vừa phán vừa khịa vui vẻ)."
    )
    reply = await ask_ai_Boss(prompt)
    await interaction.followup.send(f"🔮 **QUẺ BÓI: {que}**\n> **Câu hỏi:** {cau_hoi}\n\n{reply}")


@bot.tree.command(
    name="chon",
    description="🎲 Để Boss chốt đơn chọn giúp khi anh em phân vân (ngăn cách bằng dấu phẩy)",
)
@app_commands.describe(lua_chon="Các lựa chọn cách nhau bằng dấu phẩy, VD: Cơm tấm, Bún bò, Lẩu, Nhịn")
async def chon_command(interaction: discord.Interaction, lua_chon: str) -> None:
    options = [opt.strip() for opt in lua_chon.split(",") if opt.strip()]
    if len(options) < 2:
        await interaction.response.send_message(
            "Nhập ít nhất 2 lựa chọn cách nhau bằng dấu phẩy (`,`) đi chứ!", ephemeral=True
        )
        return

    winner = random.choice(options)
    await interaction.response.send_message(
        f"🎲 Giữa **{', '.join(options)}**...\n"
        f"👉 Anh Boss chốt đơn: **{winner}**! Không nói nhiều, triển luôn đi! 🚬😼"
    )


@bot.tree.command(
    name="poll",
    description="📊 Tạo bảng bình chọn (Vote) chuyên nghiệp trong kênh",
)
@app_commands.describe(
    cau_hoi="Chủ đề cần anh em bình chọn",
    lua_chon="Các phương án cách nhau bằng dấu phẩy (tối đa 9 phương án), VD: Đi nhậu, Chơi game, Đi ngủ",
)
async def poll_command(
    interaction: discord.Interaction, cau_hoi: str, lua_chon: str
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    options = [opt.strip() for opt in lua_chon.split(",") if opt.strip()][:9]
    if len(options) < 2:
        await interaction.response.send_message(
            "Cần nhập ít nhất 2 phương án cách nhau bằng dấu phẩy (`,`)!", ephemeral=True
        )
        return

    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    desc_lines = [
        f"{number_emojis[i]} **{ opt }**" for i, opt in enumerate(options)
    ]

    embed = discord.Embed(
        title=f"📊 BÌNH CHỌN: {cau_hoi}",
        description="\n\n".join(desc_lines),
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_footer(text=f"Khởi tạo bởi {interaction.user.display_name} • Bấm emoji bên dưới để chốt!")

    await interaction.response.send_message(embed=embed)
    poll_msg = await interaction.original_response()
    for i in range(len(options)):
        await poll_msg.add_reaction(number_emojis[i])


# ================= 4. HẸN GIỜ NHẮC VIỆC & QUẢN TRỊ SERVER CỦA SẾP =================


@bot.tree.command(
    name="remind",
    description="⏰ Sai Boss hẹn giờ nhắc việc cho Sếp hoặc cả team",
)
@app_commands.describe(
    so_phut="Số phút đếm ngược (ví dụ: 10)",
    noi_dung="Nội dung cần nhắc (ví dụ: Vào họp team / Vào làm ván game)",
)
async def remind_command(
    interaction: discord.Interaction, so_phut: int, noi_dung: str
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    if so_phut < 1 or so_phut > 1440:
        await interaction.response.send_message(
            "Số phút hẹn giờ phải từ 1 đến 1440 phút (24 giờ) nhé!", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"⏰ **Đã rõ!** Đúng **{so_phut} phút** nữa em sẽ réo tên {interaction.user.mention} nhắc vụ: **{noi_dung}**! 🫡"
    )

    async def _timer_task() -> None:
        await asyncio.sleep(so_phut * 60)
        if interaction.channel and isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread, discord.DMChannel)
        ):
            await interaction.channel.send(
                f"🔔 **TỚI GIỜ RỒI {interaction.user.mention} ƠI!**\n"
                f"👉 Nhắc lịch sau {so_phut} phút: **{noi_dung}**! Triển ngay kẻo lỡ việc! 🚬😼"
            )

    asyncio.create_task(_timer_task())


@bot.tree.command(
    name="clear_msg",
    description="🧹 [Chỉ Sếp Phát] Dọn sạch tin nhắn rác trong kênh hiện tại",
)
@app_commands.describe(so_luong="Số lượng tin nhắn muốn xoá (từ 1 đến 100)")
async def clear_msg_command(
    interaction: discord.Interaction, so_luong: int = 10
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "😼 Mày tuổi gì đòi xoá tin nhắn phòng này? Chỉ **Sếp Phát** mới có quyền dọn phòng thôi!",
        )
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            "Lệnh này chỉ dùng trong kênh Text của Server thôi Sếp ơi!", ephemeral=True
        )
        return

    so_luong = max(1, min(so_luong, 100))
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=so_luong)
    await interaction.followup.send(
        f"🧹 Báo cáo Sếp Phát: Em đã quét sạch **{len(deleted)}** tin nhắn trong kênh này rồi ạ!",
        ephemeral=True,
    )


@bot.tree.command(
    name="timeout",
    description="🔇 [Chỉ Sếp Phát] Khóa mõm (Timeout) thành viên dám bật Sếp",
)
@app_commands.describe(
    thanh_vien="Kẻ cần khóa mõm",
    so_phut="Số phút khóa mõm (ví dụ: 5)",
    ly_do="Lý do trừng phạt",
)
async def timeout_command(
    interaction: discord.Interaction,
    thanh_vien: discord.Member,
    so_phut: int = 5,
    ly_do: str = "Tội dám láo với Sếp Phát",
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await interaction.response.send_message(
            f"😼 {interaction.user.mention} định lật đổ chính quyền hay gì mà đòi dùng lệnh khóa mõm? Chỉ **Sếp Phát** mới được phán xử thôi!",
        )
        return

    try:
        duration = datetime.timedelta(minutes=max(1, min(so_phut, 1440)))
        await thanh_vien.timeout(duration, reason=ly_do)
        await interaction.response.send_message(
            f"🔇 **THI HÀNH ÁN!** Theo lệnh **Sếp Phát**, khứa {thanh_vien.mention} đã bị khóa mõm **{so_phut} phút** vì tội: *{ly_do}*! Nằm im sám hối đi con! 🚬😼"
        )
    except Exception as exc:
        await interaction.response.send_message(
            f"⚠️ Sếp ơi chưa khóa mõm được nó (do role của nó cao hơn hoặc ngang role Bot): `{exc}`",
            ephemeral=True,
        )


@bot.tree.command(
    name="nickname",
    description="🏷️ [Chỉ Sếp Phát] Đổi biệt danh của một thành viên trong Server",
)
@app_commands.describe(
    thanh_vien="Thành viên muốn đổi tên",
    biet_danh_moi="Biệt danh mới muốn đặt cho nó",
)
async def nickname_command(
    interaction: discord.Interaction,
    thanh_vien: discord.Member,
    biet_danh_moi: str,
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "😼 Chỉ có **Sếp Phát** mới có quyền ban tên hiệu cho anh em trong phòng nhé!",
        )
        return

    try:
        await thanh_vien.edit(nick=biet_danh_moi)
        await interaction.response.send_message(
            f"🏷️ **BAN TÊN HIỆU MỚI:** Theo thánh chỉ của **Sếp Phát**, {thanh_vien.mention} từ nay mang danh hiệu **`{biet_danh_moi}`**! Đỉnh nóc kịch trần! 😼"
        )
    except Exception as exc:
        await interaction.response.send_message(
            f"⚠️ Không đổi biệt danh được (do quyền role của đối phương cao hơn Bot): `{exc}`",
            ephemeral=True,
        )


@bot.tree.command(
    name="ban",
    description="🔨 [Chỉ Sếp Phát] Cấm cửa vĩnh viễn (Ban) một thành viên khỏi Server",
)
@app_commands.describe(
    thanh_vien="Kẻ cần Ban khỏi Server",
    ly_do="Lý do Ban",
)
async def ban_command(
    interaction: discord.Interaction,
    thanh_vien: discord.Member,
    ly_do: str = "Theo lệnh Sếp Phát",
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "😼 Mày tuổi gì đòi Ban người trong phòng này? Chỉ **Sếp Phát** mới có quyền sinh sát thôi!",
        )
        return

    try:
        await thanh_vien.ban(reason=ly_do, delete_message_days=0)
        await interaction.response.send_message(
            f"🔨 **TRỤC XUẤT VĨNH VIỄN!** Theo lệnh **Sếp Phát**, **{thanh_vien.display_name}** đã bị Ban khỏi Server vì tội: *{ly_do}*! 🚬😼"
        )
    except Exception as exc:
        await interaction.response.send_message(
            f"⚠️ Không Ban được (do quyền role của đối phương cao hơn Bot): `{exc}`",
            ephemeral=True,
        )


@bot.tree.command(
    name="unban",
    description="🕊️ [Chỉ Sếp Phát] Gỡ lệnh cấm (Unban) và gửi link mời quay lại phòng",
)
@app_commands.describe(
    ten_hoac_id="Tên hoặc ID của người đang bị Ban (để trống nếu muốn gỡ cho người mới bị Ban gần nhất)"
)
async def unban_command(
    interaction: discord.Interaction,
    ten_hoac_id: Optional[str] = None,
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "😼 Chỉ có **Sếp Phát** tối cao mới có quyền đại xá thiên hạ (Unban) thôi nhé!",
        )
        return

    if not interaction.guild:
        await interaction.response.send_message("Lệnh này chỉ dùng trong Server!", ephemeral=True)
        return

    await interaction.response.defer()
    query = (ten_hoac_id or "").strip().lower()
    try:
        ban_entries = [entry async for entry in interaction.guild.bans()]
        if not ban_entries:
            await interaction.followup.send(
                "📋 Báo cáo Sếp Phát: Hiện tại trong Server không có ai đang bị Ban cả!"
            )
            return

        matched_user: Optional[discord.User] = None
        for entry in ban_entries:
            u = entry.user
            u_display = getattr(u, "global_name", None) or u.name
            if (
                not query
                or query in u.name.lower()
                or query in u_display.lower()
                or query == str(u.id)
            ):
                matched_user = u
                break

        if not matched_user:
            banned_list = ", ".join(f"`{e.user.name}` (`{e.user.id}`)" for e in ban_entries[:10])
            await interaction.followup.send(
                f"⚠️ Không tìm thấy ai khớp với `{ten_hoac_id}` trong danh sách Ban.\nDanh sách đang bị Ban: {banned_list}"
            )
            return

        await interaction.guild.unban(matched_user, reason="Sếp Phát ân xá")

        invite_text = ""
        if isinstance(interaction.channel, discord.TextChannel):
            try:
                invite = await interaction.channel.create_invite(
                    max_age=86400, max_uses=5, reason="Link mời sau khi Sếp Phát unban"
                )
                invite_text = f"\n🔗 **Link mời vào lại phòng:** {invite.url}"
                try:
                    await matched_user.send(
                        f"📣 **THÁNH CHỈ ÂN XÁ:** **Sếp Phát** đã gỡ Ban cho mày! Bấm vào link này để quay lại Server nhé: {invite.url}"
                    )
                    invite_text += " *(Đã gửi thẳng vào DM của nó luôn!)*"
                except Exception:
                    pass
            except Exception:
                pass

        await interaction.followup.send(
            f"🕊️ **ĐẠI XÁ THIÊN HẠ!** Theo lệnh **Sếp Phát**, đã gỡ Ban thành công cho **{matched_user.name}** (`{matched_user.id}`)!{invite_text}"
        )
    except Exception as exc:
        await interaction.followup.send(f"⚠️ Có lỗi khi gỡ Ban: `{exc}`")


@bot.tree.command(
    name="add",
    description="➕ Thêm thành viên vào kênh/phòng, cấp quyền kênh hoặc tạo Link Mời nhanh",
)
@app_commands.describe(
    thanh_vien="(Tuỳ chọn) Thành viên trong Server muốn thêm vào kênh hiện tại",
    role="(Tuỳ chọn) Role muốn gắn thêm cho thành viên đó",
)
async def add_command(
    interaction: discord.Interaction,
    thanh_vien: Optional[discord.Member] = None,
    role: Optional[discord.Role] = None,
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    if not interaction.guild:
        await interaction.response.send_message("Lệnh này chỉ dùng trong Server!", ephemeral=True)
        return

    await interaction.response.defer()
    caller_is_boss = is_user_boss(interaction.user, interaction.guild)

    # Nếu có chọn thành viên đang ở trong Server -> thêm quyền kênh / thêm vào Thread / gắn Role
    if thanh_vien:
        notes: List[str] = []
        if role and caller_is_boss:
            try:
                await thanh_vien.add_roles(role, reason="Theo lệnh Sếp Phát")
                notes.append(f"đã cấp Role {role.mention}")
            except Exception as exc:
                notes.append(f"lỗi cấp Role (`{exc}`)")

        if isinstance(interaction.channel, discord.Thread):
            try:
                await interaction.channel.add_user(thanh_vien)
                notes.append(f"đã kéo {thanh_vien.mention} vào Thread này")
            except Exception as exc:
                notes.append(f"lỗi kéo vào Thread (`{exc}`)")
        elif isinstance(interaction.channel, discord.TextChannel) and caller_is_boss:
            try:
                await interaction.channel.set_permissions(
                    thanh_vien,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    reason="Sếp Phát add vào kênh",
                )
                notes.append(f"đã mở quyền cho {thanh_vien.mention} vào kênh {interaction.channel.mention}")
            except Exception as exc:
                notes.append(f"lỗi mở quyền kênh (`{exc}`)")

        if notes:
            await interaction.followup.send("➕ **Hoàn tất:** " + ", ".join(notes) + "! 🚬😼")
            return

    # Nếu không truyền thành viên cụ thể -> Tạo Link Mời vào phòng
    if isinstance(interaction.channel, discord.TextChannel):
        try:
            invite = await interaction.channel.create_invite(
                max_age=86400, max_uses=10, reason=f"Tạo link mời bởi {interaction.user.display_name}"
            )
            await interaction.followup.send(
                f"➕ **Link mời thêm anh em vào phòng đây Sếp ơi (hiệu lực 24h):**\n👉 {invite.url}"
            )
            return
        except Exception as exc:
            await interaction.followup.send(f"⚠️ Không tạo được link mời: `{exc}`")
            return

    await interaction.followup.send("⚠️ Hãy chạy lệnh này trong kênh chat chính để thêm người hoặc tạo link mời nhé!")


# ================= 5. CẤU HÌNH HỆ THỐNG =================


@bot.tree.command(
    name="reset", description="🧹 Xoá lịch sử nhớ hội thoại của Boss trong kênh này"
)
async def reset_command(interaction: discord.Interaction) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return
    if interaction.channel_id:
        conversation_history.pop(interaction.channel_id, None)
    await interaction.response.send_message(
        "🧹 Đã tẩy não lịch sử hội thoại kênh này theo lệnh! Làm ván mới thôi anh em! 🚬😼",
    )


@bot.tree.command(
    name="provider",
    description="⚙️ [Chỉ Sếp Phát] Chuyển đổi nguồn AI giữa Groq và Ollama",
)
@app_commands.choices(
    provider=[
        app_commands.Choice(name="Groq (Cloud miễn phí, tốc độ cao)", value="groq"),
        app_commands.Choice(name="Ollama (Chạy local trên máy)", value="ollama"),
    ]
)
async def provider_command(
    interaction: discord.Interaction,
    provider: app_commands.Choice[str],
    text_model: Optional[str] = None,
    vision_model: Optional[str] = None,
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    config.provider = provider.value
    if config.provider == "groq":
        if text_model:
            config.groq_text_model = text_model.strip()
        if vision_model:
            config.groq_vision_model = vision_model.strip()
    else:
        if text_model:
            config.ollama_text_model = text_model.strip()
        if vision_model:
            config.ollama_vision_model = vision_model.strip()

    await config.auto_detect_models()
    _, active_text, active_vision = config.get_client_and_models()
    await interaction.response.send_message(
        f"✅ Báo cáo Sếp Phát, đã chuyển sang **{config.provider.upper()}**!\n"
        f"• **Model Chat:** `{active_text}`\n"
        f"• **Model Vision:** `{active_vision}`"
    )


@bot.tree.command(
    name="persona",
    description="🎭 [Chỉ Sếp Phát] Thay đổi tính cách riêng cho Boss trong kênh này",
)
async def persona_command(
    interaction: discord.Interaction, prompt: Optional[str] = None
) -> None:
    if not is_user_boss(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return

    channel_id = interaction.channel_id or 0
    if not prompt or not prompt.strip():
        channel_system_prompts.pop(channel_id, None)
        await interaction.response.send_message(
            "🔄 Đã khôi phục tính cách Boss mặc định cho kênh này thưa Sếp!"
        )
        return

    channel_system_prompts[channel_id] = prompt.strip()
    conversation_history.pop(channel_id, None)
    await interaction.response.send_message(
        f"🎭 Đã nhận lệnh Sếp Phát, cập nhật tính cách mới cho kênh này:\n> {prompt.strip()}"
    )


@bot.tree.command(
    name="status", description="🤖 Xem trạng thái quyền lực của Boss và cấp bậc của bạn"
)
async def status_command(interaction: discord.Interaction) -> None:
    channel_id = interaction.channel_id or 0
    _, text_model, vision_model = config.get_client_and_models()
    history_count = len(conversation_history[channel_id])
    caller_role = get_user_label(interaction.user, interaction.guild)

    embed = discord.Embed(
        title="🚬 Bảng Trạng Thái Đại Ca Mèo BOSS",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Cấp bậc của bạn", value=f"**`{caller_role}`**", inline=False)
    embed.add_field(
        name="Nguồn AI", value=f"`{config.provider.upper()}`", inline=True
    )
    embed.add_field(name="Model Chat", value=f"`{text_model}`", inline=True)
    embed.add_field(
        name="Bộ nhớ kênh",
        value=f"`{history_count}/{config.max_history}` tin nhắn",
        inline=True,
    )
    embed.add_field(
        name="Số cận thần VIP",
        value=f"`{len(config.vip_user_ids)}` người được Sếp Phát bảo kê",
        inline=False,
    )
    embed.add_field(
        name="Danh sách Tuyệt Kỹ (Slash Commands)",
        value=(
            "• **Quyền lực Sếp Phát:** `/vip`, `/timeout`, `/clear_msg`, `/nickname`, `/persona`, `/provider`\n"
            "• **Bắt Trend & Trợ lý (Sếp & VIP):** `/trend`, `/search`, `/tomtat`, `/remind`, `/poll`\n"
            "• **Giải trí & Tấu hài:** `/roast` (có phản đam), `/khen`, `/boi`, `/chon`, `/status`"
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


if __name__ == "__main__":
    if not config.discord_token or config.discord_token == "your_discord_bot_token_here":
        logger.error("Vui lòng điền DISCORD_TOKEN vào file .env trước khi chạy bot!")
        raise SystemExit(1)

    bot.run(config.discord_token)
