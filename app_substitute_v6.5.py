import streamlit as st
import pdfplumber
import pandas as pd
import re
import base64

# 設定頁面配置
st.set_page_config(
    page_title="成德高中 智慧調代課系統",
    page_icon="🏫",
    layout="wide"
)

# ---------------------------------------------------------
# 1. 核心邏輯：PDF 解析與資料處理
# ---------------------------------------------------------

def clean_teacher_name(raw_name):
    """
    清洗教師姓名，移除職稱、數字等雜訊。
    例如: '陳慧敏 103導師' -> '陳慧敏'
    """
    if not isinstance(raw_name, str):
        return ""
    # 移除 "導師", "老師", 數字, 空白
    name = re.sub(r'[0-9\s導師老]+', '', raw_name)
    return name

def parse_schedule_pdf(uploaded_file):
    """
    解析成德高中課表 PDF。
    假設格式：每一頁上方有 '教師:XXX'，下方有表格。
    """
    all_data = []
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                table = page.extract_table()
                
                if not text or not table:
                    continue
                
                # 1. 提取教師姓名
                # 尋找類似 "教師:陳慧敏" 或 "教師：陳慧敏" 的字串
                teacher_match = re.search(r"教師[:：]\s*([^\s]+)", text)
                if not teacher_match:
                    continue
                
                raw_teacher_name = teacher_match.group(1)
                teacher_name = clean_teacher_name(raw_teacher_name)
                
                # 2. 解析表格
                # 假設表格結構：
                # 第一欄通常是節次/時間
                # 第二欄~第六欄通常是 星期一 ~ 星期五
                
                # 定義星期對照 (假設表格欄位順序)
                days_mapping = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}
                
                for row in table:
                    # 跳過空行或標題行 (簡單判斷：第一格若是 '節次' 或空)
                    if not row or row[0] is None or "節" in str(row[0]) or "時間" in str(row[0]) or "早自習" in str(row[0]):
                        # 嘗試解析早自習或特殊行，但在這裡我們先專注於正規課堂 1-8
                        # 如果需要解析早自習，可在此擴充
                        continue
                    
                    # 嘗試提取節次 (假設第一欄是節次，例如 "1", "08:00")
                    period_str = str(row[0]).strip()
                    
                    # 簡單的節次正規化：只取數字，或者對應常見的時間
                    # 這裡簡化處理：嘗試從字串中抓出 1-9 的數字，代表第幾節
                    period_match = re.search(r'^([1-9])', period_str)
                    
                    if period_match:
                        period = int(period_match.group(1))
                    else:
                        # 若無法辨識節次，跳過此行
                        continue
                        
                    # 遍歷星期一~五 (Index 1 to 5 in the row)
                    for col_idx, day_name in days_mapping.items():
                        if col_idx < len(row):
                            cell_content = row[col_idx]
                            
                            if cell_content and isinstance(cell_content, str):
                                cell_content = cell_content.strip()
                                if len(cell_content) > 1: # 排除空字串或雜訊
                                    # 內容通常包含 "科目" 和 "班級"
                                    # 因為 PDF 表格內可能是換行符號分隔，例如 "國語\n103"
                                    parts = cell_content.split('\n')
                                    
                                    subject = parts[0] if len(parts) > 0 else "未知"
                                    classname = parts[1] if len(parts) > 1 else ""
                                    
                                    # 若只有一行，可能格式不同，這裡做個簡單處理
                                    if len(parts) == 1:
                                        # 嘗試用空白切割
                                        sub_parts = cell_content.split()
                                        if len(sub_parts) >= 2:
                                            subject = sub_parts[0]
                                            classname = sub_parts[1]
                                    
                                    all_data.append({
                                        "Teacher": teacher_name,
                                        "Day": day_name,
                                        "Period": period,
                                        "Subject": subject,
                                        "Class": classname,
                                        "FullContent": cell_content # 用於顯示
                                    })

        return pd.DataFrame(all_data)

    except Exception as e:
        st.error(f"PDF 解析失敗: {e}")
        return pd.DataFrame()

# ---------------------------------------------------------
# UI 輔助函式
# ---------------------------------------------------------

