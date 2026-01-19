import streamlit as st
import streamlit.components.v1 as components
import pdfplumber
import pandas as pd
import re
import json
from datetime import date, timedelta

# 設定頁面資訊
st.set_page_config(page_title="成德高中 智慧調代課系統 v7.0", layout="wide")

# ==========================================
# 1. 強力資料清洗區 (針對 114-2 課表優化)
# ==========================================

def clean_cell_text_v7(text):
    """
    v7 超級清洗：
    1. 移除亂碼 (如 کم)
    2. 移除時間格式 (避免誤判為課程)
    3. 移除排版雜字
    """
    if not isinstance(text, str) or not text:
        return ""
    
    # 移除特定亂碼與雜訊 (針對您的 PDF 片段)
    text = re.sub(r'[کم]', '', text) 
    text = text.replace("科目星", "").replace("時間班期", "").replace("時間", "").replace("班級", "")
    
    # 清除時間格式 (例如 08:00, 9:00, 16:10) - 避免這些被當成課程名稱
    text = re.sub(r'\d{1,2}[:：]\d{2}', '', text)
    
    # 清除「第 X 節」
    text = re.sub(r'第\s*[0-9一二三四五六七八]\s*節', '', text)
    
    # 清除常見無意義字詞
    noise_words = ["早自習", "午休", "上", "下", "午", "課程", "星期", "導師"]
    for w in noise_words:
        text = text.replace(w, "")
        
    # 處理換行：將換行轉為空白，並移除多餘空白
    # 您的片段顯示 "文\n國一3"，這裡將其合併為 "文 國一3"
    text = text.replace("\n", " ").strip()
    
    return text

def extract_class_and_course(content_str):
    """
    分離班級與課程 (例如 "文 國一3" -> 班級:國一3, 課程:文)
    """
    if not content_str: return "", ""
    
    # 抓取班級 (高/國 + 一二三 + 數字)
    # 增加對 "國-3" 這種格式的支援 (片段中有出現)
    class_pattern = re.search(r'([高國][一二三\-]\s*\d+)', content_str)
    
    if class_pattern:
        raw_class = class_pattern.group(1)
        class_code = raw_class.replace(" ", "").replace("-", "") # 統一格式: 國-3 -> 國3
        
        # 將班級移除，剩下的就是課程
        course_name = content_str.replace(raw_class, "").strip()
        course_name = course_name.replace("_", " ").strip() # 移除底線
        return class_code, course_name
    else:
        return "", content_str

@st.cache_data
def get_teacher_list(df):
    return sorted(df['teacher'].unique())

# ==========================================
# 2. PDF 解析核心 (v7 雙重引擎)
# ==========================================

def extract_tables_with_fallback(page):
    """
    智慧重試機制：
    1. 先嘗試預設解析 (依賴格線)
    2. 如果欄位過少 (可能格線消失導致黏欄)，改用 'text' 策略 (依賴文字間隙)
    """
    # 策略 A: 預設 (lines)
    tables = page.extract_tables()
    
    # 檢查策略 A 的品質
    is_bad = False
    if not tables:
        is_bad = True
    else:
        # 檢查第一張表，如果欄位數少於 5 (正常週課表至少要有 1欄時間 + 5欄星期 = 6欄)
        # 您的片段顯示 "二三" 黏在一起，這會導致欄位數變少
        max_cols = max([len(row) for row in tables[0] if row])
        if max_cols < 6: 
            is_bad = True
            
    if is_bad:
        # 策略 B: 強制使用文字間隙 (text strategy)
        # 這能解決 "二三" 黏在一起的問題
        tables = page.extract_tables(table_settings={
            "vertical_strategy": "text", 
            "horizontal_strategy": "text",
            "snap_tolerance": 5,
        })
        
    return tables

