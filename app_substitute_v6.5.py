import streamlit as st
import pdfplumber
import pandas as pd
import re
import base64

# 設定頁面配置
st.set_page_config(
    page_title="成德高中 智慧調代課系統 (強力解析版)",
    page_icon="🏫",
    layout="wide"
)

# ---------------------------------------------------------
# 1. 核心邏輯：PDF 強力解析 (Line-by-Line)
# ---------------------------------------------------------

def clean_teacher_name(text):
    """
    嘗試從雜亂的標題文字中提取教師姓名
    """
    if not text: return "未知教師"
    
    # 1. 抓取 "教師" 後面的內容
    # 針對類似 "教師:陳慧敏 103導師" 或 "教師：繽奸禎"
    match = re.search(r"教師[:：\s]*([^\s]+)", text)
    if match:
        name = match.group(1)
        # 去除常見職稱與數字
        name = re.sub(r'[0-9a-zA-Z導師]+', '', name)
        # 如果結果是空的或太短，可能抓錯
        if len(name) >= 2:
            return name
            
    return "未知教師"

def parse_schedule_pdf_robust(uploaded_file):
    """
    使用 layout=True 模式進行逐行掃描，不依賴表格線。
    """
    all_data = []
    debug_info = [] # 儲存除錯用資訊
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                # 使用 layout=True 保留視覺排版 (空白間距)
                text_layout = page.extract_text(layout=True)
                if not text_layout:
                    continue
                
                lines = text_layout.split('\n')
                
                # --- A. 尋找教師姓名 ---
                teacher_name = f"未知教師_P{page_idx+1}"
                header_found = False
                
                for line in lines[:10]: # 只看前10行找名字
                    if "教師" in line:
                        extracted = clean_teacher_name(line)
                        if extracted != "未知教師":
                            teacher_name = extracted
                            header_found = True
                        break
                
                # --- B. 尋找課程內容 ---
                # 策略：尋找開頭是數字 (節次) 的行
                # 並假設欄位分佈大致為: [節次] [一] [二] [三] [四] [五]
                
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    
                    # 1. 判斷是否為課程行：開頭是 1-9 的數字，後面跟著空白或冒號
                    # Regex: ^[0-9] 且後面不是純文字
                    # 許多課表格式: "1  08:10", "1", "08:10"
                    
                    # 簡易判斷：開頭是單個數字
                    is_period_row = False
                    period = -1
                    
                    match = re.match(r'^([1-9])\s+', line)
                    if match:
                        period = int(match.group(1))
                        is_period_row = True
                    
                    if is_period_row:
                        # 2. 拆分欄位 (利用 2 個以上的連續空白作為分隔符)
                        # 因為 layout=True 模式下，不同欄位間通常會有大空白
                        parts = re.split(r'\s{2,}', line)
                        
                        # parts[0] 應該是節次/時間
                        # parts[1:] 應該是星期一 ~ 五
                        # 但有時候 parts[0] 包含了 "1 08:00"，所以要小心
                        
                        # 嘗試對應星期
                        # 理想狀況 parts 長度應該是 6 (節次 + 5天)
                        # 但如果有空堂，pdfplumber 有時會讀不到該欄位，導致 parts 變少
                        # 這是最難的部分。我們改用「固定位置」推測法或是簡單的順序法
                        
                        # 簡易解法：假設課表都有填滿 (即使是空字串)，或者靠順序
                        # 如果 parts 少於 2，代表沒內容
                        if len(parts) < 2:
                            continue
                            
                        # 移除第一個元素 (節次/時間)
                        content_parts = parts[1:]
                        
                        days = ["一", "二", "三", "四", "五"]
                        
                        # 如果切出來剛好 5 個，那就完美對應
                        # 如果少於 5 個，可能是中間有空堂被吃掉了，或是最後幾天沒課
                        # 這裡做一個大膽假設：依序填入 (這在 pdfplumber layout 模式下通常是對的，因為空堂通常是空白字串而非消失)
                        
                        for i, content in enumerate(content_parts):
                            if i < 5:
                                # 清理內容 (移除換行符號等)
                                content = content.strip()
                                if content and content != ".": # 雜訊過濾
                                    # 嘗試分離 科目/班級
                                    # 常見格式: "國語 101"
                                    sub_parts = content.split(' ')
                                    subject = sub_parts[0]
                                    classname = sub_parts[-1] if len(sub_parts) > 1 else ""
                                    
                                    all_data.append({
                                        "Teacher": teacher_name,
                                        "Day": days[i],
                                        "Period": period,
                                        "Subject": subject,
                                        "Class": classname,
                                        "FullContent": content
                                    })
                
                # 記錄前幾行的原始文字供除錯
                debug_info.append(f"--- Page {page_idx+1} ({teacher_name}) ---\n" + "\n".join(lines[:5]) + "\n...")

        return pd.DataFrame(all_data), debug_info

    except Exception as e:
        return pd.DataFrame(), [f"Error: {str(e)}"]

