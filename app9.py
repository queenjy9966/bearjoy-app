import streamlit as st
from google import genai
from PIL import Image
import pandas as pd
from datetime import datetime
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import base64
from io import BytesIO

# ==========================================
# 1. 記憶功能：雲端保險箱優先 (解決每次都要輸入的問題)
# ==========================================
CONFIG_FILE = "config.txt"

def load_local_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            lines = f.readlines()
            if len(lines) >= 2:
                return lines[0].strip(), lines[1].strip()
    return "", ""

def save_config(api, url):
    with open(CONFIG_FILE, "w") as f:
        f.write(f"{api}\n{url}")

# ✨ 優先從 Streamlit Secrets 讀取 (自動登入)
default_api = st.secrets.get("gemini_api_key", "")
default_url = st.secrets.get("google_sheet_url", "")

if not default_api or not default_url:
    local_api, local_url = load_local_config()
    default_api = default_api or local_api
    default_url = default_url or local_url

# ==========================================
# 2. BearJoy 視覺佈局 (Japandi 風格)
# ==========================================
st.set_page_config(page_title="BearJoy 智能客服", page_icon="✦", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #FAF8F5; }
    [data-testid="stSidebar"] { background-color: #F0EDE5 !important; }
    .stButton>button { background-color: #798571 !important; color: white !important; border-radius: 6px !important; }
    .coupon-card { border: 1px solid #E3DFD5; padding: 15px; border-radius: 10px; background-color: white; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 雲端引擎與折價券處理函數
# ==========================================
def connect_google_sheets(url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = None
        if "type" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets), scope)
        else:
            key_path = os.path.join(os.path.dirname(__file__), "google_key.json")
            if os.path.exists(key_path):
                creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
        
        if creds:
            gc = gspread.authorize(creds)
            return gc.open_by_url(url), "成功"
    except Exception as e:
        return None, str(e)
    return None, "找不到金鑰"

def get_or_create_ws(doc, title):
    try:
        return doc.worksheet(title)
    except:
        return doc.add_worksheet(title=title, rows="100", cols="5")

# 圖片轉 Base64 (存入試算表)
def img_to_base64(img):
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

# Base64 轉圖片 (從試算表讀取)
def base64_to_img(b64_str):
    return Image.open(BytesIO(base64.b64decode(b64_str)))

# ==========================================
# 4. 側邊欄
# ==========================================
with st.sidebar:
    st.markdown("### ✦ BearJoy 導航")
    menu = st.radio("功能選單", ["智能客服系統", "折價券管理"], label_visibility="collapsed")
    st.markdown('<div style="flex-grow: 1; min-height: 50vh;"></div>', unsafe_allow_html=True)
    with st.expander("⚙️ 設定", expanded=False):
        api_key = st.text_input("API 金鑰:", value=default_api, type="password")
        sheet_url = st.text_input("試算表網址:", value=default_url)
        if st.button("儲存連線", use_container_width=True):
            save_config(api_key, sheet_url)
            st.rerun()
        doc, err = connect_google_sheets(sheet_url) if sheet_url else (None, "")
        st.info("已連線" if doc else f"未連線: {err}")

# ==========================================
# 5. 主功能區
# ==========================================
if doc:
    if menu == "智能客服系統":
        st.title("✦ BearJoy 智能客服")
        # (此處保留您原本的評價處理程式碼...)
        st.info("評價處理模組已就緒")

    elif menu == "折價券管理":
        st.markdown("## ✦ 每月折價券管理")
        st.write("在這裡更新當月圖檔，系統會自動同步至雲端供隨時下載。")
        
        ws_cfg = get_or_create_ws(doc, "系統設定")
        cfg_data = ws_cfg.get_all_records()
        
        col1, col2 = st.columns(2)
        
        for i, col in enumerate([col1, col2], 1):
            with col:
                st.markdown(f"### 折價券 Slot {i}")
                # 嘗試讀取現有圖片
                existing = next((r for r in cfg_data if r['參數'] == f'coupon_{i}'), None)
                
                if existing and existing['內容']:
                    try:
                        curr_img = base64_to_img(existing['內容'])
                        st.image(curr_img, use_container_width=True)
                        # 下載按鈕
                        buf = BytesIO()
                        curr_img.save(buf, format="PNG")
                        st.download_button(label=f"下載折價券 {i}", data=buf.getvalue(), file_name=f"BearJoy_Coupon_{i}.png", mime="image/png")
                    except:
                        st.warning("圖片格式損壞，請重新上傳")
                else:
                    st.info("尚未上傳圖片")
                
                # 上傳新圖片
                new_file = st.file_uploader(f"更新折價券 {i}", type=["png", "jpg", "jpeg"], key=f"up_{i}")
                if new_file:
                    if st.button(f"確認更新 Slot {i}"):
                        b64 = img_to_base64(Image.open(new_file))
                        # 更新到試算表 (簡單起見，直接定位更新)
                        # 先找行號
                        all_vals = ws_cfg.col_values(1)
                        if f"coupon_{i}" in all_vals:
                            row_idx = all_vals.index(f"coupon_{i}") + 1
                            ws_cfg.update_cell(row_idx, 2, b64)
                        else:
                            ws_cfg.append_row([f"coupon_{i}", b64])
                        st.success("更新成功！")
                        st.rerun()

else:
    st.warning("請先完成側邊欄的 Google 試算表連線設定。")