@st.cache_data
def parse_pdf_v7(uploaded_file):
    extracted_data = []
    teacher_classes_map = {} 
    
    # 時間關鍵字 (用於定位列)
    time_keywords = {
        "1": ["第一節", "08:00", "8:00"], "2": ["第二節", "09:00", "9:00"],
        "3": ["第三節", "10:00"], "4": ["第四節", "11:00"],
        "5": ["第五節", "13:00"], "6": ["第六節", "14:00"],
        "7": ["第七節", "15:00"], "8": ["第八節", "16:00"]
    }
    
    day_map_template = {"一": "一", "二": "二", "三": "三", "四": "四", "五": "五"}

    with pdfplumber.open(uploaded_file) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            
            # 抓取教師姓名
            teacher_name = f"Teacher_{i}"
            match = re.search(r"教師[:：\s]+(\S+)", text)
            if match:
                raw_name = match.group(1).strip()
                # 排除 "103導師" 這種後綴，只取名字 (例如 "陳慧敏")
                # 假設名字通常是 2-4 個字
                if len(raw_name) > 4 and "導師" in raw_name:
                     raw_name = raw_name.replace("導師", "")
                     # 取前幾個字當名字，剩下的可能是班級
                     teacher_name = raw_name[:3] 
                else:
                    teacher_name = raw_name
            
            if teacher_name not in teacher_classes_map:
                teacher_classes_map[teacher_name] = set()

            # 使用雙重引擎提取表格
            tables = extract_tables_with_fallback(page)
            
            if not tables: continue
            raw_table = tables[0] # 取第一張表
            
            col_map = {} 
            row_map = {} 

            # --- 步驟 A: 動態定位星期欄位 (Header Scout) ---
            # 掃描前 5 列，尋找 "一", "二", "三"...
            found_header = False
            for r_idx, row in enumerate(raw_table[:6]):
                for c_idx, cell in enumerate(row):
                    if not cell: continue
                    cell_str = str(cell).replace("\n", "").strip()
                    
                    # 檢查這一格是否有星期關鍵字
                    for k, v in day_map_template.items():
                        if k in cell_str:
                            col_map[c_idx] = v
                            found_header = True
                if found_header and len(col_map) >= 3: # 至少找到三天就可以當作標題列了
                    break
            
            # 如果完全找不到標題 (Fallback)，假設標準結構
            if not col_map:
                # 假設 Col 0=Time, Col 1=一, Col 2=二 ...
                # 根據您的片段，如果有偏移，這裡可能需要調整，但 Strategy B 通常會讓它回歸標準
                col_map = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}

            # --- 步驟 B: 定位節次列 ---
            for r_idx, row in enumerate(raw_table):
                # 把整列文字接起來檢查
                row_text = "".join([str(c) for c in row if c]).replace(" ", "").replace("\n", "")
                for p_key, kws in time_keywords.items():
                    for kw in kws:
                        if kw in row_text:
                            row_map[r_idx] = p_key
                            break
            
            # --- 步驟 C: 提取資料 ---
            for r_idx, period in row_map.items():
                for c_idx, day in col_map.items():
                    if c_idx < len(raw_table[r_idx]):
                        raw_cell = str(raw_table[r_idx][c_idx])
                        
                        # 清洗內容
                        clean_content = clean_cell_text_v7(raw_cell)
                        is_free = (len(clean_content) < 1) # 清洗後為空字串即為空堂
                        
                        extracted_data.append({
                            "teacher": teacher_name, "day": day, "period": period,
                            "content": clean_content, "is_free": is_free
                        })
                        
                        cls, _ = extract_class_and_course(clean_content)
                        if cls: teacher_classes_map[teacher_name].add(cls)

            # 補科目邏輯
            subject = "綜合"
            all_content = " ".join([d['content'] for d in extracted_data if d['teacher'] == teacher_name])
            subject_keywords = {
                "國語文": "國文", "英文": "英文", "數學": "數學", "物理": "自然", "化學": "自然", 
                "生物": "自然", "地科": "自然", "歷史": "社會", "地理": "社會", "公民": "社會",
                "體育": "健體", "美術": "藝能", "音樂": "藝能", "資訊": "科技", "生科": "科技",
                "全民國防": "國防", "護理": "健體", "語文": "國文"
            }
            detected_counts = {}
            for k, v in subject_keywords.items():
                if k in all_content: detected_counts[v] = detected_counts.get(v, 0) + 1
            if detected_counts: subject = max(detected_counts, key=detected_counts.get)
            
            for item in extracted_data:
                if item['teacher'] == teacher_name: item['subject'] = subject
                
    return extracted_data, teacher_classes_map

# ==========================================
# 3. 介面與功能 (維持 v6.5 的完整功能)
# ==========================================

