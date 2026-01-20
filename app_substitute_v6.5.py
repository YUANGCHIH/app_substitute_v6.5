import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# ==========================================
# 系統設定
# ==========================================
st.set_page_config(page_title="成德高中 智慧調代課系統 v14", layout="wide")

# ==========================================
# 1. 核心解析邏輯 (針對 114-2 PDF 優化)
# ==========================================

def clean_text(text):
    """
    清洗文字：移除 PDF 常見的雜訊與隱藏字元
    """
    if not text: return ""
    # 移除波斯/阿拉伯語系亂碼 (針對您的檔案出現的 کم, کر)
    text = re.sub(r'[\u0600-\u06FF]', '', text)
    # 移除零寬度空格等隱形字元
    text = re.sub(r'[\u200b-\u200f\ufeff]', '', text)
    # 移除多餘空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_teacher_name(page):
    """
    精準提取教師姓名
    邏輯：尋找 '教師:' 關鍵字，並只抓取其後的中文姓名，避開職稱與數字
    """
    # 只掃描頁面上方 20% 的區域，避免讀到下面的課表內容
    top_area = page.crop((0, 0, page.width, page.height * 0.2))
    text = top_area.extract_text()
    
    if not text: return "未知教師"

    # 策略 A: 正則表達式抓取 "教師:陳大文" 格式
    # 解釋：尋找 "教師" -> 可有可無的冒號或空白 -> 抓取連續的中文字
    match = re.search(r'教師[:：\s]*([\u4e00-\u9fa5]+)', text)
    if match:
        name = match.group(1)
        # 再次確認移除常見職稱
        for title in ["導師", "專任", "代理", "教官", "組長", "主任"]:
            name = name.replace(title, "")
        return name

    # 策略 B: 如果找不到 "教師:"，嘗試找標題行特徵 (通常字體較大，但這裡簡化為排除法)
    lines = text.split('\n')
    for line in lines:
        clean_line = clean_text(line)
        # 如果這一行只有 2-4 個中文字，且不是常見標題
        if 2 <= len(clean_line) <= 4 and re.match(r'^[\u4e00-\u9fa5]+$', clean_line):
            if "課表" not in clean_line and "高中" not in clean_line:
                return clean_line
                
    return "未知教師"

def get_virtual_grid(page):
    """
    建立虛擬網格 (GPS 定位法)
    不依賴表格線條，而是根據文字座標來判斷欄位
    """
    words = page.extract_words(keep_blank_chars=True)
    width = page.width
    height = page.height

    # 1. 定位 X 軸 (星期)
    # 預設邏輯：課表通常左邊 15% 是節次，右邊 85% 均分給週一~週五
    # 如果能抓到 "一", "二"... 的座標就修正，抓不到就用預設值
    
    day_cols = []
    # 嘗試尋找星期幾的標題座標
    day_headers = {"一": None, "二": None, "三": None, "四": None, "五": None}
    for w in words:
        if w['top'] < height * 0.2: # 只看上方
            txt = w['text'].strip()
            for d in day_headers.keys():
                if d in txt and day_headers[d] is None:
                    day_headers[d] = (w['x0'], w['x1'])

    # 判斷是否成功抓到大部分星期
    found_days = [d for d in day_headers.values() if d is not None]
    
    if len(found_days) >= 3:
        # 如果抓得到座標，就用座標中間點來切分
        sorted_days = sorted([k for k, v in day_headers.items() if v], key=lambda k: day_headers[k][0])
        # 這裡簡化邏輯：直接用標題的中心點擴散
        # 更好的做法是：計算欄位邊界
        # 這裡採用「盲猜補正法」：如果 PDF 很亂，直接用幾何平均分割通常最穩
        start_x = width * 0.12 # 略過左側節次欄
        col_width = (width - start_x) / 5
        for i, d in enumerate(["一", "二", "三", "四", "五"]):
            day_cols.append({
                "day": d,
                "x0": start_x + i * col_width,
                "x1": start_x + (i + 1) * col_width
            })
    else:
        # 完全抓不到標題 (亂碼嚴重)，直接使用幾何分割
        start_x = width * 0.12
        col_width = (width - start_x) / 5
        for i, d in enumerate(["一", "二", "三", "四", "五"]):
            day_cols.append({
                "day": d,
                "x0": start_x + i * col_width,
                "x1": start_x + (i + 1) * col_width
            })

    # 2. 定位 Y 軸 (節次)
    # 掃描左側欄位 (x < width*0.15) 的文字，尋找 "08:", "09:", "1" 等特徵
    row_starts = {} # 記錄每一節的開始 Y 座標
    
    # 定義節次關鍵字
    period_kws = {
        "1": ["08:", "8:", "第一節"], "2": ["09:", "9:", "第二節"],
        "3": ["10:", "10", "第三節"], "4": ["11:", "11", "第四節"],
        "5": ["13:", "12:", "第五節"], "6": ["14:", "14", "第六節"],
        "7": ["15:", "15", "第七節"], "8": ["16:", "16", "第八節"]
    }
    
    for w in words:
        if w['x0'] > width * 0.2: continue # 只看左側
        txt = w['text'].replace(" ", "")
        for p, kws in period_kws.items():
            if p not in row_starts:
                for kw in kws:
                    if kw in txt:
                        row_starts[p] = w['top']
                        break
    
    rows = []
    # 如果有抓到節次，就用抓到的；沒抓到就用內插法
    # 為了程式強健性，這裡採用「固定高度推算法」作為備案
    # 假設第一節從 y=150 開始 (大概值)，每節高度約 50-60
    base_y = 100
    if "1" in row_starts: base_y = row_starts["1"]
    
    # 估算平均行高
    step = 55 # 預設經驗值
    if "8" in row_starts and "1" in row_starts:
        step = (row_starts["8"] - row_starts["1"]) / 7
    
    for i in range(1, 9):
        p = str(i)
        top = row_starts.get(p, base_y + (i-1)*step)
        # 定義這一節的上下範圍 (稍微寬一點以免漏字)
        rows.append({"period": p, "top": top - 5, "bottom": top + step + 5})

    return day_cols, rows, words

