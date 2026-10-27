# Báo cáo build & test — AI Debate

Ngày: 2026-10-27 · Môi trường agent: container Linux trên cloud (không phải Windows; lệnh PowerShell trong README chưa được chạy thử trên Windows).

## 1. Tên model (xác minh từ tài liệu chính thức, không đoán)

| Bên | Model | Nguồn |
|---|---|---|
| Claude | `claude-opus-5-5` (mặc định), `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1` | Tài liệu Anthropic / skill claude-api (cập nhật 2026-10-06) |
| Gemini | `gemini-3.8-flash` (mặc định), `gemini-4-argon`, `gemini-3.6-flash`, `gemini-3.5-flash-lite` | https://ai.google.dev/gemini-api/docs/models (đọc 2026-10-27) |

## 2. Test giả lập người dùng (Playwright, chế độ mock)

Kịch bản: (1) mở trang, (2) bấm Chạy khi task trống, (3) thiếu cả 2 API key, (4) bật mock + đổi số vòng = 2 + chạy hết, (5) tải file .md, (6) bấm Dừng giữa chừng (5 vòng), (7) chạy lại sau khi dừng, (8) kiểm tra log JSON + MD, (9, thêm ở vòng 2) key sai → API trả 401.

| Vòng | Kết quả | Lỗi tìm thấy → xử lý |
|---|---|---|
| 1 | 9/9 PASS (sau khi sửa 2 lỗi trong script test) | Lỗi của app, tìm qua ảnh chụp: heading trong câu trả lời model quá to; thông báo trạng thái (Hoàn tất/Đã dừng/lỗi) nằm cuối trang, xa nút bấm → **đã sửa** (CSS thu nhỏ heading, đưa thông báo lên ngay dưới nút). Lỗi của script test: slider bị ẩn nên `click()` treo, `isVisible` không chờ → sửa script. |
| 2 | **10/10 PASS** | Không còn lỗi chặn. Không làm vòng 3. |

Ảnh chụp màn hình: `screenshots/r1/`, `screenshots/r2/` (thư mục bị gitignore, chỉ có trên máy agent).

pytest `tests/test_debate.py`: **25/25 PASS** (lịch lượt, đổi vai, giới hạn cứng số vòng/max_tokens, prompt chống "đồng ý cho xong", tự yêu cầu làm lại khi phản biện < 2 điểm yếu, dừng giữa chừng, lỗi API, tổng token, lưu log). `ruff check` sạch.

## 3. Phần CHƯA test với API thật (chưa có key)

- Nội dung trả lời thật, streaming thật, số token thật của cả Claude và Gemini.
- Tham số `fallbacks="default"` + beta `server-side-fallback-2026-07-01` và `output_config.effort="low"` của Claude: request mới được kiểm tra đến bước xác thực (key giả → 401), chưa được kiểm tra hợp lệ toàn bộ.
- Gemini: `finish_reason == MAX_TOKENS` (cảnh báo bị cắt) và cách đếm `thoughts_token_count`.
- Quyền truy cập model theo tài khoản của bạn (ví dụ `gemini-4-argon`, `claude-fable-5-1` có thể cần quyền riêng).
- Đã test thật với key **sai**: cả hai SDK trả lỗi xác thực và app báo lỗi rõ ràng.

## 4. Lỗi / hạn chế còn lại

- Bấm **Dừng** khi đang gọi API thật: token của lượt đang chạy dở vẫn bị tính tiền, nhưng app không hiển thị được vì số token chỉ có khi stream kết thúc.
- Lượt bị lỗi hiển thị "(trống) · Lượt này chưa xong" — chỉ là chi tiết hiển thị, không ảnh hưởng luồng.
- Mỗi lượt gửi lại toàn bộ hội thoại (không dùng prompt caching) — ở mức ≤ 5 vòng thì chấp nhận được.

## 5. Công cụ

| Công cụ | Trạng thái | Kiểm tra an toàn |
|---|---|---|
| anthropic 2.3.0, google-genai 2.33.0, streamlit 1.66.1, python-dotenv 1.2.4 | Đã cài (venv) | SDK chính thức; `pip-audit`: không có lỗ hổng đã biết |
| pytest 9.1.1, ruff 0.17.3 | Đã cài | `pip-audit` sạch |
| pip-audit | Đã cài trong venv để quét (không có trong requirements) | PyPA chính thức |
| Playwright (thư viện, có sẵn trong container) | Dùng để test UI | — |
| Playwright MCP `@playwright/mcp@0.0.83` | Ghim phiên bản trong `.mcp.json` để bạn dùng với Claude Code | Repo chính thức microsoft/playwright-mcp, cập nhật 2026-09-28. CVE-2025-9611 (DNS rebinding, High) chỉ ảnh hưởng < 0.0.40 → bản 0.0.83 đã vá. MCP mới chỉ nạp ở phiên sau nên phiên này test bằng thư viện Playwright trực tiếp (cùng engine). |
| Context7 MCP | **BỎ QUA** | GHSA-97r6-3rgm-v39r / CVE-2026-75130: prompt injection qua "Custom AI Instructions" có thể khiến agent **đọc trộm file .env** và xoá file; chưa có bản vá được ghi nhận. Dự án này chứa API key trong `.env` nên rủi ro không chấp nhận được. Thay bằng đọc trực tiếp tài liệu chính thức. |
| Skill frontend-design | Không có | Không có trong danh sách skill của môi trường này |

Kiểm tra credential hardcode: không tìm thấy chuỗi key nào trong repo; `.env` không có trong `git ls-files`.
