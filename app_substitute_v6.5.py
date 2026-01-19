import streamlit as st
import streamlit.components.v1 as components
import pdfplumber
import pandas as pd
import re
import json
from datetime import date, timedelta

# 設定頁面資訊
st.set_page_config(page_title="成德高中 智慧調代課系統 v8.1", layout="wide")

# ==========================================
# 1. 核心邏輯：暴力座標解析與姓名獵捕
# ==========================================

def clean_text_v8(text):
    """v8 清洗邏輯"""
    if not text: return ""
    text = re.sub(r'[کمکر]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_teacher_name_robust(page, page_index):
    """
    [v8.1 新增] 強力姓名獵捕功能
    不依賴文字流順序，而是使用座標 (X, Y) 來尋找位於「教師」右邊的字
    """
    # 1. 嘗試簡單的 Regex (針對排版正常的頁面)
    text = page.extract_text() or ""
    # 匹配 "教師:陳大文" 或 "教師 陳大文" (排除 "導師" 字眼)
    match = re.search(r"教師[:：\s]*([\u4e00-\u9fa5]{2,4})", text)
    if match:
        name = match.group(1)
        if "導師" not in name:
            return name

    # 2. 座標獵捕法 (針對排版混亂的頁面)
    try:
        words = page.extract_words(keep_blank_chars=True)
        # 只看頁面頂端 (Y < 150)
        header_words = [w for w in words if w['top'] < 200]
        # 依照 Y 軸 (由上而下) 再 X 軸 (由左而右) 排序
        header_words.sort(key=lambda x: (int(x['top']/10), x['x0']))

        anchor_idx = -1
        # 尋找錨點 "教師"
        for i, w in enumerate(header_words):
            if "教師" in w['text']:
                anchor_idx = i
                break
        
        if anchor_idx != -1:
            # 找到錨點後，開始往後(往右)抓字
            anchor_w = header_words[anchor_idx]
            candidate_text = ""
            
            # 如果錨點本身就包含名字 (例如 "教師:陳慧敏")
            if len(anchor_w['text']) > 3:
                candidate_text = anchor_w['text']
            else:
                # 否則抓取它右邊的字 (允許一點 Y 軸誤差)
                for i in range(anchor_idx + 1, len(header_words)):
                    next_w = header_words[i]
                    # 如果 Y 軸差太多，表示換行了，停止
                    if abs(next_w['top'] - anchor_w['top']) > 20: 
                        break
                    # 串接文字
                    candidate_text += next_w['text']

            # 清洗名字
            # 移除 "教師", ":", "導師", "103" 等雜訊
            clean_name = re.sub(r'[教師:：\s\d]', '', candidate_text)
            clean_name = clean_name.replace("導師", "")
            
            # 如果抓到的名字長度合理 (2~4個中文字)
            if 1 < len(clean_name) <= 5:
                return clean_name

    except Exception:
        pass

    # 3. 保底回傳
    return f"Teacher_{page_index+1}"

def get_virtual_grid(page):
    """建立虛擬座標網格 (同 v8.0)"""
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
    
    # 1. 找尋欄位 (Header)
    width = page.width
    header_keywords = {"一": "一", "二": "二", "三": "三", "四": "四", "五": "五"}
    found_headers = []
    
    for w in words:
        if w['top'] < 150: 
            txt = w['text'].strip()
            for k, v in header_keywords.items():
                if k in txt and v not in [h['day'] for h in found_headers]:
                    found_headers.append({"day": v, "x0": w['x0'], "x1": w['x1']})
    
    found_headers.sort(key=lambda x: x['x0'])
    
    if len(found_headers) < 3:
        # 盲猜模式
        start_x = width * 0.15
        step = (width - start_x) / 5
        final_cols = []
        days = ["一", "二", "三", "四", "五"]
        for i, d in enumerate(days):
            x0 = start_x + (i * step)
            x1 = x0 + step
            final_cols.append({"day": d, "x0": x0, "x1": x1})
    else:
        final_cols = []
        for i in range(len(found_headers)):
            current = found_headers[i]
            if i == 0: left_bound = current['x0'] - 20
            else: left_bound = (found_headers[i-1]['x1'] + current['x0']) / 2
            
            if i == len(found_headers) - 1: right_bound = width
            else: right_bound = (current['x1'] + found_headers[i+1]['x0']) / 2
            final_cols.append({"day": current['day'], "x0": left_bound, "x1": right_bound})

    # 2. 找尋列 (Period)
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
    
    if len(found_rows) < 4:
        # 盲猜模式
        start_y = 150
        step_y = 60
        final_rows = []
        for i in range(1, 9):
            top = start_y + ((i-1) * step_y)
            if i >= 5: top += 30 
            bottom = top + step_y
            final_rows.append({"period": str(i), "top": top, "bottom": bottom})
    else:
        final_rows = []
        for i in range(len(found_rows)):
            curr = found_rows[i]
            if i == 0: top = curr['top'] - 10
            else: top = (found_rows[i-1]['bottom'] + curr['top']) / 2
            
            if i == len(found_rows) - 1: bottom = curr['bottom'] + 60
            else: bottom = (curr['bottom'] + found_rows[i+1]['top']) / 2
            final_rows.append({"period": curr['period'], "top": top, "bottom": bottom})

    return final_cols, final_rows, words

def extract_class_and_course(content_str):
    if not content_str: return "", ""
    content_str = content_str.replace("科目星", "").replace("時間", "")
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
            
            # [修正] 使用新的強力姓名獵捕函式
            teacher_name = get_teacher_name_robust(page, i)
            
            if teacher_name not in teacher_classes_map:
                teacher_classes_map[teacher_name] = set()

            cols, rows, all_words = get_virtual_grid(page)
            grid_buckets = {}
            
            for w in all_words:
                w_cx = (w['x0'] + w['x1']) / 2
                w_cy = (w['top'] + w['bottom']) / 2
                
                matched_day = None
                for col in cols:
                    if col['x0'] <= w_cx <= col['x1']:
                        matched_day = col['day']
                        break
                
                matched_period = None
                for row in rows:
                    if row['top'] <= w_cy <= row['bottom']:
                        matched_period = row['period']
                        break
                
                if matched_day and matched_period:
                    key = f"{matched_day}_{matched_period}"
                    if key not in grid_buckets: grid_buckets[key] = []
                    grid_buckets[key].append(w['text'])

            for r in rows:
                p = r['period']
                for c in cols:
                    d = c['day']
                    key = f"{d}_{p}"
                    
                    raw_content_list = grid_buckets.get(key, [])
                    full_text = " ".join(raw_content_list)
                    clean_content = clean_text_v8(full_text)
                    
                    if re.match(r'^\d{2}:\d{2}$', clean_content): clean_content = ""
                    if clean_content in ["一", "二", "三", "四", "五"]: clean_content = ""

                    is_free = (len(clean_content) < 1)
                    
                    extracted_data.append({
                        "teacher": teacher_name, "day": d, "period": p,
                        "content": clean_content, "is_free": is_free
                    })
                    
                    cls, _ = extract_class_and_course(clean_content)
                    if cls: teacher_classes_map[teacher_name].add(cls)

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

@st.cache_data
def get_teacher_list(df):
    return sorted(df['teacher'].unique())

# ==========================================
# 3. 介面
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
    st.title("🏫 成德高中 智慧調代課系統 v8.1")
    
    if 'table_reset_key' not in st.session_state:
        st.session_state.table_reset_key = 0

    uploaded_file = st.sidebar.file_uploader("步驟 1: 上傳全校課表 PDF", type=["pdf"], key="uploader_v81")

    if uploaded_file:
        with st.spinner("正在進行智慧解析 (v8.1 姓名修正版)..."):
            raw_data, teacher_classes_map = parse_pdf_v8(uploaded_file)
            
            if not raw_data:
                st.error("錯誤：無法從 PDF 中讀取有效課表。請確認檔案格式。")
                return
            
            df = pd.DataFrame(raw_data)
            df = df.groupby(['teacher', 'day', 'period'], as_index=False).agg({
                'content': lambda x: ' '.join(set([str(s) for s in x if s])),
                'is_free': 'all',
                'subject': 'first'
            })
            df['is_free'] = df['content'].apply(lambda x: len(x.strip()) < 1)
            
            st.success(f"解析完成！資料庫包含 {len(df['teacher'].unique())} 位教師。")
            cached_teacher_list = get_teacher_list(df)
            
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

        tab1, tab2, tab3 = st.tabs(["📅 課表檢視", "🚑 代課尋找", "🔄 調課互換"])

        with tab1:
            st.subheader("個別教師課表")
            t_select = st.selectbox("選擇教師", cached_teacher_list, key="t_sel_v81")
            if t_select:
                t_df = df[df['teacher'] == t_select]
                pivot_df = t_df.pivot(index='period', columns='day', values='content')
                pivot_df = pivot_df.reindex([str(i) for i in range(1, 9)])
                pivot_df = pivot_df.reindex(columns=["一", "二", "三", "四", "五"])
                st.dataframe(pivot_df, use_container_width=True)

        with tab2:
            st.subheader("尋找代課 (單向代課)")
            c1, c2, c3 = st.columns(3)
            q_day = c1.selectbox("星期", ["一", "二", "三", "四", "五"], key="q_d_v81")
            q_period = c2.selectbox("節次", [str(i) for i in range(1, 9)], key="q_p_v81")
            q_subject = c3.selectbox("科別篩選", ["全部"] + sorted(list(set(df['subject'].dropna()))), key="q_s_v81")

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
            initiator = col_a.selectbox("誰要調課 (A老師)?", cached_teacher_list, key="swap_who_v81")
            swap_day = col_d.selectbox("A 想調開的星期", ["一", "二", "三", "四", "五"], key="swap_day_v81")
            swap_period = col_p.selectbox("A 想調開的節次", [str(i) for i in range(1, 9)], key="swap_per_v81")

            st.markdown("👇 **進階篩選條件**")
            cf1, cf2, cf3, cf4 = st.columns(4)
            filter_teacher = cf1.selectbox("還課教師 (指定B)", ["不指定"] + cached_teacher_list, key="fil_t_v81")
            filter_day = cf2.selectbox("還課星期", ["不指定", "一", "二", "三", "四", "五"], key="fil_d_v81")
            filter_period = cf3.selectbox("還課節次", ["不指定"] + [str(i) for i in range(1, 9)], key="fil_p_v81")
            filter_class = cf4.selectbox("還課班級", ["不指定"] + cached_class_list, key="fil_c_v81")

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
            
            if 'swap_results_v81' not in st.session_state:
                st.session_state.swap_results_v81 = None

            if st.button("🔍 搜尋雙向互換方案", key="btn_swap_v81"):
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
                    st.session_state.swap_results_v81 = res_df
                else:
                    st.session_state.swap_results_v81 = pd.DataFrame()

            if st.session_state.swap_results_v81 is not None and not st.session_state.swap_results_v81.empty:
                st.success(f"找到 {len(st.session_state.swap_results_v81)} 個互換方案！")
                event = st.dataframe(st.session_state.swap_results_v81, hide_index=True, use_container_width=True, selection_mode="single-row", on_select="rerun", key=f"swap_table_v81_{st.session_state.table_reset_key}")
                
                if len(event.selection.rows) > 0:
                    row_data = st.session_state.swap_results_v81.iloc[event.selection.rows[0]]
                    target_details = {'day': row_data['還課星期'], 'period': row_data['還課節次'], 'class': row_data['還課班級'], 'course': row_data['還課課程']}
                    show_schedule_popup(row_data['教師姓名'], df, initiator, source_details, target_details)
            elif st.session_state.swap_results_v81 is not None and st.session_state.swap_results_v81.empty:
                if st.session_state.get('btn_swap_v81'):
                    st.warning("無符合條件的互換人選。")

if __name__ == "__main__":
    main()