@st.dialog("調課詳細資訊", width="large")
def show_schedule_popup(target_teacher, full_df, initiator_name, source_details, target_details):
    
    st.subheader("📆 設定調課日期")
    c1, c2 = st.columns(2)
    with c1:
        default_date_a = date.today() + timedelta(days=1)
        date_a = st.date_input(f"A老師 ({initiator_name}) 調課日期", value=default_date_a)
        str_date_a = date_a.strftime("%Y/%m/%d")
    with c2:
        default_date_b = date.today() + timedelta(days=2)
        date_b = st.date_input(f"B老師 ({target_teacher}) 調課日期", value=default_date_b)
        str_date_b = date_b.strftime("%Y/%m/%d")

    st.divider()

    st.subheader(f"📅 {target_teacher} 老師的週課表")
    t_df = full_df[full_df['teacher'] == target_teacher]
    
    if not t_df.empty:
        pivot_df = t_df.pivot(index='period', columns='day', values='content')
        pivot_df = pivot_df.reindex([str(i) for i in range(1, 9)])
        pivot_df = pivot_df.reindex(columns=["一", "二", "三", "四", "五"])

        def highlight_target(val, row_idx, col_name):
            if row_idx == target_details['period'] and col_name == target_details['day']:
                return 'background-color: #ffcccc; color: #8b0000; font-weight: bold; border: 2px solid red;'
            return ''

        styled_df = pivot_df.style.apply(lambda x: pd.DataFrame(
            [[highlight_target(x.iloc[i, j], pivot_df.index[i], pivot_df.columns[j]) 
              for j in range(len(pivot_df.columns))] 
             for i in range(len(pivot_df.index))],
            index=pivot_df.index, columns=pivot_df.columns
        ), axis=None)

        st.dataframe(styled_df, use_container_width=True)
        st.caption("🟥 紅色標記為您選定要交換的時段")
    
    st.divider()

    st.subheader("✉️ 調課邀請通知單")
    
    source_str = f"{str_date_a} (週{source_details['day']}) 第{source_details['period']}節 {source_details['class']} {source_details['course']}"
    target_str = f"{str_date_b} (週{target_details['day']}) 第{target_details['period']}節 {target_details['class']} {target_details['course']}"

    msg_template = f"""{target_teacher} 老師您好：

我是 {initiator_name}。
想詢問您 **{target_str}** 是否方便與我 **{source_str}** 調換課程？

再麻煩您確認意願，感謝幫忙！🙏"""

    st.text_area("預覽內容", value=msg_template, height=150)
    
    # 列印與關閉
    print_html = f"""
    <div style="font-family: 'Microsoft JhengHei', sans-serif; padding: 40px; border: 2px solid #333; max-width: 600px; margin: 0 auto;">
        <h2 style="text-align: center; border-bottom: 1px solid #aaa; padding-bottom: 10px;">成德高中 調課徵詢單</h2>
        <p style="font-size: 16px; margin-top: 30px;"><strong>致 {target_teacher} 老師：</strong></p>
        <p style="font-size: 16px; line-height: 1.8;">
            我是 <strong>{initiator_name}</strong>。<br><br>
            想詢問您 <strong>{target_str}</strong> <br>
            是否方便與我 <strong>{source_str}</strong> 調換課程？<br><br>
            再麻煩您確認意願，感謝幫忙！
        </p>
        <div style="margin-top: 50px; text-align: right;">
            <p>簽名：___________________</p>
            <p>日期：_____ 年 _____ 月 _____ 日</p>
        </div>
    </div>
    """

    js_code = f"""
    <script>
    function printSlip() {{
        var printContent = {json.dumps(print_html)};
        var win = window.open('', '', 'width=800,height=600');
        win.document.write('<html><head><title>調課通知單</title></head><body>');
        win.document.write(printContent);
        win.document.write('</body></html>');
        win.document.close();
        win.print();
    }}
    </script>
    <div style="display: flex; align-items: flex-start; height: 100%;">
        <button onclick="printSlip()" style="
            background-color: #ffffff; color: #31333F; padding: 0.25rem 0.75rem;
            border: 1px solid rgba(49, 51, 63, 0.2); border-radius: 0.25rem; 
            cursor: pointer; font-size: 1rem; line-height: 1.6;
            width: 100%; height: 40px; display: flex; align-items: center; justify-content: center;">
            🖨️ 直接列印通知單
        </button>
    </div>
    """
    
    c_print, c_close = st.columns([1, 1])
    with c_print: components.html(js_code, height=45) 
    with c_close:
        if st.button("關閉視窗", use_container_width=True, type="secondary"):
            st.session_state.table_reset_key += 1
            st.rerun()

