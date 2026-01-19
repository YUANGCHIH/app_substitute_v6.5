import streamlit as st
import streamlit.components.v1 as components
import pdfplumber
import pandas as pd
import re
import json
from datetime import date, timedelta
import io

# ==========================================
# 0. 系統設定
# ==========================================
st.set_page_config(page_title="成德高中 智慧調代課系統 v12.0", layout="wide")

# ==========================================
# 1. 核心邏輯：座標定位解析 (針對 114-2 優化)
# ==========================================

def clean_text_v12(text):
    """
    v12 專屬清洗：針對 114-2 PDF 的特殊亂碼進行淨化
    """
    if not text: return ""
    # 移除波斯/阿拉伯語系亂碼 (您的 PDF 裡出現了 کم, کر)
    text = re.sub(r'[\u0600-\u06FF]', '', text)
    # 移除常見雜訊
    text = text.replace("科目星", "").replace("時間班期", "").replace("時間", "").replace("班級", "")
    # 移除時間格式 (避免誤判為課程)
    text = re.sub(r'\d{1,2}[:：]\d{2}', '', text)
    # 移除多餘空白
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_class_and_course(content_str):
    """分離班級與課程"""
    if not content_str: return "", ""
    # 針對 "文 國一3" 或 "文\n國一3"
    content_str = clean_text_v12(content_str)
    
    # 抓取班級 (高/國 + 一二三/- + 數字)
    class_pattern = re.search(r'([高國][一二三\-]\s*\d+)', content_str)
    if class_pattern:
        raw_class = class_pattern.group(1)
        class_code = raw_class.replace(" ", "").replace("-", "")
        course_name = content_str.replace(raw_class, "").strip()
        return class_code, course_name
    return "", content_str

def get_teacher_name_v12(page, page_idx):
    """
    從頁面抓取教師姓名 (座標優先法)
    """
    words = page.extract_words(keep_blank_chars=True)
    # 只看上面 20% 的區域
    header_words = [w for w in words if w['top'] < page.height * 0.2]
    
    # 策略 1: 找 "教師" 關鍵字
    for i, w in enumerate(header_words):
        if "教師" in w['text']:
            # 往後找字
            raw_text = ""
            for j in range(i, min(i+5, len(header_words))):
                raw_text += header_words[j]['text']
            
            # 清洗並提取名字
            match = re.search(r"教師[:：\s]*([^\d\s]+)", raw_text)
            if match:
                name = match.group(1)
                # 移除職稱
                for title in ["導師", "專任", "組長", "教師"]:
                    name = name.replace(title, "")
                if 1 < len(name) <= 5: return name

    # 策略 2: 沒找到 "教師" 字眼，盲抓標題區塊的大字 (通常除了校名就是老師名)
    for w in header_words:
        txt = w['text'].replace(" ", "")
        if len(txt) > 1 and len(txt) <= 4:
            if not any(k in txt for k in ["成德", "課表", "學年", "列印", "版", "一", "二"]):
                # 排除純數字
                if not re.search(r'\d', txt):
                    return txt

    return f"Teacher_{page_idx+1}"

