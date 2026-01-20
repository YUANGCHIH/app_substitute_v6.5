import streamlit as st
import pdfplumber
import pandas as pd
import re
import base64

# 設定頁面配置
st.set_page_config(
    page_title="成德高中 智慧調代課系統 v2.0",
    page_icon="🏫",
    layout="wide"
)

# ---------------------------------------------------------
# 1. 核心邏輯：PDF 解析與資料處理
# ---------------------------------------------------------

def clean_teacher_name(raw_text):
    """
    從字串中提取純中文姓名 (2-4個字)，過濾職稱。
    """
    if not isinstance(raw_text, str):
        return ""
    
    # 策略 1: 尋找 "教師:XXX" 或 "教師：XXX"
    match = re.search(r"教師[:：\s]*([\u4e00-\u9fa5]{2,4})", raw_text)
    if match:
        return match.group(1)
    
    # 策略 2: 如果字串本身就很短，且全是中文，可能是名字
    clean_text = re.sub(r'[0-9a-zA-Z\s導師老師]+', '', raw_text)
    if 2 <= len(clean_text) <= 4:
        return clean_text
        
    return ""

def parse_schedule_pdf(uploaded_file, debug_mode=False):
    """
    解析成德高中課表 PDF (增強版)。
    使用 'text' 策略來偵測無格線表格。
    """
    all_data = []
    debug_logs = []
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                
                # -------------------------
                # 步驟 1: 提取教師姓名
                # -------------------------
                # 先抓取頁面最上方的幾行文字來找名字
                header_text = text[:200] if text else "" 
                teacher_name = clean_teacher_name(header_text)
                
                if not teacher_name:
                    # 如果找不到，嘗試在整頁文字找
                    teacher_name = clean_teacher_name(text)

                if not teacher_name:
                    if debug_mode:
                        debug_logs.append(f"第 {page_num+1} 頁: ⚠️ 無法辨識教師姓名，跳過。")
                    continue
                
                # -------------------------
                # 步驟 2: 解析表格 (關鍵修正)
                # -------------------------
                # 設定：使用文字間距來推斷欄位，而不是尋找黑線
                table_settings = {
                    "vertical_strategy": "text", 
                    "horizontal_strategy": "text",
                    "snap_tolerance": 5,
                }
                
                tables = page.extract_tables(table_settings)
                
                if not tables:
                    if debug_mode:
                        debug_logs.append(f"第 {page_num+1} 頁 ({teacher_name}): ⚠️ 找不到表格結構。")
                    continue
                
                # 假設最大的那個表格是課表
                # 找出含有最多列的表格
                main_table = max(tables, key=len)
                
                # -------------------------
                # 步驟 3: 遍歷表格列
                # -------------------------
                days_mapping = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}
                
                for row_idx, row in enumerate(main_table):
                    # 濾除 None
                    row = [cell.strip() if cell else "" for cell in row]
                    
                    # 判斷是否為課程資料列
                    # 特徵：第一欄通常是節次 (數字 1~9 或 時間)
                    first_col = row[0]
                    
                    # 嘗試提取節次數字
                    period = None
                    # 用 Regex 抓開頭的數字 (1, 2, ... 8)
                    p_match = re.match(r'^([1-9])', first_col)
                    if p_match:
                        period = int(p_match.group(1))
                    
                    if period is None:
                        continue # 跳過非課程列 (如標題、早自習、午休)
                        
                    # 讀取 週一 ~ 週五 的資料
                    # 假設欄位結構: [節次, 一, 二, 三, 四, 五, ...]
                    # 有時候 PDF 解析出的欄位數會變動，我們抓前 6 欄 (Index 0~5)
                    
                    current_col = 1 # 從 index 1 開始是對應星期一
                    for day_idx in range(1, 6): # 1~5 (一~五)
                        if current_col >= len(row):
                            break
                        
                        cell_content = row[current_col]
                        day_name = days_mapping[day_idx]
                        current_col += 1
                        
                        if len(cell_content) > 1: # 排除空字串
                            # 處理內容，通常是 "科目 班級" 或 "科目\n班級"
                            # 移除過多空白
                            content = re.sub(r'\s+', ' ', cell_content).strip()
                            
                            # 嘗試拆分科目與班級 (簡單邏輯：最後一個詞可能是班級)
                            parts = content.split(' ')
                            if len(parts) >= 2:
                                subject = " ".join(parts[:-1])
                                classname = parts[-1]
                            else:
                                subject = content
                                classname = "?"
                                
                            all_data.append({
                                "Teacher": teacher_name,
                                "Day": day_name,
                                "Period": period,
                                "Subject": subject,
                                "Class": classname,
                                "FullContent": content
                            })
                
                if debug_mode:
                    debug_logs.append(f"第 {page_num+1} 頁 ({teacher_name}): ✅ 成功解析 (範例: {all_data[-1]['Subject'] if all_data else '無'})")

        return pd.DataFrame(all_data), debug_logs

    except Exception as e:
        return pd.DataFrame(), [f"❌ 發生錯誤: {str(e)}"]

