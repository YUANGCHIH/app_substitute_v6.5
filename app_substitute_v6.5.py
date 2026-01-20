import streamlit as st
import pdfplumber
import pandas as pd
import re
import numpy as np
from collections import defaultdict

# ==========================================
# 1. 配置與工具函式 (Configuration & Utils)
# ==========================================

st.set_page_config(
    page_title="成德高中 智慧調代課系統",
    page_icon="🏫",
    layout="wide"
)

# Regex 用於清除 PDF 中的雜訊 (包含波斯/阿拉伯語系亂碼)
def clean_text(text):
    if not isinstance(text, str):
        return ""
    # 移除波斯/阿拉伯語系區段 [\u0600-\u06FF]
    # 移除常見雜訊與不可見字元
    text = re.sub(r'[\u0600-\u06FF]', '', text)
    text = re.sub(r'[^\w\s\u4e00-\u9fa5:()-]', '', text) # 保留中英數與基本標點
    return text.strip()

# ==========================================
# 2. 核心解析邏輯 (Core Parsing Logic)
# ==========================================

@st.cache_data(show_spinner=False)
def parse_pdf_schedule(file) -> pd.DataFrame:
    """
    解析極度混亂的課表 PDF。
    不依賴表格線，而是使用座標分群 (Virtual Grid) 策略。
    """
    all_data = []
    
    with pdfplumber.open(file) as pdf:
        total_pages = len(pdf.pages)
        progress_bar = st.progress(0)
        
        for i, page in enumerate(pdf.pages):
            progress_bar.progress((i + 1) / total_pages, text=f"正在解析第 {i+1} 頁...")
            
            width = page.width
            height = page.height
            words = page.extract_words()
            
            # 1. 嘗試抓取教師姓名 (通常在頁面上方)
            # 策略：抓取 top < 150 的文字，尋找 "教師:" 關鍵字，或取字體最大的
            header_words = [w for w in words if w['top'] < 150]
            header_text = "".join([w['text'] for w in header_words])
            header_text = clean_text(header_text)
            
            teacher_name = f"Teacher_{i+1}" # 預設 fallback
            # 簡單正則抓取 "教師:XXX"
            match = re.search(r'教師[:：]?\s*([\u4e00-\u9fa5]+)', header_text)
            if match:
                teacher_name = match.group(1)
            
            # 2. 建立虛擬網格 (Virtual Grid)
            # 定義 X 軸切分：
            # 左邊 15% 保留給「節次/時間」標示
            # 右邊 85% 平均切分為 5 等份 (週一 ~ 週五)
            margin_left_ratio = 0.15
            x_boundary = width * margin_left_ratio
            day_column_width = (width * (1 - margin_left_ratio)) / 5
            
            # 3. 建立 Y 軸錨點 (Row Anchors)
            # 找出落在左側時間欄位的文字，用來定義每一節課的 Y 軸中心
            left_col_words = [w for w in words if w['x0'] < x_boundary and w['top'] > 100] # 忽略頁首
            
            # 為了避免雜訊，我們將 Y 座標相近的字分群 (Cluster)
            y_clusters = defaultdict(list)
            for w in left_col_words:
                # 以 20px 為容忍度進行分群
                found_cluster = False
                for y_key in y_clusters.keys():
                    if abs(w['top'] - y_key) < 20:
                        y_clusters[y_key].append(w)
                        found_cluster = True
                        break
                if not found_cluster:
                    y_clusters[w['top']].append(w)
            
            # 計算每個 cluster 的平均 Y，並排序
            sorted_y_anchors = sorted(y_clusters.keys())
            
            # 我們假設課表通常有 7-9 節課 (含早自習/午休)
            # 將這些錨點映射到節次 (1, 2, 3, 4, ...)，略過太靠上的標題列
            rows_map = {} # {y_anchor: period_index}
            period_counter = 0
            
            # 過濾掉可能是標題的 row (太上面的)
            valid_anchors = [y for y in sorted_y_anchors if y > 120]
            
            # 4. 遍歷頁面所有文字，填入網格
            # 儲存結構： grid[period][day_index] = text
            grid_content = defaultdict(lambda: defaultdict(list))
            
            content_words = [w for w in words if w['x0'] >= x_boundary and w['top'] > 120]
            
            for w in content_words:
                # 判斷星期 (Day)
                relative_x = w['x0'] - x_boundary
                day_idx = int(relative_x // day_column_width) # 0=Mon, 4=Fri
                if day_idx < 0 or day_idx > 4:
                    continue
                
                # 判斷節次 (Period) - 找最近的 Y Anchor
                if not valid_anchors:
                    continue
                closest_y = min(valid_anchors, key=lambda y: abs(y - w['top']))
                
                # 如果距離太遠(超過行高的一半)，可能是不相關的字
                if abs(closest_y - w['top']) > 40:
                    continue
                    
                # 為了方便，我們直接用 valid_anchors 的 index 作為節次 (0-based)
                period_idx = valid_anchors.index(closest_y)
                
                grid_content[period_idx][day_idx].append(w['text'])

            # 5. 整理資料存入列表
            days = ['一', '二', '三', '四', '五']
            
            # 假設標準節次：
            # 若 valid_anchors 數量約為 9-10，通常 0=早自習, 1-4=上午, 5=午休, 6-9=下午
            # 這裡做一個簡單映射，實務上可根據實際 Y 值微調
            
            for p_idx in range(len(valid_anchors)):
                for d_idx in range(5):
                    raw_texts = grid_content[p_idx][d_idx]
                    full_text = "".join(raw_texts)
                    cleaned_text = clean_text(full_text)
                    
                    # 排除空值或無意義標頭
                    if not cleaned_text or cleaned_text in ["午休", "早自習", "下"]:
                        continue
                    
                    # 節次顯示優化 (假設前幾個是早自習/上午)
                    # 這裡使用簡單的序列標號，使用者可透過介面對照
                    period_name = f"第{p_idx}列" 
                    # 嘗試推斷：如果 p_idx=0 可能是早自習，p_idx > 4 可能是下午
                    # 為了通用性，暫時使用序列
                    
                    all_data.append({
                        "Teacher": teacher_name,
                        "Day": days[d_idx],
                        "Period_Seq": p_idx + 1, # 1-based index
                        "Content": cleaned_text
                    })
        
        progress_bar.empty()
        
    return pd.DataFrame(all_data)

# ==========================================
# 3. 應用程式邏輯 (App Logic)
# ==========================================

def main():
    st.title("🏫 成德高中 智慧調代課系統")
    st.markdown("針對 **格式混亂 PDF** 與 **亂碼修正** 的專用解決方案")

    # --- Session State 初始化 ---
    if 'name_correction_map' not in st.session_state:
        st.session_state['name_correction_map'] = {}

    # --- Sidebar: 檔案上傳與設定 ---
    with st.sidebar:
        st.header("1. 資料來源")
        uploaded_file = st.file_uploader("上傳課表 PDF", type=["pdf"])
        
        df_raw = None
        if uploaded_file is not None:
            try:
                df_raw = parse_pdf_schedule(uploaded_file)
                st.success(f"解析完成！共找到 {df_raw['Teacher'].nunique()} 位教師資料")
            except Exception as e:
                st.error(f"解析失敗: {str(e)}")
        
        st.divider()
        st.header("2. 教師姓名修正工具")
        st.info("因字型編碼問題 (如 CID)，部分姓名可能顯示錯誤 (例: 遲 -> 埋)。請在此修正。")
        
        if df_raw is not None:
            # 取得目前所有 (含未修正) 的名字
            current_names = sorted(df_raw['Teacher'].unique())
            
            col1, col2 = st.columns(2)
            with col1:
                target_wrong_name = st.selectbox("選擇顯示錯誤的名字", options=current_names)
            with col2:
                correct_name_input = st.text_input("輸入正確名字")
            
            if st.button("新增/更新 修正規則"):
                if target_wrong_name and correct_name_input:
                    st.session_state['name_correction_map'][target_wrong_name] = correct_name_input
                    st.success(f"已設定: {target_wrong_name} ➔ {correct_name_input}")
                    st.rerun() # 重新整理以套用

            # 顯示目前的對照表
            if st.session_state['name_correction_map']:
                st.subheader("目前修正列表")
                removals = []
                for wrong, right in st.session_state['name_correction_map'].items():
                    c1, c2 = st.columns([3, 1])
                    c1.text(f"{wrong} ➔ {right}")
                    if c2.button("刪", key=f"del_{wrong}"):
                        removals.append(wrong)
                
                if removals:
                    for r in removals:
                        del st.session_state['name_correction_map'][r]
                    st.rerun()

    # --- 主畫面邏輯 ---
    if df_raw is None:
        st.info("請先從左側上傳課表 PDF 檔案。")
        return

    # 套用姓名修正
    df = df_raw.copy()
    df['Teacher'] = df['Teacher'].replace(st.session_state['name_correction_map'])
    
    # 建立 Tabs
    tab1, tab2, tab3 = st.tabs(["📅 查詢課表", "🔍 尋找代課 (單向)", "🤝 互換調課 (雙向)"])

    # --- Tab 1: 查詢課表 ---
    with tab1:
        st.subheader("教師課表檢視")
        teacher_list = sorted(df['Teacher'].unique())
        selected_teacher = st.selectbox("選擇教師", options=teacher_list)
        
        if selected_teacher:
            # 建立 Pivot Table
            teacher_schedule = df[df['Teacher'] == selected_teacher]
            
            # 定義完整的 Grid 結構 (確保空堂也顯示)
            periods = sorted(df['Period_Seq'].unique())
            days = ['一', '二', '三', '四', '五']
            
            pivot_df = pd.DataFrame(index=periods, columns=days)
            pivot_df = pivot_df.fillna("") # 預設空字串
            
            for _, row in teacher_schedule.iterrows():
                if row['Day'] in days and row['Period_Seq'] in periods:
                    pivot_df.at[row['Period_Seq'], row['Day']] = row['Content']
            
            st.dataframe(pivot_df.style.applymap(
                lambda x: "background-color: #e6f3ff" if x else "background-color: #ffffff"
            ), use_container_width=True)

    # --- Tab 2: 尋找代課 (找空堂老師) ---
    with tab2:
        st.subheader("尋找該時段空堂的教師")
        c1, c2 = st.columns(2)
        with c1:
            target_day = st.selectbox("缺課星期", ['一', '二', '三', '四', '五'])
        with c2:
            # 找出資料中存在的節次
            avail_periods = sorted(df['Period_Seq'].unique())
            target_period = st.selectbox("缺課節次 (列號)", avail_periods)
            
        # 邏輯：找出所有老師 -> 扣除該時段有課的老師
        all_teachers = set(df['Teacher'].unique())
        busy_teachers = set(df[
            (df['Day'] == target_day) & 
            (df['Period_Seq'] == target_period)
        ]['Teacher'].unique())
        
        free_teachers = sorted(list(all_teachers - busy_teachers))
        
        st.write(f"在 **星期{target_day} 第 {target_period} 節**，共有 **{len(free_teachers)}** 位教師空堂：")
        
        # 顯示結果，加上過濾器
        search_term = st.text_input("搜尋教師姓名", "")
        display_list = [t for t in free_teachers if search_term in t] if search_term else free_teachers
        
        st.dataframe(pd.DataFrame(display_list, columns=["空堂教師姓名"]), height=300)

    # --- Tab 3: 互換調課計算機 ---
    with tab3:
        st.subheader("雙向調課計算機")
        st.markdown("""
        **使用情境**：我是 A 老師，我想把「某堂課」調出去，找 B 老師來換。
        系統會計算：
        1. B 老師在該時段是否空堂？
        2. B 老師是否有其他課，且該時段 A 老師也是空堂（可以換回來）？
        """)
        
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.markdown("#### 👤 發起人 (Teacher A)")
            teacher_a = st.selectbox("我是...", options=teacher_list, key="swap_a")
            
            # A 的課程清單
            a_courses = df[df['Teacher'] == teacher_a].sort_values(['Day', 'Period_Seq'])
            if a_courses.empty:
                st.warning("此教師無課程資料")
                a_options = []
            else:
                a_options = [f"{r['Day']} / 第{r['Period_Seq']}節 : {r['Content']}" for _, r in a_courses.iterrows()]
            
            selected_course_str = st.selectbox("我想調出的課程", options=a_options)
            
        with col_b:
            st.markdown("#### 🎯 對象 (Teacher B)")
            # 可以選特定人，或搜尋全校
            mode = st.radio("搜尋模式", ["指定特定教師", "搜尋全校合適者"])
            teacher_b_target = None
            if mode == "指定特定教師":
                other_teachers = [t for t in teacher_list if t != teacher_a]
                teacher_b_target = st.selectbox("交換對象", options=other_teachers, key="swap_b")

        if st.button("🔍 計算可行交換方案") and selected_course_str:
            # 解析 A 選的課程時間
            # 格式: "一 / 第2節 : 高一國文"
            parts = selected_course_str.split(" : ")
            time_part = parts[0]
            day_a = time_part.split(" / ")[0]
            period_a = int(re.search(r'第(\d+)節', time_part).group(1))
            subject_a = parts[1] if len(parts) > 1 else ""
            
            # 定義候選人 B 列表
            candidates = [teacher_b_target] if teacher_b_target else [t for t in teacher_list if t != teacher_a]
            
            proposals = []
            
            for b in candidates:
                # 條件 1: B 在 (Day_A, Period_A) 必須是空堂
                b_busy_at_a_time = not df[
                    (df['Teacher'] == b) & 
                    (df['Day'] == day_a) & 
                    (df['Period_Seq'] == period_a)
                ].empty
                
                if b_busy_at_a_time:
                    continue # B 沒空，無法幫 A 代課
                
                # 條件 2: 找出 B 擁有的所有課程
                b_courses = df[df['Teacher'] == b]
                
                for _, row_b in b_courses.iterrows():
                    day_b = row_b['Day']
                    period_b = row_b['Period_Seq']
                    content_b = row_b['Content']
                    
                    # 條件 3: A 在 (Day_B, Period_B) 必須是空堂
                    a_busy_at_b_time = not df[
                        (df['Teacher'] == teacher_a) & 
                        (df['Day'] == day_b) & 
                        (df['Period_Seq'] == period_b)
                    ].empty
                    
                    if not a_busy_at_b_time:
                        # 找到一個可行方案！
                        score = 0
                        note = ""
                        
                        # 加分邏輯：科目或班級內容相似 (簡單字串比對)
                        # 例如 A: "高一1 國文", B: "高一1 英文" -> 同班級互換最理想
                        if subject_a[:3] in content_b or content_b[:3] in subject_a:
                            score += 10
                            note = "⭐ 疑似同班/同科"
                        
                        proposals.append({
                            "Teacher_B": b,
                            "B_Course_Day": day_b,
                            "B_Course_Period": period_b,
                            "B_Course_Content": content_b,
                            "Note": note,
                            "Score": score
                        })
            
            # 顯示結果
            if not proposals:
                st.error("找不到任何可行的互換方案。")
            else:
                # 排序：有標註的優先
                proposals.sort(key=lambda x: x['Score'], reverse=True)
                
                st.success(f"找到 {len(proposals)} 個可行方案！")
                
                for p in proposals:
                    with st.expander(f"與 {p['Teacher_B']} 交換：{p['B_Course_Day']} 第{p['B_Course_Period']}節 ({p['B_Course_Content']}) {p['Note']}"):
                        c1, c2, c3 = st.columns([1, 1, 2])
                        c1.markdown(f"**{teacher_a}**<br>原始: {day_a} 第{period_a}節<br>去上: **{p['B_Course_Day']} 第{p['B_Course_Period']}節**", unsafe_allow_html=True)
                        c2.markdown(f"**{p['Teacher_B']}**<br>原始: {p['B_Course_Day']} 第{p['B_Course_Period']}節<br>去上: **{day_a} 第{period_a}節**", unsafe_allow_html=True)
                        
                        # 產生簡易列印按鈕 (利用 HTML)
                        print_html = f"""
                        <div style="border:2px solid black; padding:20px; width:100%">
                            <h3>調課申請單</h3>
                            <p><strong>申請人：</strong>{teacher_a} (原課: {day_a} 第{period_a}節 {subject_a})</p>
                            <p><strong>互換人：</strong>{p['Teacher_B']} (原課: {p['B_Course_Day']} 第{p['B_Course_Period']}節 {p['B_Course_Content']})</p>
                            <hr>
                            <p>雙方確認簽名：_________________ / _________________</p>
                        </div>
                        <button onclick="var printContents = this.previousElementSibling.outerHTML; var originalContents = document.body.innerHTML; document.body.innerHTML = printContents; window.print(); document.body.innerHTML = originalContents;">列印此單據</button>
                        """
                        c3.components.v1.html(print_html, height=250)

if __name__ == "__main__":
    main()
