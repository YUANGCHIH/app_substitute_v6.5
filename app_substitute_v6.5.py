import streamlit as st
import pandas as pd
import re
import datetime
import streamlit.components.v1 as components

# ==========================================
# 0. 系統設定
# ==========================================
st.set_page_config(page_title="成德高中 智慧調代課系統 v33", layout="wide")

# ==========================================
# 1. 核心邏輯：欣河系統解析
# ==========================================
def parse_xinhe_csv(uploaded_file):
    try:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding='utf-8', header=None, on_bad_lines='skip')
    except:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding='cp950', header=None, on_bad_lines='skip')
    
    df = df.fillna("").astype(str)
    all_data = []
    current_teacher = None
    day_col_map = {}
    period_map_zh = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
    
    for idx in range(len(df)):
        row = df.iloc[idx].values
        row_str = " ".join(row)

        if "教師" in row_str:
            match = re.search(r"教師[:：\s]*([^\s,0-9]+)", row_str)
            if match:
                raw_name = match.group(1).replace(":", "").strip()
                if len(raw_name) > 1 and "課程表" not in raw_name:
                    current_teacher = re.sub(r'(導師|老師|專任|代理|組長|教官|主任)', '', raw_name)
                    day_col_map = {} 
            continue

        if "一" in row and "五" in row:
            temp_map = {}
            for col_i, val in enumerate(row):
                val = val.strip()
                if val in ["一", "二", "三", "四", "五"]:
                    temp_map[col_i] = val
            if len(temp_map) >= 3:
                day_col_map = {v: k for k, v in temp_map.items()}
                continue

        if not current_teacher or not day_col_map: continue
            
        target_period = None
        for i in range(min(5, len(row))):
            val = row[i].strip()
            if val in period_map_zh:
                target_period = period_map_zh[val]
                break
        
        if target_period:
            prev_row = df.iloc[idx-1].values if idx > 0 else None
            for day, col_idx in day_col_map.items():
                if col_idx < len(row):
                    class_info = row[col_idx].strip()
                    subject_info = ""
                    if prev_row is not None and col_idx < len(prev_row):
                        subject_info = prev_row[col_idx].strip()
                    
                    subject_info = subject_info.replace("nan", "")
                    class_info = class_info.replace("nan", "")
                    
                    full_content = ""
                    if subject_info and class_info:
                        full_content = f"{subject_info} ({class_info})"
                    elif subject_info:
                        full_content = subject_info
                    elif class_info:
                        full_content = class_info
                        
                    is_free = True
                    if len(full_content) > 1 and full_content not in ["|", "nan", "None"]:
                        is_free = False
                        
                    if not is_free:
                        all_data.append({
                            "teacher": current_teacher,
                            "day": day,
                            "period": target_period,
                            "content": full_content,
                            "subject": subject_info,
                            "class_name": class_info
                        })

    if not all_data: return pd.DataFrame()
    data_df = pd.DataFrame(all_data)
    
    teachers = data_df['teacher'].unique()
    days = ["一", "二", "三", "四", "五"]
    periods = [str(i) for i in range(1, 9)]
    full_idx = pd.MultiIndex.from_product([teachers, days, periods], names=['teacher', 'day', 'period'])
    full_df = pd.DataFrame(index=full_idx).reset_index()
    final_df = pd.merge(full_df, data_df, on=['teacher', 'day', 'period'], how='left')
    
    final_df['content'] = final_df['content'].fillna("")
    final_df['subject'] = final_df['subject'].fillna("")
    final_df['class_name'] = final_df['class_name'].fillna("")
    final_df['is_free'] = final_df['content'] == ""
    
    def split_content(row):
        s, c = row['subject'], row['class_name']
        if s or c: return str(s), str(c)
        match = re.search(r"^(.*)\s+\((.*)\)$", str(row['content']))
        if match: return match.group(1), match.group(2)
        return str(row['content']), ""
    
    res = final_df.apply(split_content, axis=1)
    final_df['subject'] = [x[0] for x in res]
    final_df['class_name'] = [x[1] for x in res]
    
    return final_df.astype(str)

