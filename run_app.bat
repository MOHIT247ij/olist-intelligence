@echo off
cd /d "%~dp0"
echo ===== Dashboard khul raha hai (browser mein). Band karne ke liye ye window close karo =====
python -m streamlit run app\streamlit_app.py
pause
