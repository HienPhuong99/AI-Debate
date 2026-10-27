# Việc cần bạn làm

1. Lấy code về máy Windows: `git clone https://github.com/HienPhuong99/AI-Debate.git; cd AI-Debate; git checkout claude/ai-debate-app` (hoặc merge PR trên GitHub rồi dùng nhánh `main`).
2. Cài môi trường: `py -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt`
3. Điền API key thật (agent không có key): `Copy-Item .env.example .env; notepad .env` → điền `ANTHROPIC_API_KEY` và `GEMINI_API_KEY`.
4. Chạy thử với API thật (agent chưa test được phần này): `streamlit run app.py` → tắt chế độ demo, chạy 1 vòng với task ngắn.
5. Review và merge PR trên GitHub (quyết định của bạn): https://github.com/HienPhuong99/AI-Debate/pulls
