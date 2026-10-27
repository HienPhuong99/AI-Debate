"""Offline stand-in for a real model, used for demo mode and tests (no API calls, no cost)."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

from core.base import Usage


def _canned_reply(system: str, prompt: str) -> str:
    if "PHẢN BIỆN" in system:
        # Score rises each round (5, 7, 9...) so demo mode can show early stopping.
        return (
            "## Điểm yếu\n"
            "1. Đề xuất chưa nêu rõ tiêu chí đo lường thành công.\n"
            "2. Chưa xét rủi ro khi giả định ban đầu sai.\n"
            "3. Thiếu ước lượng chi phí và thời gian.\n\n"
            "## Gợi ý sửa\n- Thêm chỉ số cụ thể và phương án dự phòng.\n\n"
            f"Điểm: {min(10, 5 + 2 * prompt.count('— Phản biện ('))}/10"
        )
    if "TỔNG HỢP" in system:
        return (
            "# Kết quả cuối\n\n"
            "Phương án đã được điều chỉnh sau các vòng phản biện: có tiêu chí đo lường, "
            "phương án dự phòng và ước lượng chi phí.\n\n"
            "## Rủi ro còn lại\n- Cần dữ liệu thật để xác nhận giả định."
        )
    return (
        "## Đề xuất\n"
        "Chia task thành 3 bước: phân tích yêu cầu, làm bản thử, đánh giá và cải tiến.\n\n"
        "## Đã sửa theo phản biện\n- Bổ sung tiêu chí đo lường và phương án dự phòng."
    )


class MockClient:
    def __init__(self, provider: str, model: str = "mock", delay: float | None = None):
        self.provider = provider
        self.model = model
        self.last_usage = Usage()
        self.last_truncated = False
        self.delay = float(os.getenv("MOCK_DELAY", "0.03")) if delay is None else delay

    def stream(self, system: str, prompt: str, max_tokens: int) -> Iterator[str]:
        self.last_usage = Usage()
        self.last_truncated = False
        text = _canned_reply(system, prompt)
        for word in text.split(" "):
            if self.delay:
                time.sleep(self.delay)
            yield word + " "
        self.last_usage = Usage(input_tokens=len(prompt) // 4, output_tokens=len(text) // 4)
