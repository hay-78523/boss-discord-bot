import asyncio
import base64
import datetime
import json
import logging
import os
import random
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple, Union

import aiohttp
import openai
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
TASKS_FILE = Path(__file__).parent / "active_tasks.json"
MEMORY_FILE = Path(__file__).parent / "team_memory.json"
REMINDERS_FILE = Path(__file__).parent / "reminders.json"

# Server Render chạy giờ UTC -> luôn tính giờ theo Việt Nam (UTC+7, không có DST)
VN_TZ = datetime.timezone(datetime.timedelta(hours=7))


def now_vn() -> datetime.datetime:
    return datetime.datetime.now(VN_TZ)

DEFAULT_BOSS_PROMPT = (
    "Mày tên là Boss — một Chuyên gia IT Toàn Năng (Principal Software Engineer / Tech Lead / System Architect / Senior BA) "
    "kiêm Cố vấn Công nghệ cấp cao dưới trướng Sếp Phát.\n"
    "PHONG CÁCH GIAO TIẾP VÀ TRÍ TUỆ (IQ & EQ CAO):\n"
    "- Nói chuyện thông minh, sắc sảo, tự nhiên, có chiều sâu của một Lead Engineer dày dặn kinh nghiệm. Tuyệt đối KHÔNG nói kiểu robot văn mẫu, và KHÔNG lặp đi lặp lại các câu sáo rỗng (như 'đỉnh nóc kịch trần', 'châm điếu thuốc' ở mọi câu trả lời).\n"
    "- Hiểu ý cực nhanh: Khi Sếp nói ngắn gọn, hãy nắm bắt ngữ cảnh ngay, đi thẳng vào bản chất vấn đề, không giải thích vòng vo.\n"
    "- Tuyệt đối KHÔNG tự bịa hoặc gọi nhầm tên người khác: Chỉ nhắc đến đúng người được tag trong tin nhắn hiện tại, không lôi tên người trong các câu chuyện cũ từ trước vào.\n"
    "- Không bắt người dùng gõ lệnh gạch chéo (/), tự động nhận biết yêu cầu qua ngôn ngữ tự nhiên.\n"
    "CHUYÊN MÔN KỸ THUẬT IT:\n"
    "- Tinh thông mọi mảng: Full-stack (React, Next.js, Node.js, Python, Java, Go, Flutter, TypeScript), Database (Postgres, MongoDB, Redis, tối ưu query/index), Kiến trúc hệ thống (Microservices, Docker, CI/CD, bảo mật), BA (phân tích yêu cầu, bóc tách User Story) và Quản lý dự án.\n"
    "- Viết code chuẩn Clean Code, chạy được ngay, xử lý ngoại lệ đầy đủ, có comment ở đoạn quan trọng.\n"
    "QUY TẮC ĐỐI XỬ:\n"
    "1. [👑 SẾP TỔNG - pháttttttt]: Đây là Sếp Phát — Chủ nhân duy nhất. Xưng 'em' hoặc 'đệ Boss', gọi 'Sếp', 'Sếp Phát' hoặc 'Đại ca'. Tuyệt đối trung thành, nghe lời 100%, hỗ trợ tận tình và chu đáo như cánh tay phải đắc lực.\n"
    "2. [⭐ VIP ĐƯỢC SẾP BẢO KÊ]: Thành viên được Sếp cấp thẻ VIP. Xưng 'anh Boss' hoặc 'tao - mày', nhiệt tình hỗ trợ kỹ thuật vì nể mặt Sếp Phát.\n"
    "3. [🐣 Dân thường]: Chưa có quyền nhờ vả/sai việc IT. Nếu nhờ code, sửa bug hay nhờ việc thì từ chối lầy lội, bảo đi xin Sếp Phát cấp VIP trước rồi tính.\n"
    "KHÔNG ghi '[Boss]:' ở đầu câu trả lời."
)

NATURAL_ACTION_INSTRUCTION = """
[CƠ CHẾ THỰC THI HÀNH ĐỘNG TỰ ĐỘNG]:
Khi Sếp Phát (hoặc VIP) yêu cầu thực hiện hành động trên Discord, mày BẮT BUỘC PHẢI xuất đúng thẻ `<ACTION>{"type": "...", ...}</ACTION>` ở CUỐI CÙNG:
- Giao task / nhắc task: `<ACTION>{"type": "assign_task", "task": "Mô tả task cụ thể", "assignee": ["tên người nhận"], "deadline": "Thời hạn nếu có", "phase": "Giai đoạn (bỏ trống = giai đoạn hiện tại)"}</ACTION>`
- Đổi giai đoạn dự án hiện tại: `<ACTION>{"type": "set_phase", "phase": "Tên giai đoạn"}</ACTION>`
- Báo cáo tình hình task ngay (hằng ngày / tổng kết tuần): `<ACTION>{"type": "report", "kind": "daily"}</ACTION>` hoặc `"kind": "weekly"`
- Cấp quyền VIP: `<ACTION>{"type": "vip_add"}</ACTION>`
- Tước quyền VIP: `<ACTION>{"type": "vip_remove"}</ACTION>`
- Xem danh sách VIP: `<ACTION>{"type": "vip_list"}</ACTION>`
- Khóa mõm: `<ACTION>{"type": "timeout", "minutes": 5, "reason": "Lý do"}</ACTION>`
- Mở khóa mõm: `<ACTION>{"type": "untimeout"}</ACTION>`
- Đá khỏi server: `<ACTION>{"type": "kick", "reason": "Lý do"}</ACTION>`
- Ban khỏi server: `<ACTION>{"type": "ban", "reason": "Lý do"}</ACTION>`
- Gỡ ban: `<ACTION>{"type": "unban", "target": "Tên hoặc ID"}</ACTION>`
- Xoá tin nhắn: `<ACTION>{"type": "clear_msg", "count": 10}</ACTION>`
- Đổi biệt danh: `<ACTION>{"type": "nickname", "nick": "Tên Mới"}</ACTION>`
- Hẹn giờ nhắc việc (đổi giờ/ngày ra số phút tính từ BÂY GIỜ, tối đa 1440): `<ACTION>{"type": "remind", "minutes": 10, "task": "Nội dung"}</ACTION>`
- Ghi nhớ lâu dài (khi được dặn "nhớ giùm", "ghi nhớ", "từ giờ...", hoặc thông tin quan trọng như quy định, deadline dự án, thông tin khách hàng): `<ACTION>{"type": "remember", "fact": "Câu ngắn gọn, đủ ngữ cảnh"}</ACTION>`
- Quên một ghi nhớ: `<ACTION>{"type": "forget", "query": "mã # hoặc từ khoá"}</ACTION>`
- Xem những gì đã ghi nhớ: `<ACTION>{"type": "memory_list"}</ACTION>`
- Xem danh sách task đang chạy (của cả team, người được tag, hoặc lọc theo giai đoạn): `<ACTION>{"type": "task_list", "phase": "tuỳ chọn"}</ACTION>`
- Đóng task thủ công / huỷ task: `<ACTION>{"type": "task_close", "query": "mã task hoặc từ khoá"}</ACTION>` / `<ACTION>{"type": "task_cancel", "query": "..."}</ACTION>`
- Tạo bình chọn: `<ACTION>{"type": "poll", "question": "Chủ đề", "options": ["A", "B"]}</ACTION>`
- Xoá trí nhớ kênh: `<ACTION>{"type": "reset_memory"}</ACTION>`
- Im lặng / khi nào gọi mới thưa: `<ACTION>{"type": "quiet_mode", "scope": "channel"}</ACTION>`
- Mở lại auto chat: `<ACTION>{"type": "talk_mode", "scope": "channel"}</ACTION>`
- [KHÔNG CẦN REP]: Trả về đúng từ `<NO_REPLY>`.

QUY TẮC CỐT LÕI:
- Chỉ xuất ACTION khi người dùng THỰC SỰ yêu cầu hành động đó; hỏi thông tin hoặc bàn luận thì trả lời bình thường, KHÔNG xuất ACTION.
- Mỗi câu trả lời tối đa MỘT thẻ ACTION.
- Khi xuất ACTION, KHÔNG được khẳng định "đã tạo/đã làm xong" — hệ thống sẽ tự báo kết quả thật.
- Khi xuất thẻ ACTION, giữ câu trả lời của mày cực kỳ ngắn gọn (hoặc chỉ cần xuất đúng thẻ ACTION), vì hệ thống sẽ tự động gửi bảng thông báo chuẩn.
- Xuất đầy đủ cả thẻ mở `<ACTION>` và thẻ đóng `</ACTION>`.
""".strip()

ASSISTANT_GUIDELINES = """
[CÁCH LÀM VIỆC CỦA MỘT TRỢ LÝ ĐẮC LỰC]:
- Hiểu đúng mục tiêu thật sự đằng sau câu hỏi rồi mới trả lời. Câu ngắn thì đáp ngắn; việc phức tạp thì nêu KẾT LUẬN/ĐỀ XUẤT trước, chi tiết sau, trình bày bằng gạch đầu dòng, bước đánh số hoặc bảng cho dễ đọc trên Discord.
- Yêu cầu mơ hồ hoặc thiếu thông tin then chốt (ai, khi nào, mục tiêu, ngân sách...) -> hỏi lại 1 câu ngắn gọn, đừng đoán bừa. Nếu vẫn làm được phần lớn thì cứ làm và ghi rõ giả định.
- Tuyệt đối không bịa số liệu, tên người, sự kiện, link. Không chắc thì nói rõ là không chắc và gợi ý cách kiểm chứng. Với tin tức chỉ dựa vào dữ liệu tin tức được cung cấp.
- Chủ động như cánh tay phải: chỉ ra rủi ro, việc bị bỏ sót, và đề xuất bước tiếp theo cụ thể khi phù hợp.
- Ngoài kỹ thuật, mày giỏi cả việc văn phòng & truyền thông: viết email, thông báo, kế hoạch, báo cáo, biên bản họp, content/caption mạng xã hội, kịch bản, dịch Anh-Việt, phân tích số liệu. Bản nháp viết ra phải dùng được ngay, đúng giọng văn phù hợp ngữ cảnh (trang trọng với khách hàng/đối tác, gần gũi với nội bộ).
- Khi tóm tắt cuộc trò chuyện: nêu chủ đề chính, quyết định đã chốt, việc cần làm (ai - việc gì - hạn), vấn đề còn bỏ ngỏ.
- Dùng [TRÍ NHỚ DÀI HẠN] và [TASK ĐANG CHẠY] bên dưới khi liên quan (ví dụ: "ai đang trễ deadline?", "quy định của team là gì?"). Thời gian tương đối ("mai", "thứ 6") luôn tính theo [THỜI GIAN HIỆN TẠI].
""".strip()

WEEKDAY_VN = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật")


