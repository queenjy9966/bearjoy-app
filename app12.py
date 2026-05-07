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
# 1. 記憶功能：雲端保險箱優先 + 本機儲存備援
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

# ✨ 加上安全保護罩：避免本機端找不到保險箱而當機
default_api = ""
default_url = ""
try:
    default_api = st.secrets.get("gemini_api_key", "")
    default_url = st.secrets.get("google_sheet_url", "")
except Exception:
    pass

if not default_api or not default_url:
    local_api, local_url = load_local_config()
    default_api = default_api or local_api
    default_url = default_url or local_url

# ==========================================
# 2. BearJoy 視覺佈局
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
# 3. 雲端引擎與【智慧圖片壓縮技術】
# ==========================================
def connect_google_sheets(url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = None
        
        # 加上安全保護罩：嘗試讀取雲端機密
        try:
            if "type" in st.secrets:
                creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets), scope)
        except Exception:
            pass
            
        # 若雲端沒有機密，改讀本地檔案
        if not creds:
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

# ✨ 升級版：圖片轉 Base64 (自帶極限壓縮功能，突破 Google 5萬字元限制)
def img_to_base64(img):
    if img.mode in ("RGBA", "P"): 
        img = img.convert("RGB")
        
    img.thumbnail((450, 450), Image.Resampling.LANCZOS)
    
    buffered = BytesIO()
    img.save(buffered, format="JPEG", quality=60, optimize=True)
    b64_str = base64.b64encode(buffered.getvalue()).decode()
    
    if len(b64_str) > 48000:
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=30, optimize=True)
        b64_str = base64.b64encode(buffered.getvalue()).decode()
        
    return b64_str

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
        st.markdown("""
        <div style="background: linear-gradient(135deg, #E6E2D8 0%, #F5F3ED 100%); padding: 8px 15px; border-radius: 6px; text-align: center; margin-bottom: 15px;">
            <h2 style="color: #4A4238; margin: 0; padding: 0; font-weight: bold;">✦ BearJoy 智能客服系統 ✦</h2>
        </div>
        """, unsafe_allow_html=True)
        
        tab1, tab2 = st.tabs(["✦ 批次評價處理", "✦ VIP 顧客管理"])

        with tab1:
            col_up, col_res = st.columns([1, 1.5], gap="large")
            with col_up:
                files = st.file_uploader("上傳顧客好評截圖", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
                is_vip_check = st.checkbox("🌟 套用 VIP 老客專屬語氣")
                start_btn = st.button("開始解析並同步")
                preview_area = st.container()

            with col_res:
                top_success_msg = st.empty()
                cards_container = st.container()
                
                if start_btn and files and api_key:
                    results_to_cloud = []
                    client = genai.Client(api_key=api_key)
                    
                    system_prompt = """
                    你是一個專業的蝦皮賣場客服主管 Sharon。請精準辨識圖片中的 [ACCOUNT] 帳號與 [REVIEW] 內容。
                    
                    【極度嚴格規定】
                    1. 字數與行數必須精簡。
                    2. 務必使用分段與換行符號。
                    3. 完全模仿 BearJoy Sharon 的溫暖語氣，並加上適當的 Emoji。
                    4. 【絕對要客製化】：賣場回覆與私訊回覆中，必須「100% 精準引用」客人實際寫出的優點關鍵字。
                    
                    請依照以下標籤輸出：
                    [ACCOUNT]
                    (客戶帳號)
                    [REVIEW]
                    (評價內容)
                    [PUBLIC]
                    (賣場評價回覆)
                    [PRIVATE]
                    (私訊回覆)
                    """
                    
                    for file in files:
                        with preview_area:
                             img = Image.open(file)
                             st.image(img, caption=f"處理中: {file.name}", use_container_width=True) 
                        
                        with st.spinner(f"🏃‍♀️ AI 正在為您撰寫..."):
                            success = False
                            current_prompt = system_prompt + ("\n注意：此為二回購老客，請加入尊榮感。" if is_vip_check else "")
                            
                            models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"] 
                            for model_name in models_to_try:
                                if success: break
                                for attempt in range(3):
                                    try:
                                        time.sleep(3) 
                                        response = client.models.generate_content(model=model_name, contents=[current_prompt, img])
                                        res_text = response.text
                                        success = True
                                        break 
                                    except Exception:
                                        continue 
                            
                            if not success:
                                st.error(f"檔案 {file.name} 處理失敗。")
                                continue 
                            
                            acc = res_text.split("[ACCOUNT]")[1].split("[REVIEW]")[0].strip() if "[ACCOUNT]" in res_text else "未知"
                            rev = res_text.split("[REVIEW]")[1].split("[PUBLIC]")[0].strip() if "[REVIEW]" in res_text else "解析失敗"
                            pub = res_text.split("[PUBLIC]")[1].split("[PRIVATE]")[0].strip() if "[PUBLIC]" in res_text else "解析失敗"
                            priv = res_text.split("[PRIVATE]")[1].strip() if "[PRIVATE]" in res_text else "解析失敗"
                            now = datetime.now()
                            
                            with cards_container:
                                with st.expander(f"✨ 客戶帳號：{acc}", expanded=True):
                                    st.code(pub, language="text")
                                    st.code(priv, language="text")
                            
                            results_to_cloud.append([now.strftime("%Y-%m-%d %H:%M:%S"), acc, rev, pub, priv])
                            time.sleep(5)

                    if doc and results_to_cloud:
                        try:
                            ws_history = get_or_create_ws(doc, "回覆紀錄")
                            if len(ws_history.get_all_values()) == 0: ws_history.append_row(["紀錄時間", "客戶帳號", "原始評價內容", "賣場評價回覆", "VIP私訊回覆"])
                            ws_history.append_rows(results_to_cloud)
                            
                            ws_vip = get_or_create_ws(doc, "VIP名單")
                            if len(ws_vip.get_all_values()) == 0: ws_vip.append_row(["客戶帳號", "首次互動", "最後互動", "互動次數"])
                            vip_records = ws_vip.get_all_records()
                            date_str = datetime.now().strftime("%Y-%m-%d")
                            
                            for row in results_to_cloud:
                                account = row[1] 
                                if account == "未知": continue
                                found_index = next((i for i, r in enumerate(vip_records) if str(r.get('客戶帳號', '')) == account), -1)
                                if found_index != -1:
                                    ws_vip.update_cell(found_index + 2, 3, date_str) 
                                    ws_vip.update_cell(found_index + 2, 4, int(vip_records[found_index].get('互動次數', 0)) + 1)
                                else:
                                    ws_vip.append_row([account, date_str, date_str, 1])
                            top_success_msg.success(f"🎉 完美同步！已更新 {len(results_to_cloud)} 筆紀錄。")
                        except Exception as e:
                            st.error(f"雲端同步失敗：{e}")

        with tab2:
            if doc:
                try:
                    vip_ws = get_or_create_ws(doc, "VIP名單")
                    data = vip_ws.get_all_values()
                    if len(data) > 1: st.dataframe(pd.DataFrame(data[1:], columns=data[0]), use_container_width=True)
                except Exception as e:
                    st.error(f"讀取失敗：{e}")

    elif menu == "折價券管理":
        st.markdown("## ✦ 每月折價券管理")
        st.write("上傳的圖片將自動壓縮並同步至雲端，確保手機隨時可快速預覽與發送給客人。")
        
        ws_cfg = get_or_create_ws(doc, "系統設定")
        cfg_data = ws_cfg.get_all_records()
        
        col1, col2 = st.columns(2)
        
        for i, col in enumerate([col1, col2], 1):
            with col:
                st.markdown(f"### 折價券 Slot {i}")
                existing = next((r for r in cfg_data if r.get('參數') == f'coupon_{i}'), None)
                
                if existing and existing.get('內容'):
                    try:
                        curr_img = base64_to_img(existing['內容'])
                        # 顯示圖片
                        st.image(curr_img, use_container_width=True)
                        
                        # ✨ 加上溫馨防呆提示
                        st.caption("💡 **手機版：請直接「長按上方圖片」即可儲存至相簿。**")
                        
                        # 按鈕留給電腦版使用者
                        buf = BytesIO()
                        curr_img.save(buf, format="JPEG")
                        st.download_button(label=f"💻 電腦版下載", data=buf.getvalue(), file_name=f"BearJoy_Coupon_{i}.jpg", mime="image/jpeg", key=f"dl_{i}")
                    except Exception as e:
                        st.warning("圖片載入異常，請重新上傳")
                else:
                    st.info("尚未上傳圖片")
                
                new_file = st.file_uploader(f"更新折價券 {i}", type=["png", "jpg", "jpeg"], key=f"up_{i}")
                if new_file:
                    if st.button(f"確認更新 Slot {i}", key=f"btn_{i}"):
                        with st.spinner("壓縮圖片並同步至雲端..."):
                            b64 = img_to_base64(Image.open(new_file))
                            all_vals = ws_cfg.col_values(1)
                            
                            if len(all_vals) == 0:
                                ws_cfg.append_row(["參數", "內容"])
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