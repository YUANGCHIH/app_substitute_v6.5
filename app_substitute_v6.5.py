import streamlit as st
import streamlit.components.v1 as components
import pdfplumber
import pandas as pd
import re
import json
from datetime import date, timedelta
import io

# 設定頁面資訊
st.set_page_config(page_title="成德高中 智慧調代課系統 v9.0", layout="wide")

# ==========================================
# 1. 核心邏輯：Excel 解析引擎 (新功能)
# ==========================================

def parse_excel_v9(uploaded_file):
    """
    解析 Excel 格式的課表 (解決 PDF 純圖片問題)
    """
    extracted_data = []
    teacher_classes_map = {}
    
    # 讀取 Excel (讀取所有工作表)
    # header=None 表示不鎖定標題列，全部讀進來分析
    xls = pd.ExcelFile(uploaded_file)
    
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        
        # 轉成字串並填補空值
        df = df.fillna("").astype(str)
        
        # --- 1. 抓取教師姓名 ---
        teacher_name = f"Teacher_{sheet_name}"
        # 掃描前 10 行找名字
        found_name = False
        for r in range(min(10, len(df))):
            row_text = " ".join(df.iloc[r].values)
            match = re.search(r"教師[:：\s]*([^\d\s]+)", row_text)
            if match:
                raw_name = match.group(1)
                # 清洗名字
                clean_name = re.sub(r'(導師|老師|專任|組長)', '', raw_name)
                if 1 < len(clean_name) <= 5:
                    teacher_name = clean_name
                    found_name = True
                    break
        
        # 如果沒找到，試試看 Sheet Name 是否就是名字
        if not found_name and len(sheet_name) <= 4:
             teacher_name = sheet_name

        if teacher_name not in teacher_classes_map:
            teacher_classes_map[teacher_name] = set()

        # --- 2. 定位座標 (星期與節次) ---
        # Excel 的座標是 (Row, Col)
        
        # 找星期列 (Header)
        header_row_idx = -1
        col_map = {} # {col_index: "一"}
        days = ["一", "二", "三", "四", "五"]
        
        for r in range(len(df)):
            row_values = df.iloc[r].values
            found_days = 0
            temp_map = {}
            for c, val in enumerate(row_values):
                val = str(val).strip()
                for d in days:
                    if d in val and d not in temp_map.values():
                        temp_map[c] = d
                        found_days += 1
            if found_days >= 3: # 找到至少三天
                header_row_idx = r
                col_map = temp_map
                break
        
        if header_row_idx == -1: continue # 這一頁沒課表
        
        # 找節次 (Period)
        # 從 Header 之後開始找
        time_map = {
            "1": ["08:", "8:", "第一節"], "2": ["09:", "9:", "第二節"], 
            "3": ["10:", "第三節"], "4": ["11:", "第四節"],
            "5": ["13:", "12:", "第五節"], "6": ["14:", "第六節"], 
            "7": ["15:", "第七節"], "8": ["16:", "第八節"]
        }
        
        for r in range(header_row_idx + 1, len(df)):
            row_text = "".join(df.iloc[r].values).replace(" ", "")
            period = None
            for p, kws in time_map.items():
                for kw in kws:
                    if kw in row_text:
                        period = p
                        break
            
            if period:
                # 提取該列對應的星期欄位
                for c_idx, day in col_map.items():
                    content = str(df.iloc[r, c_idx]).strip()
                    
                    # 清洗內容
                    content = re.sub(r'[کمکر]', '', content)
                    content = content.replace("nan", "").strip()
                    if content in ["一", "二", "三", "四", "五"]: content = ""
                    
                    is_free = (len(content) < 1)
                    
                    extracted_data.append({
                        "teacher": teacher_name, "day": day, "period": period,
                        "content": content, "is_free": is_free
                    })
                    
                    cls, _ = extract_class_and_course(content)
                    if cls: teacher_classes_map[teacher_name].add(cls)

            # 補科目 (同 PDF 邏輯)
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
# 2. 輔助與 PDF 邏輯 (保留 v8.2 以支援正常 PDF)
# ==========================================