def main():
    st.title("🏫 成德高中 智慧調代課系統 v7.0")
    
    if 'table_reset_key' not in st.session_state:
        st.session_state.table_reset_key = 0

    uploaded_file = st.sidebar.file_uploader("步驟 1: 上傳全校課表 PDF", type=["pdf"], key="uploader_v7")

    if uploaded_file:
        with st.spinner("正在進行智慧解析 (v7.0 雙重引擎版)..."):
            raw_data, teacher_classes_map = parse_pdf_v7(uploaded_file)
            
            if not raw_data:
                st.error("錯誤：無法從 PDF 中讀取有效課表。可能是檔案格式不支援或加密。")
                return
            
            df = pd.DataFrame(raw_data)
            df = df.groupby(['teacher', 'day', 'period'], as_index=False).agg({
                'content': lambda x: ' '.join(set([s for s in x if s])),
                'is_free': 'all',
                'subject': 'first'
            })
            df['is_free'] = df['content'].apply(lambda x: len(x.strip()) < 1)
            
            st.success(f"解析完成！資料庫包含 {len(df['teacher'].unique())} 位教師。")
            cached_teacher_list = get_teacher_list(df)
            
            # 班級清單排序
            all_classes = set()
            for cls_set in teacher_classes_map.values():
                all_classes.update(cls_set)
            def class_sort_key(s):
                match = re.search(r'([高國])([一二三])(\d+)', s)
                if match:
                    grade_map = {'一': 1, '二': 2, '三': 3}
                    return (match.group(1), grade_map.get(match.group(2), 9), int(match.group(3)))
                return (s, 0, 0)
            
            try:
                cached_class_list = sorted(list(all_classes), key=class_sort_key)
            except:
                cached_class_list = sorted(list(all_classes))

        tab1, tab2, tab3 = st.tabs(["📅 課表檢視", "🚑 代課尋找 (單向)", "🔄 調課互換 (雙向)"])

        with tab1:
            st.subheader("個別教師課表")
            t_select = st.selectbox("選擇教師", cached_teacher_list, key="t_sel_v7")
            if t_select:
                t_df = df[df['teacher'] == t_select]
                pivot_df = t_df.pivot(index='period', columns='day', values='content')
                pivot_df = pivot_df.reindex([str(i) for i in range(1, 9)])
                pivot_df = pivot_df.reindex(columns=["一", "二", "三", "四", "五"])
                st.dataframe(pivot_df, use_container_width=True)

        with tab2:
            st.subheader("尋找代課 (單向代課)")
            c1, c2, c3 = st.columns(3)
            q_day = c1.selectbox("星期", ["一", "二", "三", "四", "五"], key="q_d_v7")
            q_period = c2.selectbox("節次", [str(i) for i in range(1, 9)], key="q_p_v7")
            q_subject = c3.selectbox("科別篩選", ["全部"] + sorted(list(set(df['subject'].dropna()))), key="q_s_v7")

            mask = (df['day'] == q_day) & (df['period'] == q_period)
            frees = df[mask & (df['is_free'] == True)]
            if q_subject != "全部": frees = frees[frees['subject'] == q_subject]
            
            if not frees.empty:
                st.success(f"推薦名單 ({len(frees)}人)")
                st.dataframe(frees[['teacher', 'subject']], hide_index=True, use_container_width=True)
            else:
                st.warning("無空堂教師")

        with tab3:
            st.subheader("調課互換計算機 (A ⇄ B)")
            
            col_a, col_d, col_p = st.columns([2, 1, 1])
            initiator = col_a.selectbox("誰要調課 (A老師)?", cached_teacher_list, key="swap_who_v7")
            swap_day = col_d.selectbox("A 想調開的星期", ["一", "二", "三", "四", "五"], key="swap_day_v7")
            swap_period = col_p.selectbox("A 想調開的節次", [str(i) for i in range(1, 9)], key="swap_per_v7")

            st.markdown("👇 **進階篩選條件**")
            cf1, cf2, cf3, cf4 = st.columns(4)
            filter_teacher = cf1.selectbox("還課教師 (指定B)", ["不指定"] + cached_teacher_list, key="fil_t_v7")
            filter_day = cf2.selectbox("還課星期", ["不指定", "一", "二", "三", "四", "五"], key="fil_d_v7")
            filter_period = cf3.selectbox("還課節次", ["不指定"] + [str(i) for i in range(1, 9)], key="fil_p_v7")
            filter_class = cf4.selectbox("還課班級", ["不指定"] + cached_class_list, key="fil_c_v7")

            a_status = df[(df['teacher'] == initiator) & (df['day'] == swap_day) & (df['period'] == swap_period)]
            source_details = {'day': swap_day, 'period': swap_period, 'class': '無', 'course': '空堂'}
            target_class_code = None

            if not a_status.empty:
                content_now = a_status.iloc[0]['content']
                if content_now:
                    cls, crs = extract_class_and_course(content_now)
                    target_class_code = cls
                    source_details['class'] = cls if cls else "(未識別班級)"
                    source_details['course'] = crs if crs else content_now
                    st.info(f"目標調出：{initiator} - {source_details['class']} {source_details['course']} (星期{swap_day} 第{swap_period}節)")
                else:
                    st.warning("注意：您選擇的時段目前顯示為空堂。")
            
            st.divider()
            
            if 'swap_results_v7' not in st.session_state:
                st.session_state.swap_results_v7 = None

            if st.button("🔍 搜尋雙向互換方案", key="btn_swap_v7"):
                candidates_b_df = df[(df['day'] == swap_day) & (df['period'] == swap_period) & (df['is_free'] == True) & (df['teacher'] != initiator)]
                if filter_teacher != "不指定":
                    candidates_b_df = candidates_b_df[candidates_b_df['teacher'] == filter_teacher]

                a_free_keys = set(df[(df['teacher'] == initiator) & (df['is_free'] == True)]['day'] + "_" + df[(df['teacher'] == initiator) & (df['is_free'] == True)]['period'])

                swap_options = []
                for b_name in candidates_b_df['teacher'].unique():
                    b_subset = df[df['teacher'] == b_name]
                    b_subj = b_subset.iloc[0]['subject']
                    
                    for _, row in b_subset[b_subset['is_free'] == False].iterrows():
                        if filter_day != "不指定" and row['day'] != filter_day: continue
                        if filter_period != "不指定" and row['period'] != filter_period: continue
                        
                        if (row['day'] + "_" + row['period']) in a_free_keys:
                            b_class, b_course = extract_class_and_course(row['content'])
                            if filter_class != "不指定" and b_class != filter_class: continue

                            tag = "⭐同班互調" if (target_class_code and b_class and target_class_code == b_class) else ""
                            swap_options.append({
                                "標記": tag, "教師姓名": b_name, "科目": b_subj,
                                "還課星期": row['day'], "還課節次": row['period'],
                                "還課班級": b_class, "還課課程": b_course,
                                "_sort_idx": 0 if tag else 1
                            })

                if swap_options:
                    res_df = pd.DataFrame(swap_options).sort_values(by=['_sort_idx', '還課星期', '還課節次']).drop(columns=['_sort_idx'])
                    st.session_state.swap_results_v7 = res_df
                else:
                    st.session_state.swap_results_v7 = pd.DataFrame()

            if st.session_state.swap_results_v7 is not None and not st.session_state.swap_results_v7.empty:
                st.success(f"找到 {len(st.session_state.swap_results_v7)} 個互換方案！請點擊查看 👇")
                
                dynamic_key = f"swap_table_v7_{st.session_state.table_reset_key}"
                
                event = st.dataframe(
                    st.session_state.swap_results_v7, 
                    hide_index=True, 
                    use_container_width=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    key=dynamic_key
                )
                
                if len(event.selection.rows) > 0:
                    row_data = st.session_state.swap_results_v7.iloc[event.selection.rows[0]]
                    target_details = {'day': row_data['還課星期'], 'period': row_data['還課節次'], 'class': row_data['還課班級'], 'course': row_data['還課課程']}
                    show_schedule_popup(row_data['教師姓名'], df, initiator, source_details, target_details)
            elif st.session_state.swap_results_v7 is not None and st.session_state.swap_results_v7.empty:
                if st.session_state.get('btn_swap_v7'):
                    st.warning("無符合條件的互換人選。")

if __name__ == "__main__":
    main()