def get_virtual_grid(page):
    """
    建立虛擬網格：不看表格線，只看文字座標 (GPS 定位)
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
    width = page.width
    height = page.height

    # 1. 定位 X 軸 (星期)
    # 搜尋 "一", "二", "三"...
    day_anchors = {"一": None, "二": None, "三": None, "四": None, "五": None}
    for w in words:
        if w['top'] < height * 0.25: # 只在上方找標題
            txt = w['text'].strip()
            for d in day_anchors.keys():
                if d in txt and day_anchors[d] is None:
                    day_anchors[d] = (w['x0'], w['x1']) # 記下左右邊界

    # 如果抓不到標題 (PDF太爛)，用盲猜 (平均切分頁面寬度)
    cols = []
    found_days = [d for d, pos in day_anchors.items() if pos is not None]
    
    if len(found_days) < 3:
        # 盲猜模式：假設左邊 15% 是節次，剩下 85% 分給 5 天
        start_x = width * 0.15
        step = (width - start_x) / 5
        for i, d in enumerate(["一", "二", "三", "四", "五"]):
            cols.append({"day": d, "x0": start_x + i*step, "x1": start_x + (i+1)*step})
    else:
        # 根據抓到的座標推算中間線
        sorted_days = sorted([d for d in day_anchors.items() if d[1]], key=lambda x: x[1][0])
        for i in range(len(sorted_days)):
            d, (x0, x1) = sorted_days[i]
            # 左邊界
            if i == 0: left = x0 - 20
            else: left = (sorted_days[i-1][1][1] + x0) / 2
            # 右邊界
            if i == len(sorted_days) - 1: right = width
            else: right = (x1 + sorted_days[i+1][1][0]) / 2
            cols.append({"day": d, "x0": left, "x1": right})

    # 2. 定位 Y 軸 (節次)
    # 搜尋時間 "08:", "09:"...
    time_anchors = {}
    time_kws = {
        "1": ["08:", "8:", "第一節"], "2": ["09:", "9:", "第二節"],
        "3": ["10:", "10", "第三節"], "4": ["11:", "11", "第四節"],
        "5": ["13:", "12:", "第五節"], "6": ["14:", "14", "第六節"],
        "7": ["15:", "15", "第七節"], "8": ["16:", "16", "第八節"]
    }
    
    for w in words:
        txt = w['text'].replace(" ", "")
        for p, kws in time_kws.items():
            if p not in time_anchors:
                for kw in kws:
                    if kw in txt:
                        time_anchors[p] = (w['top'], w['bottom'])
                        break
    
    rows = []
    # 檢查是否抓到足夠的節次，不夠就盲猜
    if len(time_anchors) < 4:
        # 盲猜模式
        start_y = height * 0.25
        step_y = (height * 0.7) / 8
        for i in range(1, 9):
            top = start_y + (i-1)*step_y
            rows.append({"period": str(i), "top": top, "bottom": top + step_y})
    else:
        # 填補空缺的節次 (線性插值)
        sorted_ps = sorted(time_anchors.keys(), key=lambda x: int(x))
        for i in range(1, 9):
            p = str(i)
            if p in time_anchors:
                top, bottom = time_anchors[p]
                # 擴大一點範圍
                rows.append({"period": p, "top": top - 5, "bottom": bottom + 40})
            else:
                # 如果這節沒抓到 (例如午休後)，用推算的
                if rows:
                    prev = rows[-1]
                    step = prev['bottom'] - prev['top']
                    rows.append({"period": p, "top": prev['bottom'], "bottom": prev['bottom'] + step})
                else:
                    rows.append({"period": p, "top": 150, "bottom": 200})

    return cols, rows, words

def parse_pdf_v12(uploaded_file):
    extracted_data = []
    teacher_classes_map = {}

    with pdfplumber.open(uploaded_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # 1. 抓老師名字
            teacher_name = get_teacher_name_v12(page, i)
            if teacher_name not in teacher_classes_map:
                teacher_classes_map[teacher_name] = set()

            # 2. 建立座標網格
            cols, rows, all_words = get_virtual_grid(page)

            # 3. 將文字投入網格 (Bucket Sorting)
            grid_buckets = {}
            for w in all_words:
                w_cx = (w['x0'] + w['x1']) / 2
                w_cy = (w['top'] + w['bottom']) / 2
                
                # 判定星期
                m_day = None
                for c in cols:
                    if c['x0'] <= w_cx <= c['x1']:
                        m_day = c['day']
                        break
                
                # 判定節次
                m_period = None
                for r in rows:
                    if r['top'] <= w_cy <= r['bottom']:
                        m_period = r['period']
                        break
                
                if m_day and m_period:
                    key = f"{m_day}_{m_period}"
                    if key not in grid_buckets: grid_buckets[key] = []
                    grid_buckets[key].append(w['text'])

            # 4. 整理數據
            for r in rows:
                p = r['period']
                for c in cols:
                    d = c['day']
                    key = f"{d}_{p}"
                    raw_list = grid_buckets.get(key, [])
                    
                    # 合併並清洗
                    full_text = " ".join(raw_list)
                    clean_content = clean_text_v12(full_text)
                    
                    # 過濾掉可能是 Header 殘留的字
                    if clean_content in ["一", "二", "三", "四", "五", "午休", "早自習"]:
                        clean_content = ""
                    
                    is_free = (len(clean_content) < 1)
                    
                    extracted_data.append({
                        "teacher": teacher_name, "day": d, "period": p,
                        "content": clean_content, "is_free": is_free
                    })
                    
                    # 抓班級
                    cls, _ = extract_class_and_course(clean_content)
                    if cls: teacher_classes_map[teacher_name].add(cls)

            # 5. 補科目 (多數決)
            all_content = " ".join([d['content'] for d in extracted_data if d['teacher'] == teacher_name])
            subj = "綜合"
            sk = {"國語文":"國文","英文":"英文","數學":"數學","物理":"自然","化學":"自然","生物":"自然","地科":"自然","歷史":"社會","地理":"社會","公民":"社會","體育":"健體","美術":"藝能","音樂":"藝能","資訊":"科技","生科":"科技","全民國防":"國防","護理":"健體","語文":"國文"}
            dc = {}
            for k,v in sk.items(): 
                if k in all_content: dc[v] = dc.get(v,0)+1
            if dc: subj = max(dc, key=dc.get)
            
            for item in extracted_data:
                if item['teacher'] == teacher_name: item['subject'] = subj

    return extracted_data, teacher_classes_map

# ==========================================
# 2. 標準 Excel 支援 (當 PDF 真的不行時的備案)
# ==========================================
def get_template_excel():
    data = {"教師姓名": ["陳慧敏"], "星期": ["一"], "節次": ["1"], "課程內容": ["國文 國一1"]}
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(data).to_excel(writer, index=False)
    return output.getvalue()

def parse_excel_standard(file):
    try:
        df = pd.read_excel(file).astype(str)
        df.columns = [c.strip() for c in df.columns]
        data, t_map = [], {}
        for _, r in df.iterrows():
            t, d, p, c = r.get("教師姓名",""), r.get("星期",""), r.get("節次",""), r.get("課程內容","")
            if t == "nan": continue
            c = c.replace("nan", "")
            p = re.sub(r'[第節]', '', str(p).split('.')[0])
            data.append({"teacher":t, "day":d, "period":p, "content":c, "is_free":len(c)<1})
            if t not in t_map: t_map[t] = set()
            cls, _ = extract_class_and_course(c)
            if cls: t_map[t].add(cls)
        # 補科目 (略)
        return data, t_map
    except: return [], {}

# ==========================================
# 3. UI 元件：彈出視窗與列印
# ==========================================
@st.dialog("調課詳細資訊", width="large")
def show_popup(target_t, df, init_name, src, tgt):
    st.subheader("📆 設定調課日期")
    c1, c2 = st.columns(2)
    da = c1.date_input(f"A ({init_name}) 日期", value=date.today()+timedelta(days=1))
    db = c2.date_input(f"B ({target_t}) 日期", value=date.today()+timedelta(days=2))
    
    st.divider()
    st.subheader(f"📅 {target_t} 老師的週課表")
    
    # 畫課表
    t_df = df[df['teacher'] == target_t].drop_duplicates(['day','period'])
    if not t_df.empty:
        pivot = t_df.pivot(index='period', columns='day', values='content')
        pivot = pivot.reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"])
        
        # 紅框標註
        def highlight(v, r, c):
            if r == tgt['period'] and c == tgt['day']:
                return 'background-color: #ffcccc; color: #8b0000; font-weight: bold; border: 3px solid red;'
            return ''
        
        st.dataframe(pivot.style.apply(lambda x: pd.DataFrame([[highlight(x.iloc[i,j], pivot.index[i], pivot.columns[j]) for j in range(5)] for i in range(8)], index=pivot.index, columns=pivot.columns), axis=None), use_container_width=True)

    # 訊息生成
    src_str = f"{da.strftime('%Y/%m/%d')} (週{src['day']}) 第{src['period']}節 {src['class']} {src['course']}"
    tgt_str = f"{db.strftime('%Y/%m/%d')} (週{tgt['day']}) 第{tgt['period']}節 {tgt['class']} {tgt['course']}"
    msg = (f"{target_t} 老師您好：\n\n我是 {init_name}。\n"
           f"想詢問您 **{tgt_str}** 是否方便與我 **{src_str}** 調換課程？\n\n"
           "再麻煩您確認意願，感謝幫忙！🙏")
    
    st.subheader("✉️ 通知單預覽")
    st.text_area("", value=msg, height=150)

    # 列印與關閉按鈕
    c_p, c_c = st.columns(2)
    with c_p:
        print_html = f"""
        <script>
        function p(){{
            var w=window.open('','','width=800,height=600');
            w.document.write('<html><body style="font-family:sans-serif;padding:50px;line-height:1.6">');
            w.document.write('<h2 style="text-align:center;border-bottom:2px solid #333;padding-bottom:10px">調課徵詢單</h2>');
            w.document.write('<p><strong>致 {target_t} 老師：</strong></p>');
            w.document.write('<p>我是 <strong>{init_name}</strong>。<br><br>想詢問您 <strong>{tgt_str}</strong><br>是否方便與我 <strong>{src_str}</strong> 調換？</p>');
            w.document.write('<br><br><br><div style="text-align:right"><p>簽名：________________</p></div>');
            w.document.write('</body></html>');
            w.document.close();w.print();
        }}
        </script>
        <button onclick="p()" style="width:100%;padding:10px;background:white;border:1px solid #ddd;border-radius:5px;cursor:pointer;">🖨️ 直接列印通知單</button>
        """
        components.html(print_html, height=50)
    with c_c:
        if st.button("關閉視窗", use_container_width=True, type="secondary"):
            st.rerun()

# ==========================================
# 4. 主程式
# ==========================================
def main():
    st.title("🏫 成德高中 智慧調代課系統 v12.0")
    st.caption("旗艦版：內建 GPS 座標定位解析 + 亂碼濾除引擎")

    if 'reset_key' not in st.session_state: st.session_state.reset_key = 0

    with st.sidebar:
        st.header("1. 資料來源")
        mode = st.radio("模式", ["智慧解析 PDF", "標準 Excel 匯入"])
        
        df = pd.DataFrame()
        t_map = {}
        
        if mode == "智慧解析 PDF":
            uploaded = st.file_uploader("上傳 PDF", type=["pdf"], key="pdf_up")
            if uploaded:
                with st.spinner("啟動 GPS 座標定位分析..."):
                    data, t_map = parse_pdf_v12(uploaded)
                    if data:
                        df = pd.DataFrame(data)
                        st.success(f"成功！解析出 {len(df['teacher'].unique())} 位教師")
                    else:
                        st.error("解析失敗，請改用 Excel 匯入")
        else:
            st.download_button("下載範例 Excel", get_template_excel(), "example.xlsx")
            uploaded = st.file_uploader("上傳 Excel", type=["xlsx"], key="xls_up")
            if uploaded:
                data, t_map = parse_excel_standard(uploaded)
                if data: df = pd.DataFrame(data)

        # 教師更名工具
        if not df.empty:
            with st.expander("🛠️ 修正教師姓名"):
                all_t = sorted(df['teacher'].unique())
                old = st.selectbox("原名", all_t)
                new = st.text_input("新名")
                if st.button("更名"):
                    df.loc[df['teacher']==old, 'teacher'] = new
                    st.success("已更名，請重新操作")
                    st.rerun()

    # 主畫面
    if not df.empty:
        # 準備資料
        cached_t = sorted(df['teacher'].unique())
        all_cls = set()
        for s in t_map.values(): all_cls.update(s)
        try: cached_c = sorted(list(all_cls), key=lambda x: (x[0], x[1], x[2:])) 
        except: cached_c = sorted(list(all_cls))

        t1, t2, t3 = st.tabs(["課表檢視", "尋找代課", "調課互換"])

        with t1:
            me = st.selectbox("選擇教師", cached_t)
            sub_df = df[df['teacher']==me].drop_duplicates(['day','period'])
            pivot = sub_df.pivot(index='period', columns='day', values='content').reindex([str(i) for i in range(1,9)]).reindex(columns=["一","二","三","四","五"])
            st.dataframe(pivot, use_container_width=True)

        with t2:
            c1, c2, c3 = st.columns(3)
            qd = c1.selectbox("星期", ["一","二","三","四","五"])
            qp = c2.selectbox("節次", [str(i) for i in range(1,9)])
            qs = c3.selectbox("科別", ["全部"] + sorted(list(set(df['subject'].dropna()))))
            res = df[(df['day']==qd) & (df['period']==qp) & (df['is_free']==True)]
            if qs != "全部": res = res[res['subject']==qs]
            if not res.empty: st.dataframe(res[['teacher','subject']], hide_index=True, use_container_width=True)
            else: st.warning("無空堂")

        with t3:
            c1, c2, c3 = st.columns([2,1,1])
            who_a = c1.selectbox("A (發起)", cached_t)
            day_a = c2.selectbox("A 星期", ["一","二","三","四","五"])
            per_a = c3.selectbox("A 節次", [str(i) for i in range(1,9)])

            st.markdown("👇 **篩選 B 老師 (對方)**")
            f1, f2, f3, f4 = st.columns(4)
            ft = f1.selectbox("指定教師", ["不指定"]+cached_t)
            fd = f2.selectbox("指定星期", ["不指定","一","二","三","四","五"])
            fp = f3.selectbox("指定節次", ["不指定"]+[str(i) for i in range(1,9)])
            fc = f4.selectbox("指定班級", ["不指定"]+cached_c)

            # A 的詳情
            a_row = df[(df['teacher']==who_a) & (df['day']==day_a) & (df['period']==per_a)]
            src = {'day':day_a, 'period':per_a, 'class':'', 'course':''}
            tgt_cls = None
            if not a_row.empty and not a_row.iloc[0]['is_free']:
                cnt = a_row.iloc[0]['content']
                cls, crs = extract_class_and_course(cnt)
                tgt_cls = cls
                src['class'] = cls; src['course'] = crs
                st.info(f"調出: {cls} {crs}")
            else:
                st.warning("⚠️ 選擇的是空堂")

            if st.button("🔍 搜尋方案"):
                # 邏輯: 找 B 在 [day_a, per_a] 是空堂的人
                # 且 B 在 [目標時間] 是有課的 (這樣才能換)
                
                # 1. 先找誰在 A 的時間是空堂
                cands = df[(df['day']==day_a) & (df['period']==per_a) & (df['is_free']==True) & (df['teacher']!=who_a)]
                if ft != "不指定": cands = cands[cands['teacher']==ft]
                
                # 2. A 老師自己的空堂時間 (用來接收 B 的課)
                a_frees = set(df[(df['teacher']==who_a) & (df['is_free']==True)]['day'] + df[(df['teacher']==who_a) & (df['is_free']==True)]['period'])
                
                res = []
                for b in cands['teacher'].unique():
                    # 找 B 所有的忙碌時間 (潛在交換目標)
                    b_busy = df[(df['teacher']==b) & (df['is_free']==False)]
                    for _, r in b_busy.iterrows():
                        # 篩選條件
                        if fd != "不指定" and r['day'] != fd: continue
                        if fp != "不指定" and r['period'] != fp: continue
                        
                        b_cls, b_crs = extract_class_and_course(r['content'])
                        if fc != "不指定" and b_cls != fc: continue
                        
                        # 關鍵: 這個時間 A 必須有空
                        if (r['day'] + r['period']) in a_frees:
                            tag = "⭐同班" if (tgt_cls and b_cls and tgt_cls==b_cls) else ""
                            res.append({"標記":tag, "教師姓名":b, "科目":r['subject'], "還課星期":r['day'], "還課節次":r['period'], "還課班級":b_cls, "還課課程":b_crs, "_s": 0 if tag else 1})
                
                if res:
                    st.session_state.swap_res = pd.DataFrame(res).sort_values(['_s','還課星期','還課節次']).drop(columns=['_s'])
                else:
                    st.session_state.swap_res = pd.DataFrame()

            if 'swap_res' in st.session_state and not st.session_state.swap_res.empty:
                st.success(f"找到 {len(st.session_state.swap_res)} 個方案")
                ev = st.dataframe(st.session_state.swap_res, hide_index=True, use_container_width=True, selection_mode="single-row", on_select="rerun")
                if len(ev.selection.rows) > 0:
                    r = st.session_state.swap_res.iloc[ev.selection.rows[0]]
                    tgt = {'day':r['還課星期'], 'period':r['還課節次'], 'class':r['還課班級'], 'course':r['還課課程']}
                    show_popup(r['教師姓名'], df, who_a, src, tgt)

if __name__ == "__main__":
    main()