def clean_text_v8(text):
    if not text: return ""
    text = re.sub(r'[کمکر]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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

def get_teacher_name_robust(page, page_index):
    # (保留 v8.2 的強力獵捕邏輯，略，為節省篇幅直接使用)
    raw_text = page.extract_text() or ""
    text_no_space = raw_text.replace(" ", "").replace("\n", "")
    match = re.search(r"教師[:：]?([^\d\s]+)", text_no_space)
    if match:
        name = match.group(1)
        for title in ["導師", "專任", "組長", "教師", "老師"]:
            name = name.replace(title, "")
        if 1 < len(name) <= 5: return name
    
    words = page.extract_words(keep_blank_chars=True)
    header_words = [w for w in words if w['top'] < 120]
    for w in header_words:
        txt = w['text'].replace(" ", "")
        if any(x in txt for x in ["成德", "課程", "學年", "列印", "數位"]): continue
        if txt.isdigit(): continue
        clean = re.sub(r'(教師|[:：]|\d+|導師|專任)', '', txt)
        if 1 < len(clean) <= 4: return clean
    return f"Teacher_{page_index+1}"

def get_virtual_grid(page):
    # (保留 v8.2 邏輯)
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
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
        start_x = width * 0.15
        step = (width - start_x) / 5
        final_cols = []
        for i, d in enumerate(["一", "二", "三", "四", "五"]):
            final_cols.append({"day": d, "x0": start_x + i*step, "x1": start_x + (i+1)*step})
    else:
        final_cols = []
        for i in range(len(found_headers)):
            current = found_headers[i]
            left = current['x0'] - 20 if i==0 else (found_headers[i-1]['x1'] + current['x0'])/2
            right = width if i==len(found_headers)-1 else (current['x1'] + found_headers[i+1]['x0'])/2
            final_cols.append({"day": current['day'], "x0": left, "x1": right})
            
    time_map = {"1": ["08:", "8:"], "2": ["09:", "9:"], "3": ["10:"], "4": ["11:"], "5": ["13:", "12:"], "6": ["14:"], "7": ["15:"], "8": ["16:"]}
    found_rows = []
    for w in words:
        txt = w['text'].replace(" ", "")
        for p, kws in time_map.items():
            for kw in kws:
                if kw in txt and p not in [r['period'] for r in found_rows]:
                    found_rows.append({"period": p, "top": w['top'], "bottom": w['bottom']})
    found_rows.sort(key=lambda x: x['top'])
    if len(found_rows) < 4:
        start_y = 150; step_y = 60
        final_rows = []
        for i in range(1, 9):
            top = start_y + (i-1)*step_y + (30 if i>=5 else 0)
            final_rows.append({"period": str(i), "top": top, "bottom": top+step_y})
    else:
        final_rows = []
        for i in range(len(found_rows)):
            curr = found_rows[i]
            top = curr['top'] - 10 if i==0 else (found_rows[i-1]['bottom'] + curr['top'])/2
            bottom = curr['bottom'] + 60 if i==len(found_rows)-1 else (curr['bottom'] + found_rows[i+1]['top'])/2
            final_rows.append({"period": curr['period'], "top": top, "bottom": bottom})
    return final_cols, final_rows, words

def parse_pdf_v9(uploaded_file):
    extracted_data = []
    teacher_classes_map = {} 
    with pdfplumber.open(uploaded_file) as pdf:
        for i, page in enumerate(pdf.pages):
            teacher_name = get_teacher_name_robust(page, i)
            if teacher_name not in teacher_classes_map: teacher_classes_map[teacher_name] = set()
            cols, rows, all_words = get_virtual_grid(page)
            grid_buckets = {}
            for w in all_words:
                w_cx, w_cy = (w['x0']+w['x1'])/2, (w['top']+w['bottom'])/2
                m_d, m_p = None, None
                for c in cols:
                    if c['x0'] <= w_cx <= c['x1']: m_d = c['day']; break
                for r in rows:
                    if r['top'] <= w_cy <= r['bottom']: m_p = r['period']; break
                if m_d and m_p:
                    k = f"{m_d}_{m_p}"
                    if k not in grid_buckets: grid_buckets[k] = []
                    grid_buckets[k].append(w['text'])
            for r in rows:
                p = r['period']
                for c in cols:
                    d = c['day']
                    k = f"{d}_{p}"
                    cont = clean_text_v8(" ".join(grid_buckets.get(k, [])))
                    if re.match(r'^\d{2}:\d{2}$', cont) or cont in ["一","二","三","四","五"]: cont = ""
                    extracted_data.append({"teacher": teacher_name, "day": d, "period": p, "content": cont, "is_free": len(cont)<1})
                    cls, _ = extract_class_and_course(cont)
                    if cls: teacher_classes_map[teacher_name].add(cls)
            # 補科目
            subj = "綜合"
            all_c = " ".join([x['content'] for x in extracted_data if x['teacher']==teacher_name])
            sk = {"國語文":"國文","英文":"英文","數學":"數學","物理":"自然","化學":"自然","生物":"自然","地科":"自然","歷史":"社會","地理":"社會","公民":"社會","體育":"健體","美術":"藝能","音樂":"藝能","資訊":"科技","生科":"科技","全民國防":"國防","護理":"健體"}
            dc = {}
            for k,v in sk.items(): 
                if k in all_c: dc[v] = dc.get(v,0)+1
            if dc: subj = max(dc, key=dc.get)
            for x in extracted_data:
                if x['teacher']==teacher_name: x['subject'] = subj
    return extracted_data, teacher_classes_map

@st.cache_data
def get_teacher_list(df):
    return sorted(df['teacher'].unique())

# ==========================================
# 3. 介面 (支援 Excel 與 手動改名)
# ==========================================

@st.dialog("調課詳細資訊", width="large")
def show_schedule_popup(target_teacher, full_df, initiator_name, source_details, target_details):
    # (保持原本功能)
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
        pivot = t_df.pivot(index='period', columns='day', values='content').reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"])
        def hl(v, r, c): 
            return 'background-color: #ffcccc; color: #8b0000; font-weight: bold; border: 2px solid red;' if r==target_details['period'] and c==target_details['day'] else ''
        st.dataframe(pivot.style.apply(lambda x: pd.DataFrame([[hl(x.iloc[i,j], pivot.index[i], pivot.columns[j]) for j in range(5)] for i in range(8)], index=pivot.index, columns=pivot.columns), axis=None), use_container_width=True)
    
    source_str = f"{str_date_a} (週{source_details['day']}) 第{source_details['period']}節 {source_details['class']} {source_details['course']}"
    target_str = f"{str_date_b} (週{target_details['day']}) 第{target_details['period']}節 {target_details['class']} {target_details['course']}"
    
    msg = f"{target_teacher} 老師您好：\n\n我是 {initiator_name}。\n想詢問您 **{target_str}** 是否方便與我 **{source_str}** 調換課程？\n\n再麻煩您確認意願，感謝幫忙！🙏"
    st.subheader("✉️ 調課邀請通知單")
    st.text_area("預覽內容", value=msg, height=150)
    
    # Print Button HTML (略，保持不變)
    components.html(f"""<script>function printSlip(){{var w=window.open('','','width=800,height=600');w.document.write('<html><body><div style="font-family:sans-serif;padding:40px;border:2px solid #333"><h2>調課徵詢單</h2><p>致 {target_teacher} 老師：</p><p>我是 {initiator_name}。<br>想詢問您 {target_str} <br>是否方便與我 {source_str} 調換？</p><br><p>簽名：_____________</p></div></body></html>');w.print();}}</script><button onclick="printSlip()" style="background:#fff;border:1px solid #ccc;padding:8px;width:100%">🖨️ 列印</button>""", height=45)
    if st.button("關閉視窗", use_container_width=True, type="secondary"):
        st.session_state.table_reset_key += 1
        st.rerun()

def main():
    st.title("🏫 成德高中 智慧調代課系統 v9.0")
    st.caption("🚀 支援 PDF 與 Excel 格式 | 內建教師更名功能")
    
    if 'table_reset_key' not in st.session_state: st.session_state.table_reset_key = 0
    
    # 支援上傳 PDF 或 Excel
    uploaded_file = st.sidebar.file_uploader("步驟 1: 上傳課表 (PDF 或 Excel)", type=["pdf", "xlsx"], key="uploader_v9")

    if uploaded_file:
        file_type = uploaded_file.name.split('.')[-1].lower()
        
        with st.spinner(f"正在解析 {file_type.upper()} 檔案..."):
            if file_type == 'pdf':
                raw_data, teacher_classes_map = parse_pdf_v9(uploaded_file)
            elif file_type == 'xlsx':
                raw_data, teacher_classes_map = parse_excel_v9(uploaded_file)
            else:
                st.error("不支援的格式")
                return

            if not raw_data:
                st.error("錯誤：讀取不到資料。如果是 PDF，請先轉檔為 Excel 再上傳。")
                return
            
            df = pd.DataFrame(raw_data)
            df = df.groupby(['teacher', 'day', 'period'], as_index=False).agg({
                'content': lambda x: ' '.join(set([str(s) for s in x if s])),
                'is_free': 'all', 'subject': 'first'
            })
            df['is_free'] = df['content'].apply(lambda x: len(x.strip()) < 1)
            
            st.success(f"解析完成！找到 {len(df['teacher'].unique())} 位教師。")
            
            # --- [新功能] 教師姓名修正區 ---
            with st.expander("🛠️ 修正教師姓名 (如果出現 Teacher_數字 請點此)"):
                all_teachers = sorted(df['teacher'].unique())
                t_to_rename = st.selectbox("選擇要更名的代號", all_teachers)
                new_name = st.text_input(f"請輸入 {t_to_rename} 的正確姓名", placeholder="例如：陳慧敏")
                if st.button("確認更名"):
                    df.loc[df['teacher'] == t_to_rename, 'teacher'] = new_name
                    st.success(f"已將 {t_to_rename} 更名為 {new_name}")
                    st.rerun() # 重新整理以更新清單

            cached_teacher_list = sorted(df['teacher'].unique())
            
            # 班級清單
            all_cls = set()
            for cs in teacher_classes_map.values(): all_cls.update(cs)
            try: cached_class_list = sorted(list(all_cls), key=lambda s: (re.search(r'([高國])([一二三])(\d+)',s).group(1), {'一':1,'二':2,'三':3}.get(re.search(r'([高國])([一二三])(\d+)',s).group(2),9), int(re.search(r'([高國])([一二三])(\d+)',s).group(3))) if re.search(r'([高國])([一二三])(\d+)',s) else (s,0,0))
            except: cached_class_list = sorted(list(all_cls))

        tab1, tab2, tab3 = st.tabs(["📅 課表檢視", "🚑 代課尋找", "🔄 調課互換"])

        with tab1:
            t_select = st.selectbox("選擇教師", cached_teacher_list, key="t_sel_v9")
            if t_select:
                t_df = df[df['teacher'] == t_select]
                pivot = t_df.pivot(index='period', columns='day', values='content').reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"])
                st.dataframe(pivot, use_container_width=True)

        with tab2:
            c1, c2, c3 = st.columns(3)
            qd = c1.selectbox("星期", ["一","二","三","四","五"], key="qd_v9")
            qp = c2.selectbox("節次", [str(i) for i in range(1,9)], key="qp_v9")
            qs = c3.selectbox("科別", ["全部"] + sorted(list(set(df['subject'].dropna()))), key="qs_v9")
            frees = df[(df['day']==qd) & (df['period']==qp) & (df['is_free']==True)]
            if qs!="全部": frees = frees[frees['subject']==qs]
            if not frees.empty: st.success(f"推薦 {len(frees)} 人"); st.dataframe(frees[['teacher','subject']], hide_index=True, use_container_width=True)
            else: st.warning("無空堂")

        with tab3:
            c1, c2, c3 = st.columns([2,1,1])
            init = c1.selectbox("A老師 (發起人)", cached_teacher_list, key="init_v9")
            sd = c2.selectbox("A 星期", ["一","二","三","四","五"], key="sd_v9")
            sp = c3.selectbox("A 節次", [str(i) for i in range(1,9)], key="sp_v9")
            
            st.markdown("👇 **進階篩選**")
            f1, f2, f3, f4 = st.columns(4)
            ft = f1.selectbox("指定 B 教師", ["不指定"]+cached_teacher_list, key="ft_v9")
            fd = f2.selectbox("指定 B 星期", ["不指定","一","二","三","四","五"], key="fd_v9")
            fp = f3.selectbox("指定 B 節次", ["不指定"]+[str(i) for i in range(1,9)], key="fp_v9")
            fc = f4.selectbox("指定 B 班級", ["不指定"]+cached_class_list, key="fc_v9")

            a_stat = df[(df['teacher']==init) & (df['day']==sd) & (df['period']==sp)]
            src_det = {'day':sd, 'period':sp, 'class':'無', 'course':'空堂'}
            tgt_cls_code = None
            if not a_stat.empty and not a_stat.iloc[0]['is_free']:
                cnt = a_stat.iloc[0]['content']
                cls, crs = extract_class_and_course(cnt)
                tgt_cls_code = cls
                src_det['class'] = cls if cls else "(未識別)"
                src_det['course'] = crs if crs else cnt
                st.info(f"調出: {src_det['class']} {src_det['course']}")
            
            if 'swap_res_v9' not in st.session_state: st.session_state.swap_res_v9 = None
            if st.button("🔍 搜尋互換方案"):
                cands = df[(df['day']==sd) & (df['period']==sp) & (df['is_free']==True) & (df['teacher']!=init)]
                if ft!="不指定": cands = cands[cands['teacher']==ft]
                a_free_keys = set(df[(df['teacher']==init) & (df['is_free']==True)]['day']+"_"+df[(df['teacher']==init) & (df['is_free']==True)]['period'])
                opts = []
                for b_name in cands['teacher'].unique():
                    b_sub = df[df['teacher']==b_name]
                    b_subj_name = b_sub.iloc[0]['subject']
                    for _, row in b_sub[b_sub['is_free']==False].iterrows():
                        if fd!="不指定" and row['day']!=fd: continue
                        if fp!="不指定" and row['period']!=fp: continue
                        if (row['day']+"_"+row['period']) in a_free_keys:
                            b_c, b_co = extract_class_and_course(row['content'])
                            if fc!="不指定" and b_c!=fc: continue
                            tag = "⭐同班" if (tgt_cls_code and b_c and tgt_cls_code==b_c) else ""
                            opts.append({"標記":tag, "教師姓名":b_name, "科目":b_subj_name, "還課星期":row['day'], "還課節次":row['period'], "還課班級":b_c, "還課課程":b_co, "_sort": 0 if tag else 1})
                st.session_state.swap_res_v9 = pd.DataFrame(opts).sort_values(['_sort','還課星期','還課節次']).drop(columns=['_sort']) if opts else pd.DataFrame()
            
            if st.session_state.swap_res_v9 is not None:
                if not st.session_state.swap_res_v9.empty:
                    st.success(f"找到 {len(st.session_state.swap_res_v9)} 個方案")
                    ev = st.dataframe(st.session_state.swap_res_v9, hide_index=True, use_container_width=True, selection_mode="single-row", on_select="rerun", key=f"tbl_v9_{st.session_state.table_reset_key}")
                    if len(ev.selection.rows)>0:
                        r = st.session_state.swap_res_v9.iloc[ev.selection.rows[0]]
                        show_schedule_popup(r['教師姓名'], df, init, src_det, {'day':r['還課星期'], 'period':r['還課節次'], 'class':r['還課班級'], 'course':r['還課課程']})
                else:
                    st.warning("無符合條件人選")

if __name__ == "__main__":
    main()
