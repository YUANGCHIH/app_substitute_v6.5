import streamlit as st
import pdfplumber
import pandas as pd
import re
import base64
import traceback

# ---------------------------------------------------------
# 0. 全局設定
# ---------------------------------------------------------
st.set_page_config(
    page_title="成德高中 智慧調代課系統 (安全版)",
    page_icon="🛡️",
    layout="wide"
)

# 初始化 Session State (用於儲存修正後的姓名)
if 'name_corrections' not in st.session_state:
    st.session_state['name_corrections'] = {}

# ---------------------------------------------------------
# 1. 核心邏輯：PDF 解析
# ---------------------------------------------------------

def clean_teacher_name(text):
    """
    從字串中嘗試提取教師姓名，若失敗回傳 None
    """
    if not text: return None
    
    # 模式 1: "教師:陳慧敏"
    match = re.search(r"教師[:：\s]*([^\s]+)", text)
    if match:
        name = match.group(1)
        # 過濾掉數字和常見職稱
        name = re.sub(r'[0-9a-zA-Z導師]+', '', name)
        if len(name) > 0:
            return name
            
    # 模式 2: "教師 陳慧敏" (無冒號)
    match2 = re.search(r"教師\s+([\u4e00-\u9fa5]{2,4})", text)
    if match2:
        return match2.group(1)

    return None

def parse_pdf_safely(uploaded_file):
    """
    安全解析 PDF，即使部分頁面失敗也會繼續執行。
    """
    all_data = []
    logs = []
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                try:
                    # 使用 layout=True 保留視覺間距，這對判斷空堂很重要
                    text = page.extract_text(layout=True)
                    if not text:
                        logs.append(f"⚠️ 第 {page_num} 頁：無法讀取文字 (可能是掃描圖檔)")
                        continue

                    # 1. 抓取教師姓名
                    # 先看前幾行
                    header_lines = text.split('\n')[:10]
                    header_text = " ".join(header_lines)
                    teacher_name = clean_teacher_name(header_text)
                    
                    if not teacher_name:
                        # 找不到名字，給予代號，讓使用者稍後修正
                        teacher_name = f"未知教師_P{page_num}"
                        logs.append(f"⚠️ 第 {page_num} 頁：找不到教師姓名，暫名為 '{teacher_name}'")

                    # 2. 解析課程 (行掃描法)
                    lines = text.split('\n')
                    for line in lines:
                        line = line.strip()
                        if not line: continue
                        
                        # 判斷是否為課程行：以 1~9 數字開頭
                        # Regex: 開頭是數字，後面接著空格 (避免抓到 103班級 之類的)
                        match_period = re.match(r'^([1-9])\s+', line)
                        
                        if match_period:
                            period = int(match_period.group(1))
                            
                            # 利用連續空白切割欄位
                            parts = re.split(r'\s{2,}', line)
                            
                            # parts[0] 是節次 (例如 "1 08:00")
                            # parts[1:] 是 星期一 ~ 五 的內容
                            content_parts = parts[1:]
                            
                            days = ["一", "二", "三", "四", "五"]
                            
                            # 安全寫入：避免 Index Out of Bounds
                            for d_idx, content in enumerate(content_parts):
                                if d_idx < 5: # 只取前5欄 (一~五)
                                    content = content.strip()
                                    # 忽略純符號
                                    if content and content not in ['.', ',', '-']:
                                        # 簡單拆分 科目/班級
                                        # 假設格式 "國語 101" -> 最後一個是班級
                                        sub_tokens = content.split()
                                        if len(sub_tokens) >= 2:
                                            subj = " ".join(sub_tokens[:-1])
                                            cls = sub_tokens[-1]
                                        else:
                                            subj = content
                                            cls = "?"
                                        
                                        all_data.append({
                                            "RawTeacher": teacher_name, # 原始讀到的名字 (可能是亂碼)
                                            "Day": days[d_idx],
                                            "Period": period,
                                            "Subject": subj,
                                            "Class": cls,
                                            "FullContent": content
                                        })

                except Exception as e_page:
                    logs.append(f"❌ 第 {page_num} 頁解析失敗: {str(e_page)}")
                    continue # 繼續下一頁

        return pd.DataFrame(all_data), logs

    except Exception as e_file:
        return pd.DataFrame(), [f"❌ 檔案讀取嚴重錯誤: {str(e_file)}"]

# ---------------------------------------------------------
# UI 輔助元件
# ---------------------------------------------------------