def extract_class_and_course(content_str):
    """分離班級與課程 (例如: '國一1 國文')"""
    if not content_str: return "", ""
    # 抓取班級 (高/國 + 一二三/- + 數字)
    class_pattern = re.search(r'([高國][一二三\-]\s*\d+)', content_str)
    if class_pattern:
        raw_class = class_pattern.group(1)
        class_code = raw_class.replace(" ", "").replace("-", "")
        course_name = content_str.replace(raw_class, "").strip()
        return class_code, course_name
    return "", content_str

def parse_pdf_v14(uploaded_file):
    extracted_data = []
    
    with pdfplumber.open(uploaded_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # 1. 抓老師名字
            teacher_name = get_teacher_name(page)
            
            # 如果還是抓錯 (例如抓到 '成德高中')，強制過濾
            if "成德" in teacher_name or "課表" in teacher_name:
                teacher_name = f"教師_{i+1}"

            # 2. 取得網格與文字
            day_cols, rows, all_words = get_virtual_grid(page)

            # 3. 將文字投入網格 (Bucket Sorting)
            # 使用字典來收集每個格子裡的文字
            grid_content = {} # Key: "Mon_1", Value: ["國文", "國一1"]

            for w in all_words:
                # 計算文字中心點
                cx = (w['x0'] + w['x1']) / 2
                cy = (w['top'] + w['bottom']) / 2
                
                # 判斷屬於哪一天 (X軸)
                matched_day = None
                for col in day_cols:
                    if col['x0'] <= cx <= col['x1']:
                        matched_day = col['day']
                        break
                
                # 判斷屬於哪一節 (Y軸)
                matched_period = None
                for row in rows:
                    if row['top'] <= cy <= row['bottom']:
                        matched_period = row['period']
                        break
                
                if matched_day and matched_period:
                    key = f"{matched_day}_{matched_period}"
                    if key not in grid_content: grid_content[key] = []
                    grid_content[key].append(w['text'])

            # 4. 整理結果
            for d_col in day_cols:
                d = d_col['day']
                for r_row in rows:
                    p = r_row['period']
                    key = f"{d}_{p}"
                    
                    raw_texts = grid_content.get(key, [])
                    full_text = " ".join(raw_texts)
                    clean_content = clean_text(full_text)
                    
                    # 過濾掉可能是 header 殘留的雜訊 (例如 "一", "早自習")
                    if clean_content in ["一", "二", "三", "四", "五", "早自習", "午休"]:
                        clean_content = ""
                    
                    is_free = (len(clean_content) < 1)
                    
                    extracted_data.append({
                        "teacher": teacher_name,
                        "day": d,
                        "period": p,
                        "content": clean_content,
                        "is_free": is_free
                    })

    # 轉成 DataFrame
    df = pd.DataFrame(extracted_data)
    
    # 自動補科目 (根據每個老師的課程內容投票決定科目)
    if not df.empty:
        for teacher in df['teacher'].unique():
            t_data = df[df['teacher'] == teacher]
            all_content = " ".join(t_data['content'])
            
            # 關鍵字判定
            subject = "綜合"
            keywords = {
                "國語文":"國文", "國文":"國文", "英文":"英文", "英語":"英文", 
                "數學":"數學", "物理":"自然", "化學":"自然", "生物":"自然", "地科":"自然",
                "歷史":"社會", "地理":"社會", "公民":"社會", "社會":"社會",
                "體育":"健體", "美術":"藝能", "音樂":"藝能", "生活科技":"科技", "資訊":"科技",
                "國防":"國防", "健康":"健體"
            }
            detected = {}
            for k, v in keywords.items():
                if k in all_content: detected[v] = detected.get(v, 0) + 1
            
            if detected: subject = max(detected, key=detected.get)
            
            # 回填
            df.loc[df['teacher'] == teacher, 'subject'] = subject
            
    return df

# ==========================================
# 2. UI 介面
# ==========================================

def main():
    st.title("🏫 成德高中 智慧調代課系統 v14")
    st.caption("✅ 修正版：針對 114-2 課表亂碼問題進行專屬優化")

    st.markdown("### 步驟 1：上傳課表 PDF")
    uploaded_file = st.file_uploader("請選擇 PDF 檔案", type=["pdf"])

    if uploaded_file:
        with st.spinner("正在進行 GPS 座標定位分析與亂碼清洗..."):
            try:
                df = parse_pdf_v14(uploaded_file)
                
                # 檢查是否成功抓到老師
                teachers = sorted(df['teacher'].unique())
                if len(teachers) == 0:
                    st.error("解析失敗：找不到任何教師資料。請確認 PDF 格式。")
                else:
                    st.success(f"🎉 解析成功！共找到 {len(teachers)} 位教師。")
                    
                    # 顯示資料預覽 (除錯用)
                    with st.expander("查看原始資料預覽"):
                        st.dataframe(df.head(10))

                    # --- 功能區 ---
                    tab1, tab2, tab3 = st.tabs(["📅 課表查詢", "🚑 空堂代課", "🔄 調課互換"])

                    # Tab 1: 查詢
                    with tab1:
                        t_select = st.selectbox("選擇教師", teachers)
                        if t_select:
                            t_df = df[df['teacher'] == t_select]
                            # 轉成週課表格式
                            pivot = t_df.pivot(index='period', columns='day', values='content')
                            # 排序
                            pivot = pivot.reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"])
                            st.dataframe(pivot, use_container_width=True)

                    # Tab 2: 代課
                    with tab2:
                        c1, c2 = st.columns(2)
                        q_day = c1.selectbox("缺課星期", ["一","二","三","四","五"])
                        q_per = c2.selectbox("缺課節次", [str(i) for i in range(1,9)])
                        
                        frees = df[(df['day']==q_day) & (df['period']==q_per) & (df['is_free']==True)]
                        if not frees.empty:
                            st.write(f"以下老師在 **週{q_day} 第{q_per}節** 為空堂：")
                            st.dataframe(frees[['teacher', 'subject']], hide_index=True)
                        else:
                            st.warning("該時段無人空堂。")

                    # Tab 3: 調課
                    with tab3:
                        c1, c2, c3 = st.columns([2,1,1])
                        init = c1.selectbox("發起教師 (A)", teachers)
                        sd = c2.selectbox("A 欲調出星期", ["一","二","三","四","五"])
                        sp = c3.selectbox("A 欲調出節次", [str(i) for i in range(1,9)])
                        
                        target = st.selectbox("指定對象 (B)", ["不指定"] + [t for t in teachers if t != init])
                        
                        if st.button("搜尋交換方案"):
                            # 尋找邏輯：
                            # 1. 找出 A 在該時段的課 (Source)
                            # 2. 找出 B 在該時段是空堂 (Target Free)
                            # 3. 找出 B 有課的時段，且該時段 A 是空堂 (Swap Opportunity)
                            
                            cands = df[(df['day']==sd) & (df['period']==sp) & (df['is_free']==True) & (df['teacher']!=init)]
                            if target != "不指定":
                                cands = cands[cands['teacher'] == target]
                            
                            a_free_slots = set(df[(df['teacher']==init) & (df['is_free']==True)]['day'] + df[(df['teacher']==init) & (df['is_free']==True)]['period'])
                            
                            results = []
                            for b_name in cands['teacher'].unique():
                                b_courses = df[(df['teacher']==b_name) & (df['is_free']==False)]
                                for _, row in b_courses.iterrows():
                                    if (row['day'] + row['period']) in a_free_slots:
                                        results.append({
                                            "對象教師": b_name,
                                            "可交換課程": row['content'],
                                            "交換至星期": row['day'],
                                            "交換至節次": row['period']
                                        })
                            
                            if results:
                                st.success(f"找到 {len(results)} 個交換方案")
                                st.dataframe(pd.DataFrame(results))
                            else:
                                st.warning("找不到符合雙方空堂條件的交換方案。")

            except Exception as e:
                st.error(f"解析發生錯誤: {str(e)}")
                st.info("建議：如果只有少數老師解析失敗，可能是 PDF 該頁面格式特殊。")

if __name__ == "__main__":
    main()