def generate_print_button(teacher_a, content_a, teacher_b, content_b, swap_info):
    """
    生成一個 HTML 按鈕，點擊後彈出可列印的調課單
    """
    html_content = f"""
    <html>
    <head>
        <title>調代課申請單</title>
        <style>
            body {{ font-family: "Microsoft JhengHei", Arial; padding: 20px; }}
            .container {{ border: 2px solid #333; padding: 20px; max-width: 800px; margin: 0 auto; }}
            h1 {{ text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #333; padding: 10px; text-align: center; }}
            .signature {{ margin-top: 50px; display: flex; justify-content: space-between; }}
            .btn {{ display: none; }} 
            @media print {{ .no-print {{ display: none; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>成德高中 教師調代課互換申請單</h1>
            <p><strong>申請日期：</strong> <span id="date"></span></p>
            
            <h3>調課詳情</h3>
            <table>
                <tr>
                    <th>角色</th>
                    <th>教師姓名</th>
                    <th>原定時間</th>
                    <th>科目/班級</th>
                    <th>異動後動作</th>
                </tr>
                <tr>
                    <td>申請人 (A)</td>
                    <td>{teacher_a}</td>
                    <td>{swap_info['Day_A']} 第 {swap_info['Period_A']} 節</td>
                    <td>{content_a}</td>
                    <td>轉給 {teacher_b} 上課</td>
                </tr>
                <tr>
                    <td>對象 (B)</td>
                    <td>{teacher_b}</td>
                    <td>{swap_info['Day_B']} 第 {swap_info['Period_B']} 節</td>
                    <td>{content_b}</td>
                    <td>轉給 {teacher_a} 上課</td>
                </tr>
            </table>

            <div class="signature">
                <div>申請人簽名：_________________</div>
                <div>對象教師簽名：_________________</div>
                <div>教學組長：_________________</div>
            </div>
        </div>
        <script>
            document.getElementById('date').innerText = new Date().toLocaleDateString();
            window.print();
        </script>
    </body>
    </html>
    """
    # 將 HTML 編碼為 Base64 以便放入 href Data URI
    b64_html = base64.b64encode(html_content.encode()).decode()
    href = f'data:text/html;base64,{b64_html}'
    
    return f'<a href="{href}" target="_blank" style="background-color: #FF4B4B; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">🖨️ 列印/預覽調課單</a>'

# ---------------------------------------------------------
# 主程式
# ---------------------------------------------------------

