import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import date, timedelta

# ==========================================
# 0. 系統設定
# ==========================================
st.set_page_config(page_title="成德高中 智慧調代課系統 v15 (極速版)", layout="wide")

# 初始化 Session State (用於儲存更名設定)
if 'name_mapping' not in st.session_state:
    st.session_state.name_mapping = {}

# ==========================================
# 1. 核心解析邏輯 (一次性快取處理)
# ==========================================

def clean_text_content(text):
    """
    清洗課程內容的雜訊
    """
    if not text: return ""
    # 移除特定外語亂碼
    text = re.sub(r'[\u0600-\u06FF]', '', text) 
    # 移除隱形字元
    text = re.sub(r'[\u200b-\u200f\ufeff]', '', text)
    # 移除多餘空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_teacher_name_simple(page):
    """
    最簡單粗暴的抓名法：抓頁面最上方字體最大的字，或是特定關鍵字後面的字
    """
    width = page.width
    height = page.height
    
    # 只看頁面上方 15%
    top_area = page.crop((0, 0, width, height * 0.15))
    text = top_area.extract_text() or ""
    
    # 策略 A: 找 "教師:"
    match = re.search(r"教師[:：\s]*([\u4e00-\u9fa5]+)", text)
    if match:
        name = match.group(1)
        # 移除職稱
        return re.sub(r'(導師|專任|組長|主任|教官)', '', name)
    
    # 策略 B: 如果亂碼導致 "教師" 變成奇怪的字，我們抓右上角的區塊
    # 通常教師名字會在第一行或第二行
    lines = text.split('\n')
    for line in lines:
        clean = clean_text_content(line)
        # 如果是 2-4 個字的中文字，且不是標題
        if 2 <= len(clean) <= 4 and "課表" not in clean and "高中" not in clean:
            return clean
            
    return "Unknown"

@st.cache_data(show_spinner=False)
def parse_whole_pdf(uploaded_file):
    """
    【關鍵優化】使用快取裝飾器。
    這個函數只會執行一次！之後切換老師都不會再跑進來。
    """
    all_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        # 預先定義座標切分 (假設 A4 橫向)
        # 這些比例是根據一般課表經驗調整的寬容值
        
        for page_idx, page in enumerate(pdf.pages):
            width = page.width
            height = page.height
            
            # 1. 抓名字
            raw_t_name = get_teacher_name_simple(page)
            # 如果真的抓不到，給一個代號
            if raw_t_name == "Unknown": raw_t_name = f"Teacher_{page_idx+1}"

            # 2. 定義網格 (Grid Buckets)
            # 寬度切分：左邊 12% 是節次，剩下 88% 分給 5 天
            start_x = width * 0.12
            col_w = (width - start_x) / 5
            
            day_ranges = [
                ("一", start_x, start_x + col_w),
                ("二", start_x + col_w, start_x + 2*col_w),
                ("三", start_x + 2*col_w, start_x + 3*col_w),
                ("四", start_x + 3*col_w, start_x + 4*col_w),
                ("五", start_x + 4*col_w, width)
            ]

            # 高度切分：假設上方 20% 是標題，下方 80% 分給 8 節
            # 這裡使用「關鍵字定位」來校正 Y 軸
            words = page.extract_words()
            
            # 找節次座標
            row_y_map = {} # {'1': (top, bottom), '2': ...}
            
            # 關鍵字掃描 (增加容錯，例如 '08' 可能被讀成 'O8')
            for w in words:
                if w['x0'] > start_x: continue # 只看左側
                txt = w['text'].replace(":", "").replace("：", "")
                
                # 判定節次
                p = None
                if "08" in txt or "800" in txt or "第一" in txt: p = "1"
                elif "09" in txt or "900" in txt or "第二" in txt: p = "2"
                elif "10" in txt or "第三" in txt: p = "3"
                elif "11" in txt or "第四" in txt: p = "4"
                elif "13" in txt or "12" in txt or "第五" in txt: p = "5"
                elif "14" in txt or "第六" in txt: p = "6"
                elif "15" in txt or "第七" in txt: p = "7"
                elif "16" in txt or "第八" in txt: p = "8"
                
                if p and p not in row_y_map:
                    row_y_map[p] = (w['top'] - 10, w['bottom'] + 50) # 給予寬裕的高度
            
            # 如果抓不到節次 (完全亂碼)，使用盲切
            if len(row_y_map) < 4:
                start_y = height * 0.2
                row_h = (height * 0.75) / 8
                for i in range(1, 9):
                    row_y_map[str(i)] = (start_y + (i-1)*row_h, start_y + i*row_h)

            # 3. 投遞文字 (Bucket Sort)
            # 建立一個空的課表結構
            grid_content = {} # key: "一_1", value: list of words
            
            for w in words:
                # 略過太上面的標題字
                if w['top'] < height * 0.15: continue
                
                cx = (w['x0'] + w['x1']) / 2
                cy = (w['top'] + w['bottom']) / 2
                
                # 判定 Day
                matched_day = None
                for d_name, d_min, d_max in day_ranges:
                    if d_min <= cx <= d_max:
                        matched_day = d_name
                        break
                
                # 判定 Period
                matched_period = None
                # 排序節次以防重疊
                sorted_rows = sorted(row_y_map.items(), key=lambda x: int(x[0]))
                for p, (y_min, y_max) in sorted_rows:
                    if y_min <= cy <= y_max:
                        matched_period = p
                        break
                
                if matched_day and matched_period:
                    key = f"{matched_day}_{matched_period}"
                    if key not in grid_content: grid_content[key] = []
                    grid_content[key].append(w['text'])
            
            # 4. 輸出資料
            for d_name, _, _ in day_ranges:
                for i in range(1, 9):
                    p = str(i)
                    key = f"{d_name}_{p}"
                    
                    word_list = grid_content.get(key, [])
                    full_text = " ".join(word_list)
                    clean = clean_text_content(full_text)
                    
                    # 過濾無效內容
                    if clean in ["一", "二", "三", "四", "五", "午休"]: clean = ""
                    
                    is_free = (len(clean) < 1)
                    
                    all_data.append({
                        "raw_teacher_name": raw_t_name, # 原始讀到的名字 (可能有錯字)
                        "day": d_name,
                        "period": p,
                        "content": clean,
                        "is_free": is_free
                    })

    return pd.DataFrame(all_data)

