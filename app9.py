import streamlit as st
from google import genai
from PIL import Image
import pandas as pd
from datetime import datetime
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

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

# ✨ 終極升級：優先從 Streamlit Secrets 抓取，讓手機版永遠不用重輸
default_api = ""
default_url = ""

try:
    if "gemini_api_key" in st.secrets:
        default_api = st.secrets["gemini_api_key"]
    if "google_sheet_url" in st.secrets:
        default_url = st.secrets["google_sheet_url"]
except Exception:
    pass

# 如果雲端沒設定，才去找本機的 config.txt
local_api, local_url = load_local_config()
if not default_api: default_api = local_api
if not default_url: default_url = local_url

# ==========================================
# 2. BearJoy 視覺佈局 (智慧推擠防重疊版)
# ==========================================
st.set_page_config(page_title="BearJoy 智能客服", page_icon="✦", layout="wide")

NAV_TOP_POSITION = "1rem"         
SETTINGS_BOTTOM_GAP = "2rem"      

st.markdown("""
<meta name="google" content="notranslate">
<style>
    .stApp { background-color: #FAF8F5; }
    html, body, h1, h2, h3, h4, p, label, .stMarkdown { 
        font-family: 'Helvetica Neue', 'Arial', 'Microsoft JhengHei', sans-serif !important; 
        color: #4A4238 !important; 
    }
    .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }
    header { display: none !important; } 
    div[data-testid="stAppViewContainer"] { opacity: 1 !important; transition: none !important; }
    .stApp > header { background-color: transparent !important; }
    
    [data-testid="stSidebar"] { background-color: #F0EDE5 !important; border-right: 1px solid #E3DFD5 !important; }
    [data-testid="stSidebarUserContent"] { 
        display: flex !important; flex-direction: column !important; height: 100vh !important; 
        position: relative !important; padding-top: """ + NAV_TOP_POSITION + """ !important; 
        padding-bottom: """ + SETTINGS_BOTTOM_GAP + """ !important; overflow-y: auto !important; overflow-x: hidden !important;
    }
    
    .spacer { flex-grow: 1 !important; min-height: 20px !important; }
    [data-testid="stSidebarUserContent"] > div:last-child { margin-top: auto !important; }
    
    div[data-testid="stExpander"] details { padding-bottom: 0px !important; }
    div[data-testid="stTextInput"] { margin-bottom: -10px !important; }
    div[data-testid="stTextInput"] label { padding-bottom: 0px !important; margin-bottom: 0px !important; font-size: 13px !important; }
    div[data-testid="stTextInput"] input { padding: 4px 8px !important; min-height: 30px !important; font-size: 13px !important; }
    
    [data-testid="stSidebar"] .stButton>button {
        background-color: #798571 !important; border-radius: 6px !important; border: none !important;
        height: 38px !important; min-height: 38px !important; padding: 0px !important; width: 100% !important; box-sizing: border-box !important;
        margin-top: 5px !important; margin-bottom: 0px !important; box-shadow: 0 2px 4px rgba(121, 133, 113, 0.2) !important; transition: all 0.3s ease; 
    }
    [data-testid="stSidebar"] .stButton>button p, [data-testid="stSidebar"] .stButton>button span {
        color: #FFFFFF !important; font-size: 16px !important; font-weight: bold !important; letter-spacing: 1px !important; margin: 0 !important;
    }
    [data-testid="stSidebar"] .stButton>button:hover { background-color: #5F6B58 !important; transform: translateY(-2px); }
    
    [data-testid="stSidebar"] div[data-testid="stAlert"] { display: none !important; }
    .custom-status-box {
        height: 38px !important; min-height: 38px !important; width: 100% !important; box-sizing: border-box !important;
        padding: 0px !important; display: flex !important; align-items: center !important; justify-content: center !important;
        border-radius: 6px !important; margin-top: 5px !important; margin-bottom: 0px !important;
        font-size: 16px !important; font-weight: bold !important; letter-spacing: 1px !important; color: #4A4238 !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
    }
    .status-success { background-color: #DCE8D6 !important; border: 1px solid #C4D4BC !important; }
    .status-warning { background-color: #F8E3D0 !important; border: 1px solid #E6C5A8 !important; }
    
    .stApp > div > div .stButton>button {
        background-color: #798571 !important; height: auto !important; min-height: 36px !important;
        padding: 6px 14px !important; font-size: 14px !important; width: auto !important; min-width: 120px !important; 
        border-radius: 6px !important; border: none !important; font-weight: bold !important; letter-spacing: 1px; transition: all 0.3s ease; box-shadow: 0 2px 4px rgba(121, 133, 113, 0.2) !important;
    }
    .stApp > div > div .stButton>button:hover { background-color: #5F6B58 !important; transform: translateY(-2px); }
    .stApp > div > div .stButton>button p, .stApp > div > div .stButton>button span { color: #FFFFFF !important; }
    
    div[data-testid="stExpander"] { border: 1px solid #EAE7E0 !important; background-color: #FFFFFF !important; border-radius: 8px !important; margin-bottom: 15px !important; box-shadow: 0 2px 10px rgba(0,0,0,0.03) !important; }
    .stCodeBlock { border-radius: 8px !important; border: 1px solid #EAE7E0 !important; background-color: #FAFAFA !important;}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 雲端雙棲連線引擎 & 全自動建表器
# ==========================================
def connect_google_sheets(url):
    if not url: return None, "請填寫試算表網址"
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = None

        try:
            if "type" in st.secrets:
                creds_dict = dict(st.secrets)
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        except Exception:
            pass 

        if not creds:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            key_path = os.path.join(current_dir, "google_key.json")
            if os.path.exists(key_path):
                creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
            else:
                return None, "找不到雲端機密或本地 google_key.json 檔案"

        if creds:
            gc = gspread.authorize(creds)
            return gc.open_by_url(url), "成功"
            
    except Exception as e:
        err = str(e)
        if "Requested entity was not found" in err or "403" in err or "404" in err or "permission" in err.lower():
            return None, "權限不足：請確認試算表已「共用」給機器人信箱！"
        elif "No valid" in err or "invalid" in err.lower() or "Empty" in err:
            return None, "網址錯誤：請確認貼上的是完整的試算表網址！"
        return None, f"連線異常: {err}"
        
    return None, "未知連線錯誤"

def get_or_create_worksheet(doc, title):
    try:
        return doc.worksheet(title)
    except gspread.WorksheetNotFound:
        return doc.add_worksheet(title=title, rows="1000", cols="20")

def format_google_sheet(ws):
    try:
        ws.format("A1:E1", {"horizontalAlignment": "CENTER", "textFormat": {"bold": True}})
        ws.format("A2:E1000", {"horizontalAlignment": "LEFT", "verticalAlignment": "TOP", "wrapStrategy": "WRAP"})
    except Exception:
        pass

# ==========================================
# 4. 側邊欄：導航菜單與自動推擠的設定
# ==========================================
with st.sidebar:
    st.markdown("### ✦ BearJoy 導航")
    menu = st.radio("功能選單", ["智能客服系統"], label_visibility="collapsed")
    
    st.markdown('<div class="spacer"></div>', unsafe_allow_html=True)
    
    with st.expander("⚙️ 設定", expanded=False):
        # 這裡會自動填入從雲端保險箱抓到的預設值
        api_key = st.text_input("API 金鑰:", value=default_api, type="password")
        sheet_url = st.text_input("試算表網址:", value=default_url)
        
        if st.button("儲存連線", use_container_width=True):
            save_config(api_key, sheet_url)
            st.rerun()
            
        doc, error_msg = connect_google_sheets(sheet_url) if sheet_url else (None, "")
        
        if doc: 
            st.markdown('<div class="custom-status-box status-success">已連線</div>', unsafe_allow_html=True)
        else: 
            st.markdown('<div class="custom-status-box status-warning">未連線</div>', unsafe_allow_html=True)
            if error_msg and error_msg != "成功" and sheet_url:
                st.markdown(f"<div style='font-size: 12px; color: #D9534F; text-align: center; margin-top: 5px; line-height: 1.2;'>⚠️ {error_msg}</div>", unsafe_allow_html=True)

# ==========================================
# 5. 主功能區
# ==========================================
if menu == "智能客服系統":
    
    st.markdown("""
    <div style="background: linear-gradient(135deg, #E6E2D8 0%, #F5F3ED 100%); padding: 8px 15px; border-radius: 6px; text-align: center; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.02);">
        <h2 style="color: #4A4238; margin: 0; padding: 0; font-weight: bold; letter-spacing: 1px;">✦ BearJoy 智能客服系統 ✦</h2>
        <p style="color: #8C877D; margin: 2px 0 0 0; font-size: 12px;">Japandi 美學 × AI 評價自動化管理</p>
    </div>
    """, unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["✦ 批次評價處理", "✦ VIP 顧客管理"])

    with tab1:
        col_up, col_res = st.columns([1, 1.5], gap="large")
        
        with col_up:
            st.markdown("<p style='font-size: 1.25rem; font-weight: bold; margin-bottom: 2px; color: #4A4238;'>上傳顧客好評截圖</p>", unsafe_allow_html=True)
            files = st.file_uploader("支援單張或多張上傳", type=["png", "jpg", "jpeg"], accept_multiple_files=True, label_visibility="collapsed")
            is_vip_check = st.checkbox("🌟 套用 VIP 老客專屬語氣")
            start_btn = st.button("開始解析並同步")
            
            st.markdown("<br>", unsafe_allow_html=True) 
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
                4. 【絕對要客製化】：賣場回覆與私訊回覆中，必須「100% 精準引用」客人實際寫出的優點關鍵字（如：出貨速度快、厚實牢固、拉鍊順滑...）。把這些字眼自然地融入回覆中，讓客人感受到您有認真讀評價！嚴禁使用「感謝您的好評」就句號的罐頭回覆。

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

                請嚴格依照以下標籤輸出：
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
                    
                    with st.spinner(f"🏃‍♀️ AI 正在為您撰寫 {file.name} 的專屬回覆..."):
                        
                        success = False
                        current_prompt = system_prompt + ("\n注意：此為二回購老客，請加入朋友般的尊榮感。" if is_vip_check else "")
                        
                        max_retries = 5 
                        models_to_try = [
                            "gemini-2.5-flash", 
                            "gemini-2.0-flash",
                            "gemini-1.5-flash",
                            "gemini-1.5-flash-8b"
                        ] 
                        
                        for model_name in models_to_try:
                            if success: break
                            
                            for attempt in range(max_retries):
                                try:
                                    wait_time = 3 + (2 ** attempt) 
                                    if attempt > 0:
                                         st.toast(f"[{model_name}] 免費通道擁擠，排隊等待 {wait_time} 秒後重試 ({attempt}/{max_retries})...", icon="⏳")
                                    time.sleep(wait_time) 
                                    
                                    response = client.models.generate_content(
                                        model=model_name, 
                                        contents=[current_prompt, img]
                                    )
                                    res_text = response.text
                                    success = True
                                    break 
                                    
                                except Exception as e:
                                    if "503" in str(e) or "429" in str(e):
                                        continue 
                                    else:
                                        break 
                        
                        if not success:
                            st.error(f"檔案 {file.name} 失敗：目前 Google 免費伺服器處於極度尖峰時段，請稍後再試。")
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
                        
                        results_to_cloud.append([
                            now.strftime("%Y-%m-%d %H:%M:%S"), acc, rev, pub, priv
                        ])

                        time.sleep(6)

                if doc and results_to_cloud:
                    try:
                        ws_history = get_or_create_worksheet(doc, "回覆紀錄")
                        
                        if len(ws_history.get_all_values()) == 0:
                            ws_history.append_row(["紀錄時間", "客戶帳號", "原始評價內容", "賣場評價回覆", "VIP私訊回覆"])
                            
                        ws_history.append_rows(results_to_cloud)
                        format_google_sheet(ws_history)
                        
                        ws_vip = get_or_create_worksheet(doc, "VIP名單")
                        
                        if len(ws_vip.get_all_values()) == 0:
                            ws_vip.append_row(["客戶帳號", "首次互動", "最後互動", "互動次數"])
                            
                        vip_records = ws_vip.get_all_records()
                        date_str = datetime.now().strftime("%Y-%m-%d")
                        
                        for row in results_to_cloud:
                            account = row[1] 
                            if account == "未知": continue
                            found_index = next((i for i, r in enumerate(vip_records) if str(r.get('客戶帳號', '')) == account), -1)
                            if found_index != -1:
                                current_count = int(vip_records[found_index].get('互動次數', 0))
                                ws_vip.update_cell(found_index + 2, 3, date_str) 
                                ws_vip.update_cell(found_index + 2, 4, current_count + 1)
                            else:
                                ws_vip.append_row([account, date_str, date_str, 1])
                                
                        top_success_msg.success(f"🎉 完美同步！已將 {len(results_to_cloud)} 筆紀錄更新至雲端資料庫。")
                    except Exception as e:
                        st.error(f"雲端同步失敗：請確認試算表格式是否正確。({e})")

    with tab2:
        st.subheader("VIP 顧客戰情室")
        if doc:
            try:
                vip_ws = get_or_create_worksheet(doc, "VIP名單")
                data = vip_ws.get_all_values()
                if data and len(data) > 1:
                    df = pd.DataFrame(data[1:], columns=data[0])
                    st.dataframe(df, use_container_width=True)
                else:
                    st.info("目前 VIP 名單尚無資料，趕快去解析第一筆評價吧！")
            except Exception as e:
                st.error(f"讀取失敗：{e}")
        else:
            st.info("請先連線 Google 試算表。")