def main():
    st.title("🏫 成德高中 智慧調代課系統")
    st.markdown("---")

    # 側邊欄：檔案上傳
    with st.sidebar:
        st.header("1. 資料來源")
        uploaded_file = st.file_uploader("請上傳課表 PDF (例如: 114-2教師課表.pdf)", type=["pdf"])
        
        df = pd.DataFrame()
        if uploaded_file:
            with st.spinner("正在解析 PDF 課表... 請稍候"):
                df = parse_schedule_pdf(uploaded_file)
            
            if not df.empty:
                st.success(f"讀取成功！共解析出 {len(df)} 筆課程資料。")
                st.info(f"偵測到 {df['Teacher'].nunique()} 位教師。")
            else:
                st.warning("無法從 PDF 中解析出有效資料，請確認檔案格式。")
        else:
            st.info("請先上傳課表檔案以開始使用。")
            return

    # 若無資料，停止執行後續
    if df.empty:
        return

    # 建立 Tabs
    tab1, tab2, tab3 = st.tabs(["📅 課表檢視", "🔍 尋找代課 (單向)", "🔄 互換調課 (雙向)"])

    # ==========================================
    # Tab 1: 課表檢視
    # ==========================================
    with tab1:
        st.subheader("教師週課表查詢")
        
        teacher_list = sorted(df['Teacher'].unique())
        selected_teacher = st.selectbox("請選擇教師", teacher_list)
        
        if selected_teacher:
            # 篩選資料
            teacher_df = df[df['Teacher'] == selected_teacher]
            
            # 製作 Pivot Table (列=節次, 欄=星期)
            pivot_schedule = teacher_df.pivot_table(
                index='Period', 
                columns='Day', 
                values='FullContent', 
                aggfunc='first' # 假設同一節只有一門課
            )
            
            # 補齊 1-8 節與 星期一~五，確保表格完整
            all_periods = list(range(1, 9)) # 假設1-8節
            all_days = ["一", "二", "三", "四", "五"]
            
            pivot_schedule = pivot_schedule.reindex(index=all_periods, columns=all_days)
            pivot_schedule = pivot_schedule.fillna("") # 空堂留白
            
            st.dataframe(pivot_schedule, use_container_width=True, height=400)
            st.caption("註：表格內容顯示為「科目 班級」。空白代表空堂。")

    # ==========================================
    # Tab 2: 尋找代課 (單向)
    # ==========================================
    with tab2:
        st.subheader("尋找空堂教師 (代課)")
        st.markdown("查詢特定時間**沒有排課**的教師清單。")
        
        col1, col2 = st.columns(2)
        with col1:
            target_day = st.selectbox("缺課星期", ["一", "二", "三", "四", "五"])
        with col2:
            target_period = st.selectbox("缺課節次", range(1, 9))
            
        if st.button("搜尋空堂教師"):
            # 找出該時段有課的老師
            busy_teachers = df[
                (df['Day'] == target_day) & 
                (df['Period'] == target_period)
            ]['Teacher'].unique()
            
            # 所有老師 - 有課老師 = 空堂老師
            all_teachers = set(df['Teacher'].unique())
            free_teachers = list(all_teachers - set(busy_teachers))
            free_teachers.sort()
            
            st.success(f"星期{target_day} 第 {target_period} 節，共有 {len(free_teachers)} 位教師空堂：")
            
            # 以 Tag 形式顯示，比較美觀
            st.write(", ".join([f"`{t}`" for t in free_teachers]))

    # ==========================================
    # Tab 3: 互換調課 (雙向計算機)
    # ==========================================
    with tab3:
        st.subheader("雙向調課計算機")
        st.markdown("""
        此功能協助 **A 老師** 尋找可交換課程的對象。  
        **邏輯**：A 把課給 B (B 必須空堂)，且 B 把課給 A (A 必須空堂)。
        """)
        
        # 1. 設定發起人 A
        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            teacher_a = st.selectbox("發起教師 (A)", teacher_list, index=0)
        
        # 取得 A 老師的所有課程供選擇
        df_a = df[df['Teacher'] == teacher_a].sort_values(['Day', 'Period'])
        
        if df_a.empty:
            st.warning("此教師無課程資料。")
        else:
            # 製作選項清單
            a_course_options = [
                f"{row['Day']} 第{row['Period']}節 - {row['Subject']} ({row['Class']})" 
                for _, row in df_a.iterrows()
            ]
            
            with col_a2:
                selected_course_str = st.selectbox("A 欲調出的課程", a_course_options)
            
            # 解析使用者選到的 A 課程資訊
            # 格式: "一 第1節 - 國語 (103)"
            # 需要反查 DataFrame 獲取精確資訊
            selected_idx = a_course_options.index(selected_course_str)
            course_a_info = df_a.iloc[selected_idx]
            
            day_a = course_a_info['Day']
            period_a = course_a_info['Period']
            class_a = course_a_info['Class']
            
            st.info(f"目前設定：**{teacher_a}** 欲將 **星期{day_a} 第{period_a}節** 的 **{course_a_info['Subject']} ({class_a})** 換出。")

            st.divider()
            
            # 2. 篩選目標 B
            st.write("### 篩選交換對象 (B)")
            
            # 過濾器 UI
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filter_target_day = st.multiselect("B 的課程星期 (不選則不限)", ["一", "二", "三", "四", "五"])
            with col_f2:
                # 找出資料庫中所有的班級供篩選
                all_classes = sorted(df['Class'].unique())
                filter_target_class = st.multiselect("B 的授課班級 (建議選擇同班級)", all_classes, default=[class_a] if class_a in all_classes else [])

            if st.button("開始計算可行交換方案"):
                candidates = []
                
                # 遍歷所有非 A 的課程作為潛在 B 課程
                potential_swaps = df[df['Teacher'] != teacher_a]
                
                # 應用過濾器
                if filter_target_day:
                    potential_swaps = potential_swaps[potential_swaps['Day'].isin(filter_target_day)]
                if filter_target_class:
                    potential_swaps = potential_swaps[potential_swaps['Class'].isin(filter_target_class)]
                
                # 核心演算法
                # 我們已經鎖定: A 的原課 (Day_A, Period_A)
                # 我們正在檢查: B 的原課 (Day_B, Period_B) 是否能互換
                
                # 為了效能，我們可以先取得 A 的所有忙碌時段 (Day, Period) Set
                a_busy_slots = set(zip(df_a['Day'], df_a['Period']))
                
                for _, row_b in potential_swaps.iterrows():
                    teacher_b = row_b['Teacher']
                    day_b = row_b['Day']
                    period_b = row_b['Period']
                    
                    # 條件 0: 不換同一個時間點的課 (沒有意義且邏輯會壞掉)
                    if day_a == day_b and period_a == period_b:
                        continue
                    
                    # 條件 1: B 在 (Day_A, Period_A) 必須是空堂
                    # 檢查 B 是否在 A 的時間有課
                    b_busy_at_a_slot = not df[
                        (df['Teacher'] == teacher_b) & 
                        (df['Day'] == day_a) & 
                        (df['Period'] == period_a)
                    ].empty
                    
                    if b_busy_at_a_slot:
                        continue # B 沒空，無法接 A 的課
                        
                    # 條件 2: A 在 (Day_B, Period_B) 必須是空堂
                    # 檢查 A 是否在 B 的時間有課
                    # 注意: 我們已知 A 在 Day_A, Period_A 有課，但我們要換去 Day_B, Period_B
                    # 所以只要 (Day_B, Period_B) 不在 A 的忙碌清單中即可
                    if (day_b, period_b) in a_busy_slots:
                        continue # A 沒空，無法接 B 的課
                    
                    # 通過所有檢查，加入候選名單
                    is_same_class = (row_b['Class'] == class_a)
                    candidates.append({
                        "Teacher_B": teacher_b,
                        "Day_B": day_b,
                        "Period_B": period_b,
                        "Subject_B": row_b['Subject'],
                        "Class_B": row_b['Class'],
                        "Content_B": row_b['FullContent'],
                        "Is_Same_Class": is_same_class
                    })
                
                # 顯示結果
                if not candidates:
                    st.warning("找不到符合條件的雙向調課對象。")
                else:
                    # 轉為 DataFrame 展示
                    res_df = pd.DataFrame(candidates)
                    
                    # 排序：同班級優先，然後按星期排序
                    res_df = res_df.sort_values(by=['Is_Same_Class', 'Day_B', 'Period_B'], ascending=[False, True, True])
                    
                    st.success(f"找到 {len(res_df)} 個可行方案！")
                    
                    for idx, row in res_df.iterrows():
                        # 使用 Expander 顯示每個方案
                        icon = "⭐" if row['Is_Same_Class'] else "📄"
                        title_str = f"{icon} 交換對象：{row['Teacher_B']} | 時間：星期{row['Day_B']} 第{row['Period_B']}節 | 科目：{row['Subject_B']} ({row['Class_B']})"
                        
                        with st.expander(title_str):
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                st.write(f"**方案詳情：**")
                                st.write(f"1. **{teacher_a}** 的 {course_a_info['Subject']} (星期{day_a} 第{period_a}節) -> 交給 {row['Teacher_B']}")
                                st.write(f"2. **{row['Teacher_B']}** 的 {row['Subject_B']} (星期{row['Day_B']} 第{row['Period_B']}節) -> 交給 {teacher_a}")
                                if row['Is_Same_Class']:
                                    st.markdown("Easy Swap: **班級相同，學生課表變動最小**。")
                            
                            with c2:
                                # 生成列印按鈕
                                content_a_str = f"{course_a_info['Subject']} ({course_a_info['Class']})"
                                content_b_str = f"{row['Subject_B']} ({row['Class_B']})"
                                
                                swap_context = {
                                    "Day_A": day_a, "Period_A": period_a,
                                    "Day_B": row['Day_B'], "Period_B": row['Period_B']
                                }
                                
                                btn_html = generate_print_button(
                                    teacher_a, content_a_str, 
                                    row['Teacher_B'], content_b_str, 
                                    swap_context
                                )
                                st.markdown(btn_html, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