def get_print_link(t_a, c_a, t_b, c_b, info):
    """產生列印按鈕 HTML"""
    try:
        html = f"""
        <html>
        <body style="font-family: Microsoft JhengHei, sans-serif; padding: 40px;">
            <h2 style="text-align: center;">成德高中 調課申請單</h2>
            <p>列印日期: <script>document.write(new Date().toLocaleDateString())</script></p>
            <table border="1" cellpadding="10" style="width: 100%; border-collapse: collapse; text-align: center;">
                <tr style="background-color: #f0f0f0;">
                    <th>角色</th><th>教師</th><th>原定時間</th><th>科目/班級</th><th>異動</th>
                </tr>
                <tr>
                    <td>申請人</td><td>{t_a}</td>
                    <td>{info['Day_A']} 第{info['Period_A']}節</td>
                    <td>{c_a}</td><td>轉給 {t_b}</td>
                </tr>
                <tr>
                    <td>受理人</td><td>{t_b}</td>
                    <td>{info['Day_B']} 第{info['Period_B']}節</td>
                    <td>{c_b}</td><td>轉給 {t_a}</td>
                </tr>
            </table>
            <br><br><br>
            <div style="display: flex; justify-content: space-around;">
                <span>申請人簽章：__________________</span>
                <span>受理人簽章：__________________</span>
                <span>教學組長：__________________</span>
            </div>
            <script>window.print();</script>
        </body>
        </html>
        """
        b64 = base64.b64encode(html.encode('utf-8')).decode()
        return f'<a href="data:text/html;base64,{b64}" target="_blank" style="display:inline-block; padding:8px 16px; background-color:#FF4B4B; color:white; text-decoration:none; border-radius:4px; font-weight:bold;">🖨️ 列印/預覽通知單</a>'
    except Exception as e:
        return f"<span>產生列印按鈕失敗: {e}</span>"

# ---------------------------------------------------------
# 主程式
# ---------------------------------------------------------

