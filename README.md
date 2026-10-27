# AI Debate

App Streamlit cho **Claude** và **Gemini** thảo luận một task: một bên đề xuất, bên kia chỉ phản biện (bắt buộc nêu ≥ 2 điểm yếu cụ thể mỗi vòng), sau đó một bên tổng hợp kết quả cuối.

## Cài đặt (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # rồi mở .env, điền ANTHROPIC_API_KEY và GEMINI_API_KEY
```

## Chạy

```powershell
streamlit run app.py
```

Mở http://localhost:8501. Chưa có key thì bật **Chế độ demo (mock)** ở sidebar để thử luồng mà không tốn tiền.

## Tính năng

- Chọn model Claude/Gemini, bên đề xuất, bên tổng hợp, số vòng (1–5), max_tokens mỗi lượt (≤ 4096).
- Hội thoại hiển thị realtime, nút **Dừng** giữa chừng, đếm token theo từng bên.
- Kết quả cuối hiển thị riêng, tải về `.md`. Mỗi phiên được lưu vào `logs/` (JSON + MD).
- Phản biện nêu chưa đủ 2 điểm yếu thì app tự yêu cầu làm lại một lần.
- Ước tính chi phí USD theo bảng giá chính thức; ngân sách token cả phiên (vượt thì chuyển thẳng sang tổng hợp).
- Tab **Lịch sử** xem lại và tải các phiên đã lưu; có task mẫu để thử nhanh.
- Bên phản biện chấm điểm đề xuất mỗi vòng (biểu đồ); tuỳ chọn dừng sớm khi điểm đạt ngưỡng.
- Chọn ngôn ngữ trả lời và vai chuyên môn (persona) cho từng bên.
- **Tiếp tục phiên** đã dừng hoặc bị lỗi (ngay trên màn hình hoặc từ tab Lịch sử) mà không chạy lại các lượt đã xong.

## Cấu trúc

```
app.py                 # giao diện Streamlit
core/claude_client.py  # SDK anthropic (streaming)
core/gemini_client.py  # SDK google-genai (streaming)
core/debate.py         # engine tranh luận, prompt, giới hạn, lưu log
core/mock_client.py    # client giả cho chế độ demo / test
core/pricing.py        # bảng giá model, ước tính chi phí
tests/                 # pytest
```

## Kiểm tra

```powershell
pytest
ruff check .
```
