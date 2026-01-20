import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime

# 設定頁面配置 (手機版建議用 centered 或不特別設，這裡維持預設以適應各種螢幕)
st.set_page_config(page_title="成德高中調代課系統", page_icon="🏫", layout="wide")

# --- CSS 優化：讓手機版顯示更順眼 ---
st.markdown("""
    <style>
    /* 手機上調整標題大小 */
    @media (max-width: 600px) {
        h1 { font-size: 1.5rem !important; }
        h2 { font-size: 1.2rem !important; }
    }
    /* 隱藏 Streamlit 預設選單以保持介面乾淨 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- 核心功能：解析 PDF ---
@st.cache_data
def parse_pdf_schedule(uploaded_file):
    """
    解析邏輯同前，針對手機效能做快取優化
    """
    schedule_db = {}
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text: continue
                
                # 抓取教師名稱
                teacher_match = re.search(r"教師[:：]\s*(\S+)", text)
                if teacher_match:
                    teacher_name = teacher_match.group(1)
                else:
                    continue

                # 抓取表格
                tables = page.extract_tables()
                if not tables: continue

                if teacher_name not in schedule_db:
                    schedule_db[teacher_name] = {}

                main_table = tables[0]
                days_mapping = ["一", "二", "三", "四", "五"]
                
                # 尋找星期列
                header_row_idx = 0
                for idx, row in enumerate(main_table):
                    row_text = "".join([str(cell) if cell else "" for cell in row])
                    if "一" in row_text and "五" in row_text:
                        header_row_idx = idx
                        break
                
                # 解析課程
                current_period = 0
                for row_idx in range(header_row_idx + 1, len(main_table)):
                    row = main_table[row_idx]
                    row_str = "".join([str(c) for c in row if c])
                    if len(row_str) < 2: continue

                    if len(row) >= 6:
                        period_label = str(row[0]).replace("\n", " ") if row[0] else f"第{current_period}節"
                        if "午" in period_label and "休" in period_label: continue
                        
                        for day_idx, day_name in enumerate(days_mapping):
                            col_idx = day_idx + 1
                            if col_idx < len(row):
                                course_content = row[col_idx]
                                if course_content:
                                    course_content = str(course_content).replace("\n", " ")
                                else:
                                    course_content = ""
                                
                                if day_name not in schedule_db[teacher_name]:
                                    schedule_db[teacher_name][day_name] = {}
                                
                                schedule_db[teacher_name][day_name][period_label] = course_content
    except Exception as e:
        return None
    return schedule_db

# --- UI 介面 ---
st.title("🏫 成德高中調代課系統")
st.caption("手機版：點擊左上角 `>` 可展開選單上傳課表")

# Sidebar 在手機上會變成漢堡選單
with st.sidebar:
    st.header("⚙️ 系統設定")
    uploaded_file = st.file_uploader("請上傳課表 PDF", type=["pdf"])
    st.info("💡 首次使用請先上傳 PDF，系統會自動快取資料。")

if uploaded_file:
    db = parse_pdf_schedule(uploaded_file)
    if db is None:
        st.error("❌ PDF 解析失敗，請確認檔案是否正確。")
        st.stop()
    else:
        st.sidebar.success(f"✅ 已載入 {len(db)} 位教師")
else:
    # 預設 Demo 資料
    db = {"範例教師": {"一": {"08:00": "請上傳檔案"}}}
    st.warning("👈 請先從選單上傳課表 PDF")

# --- 主操作區 ---
# 使用 container 來區隔區塊，手機閱讀更清楚
with st.container():
    st.subheader("1️⃣ 查詢與選擇")
    
    col1, col2 = st.columns(2)
    with col1:
        teacher_list = list(db.keys())
        selected_teacher = st.selectbox("教師姓名", teacher_list)
    
    with col2:
        days = ["一", "二", "三", "四", "五"]
        selected_day = st.selectbox("星期", days)

    # 動態取得節次
    periods = []
    if selected_teacher and selected_day in db.get(selected_teacher, {}):
        periods = list(db[selected_teacher][selected_day].keys())
    
    if periods:
        selected_period = st.selectbox("節次", periods)
        course_info = db[selected_teacher][selected_day][selected_period]
    else:
        selected_period = st.selectbox("節次", ["無課程"], disabled=True)
        course_info = ""

# --- 輸入與生成 ---
if selected_teacher and periods:
    st.markdown("---")
    st.subheader("2️⃣ 建立調代課單")
    
    with st.form("mobile_form"):
        st.markdown(f"**目前選擇：** {selected_teacher} / 星期{selected_day} / {selected_period}")
        st.markdown(f"**原科目：** `{course_info}`")
        
        sub_teacher = st.text_input("代課教師", placeholder="輸入姓名")
        reason = st.selectbox("事由", ["公假", "病假", "事假", "調課"])
        date_input = st.date_input("執行日期", datetime.today())
        
        # 手機上按鈕要大一點
        submitted = st.form_submit_button("🚀 生成通知單", use_container_width=True)

    if submitted:
        if not sub_teacher:
            st.error("請填寫代課教師！")
        else:
            st.success("通知單已生成！")
            
            # --- 手機版 RWD 通知單 HTML ---
            html_content = f"""
            <div style="
                border: 2px solid #333; 
                padding: 15px; 
                background-color: #fff; 
                color: #000; 
                border-radius: 5px;
                font-family: sans-serif;
                margin-top: 10px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            ">
                <h3 style="text-align: center; border-bottom: 1px solid #ccc; padding-bottom: 10px; margin-top: 0;">調代課通知單</h3>
                <div style="font-size: 0.95rem; line-height: 1.6;">
                    <p><strong>📅 日期：</strong>{date_input.strftime('%Y/%m/%d')} (週{selected_day})</p>
                    <p><strong>📝 事由：</strong>{reason}</p>
                    <hr style="border: 0; border-top: 1px dashed #ccc;">
                    
                    <div style="display: flex; flex-wrap: wrap;">
                        <div style="flex: 1; min-width: 140px; margin-bottom: 10px;">
                            <strong>🔻 原授課</strong><br>
                            師：{selected_teacher}<br>
                            課：{course_info}
                        </div>
                        <div style="flex: 1; min-width: 140px;">
                            <strong>🔻 代課</strong><br>
                            師：{sub_teacher}<br>
                            地：原教室
                        </div>
                    </div>
                </div>
                <div style="text-align: center; margin-top: 15px; font-size: 0.8rem; color: #888;">
                    成德高中教務處 • 電子憑證
                </div>
            </div>
            """
            st.markdown(html_content, unsafe_allow_html=True)
            st.info("💡 手機操作：長按上方通知單可「分享圖片」或截圖傳送。")