def main():
    st.title("🛡️ 成德高中 智慧調代課系統 (Safe Mode)")
    st.markdown("---")

    # 1. 檔案上傳區
    with st.sidebar:
        st.header("1. 系統設定")
        uploaded_file = st.file_uploader("上傳課表 PDF", type=["pdf"])
        
        show_logs = st.checkbox("顯示解析紀錄", value=False)
        
        # 資料容器
        df = pd.DataFrame()
        
        if uploaded_file:
            with st.spinner("正在安全解析 PDF..."):
                df, logs = parse_pdf_safely(uploaded_file)
            
            if show_logs and logs:
                with st.expander("解析紀錄 (Logs)"):
                    for log in logs:
                        st.text(log)
            
            if df.empty:
                st.error("❌ 無法解析出任何課程資料。請確認 PDF 格式或是否為純圖片。")
                return # 停止執行
            
            st.success(f"✅ 成功讀取 {len(df)} 筆資料")
        else:
            st.info("請先上傳 PDF 檔案")
            return

    # 2. 教師姓名修正 (處理亂碼)
    raw_teachers = sorted(df['RawTeacher'].unique())
    
    # 應用修正後的名稱
    # 建立一個新的欄位 'Teacher'，預設等於 'RawTeacher'
    df['Teacher'] = df['RawTeacher'].map(lambda x: st.session_state['name_corrections'].get(x, x))
    
    # 取得修正後的教師列表
    final_teachers = sorted(df['Teacher'].unique())

    with st.sidebar:
        with st.expander("✏️ 修正教師姓名 (解決亂碼)"):
            st.caption("如果選單中有亂碼 (如 '繽奸禎')，請在此修正：")
            target_raw = st.selectbox("選擇要修正的原始名稱", raw_teachers)
            new_name = st.text_input("輸入正確姓名", value=st.session_state['name_corrections'].get(target_raw, target_raw))
            
            if st.button("確認修正"):
                st.session_state['name_corrections'][target_raw] = new_name
                st.rerun() # 重新整理頁面以套用

    # 3. 主功能 Tabs
    try:
        t1, t2, t3 = st.tabs(["📅 課表檢視", "🔍 尋找代課", "🔄 互換調課"])

        # --- Tab 1: 課表 ---
        with t1:
            st.subheader("教師週課表")
            selected_t = st.selectbox("請選擇教師", final_teachers)
            
            # 過濾並製作課表
            t_df = df[df['Teacher'] == selected_t]
            if not t_df.empty:
                pivot = t_df.pivot_table(index='Period', columns='Day', values='FullContent', aggfunc='first')
                # 補齊 1-8 節與 星期一~五
                all_periods = list(range(1, 9))
                all_days = ["一", "二", "三", "四", "五"]
                pivot = pivot.reindex(index=all_periods, columns=all_days).fillna("")
                st.dataframe(pivot, use_container_width=True)
            else:
                st.warning("無該教師資料")

        # --- Tab 2: 代課 ---
        with t2:
            st.subheader("空堂教師查詢")
            c1, c2 = st.columns(2)
            day = c1.selectbox("缺課星期", ["一", "二", "三", "四", "五"])
            period = c2.selectbox("缺課節次", range(1, 9))
            
            if st.button("查詢"):
                # 找出該時段有課的人
                busy_list = df[(df['Day'] == day) & (df['Period'] == period)]['Teacher'].unique()
                # 所有人 - 有課的人 = 空堂的人
                free_list = sorted(list(set(final_teachers) - set(busy_list)))
                
                st.write(f"**星期{day} 第{period}節，共有 {len(free_list)} 位空堂教師：**")
                st.markdown(" ".join([f"`{t}`" for t in free_list]))

        # --- Tab 3: 調課 ---
        with t3:
            st.subheader("雙向調課計算機")
            
            col_a, col_pick = st.columns(2)
            who_a = col_a.selectbox("申請人 (A)", final_teachers, key="who_a")
            
            # 取得 A 的課程
            df_a = df[df['Teacher'] == who_a]
            if df_a.empty:
                st.warning("此教師目前無課程資料。")
            else:
                # 製作選項: "週一 1節: 國語 101"
                # 使用 index 作為 key，避免字串解析錯誤
                df_a = df_a.sort_values(['Day', 'Period']).reset_index(drop=True)
                
                # 建立一個選項 map { "顯示字串": index }
                options_map = {f"週{r['Day']} 第{r['Period']}節: {r['FullContent']}": i for i, r in df_a.iterrows()}
                selected_opt_str = col_pick.selectbox("A 欲換出的課程", list(options_map.keys()))
                
                # 取得選中的課程資料 row
                selected_idx = options_map[selected_opt_str]
                course_a = df_a.iloc[selected_idx]
                
                st.divider()
                
                if st.button("計算匹配方案"):
                    # 準備運算
                    day_a = course_a['Day']
                    period_a = course_a['Period']
                    class_a = course_a['Class']
                    
                    # A 的忙碌時間 set (加速查找)
                    a_busy_set = set(zip(df_a['Day'], df_a['Period']))
                    
                    matches = []
                    
                    # 篩選潛在對象 (非 A 的所有人)
                    # 為了效能，先過濾出 B 在 (day_a, period_a) 是空堂的人
                    # 找出在 (day_a, period_a) 有課的人
                    busy_at_a_time = df[(df['Day'] == day_a) & (df['Period'] == period_a)]['Teacher'].unique()
                    
                    # 潛在 B 必須不在 busy_at_a_time 裡
                    potential_b_teachers = set(final_teachers) - set(busy_at_a_time) - {who_a}
                    
                    # 只搜尋這些人的課程
                    df_others = df[df['Teacher'].isin(potential_b_teachers)]
                    
                    for _, row_b in df_others.iterrows():
                        # 邏輯檢查:
                        # 1. 我們已經確定 B 在 (day_a, period_a) 是空堂 (由上面的 filter 保證)
                        # 2. 檢查 A 在 B 的目標時間 (row_b.Day, row_b.Period) 是否為空堂?
                        if (row_b['Day'], row_b['Period']) in a_busy_set:
                            continue # A 沒空，無法接
                        
                        # 3. 避免換同一時間的課
                        if row_b['Day'] == day_a and row_b['Period'] == period_a:
                            continue

                        # 匹配成功
                        is_same_class = (row_b['Class'] == class_a and class_a != "?")
                        matches.append({
                            "Teacher_B": row_b['Teacher'],
                            "Day_B": row_b['Day'], 
                            "Period_B": row_b['Period'],
                            "Subject_B": row_b['Subject'],
                            "Class_B": row_b['Class'],
                            "FullContent_B": row_b['FullContent'],
                            "IsSameClass": is_same_class
                        })
                    
                    if not matches:
                        st.info("找不到符合互換條件的對象。")
                    else:
                        # 轉為 DataFrame 展示
                        res_df = pd.DataFrame(matches)
                        res_df = res_df.sort_values(['IsSameClass', 'Day_B', 'Period_B'], ascending=[False, True, True])
                        
                        st.success(f"找到 {len(res_df)} 個可行方案！")
                        
                        for _, match in res_df.iterrows():
                            # 顯示卡片
                            icon = "⭐ 同班互換 | " if match['IsSameClass'] else ""
                            label = f"{icon}{match['Teacher_B']} - 週{match['Day_B']} 第{match['Period_B']}節 ({match['Subject_B']} {match['Class_B']})"
                            
                            with st.expander(label):
                                c_info, c_act = st.columns([3, 1])
                                with c_info:
                                    st.write(f"1. **{who_a}** 原課 (週{day_a} {period_a}節) ➔ 給 **{match['Teacher_B']}**")
                                    st.write(f"2. **{match['Teacher_B']}** 原課 (週{match['Day_B']} {match['Period_B']}節) ➔ 給 **{who_a}**")
                                with c_act:
                                    # 生成按鈕
                                    info_dict = {
                                        "Day_A": day_a, "Period_A": period_a,
                                        "Day_B": match['Day_B'], "Period_B": match['Period_B']
                                    }
                                    btn_html = get_print_link(
                                        who_a, course_a['FullContent'],
                                        match['Teacher_B'], match['FullContent_B'],
                                        info_dict
                                    )
                                    st.markdown(btn_html, unsafe_allow_html=True)

    except Exception as e_main:
        st.error("程式執行中發生未預期的錯誤，請聯絡管理員或檢查 PDF 格式。")
        st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
