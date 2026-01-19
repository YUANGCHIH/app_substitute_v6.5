import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import date, timedelta

st.set_page_config(
    page_title="成德高中 智慧調代課系統 v8.0（實務穩定版）",
    layout="wide"
)

# ===============================
# 1. 基礎工具
# ===============================

def is_scanned_pdf(pdf):
    """判斷是否為掃描型 PDF"""
    for page in pdf.pages[:2]:
        text = page.extract_text()
        if text and len(text.strip()) > 30:
            return False
    return True


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\d{1,2}[:：]\d{2}[-–~～]\d{1,2}[:：]\d{2}', '', text)
    text = re.sub(r'\d{1,2}[:：]\d{2}', '', text)
    text = re.sub(r'第\s*[一二三四五六七八0-9]+\s*節', '', text)
    text = text.replace('\n', ' ').strip()
    return text


def extract_teacher_name(text, fallback):
    patterns = [
        r'教師[:：]\s*(\S+)',
        r'任課教師[:：]?\s*(\S+)',
        r'(\S+)老師'
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return fallback


def detect_period(row_text):
    period_map = {
        "1": ["08:", "第一節"],
        "2": ["09:", "第二節"],
        "3": ["10:", "第三節"],
        "4": ["11:", "第四節"],
        "5": ["12:", "13:", "第五節"],
        "6": ["14:", "第六節"],
        "7": ["15:", "第七節"],
        "8": ["16:", "第八節"]
    }
    for p, keys in period_map.items():
        for k in keys:
            if k in row_text:
                return p
    return None


# ===============================
# 2. PDF 解析核心
# ===============================

@st.cache_data
def parse_pdf(uploaded_file):
    results = []

    with pdfplumber.open(uploaded_file) as pdf:

        if is_scanned_pdf(pdf):
            return None, "掃描型 PDF，請先進行 OCR（例如 Adobe 或 Google Drive）"

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            teacher = extract_teacher_name(text, f"教師_{page_idx+1}")

            tables = page.extract_tables()
            if not tables:
                continue

            table = tables[0]

            # 偵測星期欄位
            day_cols = {}
            for r in table[:3]:
                for i, c in enumerate(r):
                    if c and "一" in c: day_cols[i] = "一"
                    if c and "二" in c: day_cols[i] = "二"
                    if c and "三" in c: day_cols[i] = "三"
                    if c and "四" in c: day_cols[i] = "四"
                    if c and "五" in c: day_cols[i] = "五"

            if not day_cols:
                day_cols = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}

            for row in table:
                row_text = "".join([str(c) for c in row if c])
                period = detect_period(row_text)
                if not period:
                    continue

                for col, day in day_cols.items():
                    if col < len(row):
                        content = clean_text(str(row[col]))
                        results.append({
                            "teacher": teacher,
                            "day": day,
                            "period": period,
                            "content": content,
                            "is_free": content == ""
                        })

    return results, None


# ===============================
# 3. 主介面
# ===============================

def main():
    st.title("🏫 成德高中 智慧調代課系統 v8.0")

    uploaded = st.sidebar.file_uploader(
        "步驟 1：上傳教師課表 PDF",
        type=["pdf"]
    )

    if uploaded:
        with st.spinner("解析中，請稍候…"):
            data, err = parse_pdf(uploaded)

        if err:
            st.error(err)
            return

        if not data:
            st.error("無法解析任何課表資料")
            return

        df = pd.DataFrame(data)
        st.success(f"解析完成，共 {df['teacher'].nunique()} 位教師")

        tab1, tab2 = st.tabs(["📅 課表檢視", "🚑 空堂代課查詢"])

        with tab1:
            t = st.selectbox("選擇教師", sorted(df['teacher'].unique()))
            view = df[df['teacher'] == t]
            pivot = view.pivot(index='period', columns='day', values='content')
            pivot = pivot.reindex([str(i) for i in range(1,9)])
            pivot = pivot.reindex(columns=["一","二","三","四","五"])
            st.dataframe(pivot, use_container_width=True)

        with tab2:
            c1, c2 = st.columns(2)
            d = c1.selectbox("星期", ["一","二","三","四","五"])
            p = c2.selectbox("節次", [str(i) for i in range(1,9)])
            frees = df[(df['day']==d)&(df['period']==p)&(df['is_free'])]
            if frees.empty:
                st.warning("無空堂教師")
            else:
                st.dataframe(frees[['teacher']], use_container_width=True)

if __name__ == "__main__":
    main()