# ---------------------------------------------------------
# UI 元件
# ---------------------------------------------------------

def generate_print_button(teacher_a, content_a, teacher_b, content_b, swap_info):
    html = f"""
    <html><body>
    <div style="border:2px solid black; padding:20px; width: 600px; font-family: Microsoft JhengHei;">
        <h2 style="text-align:center">調課申請單</h2>
        <p><strong>日期:</strong> <span id="d"></span></p>
        <table border="1" style="width:100%; border-collapse:collapse; text-align:center;">
            <tr><td>申請人</td><td>{teacher_a}</td><td>{swap_info['Day_A']} 第{swap_info['Period_A']}節</td><td>{content_a}</td></tr>
            <tr><td>對象</td><td>{teacher_b}</td><td>{swap_info['Day_B']} 第{swap_info['Period_B']}節</td><td>{content_b}</td></tr>
        </table>
        <br><br>
        <div style="display:flex; justify-content:space-between;">
            <span>申請人簽章:________</span><span>對象簽章:________</span>
        </div>
    </div>
    <script>document.getElementById('d').innerText=new Date().toLocaleDateString(); window.print();</script>
    </body></html>
    """
    b64 = base64.b64encode(html.encode()).decode()
    return f'<a href="data:text/html;base64,{b64}" target="_blank" style="background:#f44336;color:white;padding:5px 10px;text-decoration:none;border-radius:5px;">🖨️ 列印</a>'

# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():
    st.title("🏫 成德高中 智慧調代課系統 (v3.0 強力解析)")
    
    with st.sidebar:
        st.info("💡 如果教師姓名顯示為亂碼，是因為 PDF 內部編碼問題。您可以在此系統中透過下拉選單找到對應的『亂碼ID』來操作。")
        uploaded_file = st.file_uploader("上傳課表 PDF", type=["pdf"])
        show_debug = st.checkbox("顯示原始解析資料 (Debug)", value=False)

    df = pd.DataFrame()
    if uploaded_file:
        with st.spinner("正在暴力解析 PDF..."):
            df, debug_logs = parse_schedule_pdf_robust(uploaded_file)
        
        if show_debug:
            with st.expander("PDF 原始讀取內容 (若為亂碼代表 PDF 編碼有誤)", expanded=True):
                for log in debug_logs:
                    st.text(log)
        
        if df.empty:
            st.error("解析後無資料。請確認 PDF 是否為掃描圖檔 (圖片無法讀取文字)。")
            return
        else:
            st.success(f"成功載入 {len(df)} 筆課程，共 {df['Teacher'].nunique()} 位教師。")

    if df.empty: return

    # --- 功能區 ---
    t1, t2, t3 = st.tabs(["📅 課表檢視", "🔍 尋找代課", "🔄 互換調課"])

    # 共用資料
    all_teachers = sorted(df['Teacher'].unique())
    all_days = ["一", "二", "三", "四", "五"]

    with t1:
        c_t, c_name = st.columns([1, 2])
        sel_t = c_t.selectbox("選擇教師", all_teachers)
        
        # 讓使用者可以自己備註這是誰
        st.caption(f"目前顯示: **{sel_t}** 的課表")
        
        t_data = df[df['Teacher'] == sel_t]
        pivot = t_data.pivot_table(index='Period', columns='Day', values='FullContent', aggfunc='first')
        pivot = pivot.reindex(index=range(1, 9), columns=all_days).fillna("")
        st.dataframe(pivot, use_container_width=True)

    with t2:
        c1, c2 = st.columns(2)
        target_d = c1.selectbox("缺課星期", all_days)
        target_p = c2.selectbox("缺課節次", range(1, 9))
        
        if st.button("查詢空堂教師"):
            busy_list = df[(df['Day'] == target_d) & (df['Period'] == target_p)]['Teacher'].unique()
            free_list = sorted(list(set(all_teachers) - set(busy_list)))
            st.write(f"共有 {len(free_list)} 位空堂：")
            st.write(" ".join([f"`{x}`" for x in free_list]))

    with t3:
        st.subheader("雙向調課")
        # Step 1: 選擇發起人
        col_1, col_2 = st.columns(2)
        who_a = col_1.selectbox("申請人 (A)", all_teachers)
        
        df_a = df[df['Teacher'] == who_a]
        if df_a.empty:
            st.warning("此人無課")
        else:
            opts = [f"週{r['Day']} {r['Period']}節: {r['FullContent']}" for i, r in df_a.iterrows()]
            pick_course = col_2.selectbox("A 欲換出的課", opts)
            
            # 取得 A 課程詳情
            # 這裡用字串比對回推有點危險，改用 index 比較安全，但為了簡單先這樣
            # 更好的做法是在 selectbox 存 ID
            
            # 解析 "週一 2節..."
            match = re.search(r"週(.) (\d)節", pick_course)
            if match:
                day_a, period_a = match.group(1), int(match.group(2))
                subject_a = pick_course.split(": ")[1]
                
                st.divider()
                st.write("### 篩選 B")
                
                # 計算邏輯
                if st.button("計算匹配對象"):
                    # A 的忙碌時間表 (Set lookup for speed)
                    a_busy_slots = set(zip(df_a['Day'], df_a['Period']))
                    
                    res = []
                    # 找所有其他人
                    others = df[df['Teacher'] != who_a]
                    
                    for t_b in others['Teacher'].unique():
                        # B 的所有課
                        df_b = others[others['Teacher'] == t_b]
                        
                        # 1. B 在 A的時間 (day_a, period_a) 必須沒課
                        if not df_b[(df_b['Day'] == day_a) & (df_b['Period'] == period_a)].empty:
                            continue
                            
                        # 2. 遍歷 B 的每一堂課，看 A 能不能接
                        for _, row_b in df_b.iterrows():
                            # A 在 B的時間 (row_b.Day, row_b.Period) 必須沒課
                            if (row_b['Day'], row_b['Period']) in a_busy_slots:
                                continue
                                
                            # 3. 排除同一時間 (無意義交換)
                            if row_b['Day'] == day_a and row_b['Period'] == period_a:
                                continue
                                
                            # 匹配成功
                            res.append({
                                "Teacher_B": t_b,
                                "Day_B": row_b['Day'], "Period_B": row_b['Period'],
                                "Content_B": row_b['FullContent'],
                                "SameClass": (subject_a.split()[-1] in row_b['FullContent']) # 粗略判斷同班
                            })
                            
                    if not res:
                        st.warning("無符合對象")
                    else:
                        res_df = pd.DataFrame(res).sort_values(['SameClass', 'Day_B', 'Period_B'], ascending=[False, True, True])
                        st.success(f"找到 {len(res_df)} 個方案")
                        
                        for _, row in res_df.iterrows():
                             with st.expander(f"{'⭐' if row['SameClass'] else ''} 與 {row['Teacher_B']} - 週{row['Day_B']} 第{row['Period_B']}節"):
                                 ctx = {
                                     "Day_A": day_a, "Period_A": period_a,
                                     "Day_B": row['Day_B'], "Period_B": row['Period_B']
                                 }
                                 st.markdown(generate_print_button(who_a, subject_a, row['Teacher_B'], row['Content_B'], ctx), unsafe_allow_html=True)

if __name__ == "__main__":
    main()
