import streamlit as st
from google import genai
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
from datetime import datetime
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import base64
from io import BytesIO
import urllib.request
import threading

# ==========================================
# 0. 系統資源：自動下載高質感中文字體
# ==========================================
@st.cache_resource
def get_chinese_font(size):
    font_path = "NotoSansTC-Bold.otf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Bold.otf"
            urllib.request.urlretrieve(url, font_path)
        except: pass
    try:
        return ImageFont.truetype(font_path, size)
    except:
        return ImageFont.load_default()

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
    .block-container { padding-top: 2.5rem !important; padding-bottom: 1rem !important; }
    
    [data-testid="stSidebar"] { background-color: #F0EDE5 !important; }
    .stButton>button { background-color: #798571 !important; color: white !important; border-radius: 6px !important; }
    div[data-testid="stSlider"] label { font-weight: bold !important; color: #798571 !important; }
    [data-testid="stImage"] { display: flex; justify-content: center; }
    
    .main-title-box {
        background: linear-gradient(135deg, #E6E2D8 0%, #F5F3ED 100%); 
        padding: 12px 15px; border-radius: 6px; text-align: center; margin-bottom: 15px; 
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
    }
    .main-title-text { color: #4A4238; margin: 0; padding: 0; font-weight: bold; font-size: 22px; letter-spacing: 1px; }
    .sub-title-text { color: #4A4238; font-weight: bold; font-size: 16px; margin: 0; }
    
    .stDownloadButton { margin-bottom: -15px !important; margin-top: -10px !important; }
    div[data-testid="stFileUploader"] { margin-bottom: -15px !important; }
    div[data-testid="stExpander"] { margin-bottom: 5px !important; }
    
    @media (max-width: 640px) {
        .element-container:has(span.title-del-row) + .element-container div[data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important; align-items: center !important; margin-bottom: 5px !important;
        }
        .element-container:has(span.title-del-row) + .element-container div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            min-width: 0 !important; width: auto !important; padding: 0 2px !important;
        }
        .element-container:has(span.title-del-row) + .element-container div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child {
            flex: 1 !important; 
        }
        .element-container:has(span.title-del-row) + .element-container div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:not(:first-child) {
            flex: 0 0 auto !important; margin-top: 0px !important;
        }
    }
    
    .ctrl-btn-style button {
        padding: 0px 5px !important; min-height: 28px !important; height: 28px !important;
        font-size: 13px !important; color: #4A4238 !important; border: 1px solid #D0CCC1 !important;
    }
    .btn-move button { background-color: #E3DFD5 !important; }
    .btn-move button:hover { background-color: #D0CCC1 !important; }
    .btn-del button { background-color: #E6C5A8 !important; border: 1px solid #D9B391 !important;}
    .btn-del button:hover { background-color: #D9B391 !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 雲端引擎與【無損畫質切割儲存技術】
# ==========================================
def connect_google_sheets(url):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = None
        try:
            if "type" in st.secrets:
                creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets), scope)
        except Exception: pass
            
        if not creds:
            key_path = os.path.join(os.path.dirname(__file__), "google_key.json")
            if os.path.exists(key_path):
                creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
        
        if creds:
            gc = gspread.authorize(creds)
            return gc.open_by_url(url), "成功"
    except Exception as e: return None, str(e)
    return None, "找不到金鑰"

def get_or_create_ws(doc, title):
    try: return doc.worksheet(title)
    except: return doc.add_worksheet(title=title, rows="100", cols="10")

def img_to_base64_chunks(img):
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    buffered = BytesIO()
    img.save(buffered, format="JPEG", quality=90, optimize=True)
    b64_str = base64.b64encode(buffered.getvalue()).decode()
    
    return [b64_str[i:i+45000] for i in range(0, len(b64_str), 45000)]

def base64_chunks_to_img(chunks):
    b64_str = "".join(chunks)
    return Image.open(BytesIO(base64.b64decode(b64_str)))

def threaded_update_order(creds_dict, sheet_url, order_str):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if creds_dict:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            key_path = os.path.join(os.path.dirname(__file__), "google_key.json")
            creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
        gc = gspread.authorize(creds)
        doc = gc.open_by_url(sheet_url)
        ws = doc.worksheet("系統設定")
        all_vals = ws.col_values(1)
        if "coupon_order" in all_vals:
            idx = all_vals.index("coupon_order") + 1
            ws.update_cell(idx, 2, order_str)
        else:
            ws.append_row(["coupon_order", order_str])
    except Exception: pass

def trigger_order_save(url, active_slots):
    # ✨ 修正：加上安全防護罩，避免本機找不到保險箱時引發錯誤
    creds_dict = None
    try:
        if "type" in st.secrets:
            creds_dict = dict(st.secrets)
    except Exception:
        pass
        
    order_str = ",".join(map(str, active_slots))
    threading.Thread(target=threaded_update_order, args=(creds_dict, url, order_str)).start()

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
        <div class="main-title-box">
            <h2 class="main-title-text">✦ BearJoy 智能客服系統 ✦</h2>
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
                    1. 字數與行數「必須」與下方範例長度一致，絕不可自行長篇大論！
                    2. 務必使用分段與換行符號，保持版面清爽舒適。
                    3. 完全模仿 BearJoy Sharon 的溫暖語氣，並加上適當的 Emoji。
                    4. 【絕對要客製化】：賣場回覆與私訊回覆中，必須「100% 精準引用」客人實際寫出的優點關鍵字。
                    
                    [範例評價]：非常好用，厚的材質...回購第二次
                    [範例賣場回覆]：
                    親愛的顧客您好，

                    感謝您的五星好評與再次回購！🌟
                    很高興厚實的材質能讓您覺得方便。👶
                    謝謝您肯定我們的品質，
                    非常珍貴像您這樣用心回饋的好顧客！❤️
                    期待未來能繼續為您服務。

                    —— BearJoy Sharon

                    [範例私訊回覆]：
                    親愛的 (客戶帳號)，

                    感謝您撥空寫下如此詳細的評價！
                    看到您滿意我們的厚實材質與實用性，我們非常感動。🥰
                    為了表達萬分謝意，已將您列入VIP客戶名單！✨
                    未來若有專屬優惠定會第一時間發送給您。🎁
                    再次感謝支持！

                    —— BearJoy Sharon

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
                             st.image(img, caption=f"處理中: {file.name}", width=300) 
                        
                        with st.spinner(f"🏃‍♀️ AI 正在為您撰寫..."):
                            success = False
                            current_prompt = system_prompt + ("\n注意：此為二回購老客，請加入朋友般的尊榮感。" if is_vip_check else "")
                            models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"] 
                            for model_name in models_to_try:
                                if success: break
                                for attempt in range(4):
                                    try:
                                        time.sleep(3) 
                                        response = client.models.generate_content(model=model_name, contents=[current_prompt, img])
                                        res_text = response.text
                                        success = True
                                        break 
                                    except Exception: continue 
                            
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
                                    st.markdown(f"**📝 原始評價內容:** {rev}")
                                    st.markdown("**📢 賣場回覆 (點擊右上角複製):**")
                                    st.code(pub, language="text")
                                    st.markdown("**💌 私訊回覆 (點擊右上角複製):**")
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
                            top_success_msg.success(f"🎉 完美同步！已將 {len(results_to_cloud)} 筆紀錄更新至雲端資料庫。")
                        except Exception as e:
                            st.error(f"雲端同步失敗：請確認試算表格式是否正確。({e})")

        with tab2:
            st.subheader("VIP 顧客戰情室")
            if doc:
                try:
                    vip_ws = get_or_create_ws(doc, "VIP名單")
                    data = vip_ws.get_all_values()
                    if len(data) > 1: st.dataframe(pd.DataFrame(data[1:], columns=data[0]), use_container_width=True)
                    else: st.info("目前 VIP 名單尚無資料，趕快去解析第一筆評價吧！")
                except Exception as e:
                    st.error(f"讀取失敗：{e}")

    # ==========================================
    # ✨ 動態文字壓印版：折價券管理
    # ==========================================
    elif menu == "折價券管理":
        st.markdown("""
        <div class="main-title-box">
            <h2 class="main-title-text">✦ 動態日期折價券管理 ✦</h2>
        </div>
        """, unsafe_allow_html=True)
        
        ws_cfg = get_or_create_ws(doc, "系統設定")
        
        if "cfg_data" not in st.session_state or st.session_state.get("refresh_cfg", True):
            st.session_state.cfg_data = ws_cfg.get_all_values()
            st.session_state.refresh_cfg = False
        cfg_data = st.session_state.cfg_data
        
        if "active_slots" not in st.session_state:
            order_row = next((r for r in cfg_data if len(r) > 1 and r[0] == 'coupon_order'), None)
            if order_row:
                raw_slots = [int(x) for x in order_row[1].split(",") if x]
                st.session_state.active_slots = list(dict.fromkeys(raw_slots))
            else:
                existing_ids = [int(r[0].split('_')[1]) for r in cfg_data if len(r) > 0 and str(r[0]).startswith('coupon_')]
                st.session_state.active_slots = sorted(list(set(existing_ids))) if existing_ids else [1, 2]
            
        c_add, c_space = st.columns([2, 5])
        with c_add:
            if st.button("➕ 新增一個全新版位", type="primary", use_container_width=True):
                next_id = 1
                while next_id in st.session_state.active_slots:
                    next_id += 1
                st.session_state.active_slots.append(next_id)
                trigger_order_save(sheet_url, st.session_state.active_slots)
                st.rerun()
        
        display_idx = 0
        for slot_id in st.session_state.active_slots:
            idx = st.session_state.active_slots.index(slot_id)
            is_first = (idx == 0)
            is_last = (idx == len(st.session_state.active_slots) - 1)
            
            if display_idx % 2 == 0:
                col1, col2 = st.columns(2, gap="medium")
                current_col = col1
            else:
                current_col = col2
            display_idx += 1
                
            with current_col:
                st.markdown('<span class="title-del-row"></span>', unsafe_allow_html=True)
                
                c_title, c_up, c_down, c_del = st.columns([3.5, 0.8, 0.8, 1.5])
                with c_title:
                    st.markdown(f"<p class='sub-title-text'>🎟️ 折價券版位 {slot_id}</p>", unsafe_allow_html=True)
                with c_up:
                    st.markdown('<div class="ctrl-btn-style btn-move">', unsafe_allow_html=True)
                    if st.button("🔼", key=f"up_btn_{slot_id}", disabled=is_first, help="往前移"):
                        st.session_state.active_slots[idx], st.session_state.active_slots[idx-1] = st.session_state.active_slots[idx-1], st.session_state.active_slots[idx]
                        trigger_order_save(sheet_url, st.session_state.active_slots)
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                with c_down:
                    st.markdown('<div class="ctrl-btn-style btn-move">', unsafe_allow_html=True)
                    if st.button("🔽", key=f"dn_btn_{slot_id}", disabled=is_last, help="往後移"):
                        st.session_state.active_slots[idx], st.session_state.active_slots[idx+1] = st.session_state.active_slots[idx+1], st.session_state.active_slots[idx]
                        trigger_order_save(sheet_url, st.session_state.active_slots)
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                with c_del:
                    st.markdown('<div class="ctrl-btn-style btn-del">', unsafe_allow_html=True)
                    if st.button("🗑️ 刪除", key=f"del_btn_{slot_id}"):
                        rows_to_del = [i + 1 for i, r in enumerate(cfg_data) if r and r[0] == f"coupon_{slot_id}"]
                        if rows_to_del:
                            with st.spinner("刪除中..."):
                                for row_index in sorted(rows_to_del, reverse=True):
                                    ws_cfg.delete_rows(row_index)
                                st.session_state.refresh_cfg = True
                        st.session_state.active_slots.remove(slot_id)
                        trigger_order_save(sheet_url, st.session_state.active_slots)
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                
                base_img = None
                
                existing_row = next((r for r in cfg_data if len(r) > 0 and r[0] == f'coupon_{slot_id}'), None)
                if existing_row and len(existing_row) > 1:
                    try:
                        chunks = [c for c in existing_row[1:] if c] 
                        base_img = base64_chunks_to_img(chunks)
                        st.image(base_img, width=300)
                        st.caption("💡 **手機版：請直接「長按圖片」即可儲存。**")
                        
                        buf = BytesIO()
                        base_img.save(buf, format="JPEG", quality=100)
                        st.download_button(label=f"💻 電腦版下載", data=buf.getvalue(), file_name=f"BearJoy_Coupon_{slot_id}.jpg", mime="image/jpeg", key=f"dl_btn_{slot_id}")
                    except Exception: st.warning("圖片載入異常，請重新上傳")
                else:
                    st.info("此版位目前為空，請先上傳底圖。")
                
                new_file = st.file_uploader(f"更換版位 {slot_id} 圖片", type=["png", "jpg", "jpeg"], key=f"up_file_{slot_id}", label_visibility="collapsed")
                
                if new_file:
                    base_img = Image.open(new_file)
                
                if base_img:
                    with st.expander(f"✨ 開啟壓印控制台 (版位 {slot_id})", expanded=bool(new_file)):
                        if not new_file:
                            st.caption("⚠️ **溫馨提示：** 目前使用的是舊圖，若直接壓印，新字會疊在舊字上。建議上傳「乾淨空白底圖」再壓印。")
                        
                        enable_text = st.checkbox("✒️ 啟動文字壓印", value=True, key=f"en_txt_{slot_id}")
                        final_img_to_save = base_img 
                        
                        if enable_text:
                            text_input = st.text_area("輸入文字 (可換行)", value="折扣碼: BEIBHD20\n(請留意效期至 6/30)", key=f"txt_{slot_id}")
                            
                            c_s, c_c, c_r = st.columns([1.2, 1, 1.2])
                            font_size = c_s.slider("📐 字體", 10, 200, 65, key=f"sz_{slot_id}")
                            text_color = c_c.color_picker("🎨 顏色", "#FFFFFF", key=f"col_{slot_id}")
                            rotation_angle = c_r.slider("🔄 旋轉", -180, 180, 0, key=f"rot_{slot_id}")
                            
                            c_x, c_y = st.columns(2)
                            x_pos = c_x.slider("↔️ 左右", 0, base_img.width, base_img.width//2, key=f"x_{slot_id}")
                            y_pos = c_y.slider("↕️ 上下", 0, base_img.height, int(base_img.height*0.7), key=f"y_{slot_id}")
                            
                            preview_img = base_img.copy().convert("RGBA")
                            font = get_chinese_font(font_size)
                            
                            dummy_draw = ImageDraw.Draw(Image.new('RGBA', (1,1)))
                            try:
                                bbox = dummy_draw.multiline_textbbox((0, 0), text_input, font=font, align="center")
                                text_w = bbox[2] - bbox[0]
                                text_h = bbox[3] - bbox[1]
                            except:
                                text_w, text_h = 200, 100 

                            txt_layer_w = int(text_w * 2.5)
                            txt_layer_h = int(text_h * 2.5)
                            txt_img = Image.new('RGBA', (txt_layer_w, txt_layer_h), (255, 255, 255, 0))
                            txt_draw = ImageDraw.Draw(txt_img)

                            try:
                                txt_draw.multiline_text((txt_layer_w/2 - text_w/2, txt_layer_h/2 - text_h/2), text_input, fill=text_color, font=font, align="center")
                            except:
                                txt_draw.text((txt_layer_w/2 - text_w/2, txt_layer_h/2 - text_h/2), text_input, fill=text_color, font=font)

                            rotated_txt = txt_img.rotate(-rotation_angle, expand=True, resample=Image.BICUBIC)
                            paste_x = int(x_pos - rotated_txt.width / 2)
                            paste_y = int(y_pos - rotated_txt.height / 2)

                            preview_img.alpha_composite(rotated_txt, (paste_x, paste_y))
                            final_img_to_save = preview_img.convert("RGB")
                            
                            st.markdown("**👇 壓印即時預覽:**")
                            st.image(final_img_to_save, width=300) 
                        else:
                            st.markdown("**👇 原始圖片預覽:**")
                            st.image(base_img, width=300)
                            
                        if st.button(f"✅ 確認儲存", type="primary", use_container_width=True, key=f"btn_save_{slot_id}"):
                            with st.spinner("高畫質切塊處理中，並同步至雲端..."):
                                chunks = img_to_base64_chunks(final_img_to_save)
                                row_data = [f"coupon_{slot_id}"] + chunks
                                
                                rows_to_del = [i + 1 for i, r in enumerate(cfg_data) if r and r[0] == f"coupon_{slot_id}"]
                                if rows_to_del:
                                    for row_index in sorted(rows_to_del, reverse=True):
                                        ws_cfg.delete_rows(row_index)
                                ws_cfg.append_row(row_data)
                                
                                st.session_state.refresh_cfg = True
                                st.success("更新成功！")
                                st.rerun()

                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

else:
    st.warning("請先完成側邊欄的 Google 試算表連線設定。")