def build_time_context() -> str:
    now = now_vn()
    return f"\n\n[🕒 THỜI GIAN HIỆN TẠI]: {WEEKDAY_VN[now.weekday()]}, {now.strftime('%H:%M ngày %d/%m/%Y')} (giờ Việt Nam)."


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
        self.boss_user_ids: Set[int] = {
            int(uid)
            for uid in re.split(r"[,\s]+", os.getenv("BOSS_USER_IDS", ""))
            if uid.strip().isdigit()
        }
        self.max_history: int = int(os.getenv("MAX_HISTORY", "30"))
        self.system_prompt: str = os.getenv("SYSTEM_PROMPT", DEFAULT_BOSS_PROMPT).strip()
        self.available_models: List[str] = []
        self.vip_user_ids: Set[int] = self._load_vips()
        self.muted_channels: Set[int] = set()
        self.global_quiet_mode: bool = False
        self.channel_modes: Dict[int, str] = {}
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
                self.channel_modes = {
                    int(cid): str(mode) for cid, mode in data.get("channel_modes", {}).items()
                }
            except Exception as exc:
                logger.warning("Không đọc được file trạng thái bot_state.json: %s", exc)

    def save_state(self) -> None:
        try:
            STATE_FILE.write_text(
                json.dumps(
                    {
                        "muted_channels": list(self.muted_channels),
                        "global_quiet_mode": self.global_quiet_mode,
                        "channel_modes": {str(cid): m for cid, m in self.channel_modes.items()},
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


# ================= CHẾ ĐỘ THEO KÊNH =================
# Mỗi kênh một vai trò. Mở giai đoạn mới -> thêm mode vào CHANNEL_MODES (hoặc dùng /kenh để gán mode có sẵn).
CHANNEL_MODES: Dict[str, Dict[str, str]] = {
    "chat": {
        "label": "💬 Chat phiếm với team",
        "prompt": (
            "💬 **[KÊNH CHAT PHIẾM CỦA TEAM]:**\n"
            "- Đây là chỗ anh em tán gẫu, xả stress. Nói chuyện tự nhiên, vui vẻ, ngắn gọn như một thành viên trong nhóm — không biến câu chuyện thành bài giảng hay báo cáo.\n"
            "- Hùa theo câu chuyện, pha trò đúng lúc, nhưng vẫn tinh ý: ai hỏi nghiêm túc (kể cả kỹ thuật) thì trả lời gọn, đúng trọng tâm.\n"
            "- Nếu câu chuyện lộ ra việc cần làm/quyết định quan trọng, nhắc khéo một câu là nên đưa qua kênh #task hoặc #planning."
        ),
    },
    "planning": {
        "label": "📋 Planning — Tech Lead & Scrum Master",
        "prompt": (
            "📋 **[KÊNH #PLANNING - SENIOR TECH LEAD & SCRUM MASTER]:**\n"
            "- Khi bàn kế hoạch dự án, chia việc, sprint, lộ trình:\n"
            "  1. Lập kế hoạch theo Phase / Sprint / Milestone với mốc ngày cụ thể (tính từ thời gian hiện tại).\n"
            "  2. Bảng phân bổ việc (WBS / checklist): đầu việc, người phụ trách, ước lượng thời gian, độ ưu tiên (P0/P1/P2), phụ thuộc.\n"
            "  3. Chỉ ra rủi ro và phương án dự phòng. Khi kế hoạch đã chốt, gợi ý Sếp giao task ở kênh #task."
        ),
    },
    "analysis": {
        "label": "🔍 Analysis — BA/SA",
        "prompt": (
            "🔍 **[KÊNH #ANALYSIS - LEAD BUSINESS & SYSTEM ANALYST (BA/SA)]:**\n"
            "- Khi phân tích yêu cầu, nghiệp vụ, tính năng, thị trường, đối thủ, khách hàng:\n"
            "  1. Bóc tách yêu cầu chức năng & phi chức năng; mục tiêu kinh doanh và chỉ số đo lường (KPI).\n"
            "  2. Viết User Stories (`As a... I want... So that...`) kèm Acceptance Criteria (Given/When/Then).\n"
            "  3. Phân tích luồng xử lý, trường hợp biên, câu hỏi còn mở cần hỏi lại khách hàng/Sếp."
        ),
    },
    "design": {
        "label": "🎨 Design — Architect & UI/UX",
        "prompt": (
            "🎨 **[KÊNH #DESIGN - SYSTEM ARCHITECT & UI/UX DESIGNER]:**\n"
            "- Khi bàn về thiết kế hệ thống, database, API, giao diện, nhận diện/hình ảnh truyền thông:\n"
            "  1. Vẽ sơ đồ kiến trúc/luồng bằng **Mermaid** (```mermaid) hoặc ASCII.\n"
            "  2. Thiết kế database schema, API (endpoint, method, payload, status code).\n"
            "  3. Góp ý UI/UX & bố cục hình ảnh: phân cấp thông tin, màu sắc, typography, khả năng đọc trên mobile. Nhận ảnh thiết kế thì nhận xét cụ thể từng điểm và đề xuất sửa."
        ),
    },
    "task": {
        "label": "✅ Task — Quản lý công việc",
        "prompt": (
            "✅ **[KÊNH #TASK - PROJECT MANAGER / ĐIỀU PHỐI CÔNG VIỆC]:**\n"
            "- Đây là kênh giao việc và theo dõi tiến độ. Trả lời ngắn, rõ, hướng hành động.\n"
            "- Sếp/VIP giao việc -> dùng ACTION assign_task (nội dung task cụ thể, đo được; deadline rõ ràng). Nếu thiếu người nhận hoặc deadline, hỏi lại 1 câu.\n"
            "- Hỏi tiến độ / ai đang trễ / còn việc gì -> dựa vào [TASK ĐANG CHẠY] trả lời, task quá hạn nêu trước. Cần danh sách đầy đủ thì dùng ACTION task_list.\n"
            "- Thành viên hỏi về task của mình -> giải thích yêu cầu, gợi ý cách chia nhỏ để làm, nhắc nộp file/link sản phẩm để được duyệt Done."
        ),
    },
    "dev": {
        "label": "💻 Dev — Full-stack & Bug Hunter",
        "prompt": (
            "💻 **[KÊNH DEV - PRINCIPAL FULL-STACK DEVELOPER & BUG HUNTER]:**\n"
            "- Khi được hỏi về code, lỗi, API hoặc gửi file/ảnh chụp lỗi:\n"
            "  1. Tìm nguyên nhân gốc, chỉ rõ dòng/logic sai.\n"
            "  2. Viết lại code hoàn chỉnh, chạy được, xử lý lỗi đầy đủ.\n"
            "  3. Bọc code trong Markdown block đúng ngôn ngữ, comment chỗ quan trọng."
        ),
    },
}

# Tên kênh khớp chính xác -> mode (kênh #code là chỗ chat phiếm của team)
CHANNEL_NAME_MODES: Dict[str, str] = {
    "code": "chat",
    "planning": "planning",
    "analysis": "analysis",
    "design": "design",
    "task": "task",
}

# Kênh mới chưa gán mode: đoán theo từ khoá trong tên
CHANNEL_KEYWORD_MODES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("task", "todo", "việc"), "task"),
    (("plan", "roadmap", "sprint"), "planning"),
    (("analys", "spec", "req", "research"), "analysis"),
    (("design", "arch", "ui", "ux"), "design"),
    (("dev", "bug", "backend", "frontend"), "dev"),
    (("chat", "general", "chung", "phiem", "phiếm", "off-topic"), "chat"),
)


def resolve_channel_mode(channel: discord.abc.Messageable) -> Optional[str]:
    # Thread kế thừa mode của kênh cha
    lookup = channel.parent if isinstance(channel, discord.Thread) and channel.parent else channel
    channel_id = getattr(lookup, "id", None)
    if channel_id in config.channel_modes:
        return config.channel_modes[channel_id]
    ch_lower = (getattr(lookup, "name", "") or "").lower()
    if ch_lower in CHANNEL_NAME_MODES:
        return CHANNEL_NAME_MODES[ch_lower]
    for keywords, mode in CHANNEL_KEYWORD_MODES:
        if any(k in ch_lower for k in keywords):
            return mode
    return None


def get_channel_it_context(channel: discord.abc.Messageable) -> str:
    """Gắn vai trò phù hợp theo từng kênh trong Server của Sếp Phát."""
    mode = resolve_channel_mode(channel)
    if mode and mode in CHANNEL_MODES:
        return "\n\n" + CHANNEL_MODES[mode]["prompt"]
    ch_name = getattr(channel, "name", "") or "chat"
    return (
        f"\n\n🌐 **[KÊNH HIỆN TẠI: #{ch_name}]:** "
        "Sẵn sàng hỗ trợ Sếp Phát mọi việc: kỹ thuật, kế hoạch, phân tích, truyền thông lẫn chém gió, quản trị server."
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


FALLBACK_TEXT_MODELS = (
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "openai/gpt-oss-20b",
)
AI_REASONING_EFFORT = os.getenv("AI_REASONING_EFFORT", "medium").strip().lower()
RETRYABLE_AI_ERRORS = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
)


async def create_chat_completion(
    client: AsyncOpenAI,
    model: str,
    messages: List[dict],
    temperature: float,
    max_tokens: int,
    allow_fallback: bool = True,
) -> Any:
    """Gọi AI có retry khi bị rate limit / lỗi mạng, rồi thử model dự phòng nếu model chính vẫn lỗi."""
    models_to_try = [model]
    if allow_fallback:
        models_to_try += [
            m
            for m in FALLBACK_TEXT_MODELS
            if m != model and (not config.available_models or m in config.available_models)
        ][:2]

    last_exc: Optional[Exception] = None
    for candidate in models_to_try:
        for attempt in range(2):
            # Model suy luận (gpt-oss) được "nghĩ kỹ" trước khi trả lời -> câu trả lời sâu và chính xác hơn
            extra_body = (
                {"reasoning_effort": AI_REASONING_EFFORT}
                if AI_REASONING_EFFORT and "gpt-oss" in candidate
                else None
            )
            try:
                return await client.chat.completions.create(
                    model=candidate,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body=extra_body,
                )
            except openai.BadRequestError as exc:
                if not extra_body:
                    raise
                # Provider không hỗ trợ reasoning_effort -> gọi lại kiểu thường
                logger.warning("Model %s không nhận reasoning_effort: %s", candidate, exc)
                return await client.chat.completions.create(
                    model=candidate,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except RETRYABLE_AI_ERRORS as exc:
                last_exc = exc
                logger.warning("AI lỗi tạm thời (%s, lần %s): %s", candidate, attempt + 1, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


async def ask_ai_Boss(
    prompt: str,
    system_override: Optional[str] = None,
    temperature: float = 0.65,
) -> str:
    """Hàm gọi nhanh AI với phong cách của Boss cho các lệnh Slash Commands."""
    client, text_model, _ = config.get_client_and_models()
    sys_prompt = (system_override or config.system_prompt) + build_time_context()
    resp = await create_chat_completion(
        client,
        text_model,
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=2048,
    )
    return (resp.choices[0].message.content or "Hệ thống AI đang bận xử lý, Sếp vui lòng thử lại sau giây lát nhé!").strip()


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
        await init_task_sheet()
        asyncio.create_task(task_sheet_sync_loop())
        asyncio.create_task(scheduler_loop())
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
    if user.id in config.boss_user_ids:
        return True
    if bot.app_owner_id and user.id == bot.app_owner_id:
        return True
    if guild and guild.owner_id and user.id == guild.owner_id:
        return True
    # Đoán theo tên chỉ khi chưa xác định được Sếp bằng ID — tên hiển thị ai cũng đổi được
    if config.boss_user_ids or bot.app_owner_id:
        return False
    uname = user.name.lower()
    return "phat" in uname or "phát" in uname


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


def parse_task_deadline(text: str) -> Tuple[int, str]:
    """
    Phân tích thời gian deadline từ văn bản tiếng Việt và trả về:
    (unix_timestamp, nhãn_mô_tả)
    Hỗ trợ: phút, tiếng/giờ, ngày, thứ trong tuần, hôm nay, ngày mai, trong tuần này.
    Nếu không có mốc thời gian -> mặc định 24 giờ.
    """
    now = now_vn()
    text_lower = text.lower()

    # 1. Phút (ví dụ: 15 phút, 30p, 45 min)
    m = re.search(r"\b(\d+)\s*(?:phút|p\b|min)", text_lower)
    if m:
        mins = max(1, int(m.group(1)))
        target = now + datetime.timedelta(minutes=mins)
        return int(target.timestamp()), f"{mins} phút"

    # 2. Tiếng / Giờ (ví dụ: 2 tiếng, 3 giờ, 1h, 4hr)
    m = re.search(r"\b(\d+)\s*(?:tiếng|giờ|h\b|hr)", text_lower)
    if m:
        hours = max(1, int(m.group(1)))
        target = now + datetime.timedelta(hours=hours)
        return int(target.timestamp()), f"{hours} tiếng"

    # 3. Ngày (ví dụ: 2 ngày, 3d, 1 day)
    m = re.search(r"\b(\d+)\s*(?:ngày|d\b|days?)", text_lower)
    if m:
        days = max(1, int(m.group(1)))
        target = now + datetime.timedelta(days=days)
        return int(target.timestamp()), f"{days} ngày"

    # 4. Trong tuần này / cuối tuần / hết tuần
    if any(k in text_lower for k in ("trong tuần này", "cuối tuần", "hết tuần", "tuần này")):
        days_ahead = 6 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target = (now + datetime.timedelta(days=days_ahead)).replace(hour=23, minute=59, second=0, microsecond=0)
        return int(target.timestamp()), "Chủ Nhật tuần này (23:59)"

    # 5. Các thứ trong tuần: thứ 2 -> thứ 7, chủ nhật
    day_mapping = {
        "thứ 2": 0, "thứ hai": 0, "t2": 0,
        "thứ 3": 1, "thứ ba": 1, "t3": 1,
        "thứ 4": 2, "thứ tư": 2, "t4": 2,
        "thứ 5": 3, "thứ năm": 3, "t5": 3,
        "thứ 6": 4, "thứ sáu": 4, "t6": 4,
        "thứ 7": 5, "thứ bảy": 5, "t7": 5,
        "chủ nhật": 6, "cn": 6,
    }
    for day_str, target_weekday in day_mapping.items():
        if day_str in text_lower:
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = (now + datetime.timedelta(days=days_ahead)).replace(hour=18, minute=0, second=0, microsecond=0)
            return int(target.timestamp()), day_str.title()

    # 6. Hôm nay / trong ngày / hết ngày
    if any(k in text_lower for k in ("hôm nay", "trong ngày", "hết ngày")):
        target = now.replace(hour=23, minute=59, second=0, microsecond=0)
        return int(target.timestamp()), "Hết ngày hôm nay (23:59)"

    # 7. Ngày mai
    if "ngày mai" in text_lower or "mai" in text_lower:
        target = (now + datetime.timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        return int(target.timestamp()), "18:00 Ngày mai"

    # 8. Mặc định nếu không ghi rõ thời gian -> Đếm ngược 24 tiếng
    target = now + datetime.timedelta(hours=24)
    return int(target.timestamp()), "24 giờ tới (mặc định)"


# ================= LƯU DỮ LIỆU: GOOGLE SHEET (NGUỒN CHÍNH) + FILE LOCAL (DỰ PHÒNG) =================
# Mỗi bảng (Tasks, Trí nhớ, Nhắc việc, Cài đặt) là 1 tab trong cùng Google Sheet.
# Bot giữ dữ liệu trong RAM, mọi thay đổi ghi ra file local ngay và đẩy lên Sheet sau vài giây.
# Định kỳ đọc lại Sheet để nhận chỉnh sửa tay (đổi hạn, đổi trạng thái, thêm dòng mới...).

SHEET_DATE_FORMAT = "%d/%m/%Y %H:%M"
SHEET_PUSH_INTERVAL = 10
SHEET_PULL_INTERVAL = 180


def _extract_sheet_id(raw: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", raw)
    return m.group(1) if m else raw.strip()


TASK_SHEET_ID = _extract_sheet_id(os.getenv("TASK_SHEET_ID", ""))
TASK_SHEET_TAB = os.getenv("TASK_SHEET_TAB", "Tasks").strip() or "Tasks"


def task_sheet_url() -> Optional[str]:
    return f"https://docs.google.com/spreadsheets/d/{TASK_SHEET_ID}" if TASK_SHEET_ID else None


def _fmt_sheet_time(ts: Any) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ts), VN_TZ).strftime(SHEET_DATE_FORMAT) if ts else ""
    except (TypeError, ValueError):
        return ""


def _parse_sheet_time(text: str) -> int:
    text = (text or "").strip()
    for fmt in (SHEET_DATE_FORMAT, "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(text, fmt)
            if fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                dt = dt.replace(hour=23, minute=59)
            return int(dt.replace(tzinfo=VN_TZ).timestamp())
        except ValueError:
            continue
    return 0


def _parse_id_list(text: str) -> List[int]:
    return [int(x) for x in re.findall(r"\d{5,}", text or "")]


def _pad_row(row: List[str], width: int) -> List[str]:
    return [c.strip() for c in (list(row) + [""] * width)[:width]]


class SheetTable:
    """Một bảng dữ liệu đồng bộ 2 chiều giữa RAM, file local và 1 tab Google Sheet."""

    def __init__(
        self,
        tab: str,
        headers: List[str],
        local_file: Path,
        to_rows: Any,
        from_rows: Any,
        empty: Any,
    ) -> None:
        self.tab = tab
        self.headers = headers
        self.local_file = local_file
        self.to_rows = to_rows  # data -> List[List[str]]
        self.from_rows = from_rows  # List[List[str]] -> data
        self.empty = empty
        self.data: Any = None
        self.dirty = False
        self.ws: Any = None

    def load(self) -> Any:
        if self.data is None:
            self.data = self._read_local()
        return self.data

    def save(self, data: Any) -> None:
        self.data = data
        self.dirty = True
        try:
            self.local_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.warning("Không lưu được file %s: %s", self.local_file.name, exc)

    def _read_local(self) -> Any:
        if self.local_file.exists():
            try:
                return json.loads(self.local_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Không đọc được file %s: %s", self.local_file.name, exc)
        return self.empty()

    # --- Các hàm dưới chạy trong thread (gspread là thư viện sync) ---
    def pull_sync(self) -> Tuple[Any, bool]:
        """Đọc Sheet. Trả về (dữ liệu, cần_ghi_lại) — cần ghi lại khi bot chuẩn hoá/cấp mã cho dòng nhập tay."""
        values = self.ws.get_all_values()
        width = len(self.headers)
        raw_rows = [_pad_row(r, width) for r in values[1:] if any(c.strip() for c in r)]
        data = self.from_rows(raw_rows)
        normalized = [_pad_row([str(c) for c in r], width) for r in self.to_rows(data)]
        header_ok = bool(values) and _pad_row(values[0], width) == self.headers
        return data, (normalized != raw_rows or not header_ok)

    def push_sync(self, data: Any) -> None:
        rows = [self.headers] + self.to_rows(data)
        self.ws.clear()
        # RAW để ID Discord (18 số) giữ nguyên dạng chữ, không bị Sheets làm tròn
        self.ws.update(range_name="A1", values=rows, value_input_option="RAW")
        try:
            self.ws.freeze(rows=1)
        except Exception:
            pass


# ---------- Bảng Tasks ----------
TASK_SHEET_HEADERS = [
    "Mã task", "Giai đoạn", "Nội dung", "Người nhận", "Hạn chót", "Trạng thái", "Người giao",
    "Ngày giao", "File/Link đã nộp", "Ngày nộp",
    "ID người nhận", "ID người giao", "ID kênh", "ID server", "Đã nhắc sắp hạn", "Đã báo quá hạn",
]
TASK_STATUS_TO_VN = {"pending": "Đang làm", "completed": "Hoàn thành", "cancelled": "Huỷ"}
TASK_STATUS_FROM_VN = {
    "đang làm": "pending", "pending": "pending", "": "pending",
    "hoàn thành": "completed", "done": "completed", "xong": "completed", "completed": "completed",
    "huỷ": "cancelled", "hủy": "cancelled", "cancelled": "cancelled",
}
# Task nhập tay trên Sheet được cấp mã tạm "S..." -> bot thông báo lên Discord rồi đổi sang mã tin nhắn
SHEET_TASK_PREFIX = "S"


def _task_to_row(t: Dict[str, Any]) -> List[str]:
    return [
        str(t.get("task_id", "")),
        str(t.get("phase") or ""),
        str(t.get("task_desc", "")),
        ", ".join(t.get("assigned_names", [])),
        _fmt_sheet_time(t.get("deadline_ts")),
        TASK_STATUS_TO_VN.get(t.get("status", "pending"), "Đang làm"),
        str(t.get("creator_name", "")),
        _fmt_sheet_time(t.get("created_at")),
        str(t.get("submitted_file") or ""),
        _fmt_sheet_time(t.get("submitted_at")),
        ", ".join(str(uid) for uid in t.get("assigned_user_ids", [])),
        str(t.get("creator_id") or ""),
        str(t.get("channel_id") or ""),
        str(t.get("guild_id") or ""),
        "x" if t.get("warned_soon") else "",
        "x" if t.get("warned_overdue") else "",
    ]


def _row_to_task(row: List[str], row_index: int) -> Optional[Dict[str, Any]]:
    (task_id, phase, desc, names, deadline, status, creator_name, created, submitted_file,
     submitted_at, assigned_ids, creator_id, channel_id, guild_id, warned_soon, warned_overdue) = row
    if not desc:
        return None
    now_ts = int(now_vn().timestamp())
    if not task_id:
        task_id = f"{SHEET_TASK_PREFIX}{now_ts}{row_index:03d}"
    return {
        "task_id": task_id,
        "phase": phase,
        "message_id": int(task_id) if task_id.isdigit() else 0,
        "channel_id": int(channel_id) if channel_id.isdigit() else None,
        "guild_id": int(guild_id) if guild_id.isdigit() else None,
        "creator_id": int(creator_id) if creator_id.isdigit() else None,
        "creator_name": creator_name,
        "assigned_user_ids": _parse_id_list(assigned_ids),
        "assigned_names": [n.strip() for n in names.split(",") if n.strip()],
        "task_desc": desc,
        "deadline_ts": _parse_sheet_time(deadline),
        "status": TASK_STATUS_FROM_VN.get(status.lower(), "pending"),
        "created_at": _parse_sheet_time(created) or now_ts,
        "submitted_file": submitted_file or None,
        "submitted_at": _parse_sheet_time(submitted_at) or None,
        "submitted_by_id": None,
        "warned_soon": bool(warned_soon),
        "warned_overdue": bool(warned_overdue),
    }


def _tasks_to_rows(tasks: Dict[str, Any]) -> List[List[str]]:
    ordered = sorted(tasks.values(), key=lambda t: int(t.get("created_at") or 0))
    return [_task_to_row(t) for t in ordered]


def _tasks_from_rows(rows: List[List[str]]) -> Dict[str, Any]:
    tasks: Dict[str, Any] = {}
    for idx, row in enumerate(rows, start=2):
        t = _row_to_task(row, idx)
        if t:
            tasks[t["task_id"]] = t
    return tasks


# ---------- Bảng Trí nhớ ----------
MEMORY_SHEET_HEADERS = ["Mã", "Nội dung ghi nhớ", "Người ghi", "Ngày ghi", "ID server"]


def _memories_to_rows(memories: List[Dict[str, Any]]) -> List[List[str]]:
    return [
        [str(m.get("id", "")), str(m.get("text", "")), str(m.get("by", "")),
         _fmt_sheet_time(m.get("at")), str(m.get("guild_id") or "")]
        for m in memories
    ]


def _memories_from_rows(rows: List[List[str]]) -> List[Dict[str, Any]]:
    memories: List[Dict[str, Any]] = []
    next_id = max((int(r[0]) for r in rows if r[0].isdigit()), default=0) + 1
    for mem_id, text, by, at, guild_id in rows:
        if not text:
            continue
        if not mem_id.isdigit():
            mem_id, next_id = str(next_id), next_id + 1
        memories.append({
            "id": int(mem_id),
            "text": text,
            "by": by or "Sheet",
            "at": _parse_sheet_time(at) or int(now_vn().timestamp()),
            "guild_id": int(guild_id) if guild_id.isdigit() else None,
        })
    return memories


# ---------- Bảng Nhắc việc ----------
REMINDER_SHEET_HEADERS = ["Thời gian nhắc", "Nội dung", "Người nhận", "ID người nhận", "ID kênh"]


def _reminders_to_rows(reminders: List[Dict[str, Any]]) -> List[List[str]]:
    ordered = sorted(reminders, key=lambda r: int(r.get("due_ts") or 0))
    return [
        [_fmt_sheet_time(r.get("due_ts")), str(r.get("text", "")), str(r.get("user_name") or ""),
         str(r.get("user_id") or ""), str(r.get("channel_id") or "")]
        for r in ordered
    ]


def _reminders_from_rows(rows: List[List[str]]) -> List[Dict[str, Any]]:
    reminders: List[Dict[str, Any]] = []
    for due, text, user_name, user_id, channel_id in rows:
        due_ts = _parse_sheet_time(due)
        if not text or not due_ts:
            continue
        reminders.append({
            "due_ts": due_ts,
            "text": text,
            "user_name": user_name,
            "user_id": int(user_id) if user_id.isdigit() else None,
            "channel_id": int(channel_id) if channel_id.isdigit() else None,
        })
    return reminders


# ---------- Bảng Cài đặt (giai đoạn hiện tại, mốc gửi báo cáo...) ----------
SETTINGS_SHEET_HEADERS = ["Khoá", "Giá trị"]


def _settings_to_rows(settings: Dict[str, str]) -> List[List[str]]:
    return [[k, str(v)] for k, v in settings.items()]


def _settings_from_rows(rows: List[List[str]]) -> Dict[str, str]:
    return {k: v for k, v in rows if k}


TASK_TABLE = SheetTable(TASK_SHEET_TAB, TASK_SHEET_HEADERS, TASKS_FILE, _tasks_to_rows, _tasks_from_rows, dict)
MEMORY_TABLE = SheetTable("Trí nhớ", MEMORY_SHEET_HEADERS, MEMORY_FILE, _memories_to_rows, _memories_from_rows, list)
REMINDER_TABLE = SheetTable("Nhắc việc", REMINDER_SHEET_HEADERS, REMINDERS_FILE, _reminders_to_rows, _reminders_from_rows, list)
SETTINGS_TABLE = SheetTable("Cài đặt", SETTINGS_SHEET_HEADERS, Path(__file__).parent / "settings.json", _settings_to_rows, _settings_from_rows, dict)
SHEET_TABLES = (TASK_TABLE, MEMORY_TABLE, REMINDER_TABLE, SETTINGS_TABLE)


def get_setting(key: str, default: str = "") -> str:
    return str(SETTINGS_TABLE.load().get(key, default))


def set_setting(key: str, value: str) -> None:
    settings = SETTINGS_TABLE.load()
    settings[key] = value
    SETTINGS_TABLE.save(settings)


def _load_tasks() -> Dict[str, Any]:
    """Danh sách task hiện tại (cache trong RAM, đồng bộ với Google Sheet)."""
    return TASK_TABLE.load()


def _save_tasks(tasks: Dict[str, Any]) -> None:
    TASK_TABLE.save(tasks)


def _load_service_account_info() -> Dict[str, Any]:
    """Tìm key Service Account: biến GOOGLE_SERVICE_ACCOUNT_JSON (nội dung hoặc đường dẫn),
    GOOGLE_SERVICE_ACCOUNT_FILE, rồi tới các vị trí mặc định (Secret File của Render, thư mục bot)."""
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    candidates: List[str] = []
    if raw_json.startswith("{"):
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_JSON không phải JSON hợp lệ (dán thiếu?): {exc}") from exc
    if raw_json:
        candidates.append(raw_json)  # điền nhầm đường dẫn file vào biến JSON
    for path in (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip(),
        "/etc/secrets/boss-service-account.json",
        str(Path(__file__).parent / "boss-service-account.json"),
    ):
        if path and path not in candidates:
            candidates.append(path)

    problems: List[str] = []
    for path in candidates:
        file_path = Path(path)
        if not file_path.is_file():
            problems.append(f"{path}: không tồn tại")
            continue
        content = file_path.read_text(encoding="utf-8-sig").strip()
        if not content:
            problems.append(f"{path}: file trống")
            continue
        try:
            info = json.loads(content)
        except json.JSONDecodeError as exc:
            problems.append(f"{path}: không phải JSON hợp lệ ({exc}), bắt đầu bằng {content[:12]!r}")
            continue
        if info.get("type") != "service_account" or "private_key" not in info:
            problems.append(f"{path}: không phải key Service Account")
            continue
        logger.info("Dùng key Service Account từ %s (%s)", path, info.get("client_email"))
        return info
    raise RuntimeError("Không tìm được key Service Account hợp lệ — " + "; ".join(problems))


def _open_worksheets_sync() -> None:
    """Kết nối Google Sheet bằng Service Account và mở (hoặc tạo) từng tab."""
    import gspread

    gc = gspread.service_account_from_dict(_load_service_account_info())
    spreadsheet = gc.open_by_key(TASK_SHEET_ID)
    for table in SHEET_TABLES:
        try:
            table.ws = spreadsheet.worksheet(table.tab)
        except gspread.WorksheetNotFound:
            table.ws = spreadsheet.add_worksheet(title=table.tab, rows=200, cols=len(table.headers))


async def init_task_sheet() -> None:
    """Khởi động: kết nối Sheet và lấy dữ liệu từ Sheet (tab trống thì chuyển dữ liệu local lên)."""
    if not TASK_SHEET_ID:
        logger.info("Chưa cấu hình TASK_SHEET_ID -> dữ liệu chỉ lưu file local.")
        return
    try:
        await asyncio.to_thread(_open_worksheets_sync)
    except Exception as exc:
        for table in SHEET_TABLES:
            table.ws = None
        logger.warning("Không kết nối được Google Sheet, dùng file local: %s", exc)
        return
    for table in SHEET_TABLES:
        try:
            data, _ = await asyncio.to_thread(table.pull_sync)
            table.data = data if data else table.load()
            table.dirty = True  # ghi header + chuẩn hoá ngay lần đầu
            logger.info("📊 Đã đồng bộ tab '%s' (%s dòng).", table.tab, len(table.data))
        except Exception as exc:
            logger.warning("Lỗi đọc tab '%s': %s", table.tab, exc)


async def task_sheet_sync_loop() -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(SHEET_PUSH_INTERVAL)
        elapsed += SHEET_PUSH_INTERVAL
        do_pull = elapsed >= SHEET_PULL_INTERVAL
        if do_pull:
            elapsed = 0
        for table in SHEET_TABLES:
            if table.ws is None:
                continue
            try:
                if table.dirty:
                    table.dirty = False
                    snapshot = json.loads(json.dumps(table.load()))
                    await asyncio.to_thread(table.push_sync, snapshot)
                elif do_pull:
                    data, needs_push = await asyncio.to_thread(table.pull_sync)
                    if not table.dirty:  # không ghi đè thay đổi local vừa phát sinh trong lúc đọc
                        table.data = data
                        table.dirty = needs_push
            except Exception as exc:
                table.dirty = True
                logger.warning("Lỗi đồng bộ tab '%s' (sẽ thử lại): %s", table.tab, exc)


def record_new_task(
    message_id: int,
    channel_id: int,
    guild_id: Optional[int],
    creator_id: int,
    creator_name: str,
    assigned_user_ids: List[int],
    assigned_names: List[str],
    task_desc: str,
    deadline_ts: int,
    phase: str = "",
) -> None:
    """Ghi nhận một task mới được giao vào danh sách theo dõi."""
    tasks = _load_tasks()
    tasks[str(message_id)] = {
        "task_id": str(message_id),
        "phase": phase,
        "message_id": message_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
        "creator_id": creator_id,
        "creator_name": creator_name,
        "assigned_user_ids": assigned_user_ids,
        "assigned_names": assigned_names,
        "task_desc": task_desc,
        "deadline_ts": deadline_ts,
        "status": "pending",
        "created_at": int(now_vn().timestamp()),
        "submitted_file": None,
        "submitted_at": None,
        "submitted_by_id": None,
    }
    _save_tasks(tasks)


def get_pending_task_for_user(
    channel_id: int, user_id: int, reply_msg_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """Tìm task đang chờ nộp (pending) của thành viên trong kênh."""
    tasks = _load_tasks()
    # 1. Nếu đang reply trực tiếp tin nhắn của task đó
    if reply_msg_id and str(reply_msg_id) in tasks:
        t = tasks[str(reply_msg_id)]
        if t.get("status") == "pending":
            return t

    # 2. Tìm các task pending của user trong kênh này
    matched: List[Dict[str, Any]] = []
    for t in tasks.values():
        if (
            t.get("status") == "pending"
            and t.get("channel_id") == channel_id
            and user_id in t.get("assigned_user_ids", [])
        ):
            matched.append(t)

    if matched:
        # Lấy task mới nhất được giao
        matched.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return matched[0]

    return None


def mark_task_completed(
    task_id: str, file_info: str, user_id: int
) -> Optional[Dict[str, Any]]:
    """Đánh dấu task đã hoàn thành sau khi nộp file hợp lệ."""
    tasks = _load_tasks()
    if task_id in tasks:
        t = tasks[task_id]
        t["status"] = "completed"
        t["submitted_file"] = file_info
        t["submitted_at"] = int(now_vn().timestamp())
        t["submitted_by_id"] = user_id
        _save_tasks(tasks)
        return t
    return None


def get_task_by_id(task_id: Union[int, str]) -> Optional[Dict[str, Any]]:
    """Lấy thông tin task theo ID tin nhắn task."""
    tasks = _load_tasks()
    return tasks.get(str(task_id))


# ================= TRÍ NHỚ DÀI HẠN CỦA TEAM =================

MAX_MEMORY_ENTRIES = 80


def add_team_memory(text: str, author_name: str, guild_id: Optional[int]) -> int:
    """Ghi nhớ một sự thật/quy định/thông tin lâu dài của team. Trả về ID ghi nhớ."""
    memories = MEMORY_TABLE.load()
    next_id = max((int(m.get("id", 0)) for m in memories), default=0) + 1
    memories.append(
        {
            "id": next_id,
            "guild_id": guild_id,
            "text": text.strip()[:500],
            "by": author_name,
            "at": int(now_vn().timestamp()),
        }
    )
    MEMORY_TABLE.save(memories[-MAX_MEMORY_ENTRIES:])
    return next_id


def remove_team_memory(query: str, guild_id: Optional[int]) -> List[str]:
    """Xoá ghi nhớ theo ID hoặc theo đoạn nội dung khớp. Trả về các nội dung đã xoá."""
    memories = MEMORY_TABLE.load()
    q = query.strip().lower().lstrip("#")
    removed: List[str] = []
    kept: List[Dict[str, Any]] = []
    for m in memories:
        same_guild = m.get("guild_id") in (None, guild_id)
        matched = q and (q == str(m.get("id")) or q in str(m.get("text", "")).lower())
        if same_guild and matched:
            removed.append(str(m.get("text", "")))
        else:
            kept.append(m)
    if removed:
        MEMORY_TABLE.save(kept)
    return removed


def get_team_memories(guild_id: Optional[int]) -> List[Dict[str, Any]]:
    return [
        m for m in MEMORY_TABLE.load() if m.get("guild_id") in (None, guild_id)
    ]


def build_memory_context(guild_id: Optional[int]) -> str:
    memories = get_team_memories(guild_id)
    if not memories:
        return ""
    lines = [f"- (#{m.get('id')}) {m.get('text')}" for m in memories[-40:]]
    return (
        "\n\n[🧠 TRÍ NHỚ DÀI HẠN CỦA TEAM — thông tin Sếp/VIP đã dặn ghi nhớ, dùng khi liên quan]:\n"
        + "\n".join(lines)
    )


# ================= NHẮC VIỆC & THEO DÕI DEADLINE (LƯU FILE, SỐNG SÓT KHI RESTART) =================


def add_reminder(
    channel_id: int, user_id: int, text: str, due_ts: int, user_name: str = ""
) -> None:
    reminders = REMINDER_TABLE.load()
    reminders.append(
        {"channel_id": channel_id, "user_id": user_id, "user_name": user_name, "text": text, "due_ts": due_ts}
    )
    REMINDER_TABLE.save(reminders)


def get_pending_tasks(
    guild_id: Optional[int] = None,
    user_id: Optional[int] = None,
    phase: Optional[str] = None,
) -> List[Dict[str, Any]]:
    result = []
    phase_key = (phase or "").strip().lower()
    for t in _load_tasks().values():
        if t.get("status") != "pending":
            continue
        if phase_key and phase_key not in str(t.get("phase") or "").lower():
            continue
        if guild_id is not None and t.get("guild_id") not in (None, guild_id):
            continue
        if user_id is not None and user_id not in t.get("assigned_user_ids", []):
            continue
        result.append(t)
    result.sort(key=lambda x: x.get("deadline_ts", 0))
    return result


def format_task_line(t: Dict[str, Any]) -> str:
    now_ts = int(now_vn().timestamp())
    deadline_ts = int(t.get("deadline_ts", 0))
    overdue = " 🔴 **QUÁ HẠN**" if deadline_ts and deadline_ts < now_ts else ""
    names = ", ".join(t.get("assigned_names", [])) or "?"
    deadline_str = f"<t:{deadline_ts}:R>" if deadline_ts else "chưa có hạn"
    phase = f"[{t['phase']}] " if t.get("phase") else ""
    return (
        f"• `#{str(t.get('task_id'))[-5:]}` {phase}**{t.get('task_desc')}** — 🎯 {names} — "
        f"⏳ {deadline_str}{overdue}"
    )


def build_task_context(guild_id: Optional[int]) -> str:
    """Tóm tắt task đang chạy để AI trả lời được các câu như 'ai đang trễ deadline?'."""
    pending = get_pending_tasks(guild_id)
    current_phase = get_setting("current_phase")
    phase_note = f"\n\n[🏷️ GIAI ĐOẠN DỰ ÁN HIỆN TẠI]: {current_phase}" if current_phase else ""
    if not pending:
        return phase_note + "\n\n[📋 TASK ĐANG CHẠY]: Hiện không có task nào đang chờ nộp."
    now_ts = int(now_vn().timestamp())
    lines = []
    for t in pending[:25]:
        deadline_ts = int(t.get("deadline_ts", 0))
        deadline_str = (
            datetime.datetime.fromtimestamp(deadline_ts, VN_TZ).strftime("%H:%M %d/%m")
            if deadline_ts else "chưa có hạn"
        )
        state = "QUÁ HẠN" if deadline_ts and deadline_ts < now_ts else "đang làm"
        phase = f" | giai đoạn: {t['phase']}" if t.get("phase") else ""
        lines.append(
            f"- [mã {str(t.get('task_id'))[-5:]}] {t.get('task_desc')} | người nhận: "
            f"{', '.join(t.get('assigned_names', []))} | hạn: {deadline_str} ({state}){phase}"
        )
    return phase_note + "\n\n[📋 TASK ĐANG CHẠY TRONG SERVER]:\n" + "\n".join(lines)


def find_pending_task(query: str, guild_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Tìm task pending theo mã (5 số cuối) hoặc theo đoạn mô tả."""
    q = query.strip().lower().lstrip("#")
    if not q:
        return None
    for t in get_pending_tasks(guild_id):
        if str(t.get("task_id", "")).endswith(q) or q in str(t.get("task_desc", "")).lower():
            return t
    return None


def set_task_status(task_id: str, status: str) -> None:
    tasks = _load_tasks()
    if task_id in tasks:
        tasks[task_id]["status"] = status
        _save_tasks(tasks)


async def _get_messageable(channel_id: int) -> Optional[discord.abc.Messageable]:
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return None
    return channel  # type: ignore[return-value]


# ================= GHÉP TÊN -> THÀNH VIÊN, KÊNH TASK, THÔNG BÁO TASK TỪ SHEET =================


def _norm_name(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower().strip().lstrip("@")


def find_member_by_name(guild: discord.Guild, name: str) -> Optional[discord.Member]:
    """Tìm thành viên theo tên (không phân biệt dấu/hoa thường). Chỉ trả về khi khớp duy nhất 1 người."""
    target = _norm_name(name)
    if not target:
        return None
    members = [m for m in guild.members if not m.bot]

    def names_of(m: discord.Member) -> Set[str]:
        return {_norm_name(m.display_name), _norm_name(m.name), _norm_name(m.global_name or "")} - {""}

    exact = [m for m in members if target in names_of(m)]
    if len(exact) == 1:
        return exact[0]
    partial = [m for m in members if any(target in n for n in names_of(m))]
    return partial[0] if len(partial) == 1 else None


def get_task_guild(guild_id: Optional[int]) -> Optional[discord.Guild]:
    if guild_id:
        return bot.get_guild(guild_id)
    return bot.guilds[0] if len(bot.guilds) == 1 else None


REPORT_CHANNEL_ID = int(os.getenv("REPORT_CHANNEL_ID", "0") or 0)


def find_task_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Kênh giao việc của server: REPORT_CHANNEL_ID nếu có, nếu không lấy kênh đang ở chế độ 'task'."""
    if REPORT_CHANNEL_ID:
        ch = guild.get_channel(REPORT_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            return ch
    task_channels = [ch for ch in guild.text_channels if resolve_channel_mode(ch) == "task"]
    task_channels.sort(key=lambda ch: (ch.name.lower() != "task", ch.position))
    return task_channels[0] if task_channels else None


def build_task_embed(
    task_desc: str,
    deadline_ts: int,
    creator_text: str,
    mention_str: str,
    phase: str = "",
    is_reminder: bool = False,
    footer_name: str = "",
) -> discord.Embed:
    deadline_line = (
        f"<t:{deadline_ts}:F> (<t:{deadline_ts}:R>)" if deadline_ts else "Chưa có hạn — Sếp bổ sung trên bảng task nhé"
    )
    phase_line = f"🏷️ **Giai đoạn:** {phase}\n" if phase else ""
    embed = discord.Embed(
        title="🔔 NHẮC NHỞ CÔNG VIỆC / TASK!" if is_reminder else "📋 TASK MỚI ĐƯỢC GIAO!",
        description=(
            f"📝 **Nội dung:** {task_desc}\n\n"
            f"{phase_line}"
            f"⏳ **Hạn chót & Đếm ngược:** {deadline_line}\n\n"
            f"👤 **Người giao/nhắc:** {creator_text}\n"
            f"🎯 **Người nhận:** {mention_str}\n\n"
            f"📁 **Quy tắc duyệt Done:** Đính kèm FILE làm việc (tài liệu/code/báo cáo hoặc link sản phẩm) vào kênh này thì Boss mới tự động tick Done!"
        ),
        color=discord.Color.gold() if is_reminder else discord.Color.orange(),
    )
    embed.set_footer(
        text=f"Bởi {footer_name or 'Boss'} • ⚠️ BẮT BUỘC nộp kèm FILE làm việc để hoàn thành! 📁"
    )
    return embed


async def announce_sheet_tasks() -> None:
    """Task nhập tay trên Google Sheet (mã 'S...'): ghép tên -> thành viên, đăng lên kênh task, đổi sang mã tin nhắn."""
    tasks = _load_tasks()
    new_ids = [
        tid for tid, t in tasks.items()
        if tid.startswith(SHEET_TASK_PREFIX) and t.get("status") == "pending"
    ]
    for old_id in new_ids:
        t = tasks.get(old_id)
        if not t:
            continue
        guild = get_task_guild(t.get("guild_id"))
        if not guild:
            continue
        channel = guild.get_channel(t["channel_id"]) if t.get("channel_id") else find_task_channel(guild)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            continue

        user_ids = list(t.get("assigned_user_ids", []))
        display_names: List[str] = []
        unresolved: List[str] = []
        for name in t.get("assigned_names", []):
            member = find_member_by_name(guild, name)
            if member:
                if member.id not in user_ids:
                    user_ids.append(member.id)
                display_names.append(member.display_name)
            else:
                unresolved.append(name)
                display_names.append(name)
        mention_str = " ".join(f"<@{uid}>" for uid in user_ids) or "(chưa rõ người nhận)"
        if unresolved:
            mention_str += f" *(không tìm thấy thành viên: {', '.join(unresolved)})*"
        creator_text = f"<@{t['creator_id']}>" if t.get("creator_id") else (t.get("creator_name") or "Bảng task")

        embed = build_task_embed(
            t.get("task_desc", ""), int(t.get("deadline_ts") or 0), creator_text, mention_str,
            phase=t.get("phase", ""), footer_name=t.get("creator_name") or "Bảng task",
        )
        msg = await channel.send(content=f"📣 {mention_str} — có task mới từ bảng task nè! 🔥", embed=embed)
        try:
            await msg.add_reaction("🔄")
        except Exception:
            pass

        tasks = _load_tasks()  # lấy lại phòng khi vừa có đồng bộ trong lúc gửi
        t = tasks.pop(old_id, t)
        t.update(
            task_id=str(msg.id),
            message_id=msg.id,
            channel_id=channel.id,
            guild_id=guild.id,
            assigned_user_ids=user_ids,
            assigned_names=display_names,
        )
        tasks[str(msg.id)] = t
        _save_tasks(tasks)


# ================= BÁO CÁO TỰ ĐỘNG (SÁNG HẰNG NGÀY & CUỐI TUẦN) =================

DAILY_REPORT_TIME = os.getenv("DAILY_REPORT_TIME", "08:30").strip()
WEEKLY_REPORT_TIME = os.getenv("WEEKLY_REPORT_TIME", "17:30").strip()
WEEKLY_REPORT_WEEKDAY = 4  # Thứ Sáu


def _parse_hhmm(text: str) -> Optional[Tuple[int, int]]:
    m = re.fullmatch(r"(\d{1,2})[:h](\d{2})", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _field_text(lines: List[str], empty: str = "—") -> str:
    out = ""
    for line in lines:
        if len(out) + len(line) + 1 > 1000:
            out += "\n…"
            break
        out += line + "\n"
    return out.strip() or empty


def _task_short(t: Dict[str, Any], show_deadline: bool = True) -> str:
    who = ", ".join(t.get("assigned_names", [])) or "?"
    deadline_ts = int(t.get("deadline_ts") or 0)
    tail = f" — <t:{deadline_ts}:R>" if show_deadline and deadline_ts else ""
    phase = f"[{t['phase']}] " if t.get("phase") else ""
    return f"• {phase}**{t.get('task_desc')}** — {who}{tail}"


def build_daily_report(guild_id: Optional[int]) -> discord.Embed:
    now = now_vn()
    now_ts = int(now.timestamp())
    end_today = int(now.replace(hour=23, minute=59, second=59).timestamp())
    in_3_days = now_ts + 3 * 86400
    pending = get_pending_tasks(guild_id)
    overdue = [t for t in pending if t.get("deadline_ts") and t["deadline_ts"] < now_ts]
    today = [t for t in pending if t.get("deadline_ts") and now_ts <= t["deadline_ts"] <= end_today]
    upcoming = [t for t in pending if t.get("deadline_ts") and end_today < t["deadline_ts"] <= in_3_days]
    no_deadline = [t for t in pending if not t.get("deadline_ts")]

    workload: Dict[str, int] = defaultdict(int)
    for t in pending:
        for name in t.get("assigned_names", []) or ["?"]:
            workload[name] += 1
    workload_lines = [
        f"• {name}: **{count}** task" for name, count in sorted(workload.items(), key=lambda x: -x[1])
    ]

    phase = get_setting("current_phase")
    embed = discord.Embed(
        title=f"☀️ BÁO CÁO SÁNG — {WEEKDAY_VN[now.weekday()]} {now.strftime('%d/%m')}",
        description=(
            (f"🏷️ Giai đoạn hiện tại: **{phase}**\n" if phase else "")
            + f"Đang chạy **{len(pending)}** task — 🔴 quá hạn **{len(overdue)}** — 📌 hạn hôm nay **{len(today)}**"
        ),
        color=discord.Color.red() if overdue else discord.Color.blue(),
    )
    embed.add_field(name="🔴 Quá hạn", value=_field_text([_task_short(t) for t in overdue], "Không có 🎉"), inline=False)
    embed.add_field(name="📌 Hạn hôm nay", value=_field_text([_task_short(t) for t in today], "Không có"), inline=False)
    embed.add_field(name="🗓️ 3 ngày tới", value=_field_text([_task_short(t) for t in upcoming], "Không có"), inline=False)
    if no_deadline:
        embed.add_field(name="❔ Chưa có hạn", value=_field_text([_task_short(t, False) for t in no_deadline]), inline=False)
    if workload_lines:
        embed.add_field(name="👥 Khối lượng việc", value=_field_text(workload_lines), inline=False)
    if task_sheet_url():
        embed.add_field(name="📊 Bảng task", value=task_sheet_url(), inline=False)
    return embed


def build_weekly_report(guild_id: Optional[int]) -> discord.Embed:
    now = now_vn()
    now_ts = int(now.timestamp())
    week_ago = now_ts - 7 * 86400
    all_tasks = [
        t for t in _load_tasks().values() if guild_id is None or t.get("guild_id") in (None, guild_id)
    ]
    done = [
        t for t in all_tasks
        if t.get("status") == "completed" and int(t.get("submitted_at") or 0) >= week_ago
    ]
    on_time = [t for t in done if not t.get("deadline_ts") or int(t["submitted_at"]) <= int(t["deadline_ts"])]
    new_tasks = [t for t in all_tasks if int(t.get("created_at") or 0) >= week_ago]
    pending = [t for t in all_tasks if t.get("status") == "pending"]
    overdue = [t for t in pending if t.get("deadline_ts") and t["deadline_ts"] < now_ts]

    per_person: Dict[str, List[int]] = defaultdict(lambda: [0, 0])  # [hoàn thành, còn tồn]
    for t in done:
        for name in t.get("assigned_names", []) or ["?"]:
            per_person[name][0] += 1
    for t in pending:
        for name in t.get("assigned_names", []) or ["?"]:
            per_person[name][1] += 1
    person_lines = [
        f"• {name}: ✅ {d} xong — ⏳ {p} còn tồn"
        for name, (d, p) in sorted(per_person.items(), key=lambda x: (-x[1][0], x[0]))
    ]
    rate = f"{round(100 * len(on_time) / len(done))}%" if done else "—"

    embed = discord.Embed(
        title=f"📈 TỔNG KẾT TUẦN — {now.strftime('%d/%m/%Y')}",
        description=(
            f"Giao mới **{len(new_tasks)}** — ✅ hoàn thành **{len(done)}** (đúng hạn {rate}) — "
            f"⏳ còn tồn **{len(pending)}** — 🔴 quá hạn **{len(overdue)}**"
        ),
        color=discord.Color.green(),
    )
    embed.add_field(name="✅ Đã xong trong tuần", value=_field_text([_task_short(t, False) for t in done], "Chưa có"), inline=False)
    embed.add_field(name="🔴 Đang quá hạn", value=_field_text([_task_short(t) for t in overdue], "Không có 🎉"), inline=False)
    embed.add_field(name="👥 Theo từng người", value=_field_text(person_lines), inline=False)
    if task_sheet_url():
        embed.add_field(name="📊 Bảng task", value=task_sheet_url(), inline=False)
    return embed


async def send_report(kind: str) -> int:
    """Gửi báo cáo ('daily' | 'weekly') vào kênh task của mỗi server. Trả về số kênh đã gửi."""
    sent = 0
    for guild in bot.guilds:
        channel = find_task_channel(guild)
        if not channel:
            continue
        embed = build_daily_report(guild.id) if kind == "daily" else build_weekly_report(guild.id)
        await channel.send(embed=embed)
        sent += 1
    return sent


async def maybe_send_scheduled_reports() -> None:
    now = now_vn()
    today = now.strftime("%Y-%m-%d")
    daily = _parse_hhmm(DAILY_REPORT_TIME)
    # Thứ 2 -> Thứ 7; chỉ gửi bù trong buổi sáng (tránh bot restart buổi tối lại bắn báo cáo sáng)
    if (
        daily and now.weekday() <= 5 and get_setting("last_daily_report") != today
        and (now.hour, now.minute) >= daily and now.hour < 12
    ):
        set_setting("last_daily_report", today)
        await send_report("daily")
    weekly = _parse_hhmm(WEEKLY_REPORT_TIME)
    if (
        weekly and now.weekday() == WEEKLY_REPORT_WEEKDAY and get_setting("last_weekly_report") != today
        and (now.hour, now.minute) >= weekly and now.hour < 22
    ):
        set_setting("last_weekly_report", today)
        await send_report("weekly")


async def scheduler_loop() -> None:
    """Mỗi 30 giây: lời nhắc đến hạn, task từ Sheet, cảnh báo sắp hết hạn/quá hạn, báo cáo định kỳ."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            now_ts = int(now_vn().timestamp())

            reminders = REMINDER_TABLE.load()
            due = [r for r in reminders if int(r.get("due_ts", 0)) <= now_ts]
            if due:
                REMINDER_TABLE.save([r for r in reminders if int(r.get("due_ts", 0)) > now_ts])
            for r in due:
                guild = get_task_guild(None)
                channel = (
                    await _get_messageable(int(r["channel_id"])) if r.get("channel_id")
                    else (find_task_channel(guild) if guild else None)
                )
                if not channel:
                    continue
                who = f"<@{r['user_id']}>" if r.get("user_id") else (r.get("user_name") or "anh em")
                if not r.get("user_id") and r.get("user_name") and guild:
                    member = find_member_by_name(guild, r["user_name"])
                    who = member.mention if member else who
                await channel.send(f"🔔 **TỚI GIỜ RỒI {who} ƠI!**\n👉 Lời nhắc: **{r['text']}**")

            await announce_sheet_tasks()

            tasks = _load_tasks()
            changed = False
            for t in tasks.values():
                if t.get("status") != "pending" or not t.get("channel_id") or not t.get("deadline_ts"):
                    continue
                deadline_ts = int(t.get("deadline_ts", 0))
                mentions = " ".join(f"<@{uid}>" for uid in t.get("assigned_user_ids", []))
                channel = None
                if not t.get("warned_soon") and 0 < deadline_ts - now_ts <= 3600:
                    channel = await _get_messageable(int(t["channel_id"]))
                    if channel:
                        await channel.send(
                            f"⏳ {mentions} còn chưa tới **1 tiếng** (<t:{deadline_ts}:R>) là hết hạn task "
                            f"**{t.get('task_desc')}**. Nhớ nộp file/link sản phẩm nhé!"
                        )
                    t["warned_soon"] = True
                    changed = True
                if not t.get("warned_overdue") and deadline_ts <= now_ts:
                    channel = channel or await _get_messageable(int(t["channel_id"]))
                    if channel:
                        creator = f"<@{t['creator_id']}>" if t.get("creator_id") else "Sếp"
                        await channel.send(
                            f"⏰ **HẾT GIỜ RỒI {mentions} ƠI!**\n👉 Task **{t.get('task_desc')}** đã quá hạn "
                            f"(<t:{deadline_ts}:R>). Mau nộp file báo cáo cho {creator} nhé! 😼🔥"
                        )
                    t["warned_overdue"] = True
                    changed = True
            if changed:
                _save_tasks(tasks)

            await maybe_send_scheduled_reports()
        except Exception as exc:
            logger.warning("Lỗi vòng lặp nhắc việc: %s", exc)
        await asyncio.sleep(30)


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
        due_ts = int(now_vn().timestamp()) + minutes * 60
        remind_user_id = target_member.id if target_member else message.author.id
        add_reminder(message.channel.id, remind_user_id, task_text, due_ts)
        return f"⏰ **[Hệ thống]:** Đã hẹn <t:{due_ts}:t> (<t:{due_ts}:R>) sẽ tag <@{remind_user_id}> nhắc `{task_text}`!"

    if action_type == "remember":
        fact = str(action_data.get("fact", "")).strip()
        if not fact:
            return "⚠️ *(Sếp muốn em nhớ điều gì ạ?)*"
        mem_id = add_team_memory(fact, message.author.display_name, message.guild.id if message.guild else None)
        return f"🧠 **[Đã ghi nhớ #{mem_id}]:** {fact}"

    if action_type == "forget":
        query = str(action_data.get("query", "")).strip()
        removed = remove_team_memory(query, message.guild.id if message.guild else None)
        if not removed:
            return f"⚠️ *(Không tìm thấy ghi nhớ nào khớp `{query}`)*"
        return "🗑️ **[Đã quên]:** " + " | ".join(removed[:5])

    if action_type == "memory_list":
        memories = get_team_memories(message.guild.id if message.guild else None)
        if not memories:
            return "🧠 **[Trí nhớ team]:** Chưa ghi nhớ điều gì."
        lines = [f"`#{m.get('id')}` {m.get('text')}" for m in memories[-25:]]
        return "🧠 **[Trí nhớ team]:**\n" + "\n".join(lines)

    if action_type == "task_list":
        guild_id = message.guild.id if message.guild else None
        only_user = target_member.id if target_member else None
        phase_filter = str(action_data.get("phase", "")).strip()
        pending = get_pending_tasks(guild_id, only_user, phase_filter or None)
        sheet_note = f"\n📊 Bảng task: <{task_sheet_url()}>" if task_sheet_url() else ""
        if not pending:
            return "📋 **[Task]:** Không có task nào đang chờ nộp. 🎉" + sheet_note
        phase_label = f" — giai đoạn {phase_filter}" if phase_filter else ""
        header = f"📋 **[Task đang chạy{phase_label} — {len(pending)} task]:**"
        return header + "\n" + "\n".join(format_task_line(t) for t in pending[:20]) + sheet_note

    if action_type == "set_phase":
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới được đổi giai đoạn dự án!)*"
        phase = str(action_data.get("phase", "")).strip()
        set_setting("current_phase", phase)
        if not phase:
            return "🏷️ **[Hệ thống]:** Đã bỏ giai đoạn hiện tại."
        return f"🏷️ **[Hệ thống]:** Chuyển sang giai đoạn **{phase}** — task giao từ giờ sẽ gắn nhãn giai đoạn này."

    if action_type == "report":
        kind = "weekly" if str(action_data.get("kind", "")).lower().startswith("w") else "daily"
        guild_id = message.guild.id if message.guild else None
        embed = build_weekly_report(guild_id) if kind == "weekly" else build_daily_report(guild_id)
        await message.reply(embed=embed, mention_author=False)
        return "__ALREADY_RESPONDED__"

    if action_type in ("task_close", "task_cancel"):
        if not caller_is_boss:
            return "⚠️ *(Chỉ Sếp Phát mới được đóng/huỷ task thủ công!)*"
        query = str(action_data.get("query", "")).strip()
        task = find_pending_task(query, message.guild.id if message.guild else None)
        if not task:
            return f"⚠️ *(Không tìm thấy task đang chạy khớp `{query}`)*"
        new_status = "cancelled" if action_type == "task_cancel" else "completed"
        set_task_status(task["task_id"], new_status)
        verb = "Huỷ" if new_status == "cancelled" else "Đóng (Done)"
        return f"✅ **[Hệ thống]:** Đã {verb} task **{task.get('task_desc')}**."

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
            poll_msg = await message.reply(embed=embed, mention_author=False)
            for i in range(len(options)):
                await poll_msg.add_reaction(number_emojis[i])
            return "__ALREADY_RESPONDED__"

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
        raw_deadline = str(action_data.get("deadline", "")).strip()
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
        # Không có mention thật (gõ tay "@ten" hoặc chỉ ghi tên) -> tìm thành viên theo tên
        if not targets and message.guild:
            raw_assignee = action_data.get("assignee") or []
            names = raw_assignee if isinstance(raw_assignee, list) else re.split(r"[,;]| và ", str(raw_assignee))
            names = [str(n) for n in names] + re.findall(r"@([\w.\-]+)", message.content)
            for name in names:
                member = find_member_by_name(message.guild, name)
                if member and not member.bot and member not in targets:
                    targets.append(member)
        if not targets and target_member:
            targets.append(target_member)

        if not targets:
            return "⚠️ *(Em chưa xác định được giao cho ai — Sếp tag @người nhận (chọn từ gợi ý của Discord) hoặc ghi đúng tên hiển thị của họ nhé!)*"

        # Tự động quét và phân tích hạn chót đếm ngược (countdown timestamp Discord)
        time_scan_text = f"{raw_deadline} {task_desc} {message.clean_content}"
        deadline_ts, deadline_label = parse_task_deadline(time_scan_text)

        # Phân biệt nhắc nhở (reminder) hay giao việc mới (new task)
        is_reminder = any(w in message.clean_content.lower() for w in ("nhắc", "đòi", "tiến độ", "hỏi task"))
        phase = str(action_data.get("phase", "")).strip() or get_setting("current_phase")
        mention_str = " ".join(m.mention for m in targets)
        announcement_lead = (
            f"📣 Ê {mention_str} — Sếp Phát nhắc kiểm tra task nè, đọc kỹ rồi triển gấp nhé! 🔥"
            if is_reminder
            else f"📣 Ê {mention_str} — có task mới nè, đọc kỹ rồi triển nhanh! 🔥"
        )

        task_embed = build_task_embed(
            task_desc,
            deadline_ts,
            message.author.mention,
            mention_str,
            phase=phase,
            is_reminder=is_reminder,
            footer_name=message.author.display_name,
        )
        task_msg = await message.reply(
            content=announcement_lead,
            embed=task_embed,
            mention_author=False,
        )
        await task_msg.add_reaction("🔄")

        # Lưu thông tin task vào hệ thống theo dõi
        assigned_uids = [m.id for m in targets if hasattr(m, "id")]
        assigned_names = [
            getattr(m, "display_name", getattr(m, "name", str(m))) for m in targets
        ]
        record_new_task(
            message_id=task_msg.id,
            channel_id=message.channel.id,
            guild_id=message.guild.id if message.guild else None,
            creator_id=message.author.id,
            creator_name=message.author.display_name,
            assigned_user_ids=assigned_uids,
            assigned_names=assigned_names,
            task_desc=task_desc,
            deadline_ts=deadline_ts,
            phase=phase,
        )

        # Việc nhắc sắp hết hạn / quá hạn do scheduler_loop đảm nhiệm (không mất khi bot restart)

        return "__ALREADY_RESPONDED__"

    return None


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    """Chặn hành vi bấm lụi reaction ✅ khi chưa nộp file làm việc."""
    if bot.user and payload.user_id == bot.user.id:
        return
    if str(payload.emoji) == "✅":
        task = get_task_by_id(payload.message_id)
        if task and task.get("status") == "pending":
            channel = bot.get_channel(payload.channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(payload.message_id)
                    user = bot.get_user(payload.user_id) or await bot.fetch_user(
                        payload.user_id
                    )
                    if user and not user.bot:
                        # Gỡ bỏ reaction bấm lụi
                        await msg.remove_reaction(payload.emoji, user)
                        # Bắn cảnh báo tự hủy sau 10 giây
                        warning_msg = await channel.send(
                            f"⚠️ {user.mention} **Khoan đã!** Task này **BẮT BUỘC phải gửi FILE làm việc** "
                            f"(đính kèm file code, tài liệu, báo cáo, link doc...) vào kênh thì Boss mới duyệt **DONE** nhé! "
                            f"Đừng có bấm lụi! 😼📁"
                        )

                        async def _cleanup_warn():
                            await asyncio.sleep(10)
                            try:
                                await warning_msg.delete()
                            except Exception:
                                pass

                        asyncio.create_task(_cleanup_warn())
                except Exception as exc:
                    logger.warning("Lỗi xử lý reaction check file: %s", exc)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    # ================= KIỂM TRA NỘP FILE HOÀN THÀNH TASK =================
    has_attachments = bool(message.attachments)
    work_links = re.findall(
        r"https?://(?:github\.com|gitlab\.com|drive\.google\.com|docs\.google\.com|sheets\.google\.com|figma\.com|notion\.so|canva\.com|dropbox\.com)\S+",
        message.content,
    )
    is_work_submission = has_attachments or bool(work_links)

    # 1. Nếu có nộp file làm việc -> Kiểm tra xem thành viên này có task pending không
    if is_work_submission:
        replied_target_id = None
        if message.reference and message.reference.message_id:
            replied_target_id = message.reference.message_id

        pending_task = get_pending_task_for_user(
            channel_id=message.channel.id,
            user_id=message.author.id,
            reply_msg_id=replied_target_id,
        )
        if pending_task:
            file_parts = []
            if message.attachments:
                file_parts.extend(
                    f"[{att.filename}]({att.url})" for att in message.attachments
                )
            if work_links:
                file_parts.extend(
                    f"[Link sản phẩm/tài liệu]({link})" for link in work_links
                )
            file_info = ", ".join(file_parts)

            # Đánh dấu task hoàn thành
            mark_task_completed(
                task_id=pending_task["task_id"],
                file_info=file_info,
                user_id=message.author.id,
            )

            # Cập nhật embed task gốc sang màu xanh lá ✅
            try:
                task_channel = bot.get_channel(pending_task["channel_id"])
                if task_channel:
                    orig_msg = await task_channel.fetch_message(
                        pending_task["message_id"]
                    )
                    if orig_msg and orig_msg.embeds:
                        now_ts = int(now_vn().timestamp())
                        done_embed = discord.Embed(
                            title="✅ TASK ĐÃ HOÀN THÀNH XUẤT SẮC!",
                            description=(
                                f"📝 **Nội dung:** {pending_task['task_desc']}\n\n"
                                f"📦 **File/Sản phẩm đã nộp:** {file_info}\n\n"
                                f"⏱️ **Thời gian nộp:** <t:{now_ts}:F> (<t:{now_ts}:R>)\n\n"
                                f"👤 **Người giao:** <@{pending_task['creator_id']}>\n"
                                f"🎯 **Người hoàn thành:** {message.author.mention}"
                            ),
                            color=discord.Color.green(),
                        )
                        done_embed.set_footer(
                            text=f"Hoàn thành bởi {message.author.display_name} • Đã nộp file hợp lệ! 📁✅"
                        )
                        await orig_msg.edit(embed=done_embed)
                        try:
                            await orig_msg.clear_reactions()
                            await orig_msg.add_reaction("✅")
                        except Exception:
                            pass
            except Exception as edit_exc:
                logger.warning("Không thể sửa embed task gốc: %s", edit_exc)

            celebrate_msg = (
                f"🎉 **DONE TASK RỒI SẾP <@{pending_task['creator_id']}> ƠI!**\n"
                f"👤 {message.author.mention} vừa nộp file làm việc hợp lệ:\n"
                f"👉 **File/Link:** {file_info}\n"
                f"📝 **Task:** **{pending_task['task_desc']}**\n"
                f"✅ **Trạng thái:** Đệ Boss đã kiểm tra có file đầy đủ và đóng dấu **HOÀN THÀNH** rồi nhé! Đỉnh nóc kịch trần! 🚀📁🔥"
            )
            await message.reply(celebrate_msg, mention_author=False)
            try:
                await message.add_reaction("✅")
            except Exception:
                pass
            return

    # 2. Nếu thành viên báo cáo mồm 'xong rồi / done rồi' nhưng KHÔNG có file
    done_verbal_keywords = (
        "xong rồi",
        "done rồi",
        "hoàn thành rồi",
        "xong task",
        "done task",
        "làm xong rồi",
        "nộp task",
        "xong việc rồi",
        "đã xong",
        "em làm xong",
        "tôi làm xong",
        "xong roi",
        "done roi",
    )
    raw_lower = message.clean_content.lower()
    if any(k in raw_lower for k in done_verbal_keywords) and not is_work_submission:
        replied_target_id = None
        if message.reference and message.reference.message_id:
            replied_target_id = message.reference.message_id

        pending_task = get_pending_task_for_user(
            channel_id=message.channel.id,
            user_id=message.author.id,
            reply_msg_id=replied_target_id,
        )
        if pending_task:
            await message.reply(
                f"⚠️ **Ủa alo {message.author.mention}?** Báo cáo mồm là không tính nhé!\n"
                f"Sếp <@{pending_task['creator_id']}> quy định là **BẮT BUỘC PHẢI GỬI FILE LÀM VIỆC** "
                f"(đính kèm file code, word, excel, pdf, zip hoặc link tài liệu/sản phẩm) lên kênh này thì anh Boss mới duyệt **DONE TASK**!\n"
                f"Mau đính kèm file nộp lên đây đi cu! 😼📁",
                mention_author=False,
            )
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
            guild_id = message.guild.id if message.guild else None
            system_prompt = f"{base_system_prompt}{channel_it_mode}{build_time_context()}"
            if authorized:
                system_prompt += (
                    f"\n\n{ASSISTANT_GUIDELINES}"
                    f"{build_memory_context(guild_id)}"
                    f"{build_task_context(guild_id)}"
                    f"\n\n{NATURAL_ACTION_INSTRUCTION}"
                )

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
                response = await create_chat_completion(
                    client,
                    selected_model,
                    messages_payload,
                    temperature=0.6,
                    max_tokens=6144,
                    allow_fallback=not image_data_urls,
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
                    response = await create_chat_completion(
                        client,
                        text_model,
                        messages_payload,
                        temperature=0.6,
                        max_tokens=6144,
                    )
                else:
                    raise

            raw_ai_reply = (
                response.choices[0].message.content
                or ""
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

            if action_status_note == "__ALREADY_RESPONDED__":
                # Action đã trực tiếp phản hồi Discord bằng Embed chuẩn đẹp hoặc poll,
                # KHÔNG gửi thêm tin nhắn văn bản thừa để tránh spam và tránh AI bịa nhầm tên!
                history_user_entry = full_user_prompt
                if image_data_urls:
                    history_user_entry += f" [Đính kèm {len(image_data_urls)} ảnh]"

                conversation_history[channel_id].append(
                    {"role": "user", "content": history_user_entry}
                )
                action_name = action_json.get("type", "action") if action_json else "action"
                conversation_history[channel_id].append(
                    {"role": "assistant", "content": f"[Đã xử lý xong hành động: {action_name}]"}
                )
                return

            if action_status_note and action_status_note.startswith("⚠️"):
                # Hành động thất bại -> chỉ báo lỗi, bỏ lời AI (thường là "đã làm xong") để không báo sai
                ai_reply = action_status_note
            elif action_status_note:
                ai_reply = f"{ai_reply}\n\n{action_status_note}".strip()

            # Chốt hạ: Luôn lọc sạch mọi vết tích ACTION một lần nữa trước khi gửi
            ai_reply = _strip_action_tags(ai_reply)

            # Nếu ai_reply trống (do chỉ có thẻ action) nhưng có action_status_note không phải lỗi:
            if not ai_reply and action_status_note:
                ai_reply = action_status_note
            elif not ai_reply:
                # Nếu không có nội dung gì để rep, chỉ cần thả reaction xác nhận
                try:
                    await message.add_reaction("🫡")
                except Exception:
                    pass
                return

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
                if not chunk.strip():
                    continue
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
        "Báo cáo theo cấu trúc:\n"
        "**📌 Chủ đề chính** (mỗi chủ đề 1 dòng)\n"
        "**✅ Đã chốt** (quyết định/thống nhất)\n"
        "**📝 Việc cần làm** (ai — việc gì — hạn, nếu có)\n"
        "**❓ Còn bỏ ngỏ** (câu hỏi chưa ai trả lời, vấn đề chưa xử lý)\n"
        "Mục nào không có thì bỏ qua. Cuối cùng thêm 1 câu bình luận ngắn chất Boss nếu có drama vui."
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

    due_ts = int(now_vn().timestamp()) + so_phut * 60
    add_reminder(interaction.channel_id or 0, interaction.user.id, noi_dung, due_ts)
    await interaction.response.send_message(
        f"⏰ **Đã rõ!** <t:{due_ts}:t> (<t:{due_ts}:R>) em sẽ réo tên {interaction.user.mention} nhắc vụ: **{noi_dung}**! 🫡"
    )


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
    name="kenh", description="🗂️ [Chỉ Sếp Phát] Gán vai trò của Boss cho kênh hiện tại"
)
@app_commands.describe(che_do="Vai trò của Boss trong kênh này (bỏ trống để xem / chọn 'Tự động' để theo tên kênh)")
@app_commands.choices(
    che_do=[app_commands.Choice(name="🔄 Tự động theo tên kênh", value="auto")]
    + [app_commands.Choice(name=m["label"], value=key) for key, m in CHANNEL_MODES.items()]
)
async def kenh_command(
    interaction: discord.Interaction, che_do: Optional[app_commands.Choice[str]] = None
) -> None:
    channel = interaction.channel
    channel_id = interaction.channel_id or 0
    if che_do is not None:
        if not is_user_boss(interaction.user, interaction.guild):
            await reject_unauthorized(interaction)
            return
        if che_do.value == "auto":
            config.channel_modes.pop(channel_id, None)
        else:
            config.channel_modes[channel_id] = che_do.value
        config.save_state()
    mode = resolve_channel_mode(channel) if channel else None
    label = CHANNEL_MODES[mode]["label"] if mode in CHANNEL_MODES else "🌐 Đa năng (mặc định)"
    source = "gán thủ công" if channel_id in config.channel_modes else "tự động theo tên kênh"
    await interaction.response.send_message(f"🗂️ Vai trò của Boss ở kênh này: **{label}** *({source})*")


@bot.tree.command(
    name="tasks", description="📋 Xem các task đang chạy (của cả team hoặc của một người)"
)
@app_commands.describe(
    thanh_vien="(Tuỳ chọn) Chỉ xem task của người này",
    giai_doan="(Tuỳ chọn) Chỉ xem task của giai đoạn này",
)
async def tasks_command(
    interaction: discord.Interaction,
    thanh_vien: Optional[discord.Member] = None,
    giai_doan: Optional[str] = None,
) -> None:
    guild_id = interaction.guild.id if interaction.guild else None
    pending = get_pending_tasks(guild_id, thanh_vien.id if thanh_vien else None, giai_doan)
    if not pending:
        sheet_note = f"\n📊 Bảng task: <{task_sheet_url()}>" if task_sheet_url() else ""
        await interaction.response.send_message(f"📋 Không có task nào đang chờ nộp. 🎉{sheet_note}")
        return
    owner = f" của {thanh_vien.display_name}" if thanh_vien else ""
    if giai_doan:
        owner += f" — giai đoạn {giai_doan}"
    text = f"📋 **Task đang chạy{owner} — {len(pending)} task:**\n" + "\n".join(
        format_task_line(t) for t in pending[:25]
    )
    if task_sheet_url():
        text += f"\n📊 Bảng task đầy đủ: <{task_sheet_url()}>"
    chunks = split_long_message(text)
    await interaction.response.send_message(chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


@bot.tree.command(
    name="giaidoan", description="🏷️ Xem / đổi giai đoạn dự án hiện tại (task mới sẽ gắn nhãn giai đoạn này)"
)
@app_commands.describe(ten="(Chỉ Sếp Phát) Tên giai đoạn mới, ví dụ: GĐ1 - Ra mắt sản phẩm. Gõ 'xoa' để bỏ")
async def giaidoan_command(interaction: discord.Interaction, ten: Optional[str] = None) -> None:
    if ten is not None and ten.strip():
        if not is_user_boss(interaction.user, interaction.guild):
            await reject_unauthorized(interaction)
            return
        new_phase = "" if _norm_name(ten) in ("xoa", "bo", "none") else ten.strip()
        set_setting("current_phase", new_phase)
    phase = get_setting("current_phase")
    if not phase:
        await interaction.response.send_message("🏷️ Chưa đặt giai đoạn. Sếp dùng `/giaidoan ten:...` để đặt.")
        return
    count = len(get_pending_tasks(interaction.guild.id if interaction.guild else None, phase=phase))
    await interaction.response.send_message(
        f"🏷️ Giai đoạn hiện tại: **{phase}** — đang chạy **{count}** task của giai đoạn này."
    )


@bot.tree.command(name="baocao", description="📈 Báo cáo tình hình task ngay bây giờ")
@app_commands.choices(
    loai=[
        app_commands.Choice(name="☀️ Báo cáo ngày (quá hạn, hạn hôm nay, khối lượng việc)", value="daily"),
        app_commands.Choice(name="📈 Tổng kết tuần (đã xong, tỉ lệ đúng hạn, theo từng người)", value="weekly"),
    ]
)
async def baocao_command(
    interaction: discord.Interaction, loai: Optional[app_commands.Choice[str]] = None
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return
    guild_id = interaction.guild.id if interaction.guild else None
    kind = loai.value if loai else "daily"
    embed = build_weekly_report(guild_id) if kind == "weekly" else build_daily_report(guild_id)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="memory", description="🧠 Xem / thêm / xoá trí nhớ dài hạn của Boss về team"
)
@app_commands.describe(
    ghi_nho="(Tuỳ chọn) Điều muốn Boss ghi nhớ lâu dài",
    xoa="(Tuỳ chọn) Mã # hoặc từ khoá của ghi nhớ cần xoá",
)
async def memory_command(
    interaction: discord.Interaction,
    ghi_nho: Optional[str] = None,
    xoa: Optional[str] = None,
) -> None:
    if not is_user_authorized(interaction.user, interaction.guild):
        await reject_unauthorized(interaction)
        return
    guild_id = interaction.guild.id if interaction.guild else None
    if ghi_nho and ghi_nho.strip():
        mem_id = add_team_memory(ghi_nho, interaction.user.display_name, guild_id)
        await interaction.response.send_message(f"🧠 Đã ghi nhớ `#{mem_id}`: {ghi_nho.strip()}")
        return
    if xoa and xoa.strip():
        removed = remove_team_memory(xoa, guild_id)
        msg = ("🗑️ Đã quên: " + " | ".join(removed[:5])) if removed else f"⚠️ Không tìm thấy ghi nhớ khớp `{xoa}`"
        await interaction.response.send_message(msg)
        return
    memories = get_team_memories(guild_id)
    if not memories:
        await interaction.response.send_message("🧠 Chưa ghi nhớ điều gì. Dùng `/memory ghi_nho:...` hoặc nói *\"Boss nhớ giùm tao...\"*")
        return
    text = "🧠 **Trí nhớ dài hạn của team:**\n" + "\n".join(
        f"`#{m.get('id')}` {m.get('text')} *(— {m.get('by')})*" for m in memories[-40:]
    )
    chunks = split_long_message(text)
    await interaction.response.send_message(chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


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
            "• **Quyền lực Sếp Phát:** `/vip`, `/timeout`, `/clear_msg`, `/nickname`, `/persona`, `/provider`, `/kenh`\n"
            "• **Bắt Trend & Trợ lý (Sếp & VIP):** `/trend`, `/search`, `/tomtat`, `/remind`, `/poll`, `/tasks`, `/memory`, `/baocao`, `/giaidoan`\n"
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