# ---------------------------------------------------------
# UI 輔助函式
# ---------------------------------------------------------

def generate_print_button(teacher_a, content_a, teacher_b, content_b, swap_info):
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: "Microsoft JhengHei", Arial; padding: 20px; }}
            .container {{ border: 2px solid #333; padding: 20px; max-width: 800px; margin: 0 auto; }}
            h1 {{ text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #333; padding: 10px; text-align: center; }}
            .signature {{ margin-top: 50px; display: flex; justify-content: space-between; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>成德高中 教師調代課互換申請單</h1>
            <p><strong>申請日期：</strong> <span id="date"></span></p>
            <table>
                <tr>
                    <th>角色</th><th>教師</th><th>原定時間</th><th>科目/班級</th><th>異動</th>
                </tr>
                <tr>
                    <td>申請人 (A)</td><td>{teacher_a}</td>
                    <td>{swap_info['Day_A']} 第 {swap_info['Period_A']} 節</td>
                    <td>{content_a}</td><td>轉給 {teacher_b}</td>
                </tr>
                <tr>
                    <td>對象 (B)</td><td>{teacher_b}</td>
                    <td>{swap_info['Day_B']} 第 {swap_info['Period_B']} 節</td>
                    <td>{content_b}</td><td>轉給 {teacher_a}</td>
                </tr>
            </table>
            <div class="signature">
                <div>申請人：___________</div>
                <div>對象：___________</div>
                <div>教學組：___________</div>
            </div>
        </div>
        <script>
            document.getElementById('date').innerText = new Date().toLocaleDateString();
            window.print();
        </script>
    </body>
    </html>
    """
    b64_html = base64.b64encode(html_content.encode()).decode()
    return f'<a href="data:text/html;base64,{b64_html}" target="_blank" style="background-color: #FF4B4B; color: white; padding: 8px 15px; text-decoration: none; border-radius: 5px;">🖨️ 列印調課單</a>'

# ---------------------------------------------------------
# 主程式
# ---------------------------------------------------------

def main():
    st.title("🏫 成德高中 智慧調代課系統 v2.0")
    st.markdown("---")

    with st.sidebar:
        st.header("1. 資料來源")
        uploaded_file = st.file_uploader("請上傳課表 PDF", type=["pdf"])
        
        debug_mode = st.checkbox("開啟除錯模式 (顯示解析紀錄)", value=False)
        
        df = pd.DataFrame()
        if uploaded_file:
            with st.spinner("正在解析 PDF 課表 (Text Strategy)..."):
                df, logs = parse_schedule_pdf(uploaded_file, debug_mode)
            
            if debug_mode:
                with st.expander("📝 解析紀錄 (Debug Log)", expanded=True):
                    for log in logs:
                        st.text(log)
            
            if not df.empty:
                st.success(f"讀取成功！共解析出 {len(df)} 筆課程資料。")
                st.info(f"偵測到 {df['Teacher'].nunique()} 位教師。")
                if debug_mode:
                    st.write("預覽資料:", df.head())
            else:
                st.error("無法解析資料。請確認 PDF 是否為文字格式 (非掃描圖片)，或嘗試開啟除錯模式檢查。")
                return
        else:
            st.info("請先上傳檔案。")
            return

    if df.empty:
        return

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📅 課表檢視", "🔍 尋找代課", "🔄 互換調課"])

    # Tab 1: 課表檢視
    with tab1:
        st.subheader("教師週課表")
        teachers = sorted(df['Teacher'].unique())
        if not teachers:
            st.warning("無教師資料")
        else:
            selected_teacher = st.selectbox("選擇教師", teachers)
            t_df = df[df['Teacher'] == selected_teacher]
            
            # Pivot
            pivot = t_df.pivot_table(index='Period', columns='Day', values='FullContent', aggfunc='first')
            # 補齊結構
            pivot = pivot.reindex(index=range(1, 9), columns=["一", "二", "三", "四", "五"]).fillna("")
            st.dataframe(pivot, use_container_width=True)

    # Tab 2: 尋找代課
    with tab2:
        st.subheader("空堂查詢")
        c1, c2 = st.columns(2)
        d = c1.selectbox("星期", ["一", "二", "三", "四", "五"])
        p = c2.selectbox("節次", range(1, 9))
        
        if st.button("搜尋"):
            busy = df[(df['Day'] == d) & (df['Period'] == p)]['Teacher'].unique()
            all_t = set(df['Teacher'].unique())
            free = sorted(list(all_t - set(busy)))
            st.write(f"**{len(free)} 位教師空堂：**")
            st.write(", ".join([f"`{x}`" for x in free]))

    # Tab 3: 互換調課
    with tab3:
        st.subheader("雙向調課計算機")
        
        # A 設定
        col_a1, col_a2 = st.columns(2)
        teacher_a = col_a1.selectbox("發起人 (A)", teachers)
        
        df_a = df[df['Teacher'] == teacher_a].sort_values(['Day', 'Period'])
        if df_a.empty:
            st.warning("此教師無課程")
        else:
            opts = [f"{r['Day']} {r['Period']}節: {r['FullContent']}" for _, r in df_a.iterrows()]
            course_str = col_a2.selectbox("A 欲換出的課", opts)
            
            # 解析選擇
            idx = opts.index(course_str)
            course_a = df_a.iloc[idx]
            
            st.divider()
            
            # 尋找 B
            if st.button("計算可行交換"):
                # 邏輯: 找 B
                # 1. B 在 A的時間 (A_Day, A_Period) 空堂
                # 2. A 在 B的時間 (B_Day, B_Period) 空堂
                
                # A 的所有忙碌時間
                a_busy = set(zip(df_a['Day'], df_a['Period']))
                
                candidates = []
                others = df[df['Teacher'] != teacher_a]
                
                for _, row_b in others.iterrows():
                    # B 的時間
                    b_d, b_p = row_b['Day'], row_b['Period']
                    
                    # 排除相同時間 (無法交換)
                    if b_d == course_a['Day'] and b_p == course_a['Period']:
                        continue
                        
                    # 檢查 1: B 在 A 的原時間是否有課?
                    # 查詢 others 中，Teacher=B, Day=A_Day, Period=A_Period
                    b_busy_at_a = not others[
                        (others['Teacher'] == row_b['Teacher']) & 
                        (others['Day'] == course_a['Day']) & 
                        (others['Period'] == course_a['Period'])
                    ].empty
                    
                    if b_busy_at_a: continue
                    
                    # 檢查 2: A 在 B 的原時間是否有課?
                    if (b_d, b_p) in a_busy: continue
                    
                    # 符合
                    candidates.append(row_b)
                
                if not candidates:
                    st.info("無符合對象")
                else:
                    res = pd.DataFrame(candidates)
                    res['SameClass'] = res['Class'] == course_a['Class']
                    res = res.sort_values(['SameClass', 'Day', 'Period'], ascending=[False, True, True])
                    
                    st.success(f"找到 {len(res)} 個方案")
                    
                    for _, r in res.iterrows():
                        icon = "⭐" if r['SameClass'] else ""
                        with st.expander(f"{icon} {r['Teacher']} - 週{r['Day']} 第{r['Period']}節 ({r['Subject']})"):
                            st.write(f"與 {teacher_a} 的 週{course_a['Day']} 第{course_a['Period']}節 交換")
                            
                            swap_ctx = {
                                "Day_A": course_a['Day'], "Period_A": course_a['Period'],
                                "Day_B": r['Day'], "Period_B": r['Period']
                            }
                            st.markdown(generate_print_button(
                                teacher_a, course_a['FullContent'], 
                                r['Teacher'], r['FullContent'], 
                                swap_ctx
                            ), unsafe_allow_html=True)

if __name__ == "__main__":
    main()
