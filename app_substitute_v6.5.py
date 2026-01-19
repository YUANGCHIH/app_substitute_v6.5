# =========================================
# 成德高中 智慧調代課系統 v9.1（校務穩定版）
# 不內建 OCR（避免系統相依問題）
# =========================================

import streamlit as st
import pdfplumber
import pandas as pd
import re

st.set_page_config(
    page_title="成德高中 智慧調代課系統 v9.1",
    layout="wide"
)

# =========================================
# 1. 工具層
# =========================================

def is_scanned_pdf(pdf):
    for page in pdf.pages[:2]:
        t = page.extract_text()
        if t and len(t.strip()) > 30:
            return False
    return True


def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'\d{1,2}[:：]\d{2}[-–~～]\d{1,2}[:：]\d{2}', '', text)
    text = re.sub(r'\d{1,2}[:：]\d{2}', '', text)
    text = re.sub(r'第\s*[一二三四五六七八0-9]+\s*節', '', text)
    return text.replace("\n", " ").strip()


def extract_teacher(text, fallback):
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


def detect_period(text):
    period_map = {
        1: ["08:", "第一節"],
        2: ["09:", "第二節"],
        3: ["10:", "第三節"],
        4: ["11:", "第四節"],
        5: ["12:", "13:", "第五節"],
        6: ["14:", "第六節"],
        7: ["15:", "第七節"],
        8: ["16:", "第八節"]
    }
    for p, keys in period_map.items():
        for k in keys:
            if k in text:
                return p
    return None


def extract_class_course(text):
    if not text:
        return "", text
    m = re.search(r'(高|國)[一二三]\d+', text)
    if m:
        cls = m.group(0)
        course = text.replace(cls, "").strip()
        return cls, course
    return "", text


# =========================================
# 2. 課表解析
# =========================================

@st.cache_data
def parse_schedule(uploaded_file):
    records = []

    with pdfplumber.open(uploaded_file) as pdf:

        # 🚫 掃描型 PDF → 明確告知，不嘗試解析
        if is_scanned_pdf(pdf):
            return None, "此 PDF 為掃描型（圖片），請先進行 OCR 再上傳（Google Drive 或 Adobe）"

        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            teacher = extract_teacher(text, f"教師_{p_idx+1}")

            tables = page.extract_tables()
            if not tables:
                continue

            table = tables[0]

            day_cols = {}
            for r in table[:3]:
                for i, c in enumerate(r):
                    if not c: continue
                    if "一" in c: day_cols[i] = "一"
                    if "二" in c: day_cols[i] = "二"
                    if "三" in c: day_cols[i] = "三"
                    if "四" in c: day_cols[i] = "四"
                    if "五" in c: day_cols[i] = "五"

            if not day_cols:
                day_cols = {1:"一",2:"二",3:"三",4:"四",5:"五"}

            for row in table:
                row_text = "".join([str(c) for c in row if c])
                period = detect_period(row_text)
                if not period:
                    continue

                for col, day in day_cols.items():
                    if col < len(row):
                        raw = clean_text(str(row[col]))
                        cls, course = extract_class_course(raw)
                        records.append({
                            "teacher": teacher,
                            "day": day,
                            "period": period,
                            "class": cls,
                            "course": course,
                            "is_free": raw == ""
                        })

    return pd.DataFrame(records), None


# =========================================
# 3. UI
# =========================================

def main():
    st.title("🏫 成德高中 智慧調代課系統 v9.1")

    uploaded = st.sidebar.file_uploader(
        "步驟一：上傳教師課表 PDF（需為文字型）",
        type=["pdf"]
    )

    if not uploaded:
        st.info("請上傳課表 PDF")
        return

    with st.spinner("解析課表中..."):
        df, err = parse_schedule(uploaded)

    if err:
        st.error(err)
        return

    if df.empty:
        st.warning("未解析到任何課表資料")
        return

    st.success(f"解析完成｜教師數：{df['teacher'].nunique()}")

    t = st.selectbox("選擇教師", sorted(df["teacher"].unique()))
    view = df[df["teacher"] == t]
    pivot = view.pivot(index="period", columns="day", values="course")
    pivot = pivot.reindex(range(1,9))
    pivot = pivot.reindex(columns=["一","二","三","四","五"])
    st.dataframe(pivot, use_container_width=True)


if __name__ == "__main__":
    main()
