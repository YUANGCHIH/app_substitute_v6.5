# =========================================
# 成德高中 智慧調代課系統 v9.0（校務系統級）
# 單檔可執行版
# =========================================

import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime
from pdf2image import convert_from_bytes
import pytesseract

st.set_page_config(
    page_title="成德高中 智慧調代課系統 v9.0",
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


def ocr_pdf(uploaded_file):
    images = convert_from_bytes(uploaded_file.read(), dpi=300)
    texts = []
    for img in images:
        txt = pytesseract.image_to_string(img, lang="chi_tra+eng")
        texts.append(txt)
    return texts


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
# 2. 課表解析（核心）
# =========================================

@st.cache_data
def parse_schedule(uploaded_file):
    records = []

    with pdfplumber.open(uploaded_file) as pdf:

        # --- 掃描 PDF → OCR ---
        if is_scanned_pdf(pdf):
            texts = ocr_pdf(uploaded_file)
            for idx, page_text in enumerate(texts):
                teacher = extract_teacher(page_text, f"OCR教師_{idx+1}")
                for line in page_text.splitlines():
                    period = detect_period(line)
                    if not period:
                        continue
                    for day in ["一","二","三","四","五"]:
                        if day in line:
                            cls, course = extract_class_course(line)
                            records.append({
                                "teacher": teacher,
                                "day": day,
                                "period": period,
                                "class": cls,
                                "course": clean_text(course),
                                "is_free": False,
                                "source": "OCR",
                                "confidence": 0.75
                            })
            return pd.DataFrame(records)

        # --- 文字型 PDF ---
        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            teacher = extract_teacher(text, f"教師_{p_idx+1}")
            tables = page.extract_tables()
            if not tables:
                continue

            table = tables[0]

            # 偵測星期欄
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
                            "is_free": raw == "",
                            "source": "PDF",
                            "confidence": 0.95
                        })

    return pd.DataFrame(records)


# =========================================
# 3. 調代課規則引擎（v9）
# =========================================

def score_candidate(row, target_class, target_course):
    score = 0
    reason = []

    if row["class"] == target_class and target_class:
        score += 50
        reason.append("同班")

    if target_course and row["course"] and target_course[:2] in row["course"]:
        score += 30
        reason.append("相近科目")

    if row["is_free"]:
        score += 20
        reason.append("空堂")

    score += int(row["confidence"] * 10)
    return score, "、".join(reason)


# =========================================
# 4. UI 主程式
# =========================================

def main():
    st.title("🏫 成德高中 智慧調代課系統 v9.0")

    uploaded = st.sidebar.file_uploader(
        "步驟一：上傳教師課表 PDF",
        type=["pdf"]
    )

    if not uploaded:
        st.info("請先上傳課表 PDF")
        return

    with st.spinner("解析課表中（v9 語意層）..."):
        df = parse_schedule(uploaded)

    if df.empty:
        st.error("未能解析任何課表資料")
        return

    st.success(f"解析完成｜教師數：{df['teacher'].nunique()}")

    tab1, tab2 = st.tabs(["📅 課表檢視", "🔄 調代課決策"])

    # -------- 課表檢視 --------
    with tab1:
        t = st.selectbox("選擇教師", sorted(df["teacher"].unique()))
        view = df[df["teacher"] == t]
        pivot = view.pivot(index="period", columns="day", values="course")
        pivot = pivot.reindex(range(1,9))
        pivot = pivot.reindex(columns=["一","二","三","四","五"])
        st.dataframe(pivot, use_container_width=True)

    # -------- 調代課 --------
    with tab2:
        col1, col2, col3 = st.columns(3)
        teacher_a = col1.selectbox("調課教師 A", sorted(df["teacher"].unique()))
        day = col2.selectb
