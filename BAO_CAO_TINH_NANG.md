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

---

# Đợt 3 — tham khảo repo tương tự (2026-10-27)

## 1. Nguồn tham khảo

| Dự án | Ý tưởng lấy được |
|---|---|
| [Turncoat](https://discuss.streamlit.io/t/ai-models-debate-turncoat-style/120750) (Streamlit, 2 model tranh luận) | Kiểu UI chọn chủ đề/model ở sidebar — app đã có; không lấy phần đổi phe/giọng đọc |
| [MALLM](https://github.com/Multi-Agent-LLMs/mallm) (framework multi-agent) | Giám khảo chấm điểm (`judge`), **persona** cho agent, giới hạn vòng |
| [Du et al. — llm_multiagent_debate](https://github.com/composable-models/llm_multiagent_debate) | Sửa câu trả lời qua từng vòng sau khi xem phản hồi — đúng mô hình app đang dùng |
| Paper *Sequential Consensus for Multi-Agent LLM Debates* ([arXiv 2605.19193](https://arxiv.org/pdf/2605.19193)) | Chấm điểm sau mỗi vòng và **dừng sớm** khi đạt ngưỡng để tiết kiệm chi phí |
| [verd](https://pypi.org/project/verd/), [GPT Engage](https://awesome.ecosyste.ms/projects/github.com%2Frahulrajaram%2Fgptengage) (CLI nhiều provider) | Gợi ý cho đợt sau: thêm provider thứ 3 (xem mục 4) |

Mình chỉ đọc README và mô tả, không sao chép code của dự án nào.

## 2. Đã làm

| Tính năng | Chi tiết |
|---|---|
| **Chấm điểm mỗi vòng** | Bên phản biện bắt buộc kết thúc bằng `Điểm: X/10`. Điểm hiện ở tiêu đề lượt, trên biểu đồ đường (có tooltip, có dòng chữ liệt kê điểm thay bảng) và trong log (`scores`). Không cần gọi thêm API. Điểm cao **không** miễn quy tắc nêu ≥ 2 điểm yếu. |
| **Dừng sớm theo điểm** | Tuỳ chọn ngưỡng 7–10 (mặc định Tắt). Khi đạt ngưỡng, app bỏ các vòng còn lại và chuyển sang tổng hợp. Chế độ demo cho điểm tăng 5 → 7 → 9 để thử được tính năng này. |
| **Ngôn ngữ trả lời** | Theo ngôn ngữ của task / Tiếng Việt / English, áp dụng cho cả 3 vai. |
| **Vai chuyên môn (persona)** | Mỗi bên tối đa 200 ký tự, chỉ gắn vào prompt của đúng vai đó. Các quy tắc gốc giữ nguyên, persona được nối thêm phía sau. |
| **Tiếp tục phiên** | Áp dụng cho phiên đã dừng hoặc bị lỗi và chưa có kết quả cuối. Các lượt đã xong được giữ lại; lượt dở được đánh dấu "bỏ dở" (token của nó vẫn được tính) rồi chạy lại. Log của chính phiên đó được ghi đè, không tạo file mới. Trước khi tiếp tục, app đọc lại `.env`, nên sửa key xong là tiếp tục được ngay. Có thể tiếp tục từ màn hình hiện tại hoặc từ tab Lịch sử. Log cũ, thiếu các trường mới, vẫn đọc được. |

## 3. Kết quả test

- **pytest: 67/67 PASS** (21 test mới trong `tests/test_round3.py`); `ruff check` sạch.
- **Playwright (mock)**:
  - Vòng 1: 17/18. Kịch bản hỏng là do selector của script test trùng với tooltip trợ giúp, không phải lỗi của app.
  - Vòng 2: **18/18 PASS**. Gồm 12 kịch bản cũ và 4 kịch bản mới: dừng sớm + biểu đồ, Dừng → Tiếp tục, tiếp tục từ Lịch sử, ngôn ngữ + persona lưu vào log.
- **Chưa kiểm chứng với API thật**:
  - Model thật có luôn ghi đúng dòng `Điểm: X/10` không. Nếu thiếu, lượt đó không có điểm và không kích hoạt dừng sớm.
  - Persona và ngôn ngữ có thực sự đổi văn phong không. Chế độ demo bỏ qua hai tuỳ chọn này.

## 4. Đề xuất cho đợt sau (chưa làm)

- Provider thứ 3 (OpenAI hoặc OpenRouter) — cần thêm SDK và key, nên để bạn quyết định.
- Bước "đề xuất độc lập": cả hai bên cùng trả lời vòng 1 rồi mới phản biện chéo (theo Du et al.). Cách này tốn gấp đôi token ở vòng 1.
- Giám khảo độc lập là một model thứ ba thay vì để bên phản biện tự chấm. Hiện bên phản biện vừa bắt lỗi vừa chấm, nên điểm có thể bị thiên lệch.

---

# Đợt 4 — giao diện theo skill `apple-design`

**Cài skill:** [emilkowalski/skills › apple-design](https://github.com/emilkowalski/skills/tree/main/skills/apple-design), commit `2d22863`, license MIT.
- **Kiểm tra trước khi cài:** chỉ có 1 file `SKILL.md`, là hướng dẫn thiết kế bằng văn bản. Không có script, không có lệnh chạy, không đọc file hay gọi mạng, không chứa credential.
- **Vị trí cài:** `.claude/skills/apple-design/`, kèm `SOURCE.md` (nguồn + commit) và `LICENSE`. Claude Code sẽ tự nạp skill này ở phiên sau khi mở dự án.

**Áp dụng vào app:**

| Nguyên tắc trong skill | Thay đổi |
|---|---|
| Typography: font hệ thống, tracking theo cỡ chữ | Dùng font hệ thống (SF Pro / Segoe UI). Tiêu đề lớn có tracking âm (−0.025em) và leading chặt; nhãn nhóm viết hoa nhỏ, tracking dương |
| Light/dark chỉnh riêng (Craft) | Theme `[theme.light]` và `[theme.dark]` riêng, màu nhấn đất nung. Màu biểu đồ đổi theo chế độ, cả hai qua validator dataviz |
| Vật liệu trong suốt | Header mờ kính (`backdrop-filter`), nội dung cuộn bên dưới |
| Bề mặt lớn trông dày hơn | Lượt hội thoại là thẻ bóng nhẹ; kết quả cuối là thẻ bóng sâu nhất, không lồng thẻ trong thẻ |
| Phản hồi tức thì khi nhấn | Nút co lại `scale(0.97)` trong 100ms ngay lúc nhấn |
| Simplicity, không phải minimalism | Sidebar chia 3 nhóm (Mô hình & vai trò · Độ dài & chi phí · Nâng cao); tuỳ chọn ít dùng gom vào "Nâng cao". Trang trống chỉ còn hướng dẫn 3 bước, ẩn ô token và khung kết quả rỗng; ẩn nút Deploy |
| Nhãn cụ thể, không lặp lại | Badge vai trò (Đề xuất / Phản biện / Tổng hợp) + "Vòng N · **Bên** (model) · điểm". Bỏ việc lặp tên vai |
| Accessibility | Có fallback cho `prefers-reduced-motion` (bỏ hiệu ứng co nút), `prefers-reduced-transparency` (header đặc), `prefers-contrast: more` (viền rõ, bỏ bóng) |

**Không áp dụng:** spring, kéo-thả, momentum, haptics. App không có tương tác cử chỉ, Streamlit cũng không hỗ trợ; thêm vào chỉ là trang trí, trái với nguyên tắc "Purpose" của chính skill.

**Test:** pytest 67/67; Playwright 18/18 (chạy lại toàn bộ); đã chụp và soát giao diện ở cả chế độ sáng lẫn tối.
