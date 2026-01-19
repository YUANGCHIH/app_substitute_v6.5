import streamlit as st
import streamlit.components.v1 as components
import pdfplumber
import pandas as pd
import re
import json
from datetime import date, timedelta

# 設定頁面資訊
st.set_page_config(page_title="成德高中 智慧調代課系統 v8.0", layout="wide")

# ==========================================
# 1. 核心邏輯：暴力座標解析 (Grid Force)
# ==========================================

def clean_text_v8(text):
    """
    v8 清洗邏輯：針對幽靈文字與亂碼進行強力過濾
    """
    if not text: return ""
    # 移除特定干擾亂碼
    text = re.sub(r'[کمکر]', '', text)
    # 移除重複的換行與空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_virtual_grid(page):
    """
    建立虛擬座標網格：
    不依賴表格線，而是根據「星期」和「時間」的文字位置來推算欄位邊界。
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
    
    # 1. 找尋欄位 (X軸) - 定位星期
    # 預設寬度 (如果找不到字)
    width = page.width
    col_boundaries = [] # 儲存 (x0, x1, "星期X")
    
    # 搜尋關鍵字位置
    header_keywords = {"一": "一", "二": "二", "三": "三", "四": "四", "五": "五"}
    found_headers = []
    
    for w in words:
        # 只看頁面上方 (Header區域)
        if w['top'] < 150: 
            txt = w['text'].strip()
            for k, v in header_keywords.items():
                if k in txt and v not in [h['day'] for h in found_headers]:
                    found_headers.append({"day": v, "x0": w['x0'], "x1": w['x1']})
    
    # 排序並補全邊界
    found_headers.sort(key=lambda x: x['x0'])
    
    # 如果抓不到標題，使用「盲猜」模式 (假設標準A4分佈)
    if len(found_headers) < 3:
        # 假設左邊 15% 是標題，剩下平均分給五天
        start_x = width * 0.15
        step = (width - start_x) / 5
        final_cols = []
        days = ["一", "二", "三", "四", "五"]
        for i, d in enumerate(days):
            x0 = start_x + (i * step)
            x1 = x0 + step
            final_cols.append({"day": d, "x0": x0, "x1": x1})
    else:
        # 根據抓到的字，推算中間的分隔線
        final_cols = []
        for i in range(len(found_headers)):
            current = found_headers[i]
            # 左邊界：如果是第一個，取字左邊一點；否則取跟上一個的中點
            if i == 0:
                left_bound = current['x0'] - 20
            else:
                left_bound = (found_headers[i-1]['x1'] + current['x0']) / 2
            
            # 右邊界：如果是最後一個，取頁面邊緣；否則取跟下一個的中點
            if i == len(found_headers) - 1:
                right_bound = width
            else:
                right_bound = (current['x1'] + found_headers[i+1]['x0']) / 2
                
            final_cols.append({"day": current['day'], "x0": left_bound, "x1": right_bound})

    # 2. 找尋列 (Y軸) - 定位節次
    # 搜尋時間關鍵字 (08:, 09: ...)
    row_boundaries = []
    time_map = {
        "1": ["08:", "8:"], "2": ["09:", "9:"], "3": ["10:"], "4": ["11:"],
        "5": ["13:", "12:"], "6": ["14:"], "7": ["15:"], "8": ["16:"]
    }
    
    found_rows = []
    for w in words:
        txt = w['text'].replace(" ", "")
        for p, kws in time_map.items():
            for kw in kws:
                if kw in txt and p not in [r['period'] for r in found_rows]:
                    found_rows.append({"period": p, "top": w['top'], "bottom": w['bottom']})
                    
    found_rows.sort(key=lambda x: x['top'])
    
    # 如果抓不到時間，使用「盲猜」模式
    if len(found_rows) < 4:
        # 假設從 Y=150 開始，每隔 50 單位一節
        start_y = 150
        step_y = 60 # 根據經驗估計
        final_rows = []
        for i in range(1, 9):
            top = start_y + ((i-1) * step_y)
            # 第五節(午休後)通常會空比較大，加一點偏移
            if i >= 5: top += 30 
            bottom = top + step_y
            final_rows.append({"period": str(i), "top": top, "bottom": bottom})
    else:
        final_rows = []
        for i in range(len(found_rows)):
            curr = found_rows[i]
            # 上邊界
            if i == 0: top = curr['top'] - 10
            else: top = (found_rows[i-1]['bottom'] + curr['top']) / 2
            
            # 下邊界
            if i == len(found_rows) - 1: bottom = curr['bottom'] + 60
            else: bottom = (curr['bottom'] + found_rows[i+1]['top']) / 2
            
            final_rows.append({"period": curr['period'], "top": top, "bottom": bottom})

    return final_cols, final_rows, words

def extract_class_and_course(content_str):
    if not content_str: return "", ""
    # 移除常見雜訊
    content_str = content_str.replace("科目星", "").replace("時間", "")
    
    # 抓取班級 (高/國 + 一二三 + 數字)
    class_pattern = re.search(r'([高國][一二三\-]\s*\d+)', content_str)
    if class_pattern:
        raw_class = class_pattern.group(1)
        class_code = raw_class.replace(" ", "").replace("-", "")
        course_name = content_str.replace(raw_class, "").strip()
        return class_code, course_name
    else:
        return "", content_str

@st.cache_data
def parse_pdf_v8(uploaded_file):
    extracted_data = []
    teacher_classes_map = {} 

    with pdfplumber.open(uploaded_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # 1. 抓取教師姓名 (嘗試多種位置)
            text = page.extract_text() or ""
            teacher_name = f"Teacher_{i}"
            
            # 策略A: 正規表達式抓取
            match = re.search(r"教師[:：\s]+(\S+)", text)
            if match:
                raw_name = match.group(1).strip()
                teacher_name = re.sub(r'(導師|老師|\d+)', '', raw_name)
            
            if teacher_name not in teacher_classes_map:
                teacher_classes_map[teacher_name] = set()

            # 2. 執行「虛擬網格」座標分析
            cols, rows, all_words = get_virtual_grid(page)
            
            # 3. 將每個字分配到網格中
            # 建立一個暫存的 grid buckets
            grid_buckets = {} # Key: "day_period", Value: list of strings
            
            for w in all_words:
                w_cx = (w['x0'] + w['x1']) / 2 # 字的中心 X
                w_cy = (w['top'] + w['bottom']) / 2 # 字的中心 Y
                
                # 判斷屬於哪一欄 (星期)
                matched_day = None
                for col in cols:
                    if col['x0'] <= w_cx <= col['x1']:
                        matched_day = col['day']
                        break
                
                # 判斷屬於哪一列 (節次)
                matched_period = None
                for row in rows:
                    if row['top'] <= w_cy <= row['bottom']:
                        matched_period = row['period']
                        break
                
                # 只有當文字同時落在有效的行列內，才算課程資料
                if matched_day and matched_period:
                    key = f"{matched_day}_{matched_period}"
                    if key not in grid_buckets: grid_buckets[key] = []
                    grid_buckets[key].append(w['text'])

            # 4. 整理資料
            for r in rows:
                p = r['period']
                for c in cols:
                    d = c['day']
                    key = f"{d}_{p}"
                    
                    raw_content_list = grid_buckets.get(key, [])
                    # 合併文字並清洗
                    full_text = " ".join(raw_content_list)
                    clean_content = clean_text_v8(full_text)
                    
                    # 過濾掉如果是時間或標題被誤抓進來
                    if re.match(r'^\d{2}:\d{2}$', clean_content): clean_content = ""
                    if clean_content in ["一", "二", "三", "四", "五"]: clean_content = ""

                    is_free = (len(clean_content) < 1)
                    
                    extracted_data.append({
                        "teacher": teacher_name, "day": d, "period": p,
                        "content": clean_content, "is_free": is_free
                    })
                    
                    cls, _ = extract_class_and_course(clean_content)
                    if cls: teacher_classes_map[teacher_name].add(cls)

            # 補科目 (同 v7 邏輯)
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
# 3. 介面 (維持完整功能)
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
    
    source_str = f"{str_date_a} (週{source_details['day']}) 第{source_details['period']}節 {source_details['class']} {source_details['course']}"
    target_str = f"{str_date_b} (週{target_details['day']}) 第{target_details['period']}節 {target_details['class']} {target_details['course']}"

    msg_template = (
        f"{target_teacher} 老師您好：\n\n"
        f"我是 {initiator_name}。\n"
        f"想詢問您 **{target_str}** 是否方便與我 **{source_str}** 調換課程？\n\n"
        "再麻煩您確認意願，感謝幫忙！🙏"
    )

    st.subheader("✉️ 調課邀請通知單")
    st.text_area("預覽內容", value=msg_template, height=150)
    
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
    st.title("🏫 成德高中 智慧調代課系統 v8.0 (暴力座標版)")
    st.caption("專門解決：幽靈文字、無格線、亂碼干擾的 PDF 課表")
    
    if 'table_reset_key' not in st.session_state:
        st.session_state.table_reset_key = 0

    uploaded_file = st.sidebar.file_uploader("步驟 1: 上傳全校課表 PDF", type=["pdf"], key="uploader_v8")

    if uploaded_file:
        with st.spinner("正在進行暴力座標定位 (Grid Force) 解析..."):
            raw_data, teacher_classes_map = parse_pdf_v8(uploaded_file)
            
            # 安全檢查
            if not raw_data:
                st.error("錯誤：即使使用暴力座標定位，仍無法讀取文字。這份 PDF 極可能是純圖片 (掃描檔)。請先使用 OCR 軟體轉成文字檔後再上傳。")
                return
            
            df = pd.DataFrame(raw_data)
            # 資料聚合 (同一格可能有多個字塊，需合併)
            df = df.groupby(['teacher', 'day', 'period'], as_index=False).agg({
                'content': lambda x: ' '.join(set([str(s) for s in x if s])),
                'is_free': 'all',
                'subject': 'first'
            })
            df['is_free'] = df['content'].apply(lambda x: len(x.strip()) < 1)
            
            st.success(f"解析成功！已重建 {len(df['teacher'].unique())} 位教師的課表網格。")
            cached_teacher_list = sorted(df['teacher'].unique())
            
            all_classes = set()
            for cls_set in teacher_classes_map.values():
                all_classes.update(cls_set)
            def class_sort_key(s):
                match = re.search(r'([高國])([一二三])(\d+)', s)
                if match:
                    grade_map = {'一': 1, '二': 2, '三': 3}
                    return (match.group(1), grade_map.get(match.group(2), 9), int(match.group(3)))
                return (s, 0, 0)
            cached_class_list = sorted(list(all_classes), key=class_sort_key)

        tab1, tab2, tab3 = st.tabs(["📅 課表檢視", "🚑 代課尋找", "🔄 調課互換"])

        with tab1:
            st.subheader("個別教師課表")
            t_select = st.selectbox("選擇教師", cached_teacher_list, key="t_sel_v8")
            if t_select:
                t_df = df[df['teacher'] == t_select]
                pivot_df = t_df.pivot(index='period', columns='day', values='content')
                # 確保 1-8 節都有顯示，即使是空堂
                pivot_df = pivot_df.reindex([str(i) for i in range(1, 9)])
                pivot_df = pivot_df.reindex(columns=["一", "二", "三", "四", "五"])
                st.dataframe(pivot_df, use_container_width=True)

        with tab2:
            st.subheader("尋找代課 (單向代課)")
            c1, c2, c3 = st.columns(3)
            q_day = c1.selectbox("星期", ["一", "二", "三", "四", "五"], key="q_d_v8")
            q_period = c2.selectbox("節次", [str(i) for i in range(1, 9)], key="q_p_v8")
            q_subject = c3.selectbox("科別篩選", ["全部"] + sorted(list(set(df['subject'].dropna()))), key="q_s_v8")

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
            initiator = col_a.selectbox("誰要調課 (A老師)?", cached_teacher_list, key="swap_who_v8")
            swap_day = col_d.selectbox("A 想調開的星期", ["一", "二", "三", "四", "五"], key="swap_day_v8")
            swap_period = col_p.selectbox("A 想調開的節次", [str(i) for i in range(1, 9)], key="swap_per_v8")

            st.markdown("👇 **進階篩選條件**")
            cf1, cf2, cf3, cf4 = st.columns(4)
            filter_teacher = cf1.selectbox("還課教師 (指定B)", ["不指定"] + cached_teacher_list, key="fil_t_v8")
            filter_day = cf2.selectbox("還課星期", ["不指定", "一", "二", "三", "四", "五"], key="fil_d_v8")
            filter_period = cf3.selectbox("還課節次", ["不指定"] + [str(i) for i in range(1, 9)], key="fil_p_v8")
            filter_class = cf4.selectbox("還課班級", ["不指定"] + cached_class_list, key="fil_c_v8")

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
            
            st.divider()
            
            if 'swap_results_v8' not in st.session_state:
                st.session_state.swap_results_v8 = None

            if st.button("🔍 搜尋雙向互換方案", key="btn_swap_v8"):
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
                    st.session_state.swap_results_v8 = res_df
                else:
                    st.session_state.swap_results_v8 = pd.DataFrame()

            if st.session_state.swap_results_v8 is not None and not st.session_state.swap_results_v8.empty:
                st.success(f"找到 {len(st.session_state.swap_results_v8)} 個互換方案！")
                event = st.dataframe(st.session_state.swap_results_v8, hide_index=True, use_container_width=True, selection_mode="single-row", on_select="rerun", key=f"swap_table_v8_{st.session_state.table_reset_key}")
                
                if len(event.selection.rows) > 0:
                    row_data = st.session_state.swap_results_v8.iloc[event.selection.rows[0]]
                    target_details = {'day': row_data['還課星期'], 'period': row_data['還課節次'], 'class': row_data['還課班級'], 'course': row_data['還課課程']}
                    show_schedule_popup(row_data['教師姓名'], df, initiator, source_details, target_details)
            elif st.session_state.swap_results_v8 is not None and st.session_state.swap_results_v8.empty:
                if st.session_state.get('btn_swap_v8'):
                    st.warning("無符合條件的互換人選。")

if __name__ == "__main__":
    main()
