import streamlit as st
import pdfplumber
import pandas as pd

st.set_page_config(page_title="PDF 結構診斷器", layout="wide")

st.title("🔧 PDF 原始結構診斷工具")
st.info("請上傳您的課表 PDF，此工具會顯示程式眼中的原始資料。")

uploaded_file = st.file_uploader("上傳 PDF", type=["pdf"])

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        # 只分析第一頁 (通常第一頁有問題，後面都有問題)
        page = pdf.pages[0] 
        
        st.subheader("1. 原始文字 (Raw Text)")
        st.markdown("程式讀到了什麼文字？請確認關鍵字（如「星期」、「08:00」）是否變成了亂碼。")
        raw_text = page.extract_text()
        st.text_area("Raw Text Output", raw_text, height=300)
        
        st.subheader("2. 表格偵測 (Table Extraction)")
        st.markdown("程式能看到表格線嗎？")
        
        # 測試 A: 預設模式
        tables_default = page.extract_tables()
        st.write(f"預設模式抓到的表格數: {len(tables_default)}")
        if tables_default:
            st.write("預設模式 - 第一個表格的前 5 列：")
            st.table(pd.DataFrame(tables_default[0]).head(5))
        else:
            st.warning("❌ 預設模式抓不到任何表格 (可能是沒有格線)")

        # 測試 B: 文字間隙模式 (Text Strategy)
        tables_text = page.extract_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"})
        st.write(f"文字間隙模式抓到的表格數: {len(tables_text)}")
        if tables_text:
            st.write("文字間隙模式 - 第一個表格的前 5 列：")
            st.table(pd.DataFrame(tables_text[0]).head(5))
        else:
            st.warning("❌ 文字間隙模式也抓不到表格 (排版過於混亂)")
            
        st.subheader("3. 診斷結論與回報")
        st.markdown("""
        請協助確認以下資訊，並回傳給工程師：
        1. **Raw Text** 裡面，原本該是「星期一、二...」的地方，顯示為什麼字？(有亂碼嗎？)
        2. **Raw Text** 裡面，時間 (例如 08:00) 是顯示完整的數字，還是被切斷了？
        3. 上面兩種表格模式，哪一種看起來比較像原本的課表？(還是兩種都很亂？)
        """)
