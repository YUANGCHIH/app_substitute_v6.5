@echo off
chcp 65001
cd /d "%~dp0"

echo ==========================================
echo 正在啟動 成德高中智慧排代系統...
echo 請勿關閉此視窗，網頁將自動開啟。
echo ==========================================

:: 執行 Streamlit
streamlit run app_substitute_v6.5.py

:: 如果發生錯誤，暫停讓使用者看得到
if %errorlevel% neq 0 (
    echo.
    echo 發生錯誤！請確認：
    echo 1. app_substitute_v3.py 是否在同一個資料夾？
    echo 2. 是否已安裝 streamlit？
    pause
)