# ==========================================
# 2. 領域判定邏輯
# ==========================================
def determine_domain(teacher_name, df):
    manual_fix = {
        "王安順": "自然",
        "黃琮琪": "自然",
    }
    if teacher_name in manual_fix: return manual_fix[teacher_name]

    subjects = df[(df['teacher'] == teacher_name) & (df['subject'] != "")]['subject'].unique()
    all_subjects_str = "".join([str(s) for s in subjects])
    
    domain_map = {
        "國文": ["國文", "國語", "閱讀", "寫作", "語文"],
        "英文": ["英文", "英語", "English", "聽講"],
        "數學": ["數學", "數A", "數B", "幾何", "微積分", "補強"],
        "自然": ["物理", "化學", "生物", "地科", "科學", "探究", "實驗", "理化"],
        "社會": ["歷史", "地理", "公民", "社會", "經濟", "心理"],
        "健體": ["體育", "健康", "護理", "運動"],
        "藝能": ["美術", "音樂", "藝術", "表演", "繪畫"],
        "科技": ["資訊", "生活科技", "生科", "程式", "電腦", "機器人"],
        "國防": ["國防", "軍訓"],
        "特教": ["特教", "資源", "特殊"],
        "綜合": ["班會", "週會", "輔導", "彈性", "自主", "團體"]
    }
    
    scores = {domain: 0 for domain in domain_map}
    for domain, keywords in domain_map.items():
        for kw in keywords:
            if kw in all_subjects_str:
                scores[domain] += all_subjects_str.count(kw)
    
    best_domain = max(scores, key=scores.get)
    if scores[best_domain] == 0:
        return "其他" if len(all_subjects_str) > 0 else "未知"
    return best_domain

# ==========================================
# 3. 彈出視窗與通知單 (核心修改處)
# ==========================================
@st.dialog("課程互換與通知單", width="large")
def show_swap_dialog(teacher_b, b_row, teacher_a, source_info, full_df):
    st.subheader(f"🤝 與 {teacher_b} 老師的互換詳情")
    
    # 顯示 B 老師課表
    st.markdown(f"**{teacher_b} 老師的課表：**")
    b_df = full_df[full_df['teacher'] == teacher_b]
    pivot = b_df.pivot(index='period', columns='day', values='content')
    pivot = pivot.reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"]).fillna("")
    
    def highlight_cells(val, r, c):
        if r == b_row['還課節次'] and c == b_row['還課星期']:
            return 'background-color: #ffcccc; color: darkred; font-weight: bold'
        return ''

    st.dataframe(pivot.style.apply(lambda x: pd.DataFrame([[highlight_cells(x.iloc[i,j], pivot.index[i], pivot.columns[j]) for j in range(5)] for i in range(8)], index=pivot.index, columns=pivot.columns), axis=None), use_container_width=True)

    st.divider()

    # 1. 解析原始字串資訊
    src_day = re.search(r"週(.)", source_info).group(1)
    src_per = re.search(r"第(\d)", source_info).group(1)
    src_content = source_info.split("|")[1].strip()
    match_src = re.search(r"^(.*)\s+\((.*)\)$", src_content)
    if match_src:
        src_subj, src_cls = match_src.group(1), match_src.group(2)
    else:
        src_subj, src_cls = src_content, ""

    tgt_day = b_row['還課星期']
    tgt_per = b_row['還課節次']
    tgt_subj = b_row['課程名稱']
    tgt_cls = b_row['班級']
    
    a_name_only = teacher_a.split(" (")[0]
    b_name_only = teacher_b

    # ==========================
    # v33 新增：日期控制區
    # ==========================
    st.markdown("#### 📅 設定調課日期")
    col_chk, col_da, col_db = st.columns([1, 2, 2])
    
    with col_chk:
        st.write("") # Spacer
        st.write("")
        enable_date = st.checkbox("加入日期顯示", value=False)
    
    with col_da:
        date_a = st.date_input(f"我 (A) 調出的日期 (週{src_day})", datetime.date.today())
    
    with col_db:
        date_b = st.date_input(f"對方 (B) 還課的日期 (週{tgt_day})", datetime.date.today())

    # 根據是否勾選，組合時間字串
    if enable_date:
        str_src_time = f"{date_a.strftime('%Y/%m/%d')} (星期{src_day} 第{src_per}節)"
        str_tgt_time = f"{date_b.strftime('%Y/%m/%d')} (星期{tgt_day} 第{tgt_per}節)"
    else:
        str_src_time = f"星期{src_day} 第{src_per}節"
        str_tgt_time = f"星期{tgt_day} 第{tgt_per}節"

    # 產生通知單內容
    note_content = f"""{b_name_only} 老師您好：

希望 {str_tgt_time} {tgt_cls} ({tgt_subj}) 可以跟您換 {str_src_time} {src_cls} ({src_subj})

您上 {str_src_time} {src_cls}
我上 {str_tgt_time} {tgt_cls}

感謝您的協助！
敬祝平安
                                                {a_name_only}
"""

    st.subheader("📝 調課通知單 (可編輯)")
    final_note = st.text_area("內容預覽", value=note_content, height=250)
    
    col_p, col_c = st.columns([1, 1])
    with col_p:
        html_note = final_note.replace("\n", "<br>")
        print_js = f"""
        <script>
        function printNote() {{
            var printWindow = window.open('', '', 'height=600,width=800');
            printWindow.document.write('<html><head><title>調課通知單</title>');
            printWindow.document.write('<style>body{{font-family: "Microsoft JhengHei", sans-serif; padding: 40px; font-size: 16px; line-height: 1.8;}}</style>');
            printWindow.document.write('</head><body>');
            printWindow.document.write('<div style="border: 1px solid #000; padding: 30px;">');
            printWindow.document.write('{html_note}');
            printWindow.document.write('</div>');
            printWindow.document.write('</body></html>');
            printWindow.document.close();
            printWindow.print();
        }}
        </script>
        <button onclick="printNote()" style="
            background-color: #4CAF50; border: none; color: white; padding: 10px 24px;
            text-align: center; text-decoration: none; display: inline-block;
            font-size: 16px; margin: 4px 2px; cursor: pointer; border-radius: 4px; width: 100%;">
            🖨️ 列印通知單
        </button>
        """
        components.html(print_js, height=50)

    with col_c:
        if st.button("關閉視窗", use_container_width=True):
            st.rerun()

