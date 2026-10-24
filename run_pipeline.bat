@echo off
cd /d "%~dp0"
echo ===== Olist pipeline chal raha hai... window band mat karna =====
if not exist "data\raw\olist_orders_dataset.csv" python scripts\generate_sample_data.py
python pipeline.py
echo.
echo ===== DONE. Ab run_app.bat par double-click karo =====
pause
