import streamlit as st
import pdfplumber
import pandas as pd

st.set_page_config(page_title="PDF 深度診斷器", layout="wide")
st.title("🔬 PDF 結構深度診斷報告")
st.warning("請上傳 PDF，此工具將揭露檔案內部的真實座標與文字順序。")

uploaded_file = st.file_uploader("請上傳課表 PDF", type=["pdf"])

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        # 只分析第一頁 (通常格式都一樣)
        page = pdf.pages[0]
        
        c1, c2 = st.columns(2)
        
        # --- 診斷 1: 名字為什麼抓不到？ ---
        with c1:
            st.subheader("1. 頁首文字座標 (Header Words)")
            st.caption("這會顯示「教師」這兩個字到底在哪裡，以及它的右邊/下面有什麼字。")
            
            # 抓取頁面最上方 1/5 的所有文字
            words = page.extract_words(keep_blank_chars=True)
            header_words = [w for w in words if w['top'] < 150]
            
            # 轉換成 DataFrame 方便閱讀
            data = []
            for w in header_words:
                data.append({
                    "文字": w['text'],
                    "X (左邊界)": f"{w['x0']:.1f}",
                    "Y (上邊界)": f"{w['top']:.1f}", # Y 越小越上面
                    "寬度": f"{w['width']:.1f}"
                })
            st.dataframe(pd.DataFrame(data), height=400)

        # --- 診斷 2: 為什麼調課計算機是空的？ ---
        with c2:
            st.subheader("2. 內容文字座標 (Content Words)")
            st.caption("這會顯示「星期」與「節次」的座標，用來檢查網格是否對齊。")
            
            # 搜尋關鍵定位點
            anchors = []
            target_keywords = ["一", "二", "三", "08:", "09:", "13:", "國文", "數學"]
            
            for w in words:
                # 只要字裡面包含關鍵字，就抓出來
                txt = w['text'].replace(" ", "")
                if any(k in txt for k in target_keywords) and len(txt) < 10:
                    anchors.append({
                        "文字": w['text'],
                        "X (左)": f"{w['x0']:.1f}",
                        "Y (上)": f"{w['top']:.1f}",
                        "Y (下)": f"{w['bottom']:.1f}"
                    })
            
            if anchors:
                st.dataframe(pd.DataFrame(anchors), height=400)
            else:
                st.error("⚠️ 找不到任何關鍵字 (星期或時間)，這可能是亂碼問題！")

        # --- 診斷 3: 原始文字流 ---
        st.subheader("3. extract_text() 原始輸出")
        st.caption("程式第一眼看到的純文字內容：")
        st.text_area("Raw Text", page.extract_text(), height=200)