# ==========================================
# 2. 輔助函式
# ==========================================
def extract_class_course(text):
    if not text: return "", ""
    # 簡單的正則抓取班級
    match = re.search(r'([高國][一二三\-]\s*\d+)', text)
    if match:
        cls = match.group(1).replace(" ", "").replace("-", "")
        crs = text.replace(match.group(1), "").strip()
        return cls, crs
    return "", text

def apply_name_mapping(df):
    """應用使用者設定的名字修正"""
    if df.empty: return df
    # 複製一份以免改到快取
    df_out = df.copy()
    # 建立映射列
    # 如果 raw_name 在 mapping 裡，就用 mapping 的值，否則用原值
    df_out['teacher'] = df_out['raw_teacher_name'].apply(
        lambda x: st.session_state.name_mapping.get(x, x)
    )
    return df_out

# ==========================================
# 3. 主程式 UI
# ==========================================
def main():
    st.title("🏫 成德高中 智慧調代課系統 v15 (極速修正版)")
    
    with st.sidebar:
        st.header("步驟 1：上傳 PDF")
        uploaded_file = st.file_uploader("上傳全校課表", type=["pdf"], key="pdf_v15")
        
        st.divider()
        st.header("步驟 2：教師名稱修正")
        st.caption("如果名字有亂碼 (如: 遲->埋)，請在此修正。修正後全系統會自動更新。")
        
        # 只有當檔案上傳後才顯示修正工具
        if uploaded_file:
            # 1. 解析 (這步會被快取，第二次很快)
            with st.spinner("正在讀取課表... (首次需耗時幾秒，之後會變快)"):
                raw_df = parse_whole_pdf(uploaded_file)
            
            if not raw_df.empty:
                # 取得所有「原始」名字
                raw_teachers = sorted(raw_df['raw_teacher_name'].unique())
                
                # 修正介面
                col_a, col_b = st.columns(2)
                target_raw = col_a.selectbox("選擇顯示錯誤的名字", raw_teachers)
                correct_name = col_b.text_input("輸入正確名字", placeholder="例如: 遲宇昂")
                
                if st.button("新增/更新 修正規則"):
                    if correct_name:
                        st.session_state.name_mapping[target_raw] = correct_name
                        st.success(f"已設定：'{target_raw}' 將顯示為 '{correct_name}'")
                        st.rerun() # 重新整理以套用
                
                # 顯示目前的修正列表
                if st.session_state.name_mapping:
                    st.markdown("---")
                    st.markdown("**目前已設定的修正：**")
                    for k, v in st.session_state.name_mapping.items():
                        c1, c2 = st.columns([3, 1])
                        c1.text(f"{k} ➝ {v}")
                        if c2.button("刪", key=f"del_{k}"):
                            del st.session_state.name_mapping[k]
                            st.rerun()

    # --- 主視窗邏輯 ---
    if uploaded_file and 'raw_df' in locals() and not raw_df.empty:
        # 2. 套用名字修正 (這是瞬間完成的 Dataframe 操作)
        df = apply_name_mapping(raw_df)
        
        # 3. 補上科目 (自動推斷)
        # 為了效能，這步也可以簡化，這裡做一個簡單的 map
        teachers = sorted(df['teacher'].unique())
        
        # --- 介面開始 ---
        tab1, tab2, tab3 = st.tabs(["📅 課表檢視", "🚑 代課搜尋", "🔄 互換調課"])

        with tab1:
            t_select = st.selectbox("請選擇教師", teachers)
            t_data = df[df['teacher'] == t_select]
            
            # 轉成 Pivot Table
            pivot = t_data.pivot_table(index='period', columns='day', values='content', aggfunc='first')
            # 補齊格式
            pivot = pivot.reindex([str(i) for i in range(1, 9)]).reindex(columns=["一", "二", "三", "四", "五"]).fillna("")
            
            st.dataframe(pivot, use_container_width=True)

        with tab2:
            c1, c2 = st.columns(2)
            q_d = c1.selectbox("缺課星期", ["一", "二", "三", "四", "五"])
            q_p = c2.selectbox("缺課節次", [str(i) for i in range(1, 9)])
            
            # 搜尋空堂
            frees = df[(df['day'] == q_d) & (df['period'] == q_p) & (df['is_free'] == True)]
            
            if not frees.empty:
                st.success(f"找到 {len(frees)} 位老師有空堂")
                # 顯示前簡單過濾重複
                st.dataframe(frees[['teacher']].drop_duplicates(), hide_index=True, use_container_width=True)
            else:
                st.warning("該時段無人空堂")

        with tab3:
            st.info("搜尋：我想調出 A 的課，找 B 幫忙代課，並且我幫 B 上他的課 (互換)")
            c1, c2, c3 = st.columns([2, 1, 1])
            who_a = c1.selectbox("A 老師 (發起)", teachers)
            day_a = c2.selectbox("A 調出星期", ["一", "二", "三", "四", "五"])
            per_a = c3.selectbox("A 調出節次", [str(i) for i in range(1, 9)])
            
            st.markdown("👇 **篩選 B 老師**")
            who_b = st.selectbox("指定 B 老師 (選填)", ["不指定"] + [t for t in teachers if t != who_a])
            
            # 檢查 A 該堂課是否存在
            course_a = df[(df['teacher'] == who_a) & (df['day'] == day_a) & (df['period'] == per_a)]
            if course_a.empty or course_a.iloc[0]['is_free']:
                st.error("錯誤：A 老師在該時段是空堂，無法調出。")
            else:
                cls_a, _ = extract_class_course(course_a.iloc[0]['content'])
                st.text(f"預計調出課程：{course_a.iloc[0]['content']}")
                
                if st.button("🔍 搜尋互換方案"):
                    # 邏輯：
                    # 1. 找 B: 在 [day_a, per_a] 是空堂 (可以幫A上)
                    # 2. 找 B: 有某一堂課 [day_b, per_b]
                    # 3. 檢查 A: 在 [day_b, per_b] 是空堂 (可以接B的課)
                    
                    # 步驟 1
                    candidates_b = df[(df['day'] == day_a) & (df['period'] == per_a) & (df['is_free'] == True) & (df['teacher'] != who_a)]
                    if who_b != "不指定":
                        candidates_b = candidates_b[candidates_b['teacher'] == who_b]
                    
                    # A 的所有空堂時段 (Set 加速查詢)
                    a_frees = set(df[(df['teacher'] == who_a) & (df['is_free'] == True)].apply(lambda x: f"{x['day']}_{x['period']}", axis=1))
                    
                    results = []
                    
                    for b_name in candidates_b['teacher'].unique():
                        # 步驟 2: 找 B 的所有課
                        b_courses = df[(df['teacher'] == b_name) & (df['is_free'] == False)]
                        
                        for _, row in b_courses.iterrows():
                            # 步驟 3: 檢查 A 是否有空
                            if f"{row['day']}_{row['period']}" in a_frees:
                                cls_b, _ = extract_class_course(row['content'])
                                
                                # 加分項：如果是同一個班級互換，標記星星
                                tag = "⭐同班互換" if (cls_a and cls_b and cls_a == cls_b) else ""
                                
                                results.append({
                                    "標記": tag,
                                    "對象教師": b_name,
                                    "B 還課星期": row['day'],
                                    "B 還課節次": row['period'],
                                    "B 還課內容": row['content']
                                })
                    
                    if results:
                        res_df = pd.DataFrame(results)
                        # 排序：有星星的排前面
                        res_df = res_df.sort_values(by="標記", ascending=False)
                        st.success(f"找到 {len(res_df)} 個互換方案")
                        st.dataframe(res_df, use_container_width=True)
                    else:
                        st.warning("找不到符合的互換對象 (可能是對方該時段沒空，或對方的課您沒空接)。")

    elif uploaded_file:
        st.error("讀取不到任何資料，請確認 PDF 格式是否正確。")

if __name__ == "__main__":
    main()
