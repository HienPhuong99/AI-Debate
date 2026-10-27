# Báo cáo phát triển tính năng — đợt 2

Ngày: 2026-10-27 · Nhánh: `claude/ai-debate-app` (PR #1)

## 1. Tính năng đề xuất

| # | Tính năng | Lý do | Trạng thái |
|---|---|---|---|
| A | **Ước tính chi phí USD** theo từng bên và cả phiên | Có token nhưng chưa biết tốn bao nhiêu tiền | ✅ Đã làm |
| B | **Ngân sách token cả phiên** (5k–200k, mặc định 60k): vượt thì bỏ các vòng còn lại, chuyển thẳng sang tổng hợp | Giới hạn cứng theo tổng chi phí, không chỉ theo từng lượt | ✅ Đã làm |
| C | **Ước tính token cho lượt bị Dừng** | Sửa hạn chế cũ: lượt bị dừng vẫn tốn tiền nhưng hiện 0 token | ✅ Đã làm |
| D | **Tab Lịch sử**: xem lại các phiên trong `logs/`, tải .md/.json | Log đã lưu nhưng trước đây phải mở file thủ công | ✅ Đã làm |
| E | **Task mẫu** + **tải log .json** của phiên hiện tại | Thử nhanh, xuất dữ liệu | ✅ Đã làm |
| F | Tên file log ASCII không dấu, không ghi đè khi trùng giây | Lỗi tìm ra khi test D (xem mục 3) | ✅ Đã làm |
| G | Prompt caching cho Claude | Lợi ích nhỏ ở ≤ 5 vòng (prompt ngắn, dưới ngưỡng cache tối thiểu) | ⏸ Chưa làm — không đáng thêm code |
| H | Dừng sớm khi hai bên "đồng thuận" | Mâu thuẫn với yêu cầu chống "đồng ý cho xong" | ✗ Không làm |
| I | Sửa/tiếp tục một phiên cũ (resume) | Cần thiết kế lại engine; để bạn quyết định có cần không | ⏸ Đề xuất cho đợt sau |
| J | Chọn ngôn ngữ trả lời / tuỳ biến prompt hệ thống | Hữu ích nhưng tăng rủi ro làm hỏng quy tắc phản biện | ⏸ Đề xuất cho đợt sau |

## 2. Chi tiết đã làm

- **Giá** (`core/pricing.py`) lấy từ bảng giá chính thức ngày 2026-10-27 (tier trả phí chuẩn, text). Giá có ngày hiệu lực: Gemini 4 Argon tăng từ 2026-12-01, Gemini 3.8/3.6 Flash tăng từ 2027-01-01. Chi phí tính theo ngày bắt đầu phiên. Model không có trong bảng thì hiện "chưa rõ giá", không đoán. Chế độ demo hiển thị chi phí *giả định* theo model đã chọn.
- **Ngân sách token** kiểm tra sau mỗi lượt đề xuất/phản biện. Lượt tổng hợp vẫn chạy để luôn có kết quả cuối, nên chi phí thực tế có thể vượt ngân sách tối đa 1 lượt (≤ max_tokens).
- **Dừng**: `Debate.stop()` chốt trạng thái và ước tính token của lượt dở (~4 ký tự/token) **ngay trong callback của nút Dừng**. Lượt đó được đánh dấu "≈ ước tính" trong UI và log (`usage_estimated: true`).
- Metric mới: cột "Chi phí ước tính", thanh tiến độ so với ngân sách token. Log JSON có thêm `cost_usd`, `budget_hit`, `config.token_budget`.

## 3. Lỗi phát hiện & đã sửa trong đợt này

1. **Lượt bị Dừng không được ước tính token** (chỉ lộ ra khi test UI thật, unit test vẫn qua). Nguyên nhân: Streamlit (`fastReruns`) bắt đầu lượt chạy mới — chạy callback, lưu log, vẽ UI — *trước khi* thread cũ kịp dừng; ngoài ra `StopException` được ném ngay bên trong stream. Sửa: chốt trạng thái trong callback qua `Debate.stop()`, và engine bắt mọi kiểu ngắt (`BaseException`) rồi ném lại. Có 4 unit test bao các tình huống.
2. **Tải file từ tab Lịch sử bị đổi tên thành `download`** vì tên log có dấu tiếng Việt. Sửa: tên file ASCII (`dat-ten-tiem-banh`), thêm hậu tố `-2`, `-3` khi trùng giây.
3. Heading trong phần xem lịch sử quá to → áp CSS thu nhỏ như phần hội thoại.

## 4. Kết quả test

- **pytest: 46/46 PASS** (25 cũ + 21 mới trong `tests/test_features.py`); `ruff check` sạch.
- **Playwright (mock)**: chạy lại toàn bộ 9 kịch bản cũ và thêm 4 kịch bản mới (task mẫu; chi phí + tải JSON; ghi chú ước tính khi dừng; tab Lịch sử). Kết quả cuối **14/14 PASS**. Các vòng chạy giữa chừng làm lộ lỗi 1–3 ở trên.
- Ngân sách token chỉ có unit test: ở chế độ demo mỗi lượt quá ít token để chạm mức tối thiểu 5.000.

## 5. Chưa kiểm chứng với API thật

- Giá đúng cho tài khoản của bạn: tier miễn phí, giảm giá hay batch không được tính.
- Mức sai lệch của ước tính ~4 ký tự/token với tiếng Việt: thường **thấp hơn** thực tế, vì tiếng Việt tốn nhiều token hơn.
- Các mục trong `BAO_CAO.md` §3 vẫn còn nguyên.