# ==========================================
# 3. 主程式 UI
# ==========================================
def main():
    st.title("🏫 成德高中 智慧調代課系統 v33")
    
    if 'data_loaded' not in st.session_state: st.session_state.data_loaded = False
    if 'swap_results' not in st.session_state: st.session_state.swap_results = None
    
    with st.sidebar:
        st.header("步驟 1：匯入資料")
        uploaded_file = st.file_uploader("上傳欣河 CSV", type=["csv", "xls", "xlsx"])

    if uploaded_file:
        if not st.session_state.data_loaded:
            with st.spinner("解析欣河系統格式..."):
                df = parse_xinhe_csv(uploaded_file)
                st.session_state.df = df
                st.session_state.data_loaded = True
        else:
            df = st.session_state.df
        
        if df.empty:
            st.error("讀取失敗。")
        else:
            # --- Map Setup ---
            teacher_domain_map = {}
            for t in df['teacher'].unique():
                teacher_domain_map[t] = determine_domain(t, df)
            teacher_display_map = {t: f"{t} ({d})" for t, d in teacher_domain_map.items()}
            all_domains = ["全部"] + sorted([d for d in set(teacher_domain_map.values()) if d != "未知"])
            unique_classes = df['class_name'].unique()
            clean_classes = sorted([str(c) for c in unique_classes if pd.notna(c) and str(c).strip() != ""])
            all_teachers_real = sorted(df['teacher'].unique())

            # --- Tabs ---
            tab1, tab2, tab3, tab4 = st.tabs(["📅 課表檢視", "🚑 尋找空堂", "🔄 雙人互換", "🔀 三角多角調"])

            # Tab 1: 課表檢視
            with tab1:
                col_d, col_t = st.columns([1, 2])
                with col_d: t1_domain = st.selectbox("篩選領域", all_domains, key="t1_dom")
                with col_t:
                    t1_opts = sorted(teacher_display_map.values()) if t1_domain == "全部" else sorted([v for k, v in teacher_display_map.items() if teacher_domain_map[k] == t1_domain])
                    t_sel_display = st.selectbox("選擇教師", t1_opts, key="t1_who")

                if t_sel_display:
                    t_real = [k for k, v in teacher_display_map.items() if v == t_sel_display][0]
                    t_df = df[df['teacher'] == t_real]
                    pivot = t_df.pivot(index='period', columns='day', values='content')
                    pivot = pivot.reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"]).fillna("")
                    st.dataframe(pivot, use_container_width=True)

            # Tab 2: 尋找空堂
            with tab2:
                st.subheader("1. 設定缺課時段")
                c1, c2 = st.columns(2)
                q_day = c1.selectbox("缺課星期", ["一","二","三","四","五"])
                q_per = c2.selectbox("缺課節次", [str(i) for i in range(1,9)])
                frees = df[(df['day']==q_day) & (df['period']==q_per) & (df['is_free'] == "True")]
                
                st.divider()
                st.subheader("2. 篩選空堂名單")
                c3, c4 = st.columns([1, 2])
                with c3: t2_domain = st.selectbox("篩選領域 (科別)", all_domains, key="t2_dom")
                with c4:
                    available_teachers = sorted(frees['teacher'].unique()) if t2_domain == "全部" else sorted([t for t in frees['teacher'].unique() if teacher_domain_map[t] == t2_domain])
                    available_display = [teacher_display_map[t] for t in available_teachers]
                    t2_name_filter = st.selectbox("篩選特定教師 (可選)", ["全部顯示"] + available_display, key="t2_who")

                if not frees.empty:
                    final_frees = frees.copy()
                    if t2_domain != "全部": final_frees = final_frees[final_frees['teacher'].isin([k for k,v in teacher_domain_map.items() if v==t2_domain])]
                    if t2_name_filter != "全部顯示":
                        target_real = [k for k, v in teacher_display_map.items() if v == t2_name_filter][0]
                        final_frees = final_frees[final_frees['teacher'] == target_real]

                    if not final_frees.empty:
                        st.success(f"符合條件的空堂教師共 {len(final_frees)} 位：")
                        final_frees['display_name'] = final_frees['teacher'].map(teacher_display_map)
                        st.dataframe(final_frees[['display_name']].reset_index(drop=True), use_container_width=True)
                    else:
                        st.warning("在此篩選條件下，無空堂教師。")
                else:
                    st.warning("該時段全校皆有課。")

            # Tab 3: 雙人互換
            with tab3:
                st.markdown("### 🔄 雙人直接調課")
                col_sub, col_tea = st.columns([1, 2])
                with col_sub: filter_domain = st.selectbox("1. 篩選領域 (科別)", all_domains, key="t3_dom")
                with col_tea:
                    filtered_teachers = sorted(teacher_display_map.values()) if filter_domain == "全部" else sorted([v for k, v in teacher_display_map.items() if teacher_domain_map[k] == filter_domain])
                    who_a_display = st.selectbox("2. 我是 (A老師)", filtered_teachers, key="t3_who")
                
                if who_a_display:
                    who_a = [k for k, v in teacher_display_map.items() if v == who_a_display][0]
                    
                    with st.expander(f"查看 {who_a} 的課表", expanded=False):
                        a_full_df = df[df['teacher'] == who_a]
                        a_pivot = a_full_df.pivot(index='period', columns='day', values='content')
                        a_pivot = a_pivot.reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"]).fillna("")
                        st.dataframe(a_pivot, use_container_width=True)
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.info("步驟 1：選擇您要調出的課")
                        a_busy = df[(df['teacher']==who_a) & (df['is_free'] == "False")]
                        src_opts = []
                        a_src_class_map = {} 
                        my_teaching_classes = set()
                        if not a_busy.empty:
                            for _, r in a_busy.iterrows():
                                opt_str = f"週{r['day']} 第{r['period']}節 | {r['content']}"
                                src_opts.append(opt_str)
                                a_src_class_map[opt_str] = r['class_name']
                                if r['class_name']: my_teaching_classes.add(r['class_name'])
                        sel_src = st.selectbox("我的調出課程", src_opts)

                    with col_b:
                        st.info("步驟 2：選擇您想換過去的時間")
                        a_free = df[(df['teacher']==who_a) & (df['is_free'] == "True") & (df['period'] != '8')]
                        tgt_opts = ["不指定"] + [f"週{r['day']} 第{r['period']}節" for _, r in a_free.iterrows()]
                        sel_tgt = st.selectbox("我的調入時間 (空堂)", tgt_opts)

                    st.markdown("---")
                    st.markdown("#### 🛠️ 進階篩選 (選填)")
                    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
                    with col_f1: filter_teacher = st.selectbox("指定 B 老師", ["不指定"] + [t for t in all_teachers_real if t != who_a])
                    with col_f2: 
                        my_classes_sorted = sorted(list(my_teaching_classes))
                        special_class_opt = "⭐ 我的任課班級"
                        filter_class = st.selectbox("指定 B 的班級", ["不指定", special_class_opt] + clean_classes)
                    with col_f3: filter_b_day = st.selectbox("指定 B 的課程星期", ["不指定", "一", "二", "三", "四", "五"])
                    with col_f4: filter_b_per = st.selectbox("指定 B 的課程節次", ["不指定"] + [str(i) for i in range(1,9)])

                    st.divider()

                    if sel_src and sel_tgt:
                        s_day = re.search(r"週(.)", sel_src).group(1)
                        s_per = re.search(r"第(\d)", sel_src).group(1)
                        my_src_class = a_src_class_map.get(sel_src, "")

                        if sel_tgt != "不指定":
                            t_day = re.search(r"週(.)", sel_tgt).group(1)
                            t_per = re.search(r"第(\d)", sel_tgt).group(1)
                        else:
                            t_day, t_per = None, None

                        if st.button("🔍 搜尋可互換對象"):
                            cands = df[(df['day']==s_day) & (df['period']==s_per) & (df['is_free'] == "True") & (df['teacher']!=who_a)]
                            if filter_teacher != "不指定": cands = cands[cands['teacher'] == filter_teacher]
                            cand_teachers = cands['teacher'].unique()
                            
                            results = []
                            for b in cand_teachers:
                                if t_day and t_per:
                                    b_crs = df[(df['teacher']==b) & (df['day']==t_day) & (df['period']==t_per)]
                                else:
                                    b_crs = df[(df['teacher']==b) & (df['is_free'] == "False")]
                                
                                for _, row_data in b_crs.iterrows():
                                    if not t_day:
                                        a_check = a_free[(a_free['day'] == row_data['day']) & (a_free['period'] == row_data['period'])]
                                        if a_check.empty: continue
                                    
                                    if row_data['is_free'] == "True": continue

                                    b_class = row_data['class_name']
                                    if filter_class == "⭐ 我的任課班級":
                                        if b_class not in my_teaching_classes: continue
                                    elif filter_class != "不指定" and b_class != filter_class:
                                        continue

                                    if filter_b_day != "不指定" and row_data['day'] != filter_b_day: continue
                                    if filter_b_per != "不指定" and row_data['period'] != filter_b_per: continue

                                    mark = ""
                                    if my_src_class and b_class and my_src_class == b_class: mark = "⭐"
                                    
                                    results.append({
                                        "標記": mark,
                                        "教師": b,
                                        "課程名稱": row_data['subject'],
                                        "班級": b_class,
                                        "還課星期": row_data['day'],
                                        "還課節次": row_data['period'],
                                        "_sort_score": 1 if mark else 0
                                    })
                            
                            if results:
                                st.session_state.swap_results = pd.DataFrame(results).sort_values(by='_sort_score', ascending=False).drop(columns=['_sort_score'])
                            else:
                                st.session_state.swap_results = pd.DataFrame()

                        if st.session_state.swap_results is not None:
                            if not st.session_state.swap_results.empty:
                                st.success(f"找到 {len(st.session_state.swap_results)} 個可互換方案！")
                                event = st.dataframe(
                                    st.session_state.swap_results, 
                                    use_container_width=True, 
                                    selection_mode="single-row",
                                    on_select="rerun",
                                    hide_index=True,
                                    key="swap_table"
                                )
                                if len(event.selection.rows) > 0:
                                    selected_idx = event.selection.rows[0]
                                    selected_row = st.session_state.swap_results.iloc[selected_idx]
                                    show_swap_dialog(selected_row['教師'], selected_row, who_a_display, sel_src, df)
                            else:
                                st.warning("無符合條件的互換對象。")

            # Tab 4: 多角調
            with tab4:
                st.markdown("### 🔀 三角循環調課 (A → B → C → A)")
                st.info("說明：若找不到直接互換的對象，可嘗試此功能。\n邏輯：A 把課給 B，B 把課給 C，C 把 A 想要的時段還給 A。")

                col_sub4, col_tea4 = st.columns([1, 2])
                with col_sub4: filter_domain4 = st.selectbox("1. 篩選領域", all_domains, key="t4_dom")
                with col_tea4:
                    filtered_teachers4 = sorted(teacher_display_map.values()) if filter_domain4 == "全部" else sorted([v for k, v in teacher_display_map.items() if teacher_domain_map[k] == filter_domain4])
                    who_a_display4 = st.selectbox("2. 我是 (A老師)", filtered_teachers4, key="t4_who")

                if who_a_display4:
                    who_a4 = [k for k, v in teacher_display_map.items() if v == who_a_display4][0]
                    
                    c_src, c_tgt = st.columns(2)
                    with c_src:
                        st.warning("步驟 1：A 丟出")
                        a_busy4 = df[(df['teacher']==who_a4) & (df['is_free'] == "False")]
                        src_opts4 = []
                        if not a_busy4.empty:
                            for _, r in a_busy4.iterrows():
                                src_opts4.append(f"週{r['day']} 第{r['period']}節 | {r['content']}")
                        sel_src4 = st.selectbox("A 丟出的課 (給 B)", src_opts4, key="t4_src")

                    with c_tgt:
                        st.success("步驟 2：A 接收")
                        a_free4 = df[(df['teacher']==who_a4) & (df['is_free'] == "True") & (df['period'] != '8')]
                        tgt_opts4 = [f"週{r['day']} 第{r['period']}節" for _, r in a_free4.iterrows()]
                        sel_tgt4 = st.selectbox("A 想要的空堂 (C 給)", tgt_opts4, key="t4_tgt")

                    st.divider()

                    if sel_src4 and sel_tgt4:
                        if st.button("🚀 搜尋三角路徑"):
                            s_day = re.search(r"週(.)", sel_src4).group(1)
                            s_per = re.search(r"第(\d)", sel_src4).group(1)
                            t_day = re.search(r"週(.)", sel_tgt4).group(1)
                            t_per = re.search(r"第(\d)", sel_tgt4).group(1)
                            
                            candidates_b = df[(df['day']==s_day) & (df['period']==s_per) & (df['is_free'] == "True") & (df['teacher']!=who_a4)]['teacher'].unique()
                            candidates_c_source = df[(df['day']==t_day) & (df['period']==t_per) & (df['is_free'] == "False") & (df['teacher']!=who_a4)]
                            
                            chain_results = []

                            for b in candidates_b:
                                b_busy_slots = df[(df['teacher']==b) & (df['is_free'] == "False")]
                                for _, b_row in b_busy_slots.iterrows():
                                    mid_day = b_row['day']
                                    mid_per = b_row['period']
                                    
                                    valid_c_list = candidates_c_source[
                                        (candidates_c_source['teacher'] != b) & 
                                        (candidates_c_source['teacher'] != who_a4)
                                    ]
                                    
                                    for _, c_row in valid_c_list.iterrows():
                                        c_name = c_row['teacher']
                                        c_is_free_at_mid = df[
                                            (df['teacher'] == c_name) & 
                                            (df['day'] == mid_day) & 
                                            (df['period'] == mid_per) & 
                                            (df['is_free'] == "True")
                                        ]
                                        
                                        if not c_is_free_at_mid.empty:
                                            chain_results.append({
                                                "路徑預覽": f"{who_a4} ➔ {b} ➔ {c_name} ➔ {who_a4}",
                                                "1. A給B": f"{s_day}{s_per} {sel_src4.split('|')[1]}",
                                                "2. B給C": f"{mid_day}{mid_per} {b_row['content']}",
                                                "3. C給A": f"{t_day}{t_per} {c_row['content']}",
                                                "中間人(B)": b,
                                                "收尾人(C)": c_name
                                            })
                            
                            if chain_results:
                                st.success(f"找到 {len(chain_results)} 條三角循環路徑！")
                                st.dataframe(pd.DataFrame(chain_results), use_container_width=True)
                            else:
                                st.warning("找不到可行的三角路徑。")

if __name__ == "__main__":
    main()
