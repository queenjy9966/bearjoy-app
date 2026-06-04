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
import calendar

# 點圖定位元件（沒裝成功就自動退回拉桿，不影響其他功能）
try:
    from streamlit_image_coordinates import streamlit_image_coordinates as st_image_coordinates
    HAS_IMG_COORDS = True
except Exception:
    HAS_IMG_COORDS = False

# ==========================================
# 0. 系統資源：自動下載高質感中文字體
# ==========================================
@st.cache_resource
def get_chinese_font(size):
    font_path = "NotoSansTC-Bold.otf"
    if not os.path.exists(font_path):
        try:
            url = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Bold.otf"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response, open(font_path, 'wb') as out_file:
                out_file.write(response.read())
        except Exception: pass
    
    try:
        return ImageFont.truetype(font_path, size)
    except:
        local_fonts = ["C:\\Windows\\Fonts\\msjh.ttc", "C:\\Windows\\Fonts\\msjh.ttf", "/System/Library/Fonts/PingFang.ttc"]
        for f in local_fonts:
            if os.path.exists(f):
                try: return ImageFont.truetype(f, size)
                except: continue
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

# ✨ 隱形防護網：加上 Try-Except 避免本機找不到 Secrets 時當機
api_key = ""
sheet_url = ""

try:
    api_key = st.secrets.get("gemini_api_key", "")
    sheet_url = st.secrets.get("google_sheet_url", "")
except Exception:
    pass # 找不到 Secrets 時安靜忽略，不跳紅字

# 如果雲端沒設定，就抓本機的備用設定
if not api_key or not sheet_url:
    local_api, local_url = load_local_config()
    api_key = api_key or local_api
    sheet_url = sheet_url or local_url

# ==========================================
# 2. BearJoy 視覺佈局與終極防護 CSS
# ==========================================
st.set_page_config(page_title="BearJoy 智能客服", page_icon="✦", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #FAF8F5; }
    .block-container { padding-top: 2.9rem !important; padding-bottom: 1rem !important; max-width: 1100px; }

    /* ✨ 字級層次：大標 → 中標 → 小標 → 註解小字，一眼分得出輕重 */
    /* ✨ 小標統一：所有區塊標題同一大小、同一左側細色條（與 VIP 顧客戰情室一致，前面不放 emoji 圖案） */
    h1, h2, h3, h4, h5, h6 { font-size: 16.5px !important; line-height: 1.35 !important; margin: 0.35rem 0 0.3rem 0 !important; color: #4A4238 !important; font-weight: 700 !important; letter-spacing: 0.3px !important; }
    h3, h4, h5, h6 { border-left: 3px solid #B7A98C !important; padding-left: 9px !important; }
    [data-testid="stMarkdownContainer"] p { margin-bottom: 0.35rem !important; line-height: 1.5 !important; color: #4A4238 !important; }
    /* 註解小字：說明性文字，灰、小、不搶眼 */
    [data-testid="stCaptionContainer"] { font-size: 11.5px !important; color: #A39C90 !important; line-height: 1.4 !important; }
    hr { margin: 0.7rem 0 !important; border-color: #E6E2D8 !important; }
    [data-testid="stVerticalBlock"] { gap: 0.55rem !important; }
    /* 分頁籤縮小、清爽，選中態更明顯 */
    [data-testid="stTabs"] button[role="tab"] { font-size: 14px !important; padding: 7px 14px !important; font-weight: 600 !important; }
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color: #4A4238 !important; font-weight: 700 !important; }

    [data-testid="stSidebar"] { background-color: #F0EDE5 !important; }
    /* 側欄標題（✦ BearJoy 導航）不要左側線條 */
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4, [data-testid="stSidebar"] h5, [data-testid="stSidebar"] h6 {
        border-left: none !important; padding-left: 0 !important;
    }
    .stButton>button { background-color: #798571 !important; color: white !important; border-radius: 6px !important; }
    [data-testid="stImage"] { display: flex; justify-content: center; }
    /* ✨ 勾選框文字一排不換行（回購語氣／保存截圖） */
    [data-testid="stCheckbox"] label { white-space: nowrap !important; }
    [data-testid="stCheckbox"] label p { white-space: nowrap !important; font-size: 13.5px !important; margin: 0 !important; }
    /* ✨ 折價券下載鍵：維持原本窄寬度（不套用全站 240px），讓旁邊長按提示不被擠到重疊 */
    div[data-testid="stHorizontalBlock"]:has(.coupon-dl-narrow) .stDownloadButton > button {
        width: auto !important; min-width: 84px !important; max-width: 140px !important;
        padding: 0 14px !important;
    }

    .main-title-box {
        background: #EFEBE2;
        padding: 20px 22px; border-radius: 10px; margin: 0 0 16px 0;
        border: 1px solid #DED8CC; box-sizing: border-box; width: 100%; overflow: visible;
        display: flex; align-items: center; justify-content: center; min-height: 70px;
    }
    .main-title-text { color: #4A4238 !important; margin: 0 !important; padding: 0 !important; font-weight: bold !important; font-size: 23px !important; letter-spacing: 1px !important; line-height: 1.5 !important; border: none !important; text-align: center !important; }
    .sub-title-text { color: #4A4238; font-weight: bold; font-size: 14px; margin: 0; }
    
    div[data-testid="stFileUploader"] { margin-bottom: -15px !important; margin-top: 5px !important; }
    div[data-testid="stExpander"] { margin-bottom: 5px !important; }
    
    /* ========================================================= */
    /* ✨ 錨點魔法 1：下載鈕與操控按鈕，絕對強制「水平同一行」 */
    /* ========================================================= */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        margin-top: 2px !important;
        margin-bottom: 6px !important;
        gap: 8px !important;
        width: 100% !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(1) {
        flex: 1 1 0 !important;
        width: auto !important;
        min-width: 0 !important;
        padding: 0 !important;
    }

    /* 強制鎖死後三個欄位為 40px (手機手指好按) */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(n+2) {
        flex: 0 0 40px !important;
        width: 40px !important;
        min-width: 40px !important;
        max-width: 40px !important;
        padding: 0 !important;
    }
    
    /* 下載按鈕的精準對齊 */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) .stDownloadButton { margin: 0 !important; width: 100% !important;}
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) .stDownloadButton button {
        height: 40px !important; min-height: 40px !important; padding: 0 10px !important;
        width: 100% !important; margin: 0 !important; font-size: 14px !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
    }
    
    /* ✨ 小正方形操控按鈕：統一底色塊＋白字，尺寸一致、文字置中 */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(n+2) div.stButton > button {
        background: #798571 !important;
        border: none !important;
        border-radius: 6px !important;
        color: #FFFFFF !important;
        font-size: 18px !important;
        font-weight: bold !important;
        padding: 0 !important;
        width: 40px !important; min-width: 40px !important; max-width: 40px !important;
        height: 40px !important; min-height: 40px !important; max-height: 40px !important;
        display: flex !important; justify-content: center !important; align-items: center !important;
        margin: 0 !important;
        box-shadow: none !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(n+2) div.stButton > button:hover {
        background: #687560 !important; color: #FFFFFF !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(n+2) div.stButton > button:disabled {
        opacity: 1 !important; color: #FFFFFF !important;
    }
    /* ✨ 三鍵大地色系（每個版位都一致）：↑上移＝卡其、↓下移＝大地綠、✕刪除＝大地紅，白字 */
    /* ↑ 上移：卡其 */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(2) div.stButton > button {
        background: #A38F5A !important; color: #FFFFFF !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(2) div.stButton > button:hover {
        background: #8E7C4C !important;
    }
    /* ↓ 下移：大地綠 */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(3) div.stButton > button {
        background: #798571 !important; color: #FFFFFF !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(3) div.stButton > button:hover {
        background: #687560 !important;
    }
    /* ✕ 刪除：大地紅 */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(4) div.stButton > button {
        background: #B0746A !important; color: #FFFFFF !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(4) div.stButton > button:hover {
        background: #9C6359 !important;
    }

    /* ========================================================= */
    /* ✨ 錨點魔法 2：文字方框拉長，顏色調整紐靠右，絕對強制「水平同一行」 */
    /* ========================================================= */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-txt):not(:has(.coupon-grid-anchor)) {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: flex-end !important;
        margin-bottom: 0px !important;
        gap: 8px !important;
        width: 100% !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-txt):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(1) {
        flex: 1 1 0 !important;
        width: auto !important;
        min-width: 0 !important;
        padding: 0 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-txt):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(2) {
        flex: 0 0 45px !important; 
        width: 45px !important; 
        min-width: 45px !important; 
        max-width: 45px !important;
        padding: 0 !important;
        padding-bottom: 2px !important;
    }
    
    div[data-testid="stTextArea"] label, div[data-testid="stColorPicker"] label {
        font-size: 13px !important; font-weight: bold !important; color: #798571 !important;
        margin-bottom: 4px !important; padding: 0 !important; white-space: nowrap !important;
    }
    div[data-testid="stTextArea"] textarea { min-height: 52px !important; height: 52px !important; padding: 6px 10px !important; }
    div[data-testid="stColorPicker"] { margin-top: 0px !important; display: flex; flex-direction: column; justify-content: flex-end; align-items: flex-end;}
    div[data-testid="stColorPicker"] div[role="button"] { width: 34px !important; height: 34px !important; padding: 0 !important; border-radius: 4px !important; }

    /* ========================================================= */
    /* 拉桿(BAR)對齊優化 */
    /* ========================================================= */
    div[data-testid="stSlider"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
        align-items: center !important; margin-bottom: -5px !important;
    }
    div[data-testid="stSlider"] > label {
        flex: 0 0 auto !important; width: 60px !important; margin-bottom: 0px !important;
        margin-right: 5px !important; font-size: 13px !important; font-weight: bold !important;
        color: #798571 !important; white-space: nowrap !important;
    }
    div[data-testid="stSlider"] > div { flex: 1 1 auto !important; }

    /* ========================================================= */
    /* ✨ 手機優化：折價券改單欄全寬，按鈕排才不會被擠到跑版 */
    /* ========================================================= */
    @media (max-width: 820px) {
        /* 折價券左右兩欄 → 改成上下單欄，每張券吃滿整個螢幕寬 */
        div[data-testid="stHorizontalBlock"]:has(.coupon-grid-anchor) {
            flex-direction: column !important;
            gap: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.coupon-grid-anchor) > div:is([data-testid="column"],[data-testid="stColumn"]) {
            flex: 1 1 100% !important;
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }
        /* 大小/旋轉、左右/上下 這幾組拉桿在手機上也改成單欄，比較好拖 */
        div[data-testid="stHorizontalBlock"]:has(.slider-pair-anchor):not(:has(.coupon-grid-anchor)) {
            flex-direction: column !important;
            gap: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.slider-pair-anchor):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]) {
            flex: 1 1 100% !important;
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }
    }

    /* ========================================================= */
    /* ✨ 新增：按鈕統一大小 + 折價券版位色塊區隔 */
    /* ========================================================= */
    /* ✨ 按鈕統一規格：底色塊（綠）、白字、固定高度、文字置中（折價券小方塊鍵有自己的規則，不受影響） */
    .stButton > button, .stDownloadButton > button {
        background-color: #798571 !important; color: #FFFFFF !important;
        border: none !important; border-radius: 6px !important;
        height: 42px !important; min-height: 42px !important;
        /* ✨ 全站按鈕寬度一致：固定 240px；空間不足時最多撐滿容器，不會破版 */
        width: 240px !important; max-width: 100% !important;
        font-size: 14px !important; font-weight: 600 !important;
        padding: 0 16px !important;
        display: inline-flex !important; align-items: center !important; justify-content: center !important;
        text-align: center !important; line-height: 1.2 !important;
        box-shadow: none !important;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        background-color: #687560 !important; color: #FFFFFF !important;
    }
    .stButton > button:disabled {
        background-color: #C9C4B8 !important; color: #FFFFFF !important;
    }
    /* ✨ 按鈕內所有文字一律白色、置中（含 Streamlit 把文字包進 <p>/<span> 的情況） */
    .stButton > button *, .stDownloadButton > button * { color: #FFFFFF !important; }
    .stButton > button p, .stDownloadButton > button p,
    .stButton > button div, .stDownloadButton > button div {
        margin: 0 !important; text-align: center !important;
        width: 100% !important; display: flex !important;
        align-items: center !important; justify-content: center !important;
    }
    /* 折價券那一排的下載鍵維持原欄寬，不被上面的限制縮短 */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn) .stDownloadButton > button {
        max-width: none !important;
    }
    /* ✨ 折價券：每個版位包成米色卡片，清楚分辨哪些按鈕屬於哪個版位 */
    div:is([data-testid="column"],[data-testid="stColumn"]):has(.coupon-grid-anchor) {
        background: #F5F3EC !important;
        border: 1px solid #E6E2D8 !important;
        border-radius: 12px !important;
        padding: 14px !important;
        overflow: visible !important;
    }
    /* ✨ 折疊區（expander）：邊框完整呈現、不被卡片邊緣截掉（含「✏️ 想加日期/文字」） */
    div[data-testid="stExpander"] { overflow: visible !important; margin-top: 8px !important; }
    div[data-testid="stExpander"] > details {
        border: 1px solid #E0DBD0 !important; border-radius: 8px !important;
        background: #FFFFFF !important; overflow: visible !important;
    }
    div[data-testid="stExpander"] > details > summary { border-radius: 8px !important; }
    /* ✨ 側邊欄折疊標題（💡 開啟太慢…）：字縮小、強制一排不換行、文字在方框內「上下置中」 */
    [data-testid="stSidebar"] div[data-testid="stExpander"] > details > summary {
        display: flex !important; align-items: center !important;
        min-height: 42px !important; padding-top: 0 !important; padding-bottom: 0 !important;
    }
    [data-testid="stSidebar"] div[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] {
        display: flex !important; align-items: center !important; margin: 0 !important;
    }
    [data-testid="stSidebar"] div[data-testid="stExpander"] summary p {
        font-size: 12px !important; white-space: nowrap !important; line-height: 1.2 !important;
        overflow: hidden !important; text-overflow: ellipsis !important; margin: 0 !important;
        display: flex !important; align-items: center !important;
    }
    /* ✨ 側邊欄折疊內文：整區（含粗體標題、條列數字 1/2/3）統一同一字級、同樣行距，不雜亂 */
    [data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] li,
    [data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] ol,
    [data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] ul,
    [data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] strong {
        font-size: 11.5px !important; line-height: 1.5 !important; color: #4A4238 !important;
    }
    [data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {
        margin-bottom: 0.45rem !important;
    }
    [data-testid="stSidebar"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] ol {
        margin: 0 0 0.45rem 0 !important; padding-left: 1.1rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 雲端引擎與【無損高畫質儲存技術】
# ==========================================
@st.cache_resource(show_spinner=False)
def _open_sheet_cached(url):
    """✨ 速度優化：成功的連線會被快取,之後每次互動都直接重用,不再重新登入金鑰、
    重新打開試算表(這是操作卡頓的主因)。失敗時丟出例外→不快取,下次互動會自動重試。"""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = None
    try:
        if "type" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets), scope)
    except Exception:
        pass
    if not creds:
        key_path = os.path.join(os.path.dirname(__file__), "google_key.json")
        if os.path.exists(key_path):
            creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
    if not creds:
        raise RuntimeError("找不到金鑰")
    gc = gspread.authorize(creds)
    return gc.open_by_url(url)

def connect_google_sheets(url):
    """對外介面不變,維持回傳 (doc, 訊息);底層改用上方快取連線。"""
    try:
        return _open_sheet_cached(url), "成功"
    except Exception as e:
        return None, str(e)

def get_or_create_ws(doc, title):
    try: return doc.worksheet(title)
    except: return doc.add_worksheet(title=title, rows="100", cols="10")

def img_to_base64_chunks(img):
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    # ✨ 畫質升級：解析度拉高至 2400，確保文字銳利度
    img.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    buffered = BytesIO()
    # ✨ 畫質升級：使用最高品質 100 儲存
    img.save(buffered, format="JPEG", quality=100, subsampling=0)
    b64_str = base64.b64encode(buffered.getvalue()).decode()
    return [b64_str[i:i+45000] for i in range(0, len(b64_str), 45000)]

def base64_chunks_to_img(chunks):
    b64_str = "".join(chunks)
    return Image.open(BytesIO(base64.b64decode(b64_str)))

def img_to_chunks_compact(img, maxpx=1600, quality=92):
    """素材用：base64 切塊（畫質提高，版型A拼接更清晰；仍壓縮避免雲端肥大）。"""
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((maxpx, maxpx), Image.Resampling.LANCZOS)
    buffered = BytesIO()
    img.save(buffered, format="JPEG", quality=quality)
    b64 = base64.b64encode(buffered.getvalue()).decode()
    return [b64[i:i + 45000] for i in range(0, len(b64), 45000)]

def _save_kv(ws, key, value):
    """在工作表第一欄找 key：有就更新第二欄，沒有就新增一列（即時讀取，安全）。"""
    col = ws.col_values(1)
    if key in col:
        ws.update_cell(col.index(key) + 1, 2, value)
    else:
        ws.append_row([key, value])

def write_df_to_sheet(doc, title, df):
    """把整份 DataFrame 覆蓋寫入指定 Google Sheet 工作表（沒有就新建），回傳該工作表網址。
    讓沉睡客名單、顧客優點分析也能像 VIP名單一樣，直接在雲端 Google Sheet 的新分頁查看／下載 Excel。"""
    ws = get_or_create_ws(doc, title)
    ws.clear()
    rows = [list(map(str, df.columns))] + df.astype(str).values.tolist()
    ws.append_rows(rows, value_input_option="RAW")
    # 📐 每格靠左、靠上對齊（並自動換行），日期也不會變成靠右
    try:
        last_col = chr(ord('A') + min(len(df.columns) - 1, 25))
        ws.format(f"A1:{last_col}{len(rows)}",
                  {"horizontalAlignment": "LEFT", "verticalAlignment": "TOP", "wrapStrategy": "WRAP"})
    except Exception:
        pass
    try:
        return f"{doc.url}#gid={ws.id}"
    except Exception:
        return None

def _review_spec(content):
    """從『規格：xxx｜評價…』的內容開頭取出規格；沒有規格就回空字串。"""
    s = str(content).strip()
    if s.startswith("規格："):
        return s[3:].split("｜", 1)[0].strip()
    return ""

def _excel_align_left_top(ws):
    """把 openpyxl 工作表每一格設成靠左、靠上對齊（並自動換行）。"""
    try:
        from openpyxl.styles import Alignment
        al = Alignment(horizontal="left", vertical="top", wrap_text=True)
        for row in ws.iter_rows():
            for c in row:
                c.alignment = al
    except Exception:
        pass

# ==========================================
# ✨ 銷售加值工具：AI 分析、好評圖
# ==========================================
def gemini_generate(api_key, contents, models=None):
    """呼叫 Gemini，自動換模型重試；失敗回傳 None。
    ✨ 速度優化：第一次嘗試不再空等 2 秒，只有「失敗要重試」時才退避等待
    （等待時間隨次數加長，避免觸發免費版流量限制）。
    contents 可為純文字 [prompt]，也可為圖文 [prompt, img]，批次處理共用同一套邏輯。"""
    try:
        client = genai.Client(api_key=api_key)
    except Exception:
        return None
    models = models or ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    first = True
    for model_name in models:
        for attempt in range(3):
            try:
                if not first:
                    time.sleep(2 + attempt * 2)  # 退避：第 0/1/2 次重試分別等 2/4/6 秒
                first = False
                resp = client.models.generate_content(model=model_name, contents=contents)
                return resp.text
            except Exception:
                continue
    return None


def _extract_section(text, start_tag, end_tags):
    """從 AI 回覆中安全擷取某段落，找不到標籤回傳 None（取代易出錯的多重 split）。"""
    if not text or start_tag not in text:
        return None
    seg = text.split(start_tag, 1)[1]
    for et in end_tags:
        if et in seg:
            seg = seg.split(et, 1)[0]
            break
    return seg.strip()

def _mask_account(acc):
    """遮罩客戶帳號中間字元，保護隱私（公開貼圖用）。"""
    acc = str(acc).strip()
    if len(acc) <= 2:
        return acc[:1] + "*"
    return acc[0] + "*" * (len(acc) - 2) + acc[-1]

def _clean_text(s):
    """只保留中文、英數、常用標點，移除 emoji / 符號 / 亂碼方框。"""
    out = []
    for ch in str(s):
        o = ord(ch)
        if ch in "\n\t ":
            out.append(ch)
        elif 0x20 <= o <= 0x7E:
            out.append(ch)
        elif 0x2018 <= o <= 0x201F:
            out.append(ch)
        elif 0x3000 <= o <= 0x303F:
            out.append(ch)
        elif 0x3400 <= o <= 0x4DBF:
            out.append(ch)
        elif 0x4E00 <= o <= 0x9FFF:
            out.append(ch)
        elif 0xFF00 <= o <= 0xFFEF:
            out.append(ch)
    return "".join(out).strip()

def _wrap_cjk(text, max_chars):
    text = " ".join(_clean_text(text).split())
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars:
            lines.append(cur); cur = ""
    if cur:
        lines.append(cur)
    return lines or [""]

def _text_w(draw, text, font):
    try:
        b = draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0]
    except Exception:
        return len(text) * 20

def _render_content(reviews, template):
    """回傳一張內容圖（米底），之後再縮放置中到目標尺寸。
    ✨ 大標題置中；每則評價的星星、帳號、內文一律『靠左對齊』；規格已併入評價內容一起顯示。
    ✨ 卡片高度用『實際量測的文字高度』決定，文字一定包在框內、不會超出。"""
    BW, pad = 1000, 50
    stars = "★ ★ ★ ★ ★"
    is_quote = (template == "quote")
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    title_font = get_chinese_font(52 if is_quote else 50)
    body_font = get_chinese_font(40 if is_quote else 34)
    acc_font = get_chinese_font(28)
    star_font = get_chinese_font(30)

    line_gap = 12          # 內文行距
    pads_v = 28            # 卡片上下內留白
    star_h, acc_h = 44, 42
    gap_between = 30       # 卡片之間距
    max_chars = 18 if is_quote else 22

    blocks = [(_mask_account(it[0]), "\n".join(_wrap_cjk(it[1], max_chars))) for it in reviews]

    def measure(text, font):
        try:
            bb = dummy.multiline_textbbox((0, 0), text, font=font, spacing=line_gap)
            return bb[2] - bb[0], bb[3] - bb[1]
        except Exception:
            return 600, (text.count("\n") + 1) * 50

    heights = []
    for _, body in blocks:
        _, bh = measure(body, body_font)
        heights.append(pads_v + star_h + acc_h + 10 + bh + pads_v)

    title = "顧客真實心得" if is_quote else "BearJoy 顧客真實好評"
    top = 150
    H = top + sum(h + gap_between for h in heights) + pad
    img = Image.new("RGB", (BW, H), "#FAF8F5")
    d = ImageDraw.Draw(img)
    d.text(((BW - _text_w(d, title, title_font)) / 2, 55), title, font=title_font, fill="#4A4238")

    y = top
    for (acc, body), h in zip(blocks, heights):
        cb = y + h
        if not is_quote:
            try:
                d.rounded_rectangle([pad, y, BW - pad, cb], radius=22, fill="#FFFFFF", outline="#E6E2D8", width=2)
            except Exception:
                d.rectangle([pad, y, BW - pad, cb], fill="#FFFFFF", outline="#E6E2D8")
        x0 = pad + 36           # 卡片左內留白
        ty = y + pads_v
        # 靠左：星星 + 帳號 + 內文（大標題仍置中，於上方已畫）
        d.text((x0, ty), stars, font=star_font, fill="#E0A96D")
        d.text((x0, ty + star_h), f"@{acc}", font=acc_font, fill="#A0998C")
        d.multiline_text((x0, ty + star_h + acc_h + 10), body,
                         font=body_font, fill="#4A4238", spacing=line_gap, align="left")
        y = cb + gap_between
    return img

def make_review_image(reviews, size=(1080, 1080), template="cards"):
    """reviews: [(帳號, 內容), ...]；回傳指定尺寸 (W,H) 的 PIL Image。"""
    TW, TH = size
    content = _render_content(reviews, template)
    canvas = Image.new("RGB", (TW, TH), "#FAF8F5")
    margin = int(min(TW, TH) * 0.04)
    avail_w, avail_h = TW - margin * 2, TH - margin * 2
    scale = avail_w / content.width
    if content.height * scale > avail_h:
        scale = avail_h / content.height
    nw, nh = max(1, int(content.width * scale)), max(1, int(content.height * scale))
    content_r = content.resize((nw, nh), Image.LANCZOS)
    canvas.paste(content_r, ((TW - nw) // 2, (TH - nh) // 2))
    return canvas

def _render_collage(images):
    """把實際上傳的評價截圖拼成一張內容圖（米底＋標題＋masonry 拼貼）。
    ✨ 滿版＋高解析：縮小邊距讓評價圖盡量填滿、BW 拉高讓文字/截圖更清晰。"""
    BW, pad, gap = 1280, 16, 12
    title_font = get_chinese_font(54)
    star_font = get_chinese_font(38)
    top = 150
    cols = 2 if len(images) > 1 else 1
    cell_w = int((BW - 2 * pad - (cols - 1) * gap) / cols)
    placed, col_y = [], [top] * cols
    for im in images:
        im = im.convert("RGB")
        sw = cell_w
        sh = max(1, int(im.height * sw / im.width))
        c = col_y.index(min(col_y))
        x = pad + c * (cell_w + gap)
        y = col_y[c]
        placed.append((im.resize((sw, sh), Image.LANCZOS), x, y, sw, sh))
        col_y[c] += sh + gap
    H = max(col_y) + pad - gap
    img = Image.new("RGB", (BW, H), "#FAF8F5")
    d = ImageDraw.Draw(img)
    title, stars = "BearJoy 顧客真實好評", "★ ★ ★ ★ ★"
    d.text(((BW - _text_w(d, title, title_font)) / 2, 50), title, font=title_font, fill="#4A4238")
    d.text(((BW - _text_w(d, stars, star_font)) / 2, 118), stars, font=star_font, fill="#E0A96D")
    for im, x, y, sw, sh in placed:
        try:
            d.rounded_rectangle([x - 3, y - 3, x + sw + 3, y + sh + 3], radius=12, outline="#E6E2D8", width=3)
        except Exception:
            d.rectangle([x - 3, y - 3, x + sw + 3, y + sh + 3], outline="#E6E2D8")
        img.paste(im, (x, y))
    return img

def make_collage_image(images, size=(1080, 1080)):
    """把實際截圖拼貼後縮放置中到目標尺寸。"""
    TW, TH = size
    content = _render_collage(images)
    canvas = Image.new("RGB", (TW, TH), "#FAF8F5")
    margin = int(min(TW, TH) * 0.015)  # 邊距縮小，評價圖更滿版
    aw, ah = TW - margin * 2, TH - margin * 2
    scale = aw / content.width
    if content.height * scale > ah:
        scale = ah / content.height
    nw, nh = max(1, int(content.width * scale)), max(1, int(content.height * scale))
    canvas.paste(content.resize((nw, nh), Image.LANCZOS), ((TW - nw) // 2, (TH - nh) // 2))
    return canvas

def _draw_marker(img, x, y):
    """在預覽圖畫紅色十字準心，標出文字中心點。只用於畫面預覽，不會存進實際檔案。
    拉動「左右 / 上下」拉桿時，這個十字會即時跟著移動，方便對準想要的位置。"""
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    r = max(16, int(min(im.width, im.height) * 0.04))
    # 先畫白色粗框（深色底圖也看得見），再疊紅色細線
    d.line([(x - r, y), (x + r, y)], fill="#FFFFFF", width=6)
    d.line([(x, y - r), (x, y + r)], fill="#FFFFFF", width=6)
    d.line([(x - r, y), (x + r, y)], fill="#E0533D", width=2)
    d.line([(x, y - r), (x, y + r)], fill="#E0533D", width=2)
    d.ellipse([x - 5, y - 5, x + 5, y + 5], outline="#E0533D", width=2)
    return im

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
    creds_dict = None
    try:
        if "type" in st.secrets:
            creds_dict = dict(st.secrets)
    except Exception: pass
    order_str = ",".join(map(str, active_slots))
    threading.Thread(target=threaded_update_order, args=(creds_dict, url, order_str)).start()

# ==========================================
# 4. 側邊欄 (🛡️ 電腦/手機雙平台企業級資安防護版)
# ==========================================
doc, err = connect_google_sheets(sheet_url) if sheet_url else (None, "")
is_connected = bool(api_key and sheet_url and doc)

with st.sidebar:
    st.markdown("### ✦ BearJoy 導航")
    menu = st.radio("功能選單", ["智能客服系統", "折價券管理"], label_visibility="collapsed")
    st.markdown('<div style="flex-grow: 1; min-height: 50vh;"></div>', unsafe_allow_html=True)
    
    # 🛡️ 資安魔法：只要成功連線，不管手機或電腦，密碼框完全消失！
    if is_connected:
        st.markdown("""
        <div style='background-color:#E3DFD5; padding:12px; border-radius:8px; text-align:center; border: 1px solid #D0CCC1;'>
            <p style='color:#4A4238; font-weight:bold; font-size:15px; margin:0; margin-bottom:5px;'>✅ 系統已安全連線</p>
            <p style='color:#798571; font-size:12px; margin:0;'>金鑰已啟動最高級別隱藏防護</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # 只有在沒有金鑰或連線失敗時，才會顯示輸入框
        with st.expander("⚙️ 設定 (未偵測到有效金鑰)", expanded=True):
            input_api = st.text_input("API 金鑰:", value=api_key, type="password")
            input_url = st.text_input("試算表網址:", value=sheet_url)
            if st.button("儲存連線", use_container_width=True):
                save_config(input_api, input_url)
                st.rerun()
                
        if err:
            st.markdown(f"<p style='color:#A94442; font-weight:bold; font-size:14px; text-align:center;'>⚠️ 連線失敗: {err}</p>", unsafe_allow_html=True)

    # 💡 使用小提醒：休眠與「保持清醒」說明（給未來的自己看）
    st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
    with st.expander("💡 開啟太慢/休眠畫面?"):
        st.markdown("""
**為什麼要等一下?**
免費雲端超過約 7 天沒人開會自動休眠。再開時按「喚醒」等 30 秒～1 分鐘即可,屬正常現象、不是當機。

**想每次秒開**
到 cron-job.org 把「保持 BearJoy 客服清醒」開關切 ON,定時戳網址讓系統不睡;不常用再切 OFF。

**正確開啟順序**
1. 先用手機開本頁、按「喚醒」
2. 再去 cron-job.org 切 ON
3. pinger 只能維持清醒、叫不醒睡著的

**小提醒**
左邊方框是「選取框」不是開關。開關請點 EDIT → Enabled 切換後存檔。
        """)
        st.markdown("**建議間隔:每 6 小時或每天 1 次就夠,又省又不休眠。**")

# ==========================================
# 5. 主功能區
# ==========================================
if doc:
    if menu == "智能客服系統":
        st.markdown("""
        <div class="main-title-box">
            <div class="main-title-text">✦ BearJoy 智能客服系統 ✦</div>
        </div>
        """, unsafe_allow_html=True)
        
        tab1, tab2, tab3 = st.tabs(["批次評價處理", "VIP 顧客管理", "好評洞察 / 素材"])

        with tab1:
            col_up, col_res = st.columns([1, 1.5], gap="large")
            with col_up:
                st.markdown("##### ① 上傳好評截圖")
                files = st.file_uploader("上傳顧客好評截圖", type=["png", "jpg", "jpeg"], accept_multiple_files=True, label_visibility="collapsed")

                st.markdown("##### ② 回覆設定")
                cck1, cck2 = st.columns(2)
                is_vip_check = cck1.checkbox("🌟 回購語氣")
                save_screenshots = cck2.checkbox("💾 保存截圖", value=True,
                                                 help="會把你上傳的截圖存到雲端「評價截圖素材」工作表，之後做素材用。會多花一點同步時間。")
                # 🎁 功能1：回購優惠碼設定收進摺疊區，平時不佔版面、要用再展開
                if "saved_repurchase" not in st.session_state:
                    try:
                        cfg_rows = get_or_create_ws(doc, "系統設定").get_all_values()
                        rc = next((r for r in cfg_rows if r and r[0] == "repurchase_code"), None)
                        ro = next((r for r in cfg_rows if r and r[0] == "repurchase_offer"), None)
                        st.session_state.saved_repurchase = (rc[1] if rc and len(rc) > 1 else "",
                                                             ro[1] if ro and len(ro) > 1 else "")
                    except Exception:
                        st.session_state.saved_repurchase = ("", "")
                _saved_code, _saved_offer = st.session_state.saved_repurchase
                with st.expander("🎁 回購優惠碼（選填，會附在私訊結尾）", expanded=bool(_saved_code)):
                    repurchase_code = st.text_input("回購優惠碼", value=_saved_code, placeholder="例如 BEARJOY50")
                    repurchase_offer = st.text_input("優惠說明", value=_saved_offer, placeholder="例如 全館滿299折20")
                    if st.button("💾 設為預設範例", use_container_width=True):
                        try:
                            cfg_ws = get_or_create_ws(doc, "系統設定")
                            _save_kv(cfg_ws, "repurchase_code", repurchase_code.strip())
                            _save_kv(cfg_ws, "repurchase_offer", repurchase_offer.strip())
                            st.session_state.saved_repurchase = (repurchase_code.strip(), repurchase_offer.strip())
                            st.success("已儲存為預設，下次打開會自動帶入 ✅")
                        except Exception as e:
                            st.error(f"儲存失敗：{e}")

                st.markdown("##### ③ 開始處理")
                start_btn = st.button("🚀 開始解析並同步", type="primary", use_container_width=True)
                preview_area = st.container()

            with col_res:
                top_success_msg = st.empty()
                cards_container = st.container()
                
                if start_btn and files and api_key:
                    results_to_cloud = []

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
                    [SPEC]
                    (顧客購買的規格/款式：務必從圖片中「規格」或商品變體欄位「完整讀出」，例如「三層款」「壓縮款」「標準款」「304接水盤」等。除非圖片真的完全沒有任何規格資訊，否則一律要填，不可留空、不可只寫「無」)
                    [PUBLIC]
                    (賣場評價回覆)
                    [PRIVATE]
                    (私訊回覆)
                    """
                    
                    for file_idx, file in enumerate(files):
                        with preview_area:
                             img = Image.open(file)
                             st.image(img, caption=f"處理中: {file.name}", width=300)

                        with st.spinner(f"🏃‍♀️ AI 正在為您撰寫..."):
                            current_prompt = system_prompt + ("\n注意：此為二回購老客，請加入朋友般的尊榮感。" if is_vip_check else "")
                            # ✨ 速度優化：第一張立即處理，之後每張間隔 4 秒，避免免費版流量限制；
                            # 重試/退避邏輯統一交給 gemini_generate()，不再每次嘗試前都空等 3 秒。
                            if file_idx > 0:
                                time.sleep(4)
                            res_text = gemini_generate(api_key, [current_prompt, img])

                            if not res_text:
                                st.error(f"檔案 {file.name} 處理失敗。")
                                continue

                            # ✨ 穩定性：用安全解析，AI 少打一個標籤也不會整個崩潰
                            acc = _extract_section(res_text, "[ACCOUNT]", ["[REVIEW]"]) or "未知"
                            rev = _extract_section(res_text, "[REVIEW]", ["[SPEC]", "[PUBLIC]"]) or "解析失敗"
                            spec = (_extract_section(res_text, "[SPEC]", ["[PUBLIC]"]) or "").strip()
                            pub = _extract_section(res_text, "[PUBLIC]", ["[PRIVATE]"]) or "解析失敗"
                            priv = _extract_section(res_text, "[PRIVATE]", []) or "解析失敗"
                            # 📌 把購買規格併進「原始評價內容」開頭，後續做好評素材就會自動帶到規格
                            if spec and spec != "無" and rev != "解析失敗" and not rev.startswith("規格"):
                                rev = f"規格：{spec}｜{rev}"
                            # 🎁 功能1：私訊結尾自動附上回購優惠碼，把「感謝」變成「再買一次」
                            if priv != "解析失敗" and repurchase_code.strip():
                                offer_txt = f"（{repurchase_offer.strip()}）" if repurchase_offer.strip() else ""
                                priv = priv + f"\n\nP.S. 送您專屬回購碼 👉 {repurchase_code.strip()}{offer_txt}\n下次下單輸入即可享優惠，期待再為您服務 🎁"
                            now = datetime.now()

                            # 💾 功能6：保存原始評價截圖到雲端，供日後做素材
                            if save_screenshots:
                                try:
                                    ws_mat = get_or_create_ws(doc, "評價截圖素材")
                                    ws_mat.append_row([f"{now.strftime('%Y%m%d_%H%M%S')}_{acc}"] + img_to_chunks_compact(img.copy()))
                                except Exception as e:
                                    st.caption(f"⚠️ 此筆截圖素材保存略過（不影響回覆）：{e}")
                            
                            with cards_container:
                                with st.expander(f"✨ 客戶帳號：{acc}", expanded=True):
                                    st.markdown(f"**📝 原始評價內容:** {rev}")
                                    st.markdown("**📢 賣場回覆 (點擊右上角複製):**")
                                    st.code(pub, language="text")
                                    st.markdown("**💌 私訊回覆 (點擊右上角複製):**")
                                    st.code(priv, language="text")
                            
                            results_to_cloud.append([now.strftime("%Y-%m-%d %H:%M:%S"), acc, rev, pub, priv])

                    if doc and results_to_cloud:
                        try:
                            ws_history = get_or_create_ws(doc, "回覆紀錄")
                            existing = ws_history.get_all_values()
                            if len(existing) == 0:
                                header = ["紀錄時間", "客戶帳號", "原始評價內容", "賣場評價回覆", "VIP私訊回覆"]
                                ws_history.append_row(header)
                                existing = [header]
                            # 🔁 功能5：用 (帳號, 評價內容) 去重，同一筆評價不重複計算
                            seen_pairs = set((str(r[1]).strip(), str(r[2]).strip()) for r in existing[1:] if len(r) > 2)
                            new_rows, dup_count = [], 0
                            for row in results_to_cloud:
                                pair = (str(row[1]).strip(), str(row[2]).strip())
                                if pair in seen_pairs:
                                    dup_count += 1
                                    continue
                                seen_pairs.add(pair)
                                new_rows.append(row)
                            if new_rows:
                                ws_history.append_rows(new_rows)

                            ws_vip = get_or_create_ws(doc, "VIP名單")
                            # ✨ 速度優化：原本對 VIP 名單讀了兩次（get_all_values + get_all_records），
                            # 改成只讀一次再自行組成紀錄，少一趟雲端來回。
                            vip_vals = ws_vip.get_all_values()
                            if len(vip_vals) == 0:
                                v_header = ["客戶帳號", "首次互動", "最後互動", "互動次數"]
                                ws_vip.append_row(v_header)
                                vip_vals = [v_header]
                            v_header = vip_vals[0]
                            vip_records = [dict(zip(v_header, r)) for r in vip_vals[1:]]
                            date_str = datetime.now().strftime("%Y-%m-%d")

                            for row in new_rows:
                                account = row[1]
                                if account == "未知": continue
                                found_index = next((i for i, r in enumerate(vip_records) if str(r.get('客戶帳號', '')) == account), -1)
                                if found_index != -1:
                                    ws_vip.update_cell(found_index + 2, 3, date_str)
                                    ws_vip.update_cell(found_index + 2, 4, int(vip_records[found_index].get('互動次數', 0)) + 1)
                                else:
                                    ws_vip.append_row([account, date_str, date_str, 1])
                            # 📐 VIP 名單整欄靠左、靠上對齊（日期才不會自動靠右、看起來不一致）
                            try:
                                ws_vip.format("A:D", {"horizontalAlignment": "LEFT", "verticalAlignment": "TOP"})
                            except Exception:
                                pass
                            msg = f"🎉 完美同步！新增 {len(new_rows)} 筆紀錄"
                            if dup_count:
                                msg += f"（已自動略過 {dup_count} 筆重複評價，不重複計算互動次數）"
                            top_success_msg.success(msg)
                        except Exception as e:
                            st.error(f"雲端同步失敗：請確認試算表格式是否正確。({e})")

        with tab2:
            st.subheader("VIP 顧客戰情室")
            if doc:
                try:
                    vip_ws = get_or_create_ws(doc, "VIP名單")
                    data = vip_ws.get_all_values()
                    if len(data) > 1:
                        st.caption(f"目前共 {len(data) - 1} 位 VIP 顧客　·　最多顯示 5 筆，其餘用表格右側滾輪查看")
                        # ✨ 固定高度＝表頭＋5 列：最多呈現 5 筆，其餘在框內用右側滾輪捲動，不會把整頁撐長
                        st.dataframe(pd.DataFrame(data[1:], columns=data[0]), use_container_width=True, height=213)
                    else: st.info("目前 VIP 名單尚無資料，趕快去解析第一筆評價吧！")

                    # 💤 功能3：沉睡客喚回——找出好久沒回來的老客，一鍵生成喚回訊息
                    if len(data) > 1:
                        st.divider()
                        st.markdown("#### 沉睡客喚回")
                        st.caption("找出好久沒回來的老客，生成專屬喚回訊息＋優惠碼，貼到蝦皮聊聊就能發。建議 30～90 天；想測試可先把天數設小一點看效果。")
                        days = st.number_input("幾天沒互動就算沉睡客?", min_value=1, max_value=365, value=30, step=1, key="sleep_days")
                        wb_code = st.text_input("喚回專屬優惠碼（選填）", placeholder="例如 COMEBACK50", key="wb_code")
                        header = data[0]
                        i_acc = header.index("客戶帳號") if "客戶帳號" in header else 0
                        i_last = header.index("最後互動") if "最後互動" in header else 2
                        today = datetime.now()
                        sleepers, parsed = [], 0
                        for r in data[1:]:
                            if len(r) <= max(i_acc, i_last):
                                continue
                            last = str(r[i_last]).strip()[:10]
                            try:
                                gap = (today - datetime.strptime(last, "%Y-%m-%d")).days
                                parsed += 1
                                if gap >= int(days):
                                    sleepers.append((str(r[i_acc]), last, gap))
                            except Exception:
                                continue
                        if sleepers:
                            sleepers.sort(key=lambda x: -x[2])
                            st.write(f"共找到 **{len(sleepers)}** 位沉睡客（依沉睡天數排序）：")
                            coupon_line = f"為感謝您的支持，送上專屬優惠碼 👉 {wb_code.strip()} 🎁\n" if wb_code.strip() else ""

                            def _wakeback_msg(acc):
                                return (f"親愛的 {acc}，\n\n"
                                        f"好久不見了，BearJoy Sharon 一直記得您 🥰\n"
                                        f"最近上了新品與優惠，特別想第一個和您分享！\n"
                                        f"{coupon_line}"
                                        f"期待您再回來逛逛 ❤️\n\n—— BearJoy Sharon")

                            # 📥 下載沉睡客名單 Excel（含帳號、最後互動、沉睡天數、可直接複製的喚回訊息）
                            try:
                                df_sleep = pd.DataFrame(
                                    [{"客戶帳號": acc, "最後互動日期": last, "已沉睡天數": gap,
                                      "喚回訊息": _wakeback_msg(acc)} for acc, last, gap in sleepers])
                                xbuf = BytesIO()
                                with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
                                    df_sleep.to_excel(writer, index=False, sheet_name="沉睡客名單")
                                    _excel_align_left_top(writer.sheets["沉睡客名單"])
                                cdl1, cdl2 = st.columns(2)
                                with cdl1:
                                    st.download_button(
                                        "📥 下載 Excel",
                                        data=xbuf.getvalue(),
                                        file_name=f"BearJoy_沉睡客名單_{datetime.now().strftime('%Y%m%d')}.xlsx",
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        use_container_width=True)
                                with cdl2:
                                    if st.button("☁️ 同步到雲端", use_container_width=True, key="sleep_cloud"):
                                        try:
                                            with st.spinner("寫入雲端中…"):
                                                link = write_df_to_sheet(doc, "沉睡客名單", df_sleep)
                                            st.success("已寫入雲端 Google Sheet「沉睡客名單」分頁 ✅")
                                            if link:
                                                st.markdown(f"[👉 點此開啟雲端名單]({link})")
                                        except Exception as e:
                                            st.error(f"雲端同步失敗：{e}")
                            except Exception as e:
                                st.caption(f"⚠️ Excel 名單產生失敗（不影響下方訊息）：{e}")

                            for acc, last, gap in sleepers:
                                with st.expander(f"💤 {acc}（已 {gap} 天沒互動，最後 {last}）"):
                                    st.code(_wakeback_msg(acc), language="text")
                        elif parsed == 0:
                            st.warning("讀不到「最後互動」日期，請確認 VIP名單 的日期格式為 2026-06-02。")
                        else:
                            st.success(f"已檢查 {parsed} 位顧客，目前沒有超過 {int(days)} 天沒互動的沉睡客 🎉")
                except Exception as e:
                    st.error(f"讀取失敗：{e}")

        with tab3:
            # 共用：載入文字評價清單（最新在前）；分析與好評圖挑選都用這份，避免重複讀取
            if "review_pool" not in st.session_state or st.session_state.get("refresh_review_pool"):
                try:
                    _hist = get_or_create_ws(doc, "回覆紀錄").get_all_values()
                    _rows = [r for r in _hist[1:] if len(r) > 2 and r[2].strip() and r[2].strip() != "解析失敗"]
                    st.session_state.review_pool = list(reversed(_rows))
                except Exception:
                    st.session_state.review_pool = []
                st.session_state.refresh_review_pool = False
            review_pool = st.session_state.review_pool

            # 📊 功能2：好評關鍵字洞察（依規格分析）
            st.subheader("顧客最愛優點分析")
            st.caption("依『規格（款式）』統整顧客最常稱讚的優點，直接拿去寫該款的蝦皮標題與賣點。")
            _specs = sorted({_review_spec(r[2]) for r in review_pool if _review_spec(r[2])})
            sel_spec = st.selectbox("選規格分析（同款式一起分析；選『全部』＝不分款）",
                                    ["全部"] + _specs, key="insight_spec")
            if st.button("🔍 開始分析顧客最愛優點"):
                if not api_key:
                    st.error("需要 API 金鑰才能分析。")
                else:
                    try:
                        if sel_spec == "全部":
                            reviews = [r[2] for r in review_pool]
                        else:
                            reviews = [r[2] for r in review_pool if _review_spec(r[2]) == sel_spec]
                        if not reviews:
                            st.info("這個規格目前還沒有評價可分析。")
                        else:
                            with st.spinner(f"AI 正在分析 {len(reviews)} 筆評價..."):
                                joined = "\n".join(f"- {r}" for r in reviews[:200])
                                prompt = (
                                    "以下是某蝦皮賣場的真實顧客評價。請統整出顧客最常稱讚的「5 個優點」，"
                                    "用 Markdown 條列，每點格式為：\n"
                                    "**1. 優點標題** — 簡短說明（附 1 句顧客原話佐證）\n"
                                    "最後另起一段，以 **🛒 賣點建議：** 開頭，給 2~3 句可直接用在商品標題或描述的文案。\n\n"
                                    f"顧客評價如下：\n{joined}"
                                )
                                result = gemini_generate(api_key, [prompt])
                            if result:
                                st.session_state.insight_result = result
                                st.session_state.insight_spec_used = sel_spec
                            else:
                                st.error("分析失敗，請稍後再試（可能是 AI 額度或網路問題）。")
                    except Exception as e:
                        st.error(f"分析失敗：{e}")
            if st.session_state.get("insight_result"):
                st.markdown(st.session_state.insight_result)
                # 第一欄＝規格（哪一款），分析內容整段放同一格
                df_insight = pd.DataFrame([{
                    "規格": st.session_state.get("insight_spec_used", "全部"),
                    "顧客優點分析": str(st.session_state.insight_result).strip(),
                }])
                cin1, cin2 = st.columns(2)
                with cin1:
                    try:
                        ibuf = BytesIO()
                        with pd.ExcelWriter(ibuf, engine="openpyxl") as writer:
                            df_insight.to_excel(writer, index=False, sheet_name="顧客優點分析")
                            _excel_align_left_top(writer.sheets["顧客優點分析"])
                        st.download_button(
                            "📥 下載 Excel",
                            data=ibuf.getvalue(),
                            file_name=f"BearJoy_顧客優點分析_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True)
                    except Exception as e:
                        st.caption(f"⚠️ Excel 產生失敗：{e}")
                with cin2:
                    if st.button("☁️ 同步到雲端", use_container_width=True, key="insight_cloud"):
                        try:
                            with st.spinner("寫入雲端中…"):
                                link = write_df_to_sheet(doc, "顧客優點分析", df_insight)
                            st.success("已寫入雲端 Google Sheet「顧客優點分析」分頁 ✅")
                            if link:
                                st.markdown(f"[👉 點此開啟雲端分析]({link})")
                        except Exception as e:
                            st.error(f"雲端同步失敗：{e}")

            # 🖼️ 功能4：一鍵生成顧客好評圖（多尺寸、兩種版型）
            st.divider()
            st.markdown("#### 一鍵生成「顧客好評圖」")
            st.caption("放蝦皮置頂、IG、FB、TikTok、LINE 等，提升新客下單信任感。")
            c_n, c_tpl = st.columns(2)
            rev_n = c_n.number_input("要放幾筆好評?", min_value=1, max_value=12, value=3, step=1, key="rev_img_n")
            template_label = c_tpl.selectbox("版型", [
                "版型A：真實截圖拼接（用你上傳的評價圖）",
                "版型B：文字精選卡",
                "版型C：大字引用感",
            ], key="rev_tpl")

            # ✋ 自己挑要放哪幾筆評價（版型B/C；勾選後可看完整內容；不挑＝自動用最新、且只取有規格的）
            with st.expander("✋ 自己挑要放哪幾筆好評（版型B/C；可看完整內容）"):
                if st.button("🔄 重新整理評價清單", key="refresh_pool_btn"):
                    st.session_state.refresh_review_pool = True
                    st.rerun()
                if review_pool:
                    def _rev_label(i):
                        r = review_pool[i]
                        spec = _review_spec(r[2])
                        snippet = " ".join(str(r[2]).split())[:30]
                        return f"{r[1]} ［{spec or '無規格'}］ {snippet}…"
                    st.multiselect("勾選要做成素材的評價（可多選；勾了就以這些為準）",
                                   options=list(range(len(review_pool))),
                                   format_func=_rev_label, key="picked_reviews")
                    # 顯示已勾選評價的完整內容，挑的時候看得到全文
                    for i in st.session_state.get("picked_reviews", []):
                        if i < len(review_pool):
                            r = review_pool[i]
                            st.markdown(f"- **{r[1]}**：{r[2]}")
                else:
                    st.caption("目前沒有可挑選的文字評價，先去「批次評價處理」處理幾筆吧。")
            SIZE_PRESETS = {
                "正方形 1:1（IG貼文 / 蝦皮 1080×1080）": (1080, 1080),
                "直式 9:16（IG/FB限動・TikTok・Reels 1080×1920）": (1080, 1920),
                "橫式（FB貼文 1200×630）": (1200, 630),
                "LINE 圖文（1040×1040）": (1040, 1040),
                "自訂尺寸…": None,
            }
            size_label = st.selectbox("圖片尺寸", list(SIZE_PRESETS.keys()), key="rev_size")
            target_size = SIZE_PRESETS[size_label]
            if target_size is None:
                cw, ch = st.columns(2)
                cust_w = cw.number_input("寬 (px)", 300, 4000, 1080, 20, key="rev_cw")
                cust_h = ch.number_input("高 (px)", 300, 4000, 1080, 20, key="rev_ch")
                target_size = (int(cust_w), int(cust_h))

            # 🖼️ 版型A：挑選要拼接的真實評價截圖（縮圖；數量多時可在框內捲動）
            mat_pool = []
            if template_label.startswith("版型A"):
                if "mat_pool" not in st.session_state or st.session_state.get("refresh_mat_pool"):
                    try:
                        _mat = get_or_create_ws(doc, "評價截圖素材").get_all_values()
                        _mat = [r for r in _mat if len(r) > 1 and r[0]]
                        st.session_state.mat_pool = list(reversed(_mat))[:40]  # 最新40張(縮圖解碼較重故設上限)
                    except Exception:
                        st.session_state.mat_pool = []
                    st.session_state.refresh_mat_pool = False
                mat_pool = st.session_state.mat_pool
                with st.expander("🖼️ 挑選要拼接的真實評價截圖（不挑＝用最新幾張）", expanded=True):
                    if st.button("🔄 重新整理截圖清單", key="refresh_mat"):
                        st.session_state.refresh_mat_pool = True
                        st.rerun()
                    if not mat_pool:
                        st.caption("還沒有已保存的評價截圖。請到「批次評價處理」勾選『💾 保存截圖』並處理幾筆。")
                    else:
                        st.caption(f"共 {len(mat_pool)} 張（最新在前）。勾選想要的；不勾就用最新 {int(rev_n)} 張。框內可上下捲動。")
                        thumbs = st.session_state.setdefault("_mat_thumbs", {})
                        with st.container(height=330):
                            cols = st.columns(3)
                            for idx, r in enumerate(mat_pool):
                                with cols[idx % 3]:
                                    th = thumbs.get(r[0])
                                    if th is None:
                                        try:
                                            im = base64_chunks_to_img([c for c in r[1:] if c])
                                            im.thumbnail((220, 220))
                                            th = im
                                        except Exception:
                                            th = False
                                        thumbs[r[0]] = th
                                    if th:
                                        st.image(th, use_container_width=True)
                                    st.checkbox(f"選 #{idx + 1}", key=f"matpick_{idx}")

            if st.button("✨ 產生好評圖", type="primary"):
                try:
                    card = None
                    if template_label.startswith("版型A"):
                        # 版型A：用實際評價截圖拼接；有勾選就用勾的，沒勾就用最新幾張
                        sel_idx = [i for i in range(len(mat_pool)) if st.session_state.get(f"matpick_{i}")]
                        chosen = [mat_pool[i] for i in sel_idx] if sel_idx else mat_pool[:int(rev_n)]
                        imgs = []
                        for r in chosen:
                            try:
                                imgs.append(base64_chunks_to_img([c for c in r[1:] if c]))
                            except Exception:
                                continue
                        if not imgs:
                            st.info("還沒有已保存的評價截圖。請先到「批次評價處理」勾選『💾 保存截圖』並處理幾筆，再回來生成。")
                        else:
                            card = make_collage_image(imgs, size=target_size)
                    else:
                        # 版型B/C：用 AI 解析後的文字做圖
                        # 有勾選就用勾選的；沒勾就自動取最新、且「只取有規格」的（確保每則都有規格、也避免新舊重複）
                        picked = [i for i in st.session_state.get("picked_reviews", []) if i < len(review_pool)]
                        if picked:
                            rows = [review_pool[i] for i in picked]
                        else:
                            spec_rows = [r for r in review_pool if _review_spec(r[2])]
                            rows = (spec_rows or review_pool)[:int(rev_n)]
                        reviews = [(r[1], r[2]) for r in rows]
                        if not reviews:
                            st.info("還沒有評價可以做圖，先處理幾筆好評吧！")
                        else:
                            tpl = "quote" if template_label.startswith("版型C") else "cards"
                            card = make_review_image(reviews, size=target_size, template=tpl)
                    if card is not None:
                        st.image(card, use_container_width=True)
                        st.caption("💡 手機：長按上方圖片即可儲存，或按下方按鈕下載到手機。")
                        buf = BytesIO(); card.save(buf, format="PNG")
                        st.download_button("💻 下載好評圖", data=buf.getvalue(),
                                           file_name=f"BearJoy_好評圖_{target_size[0]}x{target_size[1]}.png", mime="image/png")
                except Exception as e:
                    st.error(f"產生失敗：{e}")

    # ==========================================
    # ✨ 動態文字壓印版：折價券管理
    # ==========================================
    elif menu == "折價券管理":
        st.markdown("""
        <div class="main-title-box">
            <div class="main-title-text">✦ 動態日期折價券管理 ✦</div>
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
        
        now = datetime.now()
        last_day = calendar.monthrange(now.year, now.month)[1]
        default_coupon_txt = f"{now.month}/{last_day}"
        
        st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)
        
        display_idx = 0
        for slot_id in st.session_state.active_slots:
            idx = st.session_state.active_slots.index(slot_id)
            is_first = (idx == 0)
            is_last = (idx == len(st.session_state.active_slots) - 1)
            display_num = display_idx + 1 
            
            if display_idx % 2 == 0:
                col1, col2 = st.columns(2, gap="medium")
                current_col = col1
            else:
                current_col = col2
            display_idx += 1
                
            with current_col:
                # 埋入隱形錨點：讓 CSS 在手機上把左右兩欄改成上下單欄
                st.markdown('<span class="coupon-grid-anchor" style="display:none;"></span>', unsafe_allow_html=True)

                # ✨ 標題＋上移／下移／刪除：同一排（標題在左，三顆方塊鍵靠右）
                c_title, c_up, c_down, c_del = st.columns(4)
                with c_title:
                    # 埋入隱形錨點供 CSS 辨識（第一欄彈性、後三欄固定 40px 方塊鍵）
                    st.markdown('<span class="inline-row-btn" style="display:none;"></span>', unsafe_allow_html=True)
                    st.markdown(f"<p class='sub-title-text' style='margin:0; line-height:40px;'>折價券版位 {display_num}</p>", unsafe_allow_html=True)
                with c_up:
                    if st.button("↑", key=f"up_btn_{slot_id}", disabled=is_first):
                        st.session_state.active_slots[idx], st.session_state.active_slots[idx-1] = st.session_state.active_slots[idx-1], st.session_state.active_slots[idx]
                        trigger_order_save(sheet_url, st.session_state.active_slots)
                        st.rerun()
                with c_down:
                    if st.button("↓", key=f"dn_btn_{slot_id}", disabled=is_last):
                        st.session_state.active_slots[idx], st.session_state.active_slots[idx+1] = st.session_state.active_slots[idx+1], st.session_state.active_slots[idx]
                        trigger_order_save(sheet_url, st.session_state.active_slots)
                        st.rerun()
                with c_del:
                    if st.button("✕", key=f"del_btn_{slot_id}"):
                        rows_to_del = [i + 1 for i, r in enumerate(cfg_data) if r and r[0] == f"coupon_{slot_id}"]
                        if rows_to_del:
                            with st.spinner("刪除中..."):
                                for row_index in sorted(rows_to_del, reverse=True):
                                    ws_cfg.delete_rows(row_index)
                                st.session_state.refresh_cfg = True
                        st.session_state.active_slots.remove(slot_id)
                        trigger_order_save(sheet_url, st.session_state.active_slots)
                        st.rerun()

                base_img = None
                existing_row = next((r for r in cfg_data if len(r) > 0 and r[0] == f'coupon_{slot_id}'), None)
                if existing_row and len(existing_row) > 1:
                    try:
                        # ✨ 抗閃爍/加速：解碼過的底圖快取在 session，之後每次互動(換日期/拖曳/調大小)
                        #    都直接重用，不再重新解碼大圖，畫面更新快很多、不再閃半天。
                        sig = (len(existing_row), existing_row[1][:32])
                        cache = st.session_state.setdefault("_decoded_imgs", {})
                        ent = cache.get(slot_id)
                        if ent and ent[0] == sig:
                            base_img = ent[1]
                        else:
                            base_img = base64_chunks_to_img([c for c in existing_row[1:] if c])
                            cache[slot_id] = (sig, base_img)
                        st.image(base_img, width=300)
                    except Exception: st.warning("圖片載入異常，請重新上傳")
                else:
                    st.info("此版位目前為空，請先上傳底圖。")

                # ✨ 下載鈕（窄）＋長按提示：同一排；提示文字與下載鍵框上下置中、不重疊
                if base_img:
                    c_dl, c_hint = st.columns([0.8, 1.7])
                    with c_dl:
                        # 埋入錨點，讓此下載鍵維持原本窄寬度（不套用全站 240px 統一寬）
                        st.markdown('<span class="coupon-dl-narrow" style="display:none;"></span>', unsafe_allow_html=True)
                        buf = BytesIO()
                        # ✨ 畫質升級：無損 PNG 下載
                        base_img.save(buf, format="PNG")
                        st.download_button(label="💻 下載", data=buf.getvalue(), file_name=f"BearJoy_Coupon_{display_num}.png", mime="image/png", key=f"dl_btn_{slot_id}")
                    with c_hint:
                        st.markdown("<p style='font-size:13.5px; color:#8A8275; margin:0; height:42px; display:flex; align-items:center; white-space:nowrap;'>💡 手機版可「長按圖片」儲存</p>", unsafe_allow_html=True)

                new_file = st.file_uploader(f"更換版位 {display_num} 圖片", type=["png", "jpg", "jpeg"], key=f"up_file_{slot_id}", label_visibility="collapsed")
                
                if new_file:
                    base_img = Image.open(new_file)
                    # 直接上傳、不需編輯：一鍵存原圖
                    if st.button("✅ 直接儲存原圖（不加字）", type="primary", use_container_width=True, key=f"save_raw_{slot_id}"):
                        with st.spinner("儲存中..."):
                            chunks = img_to_base64_chunks(base_img.convert("RGB"))
                            rows_to_del = [i + 1 for i, r in enumerate(cfg_data) if r and r[0] == f"coupon_{slot_id}"]
                            if rows_to_del:
                                for ri in sorted(rows_to_del, reverse=True):
                                    ws_cfg.delete_rows(ri)
                            ws_cfg.append_row([f"coupon_{slot_id}"] + chunks)
                            st.session_state.refresh_cfg = True
                            st.success("已儲存！")
                            st.rerun()

                if base_img:
                    with st.expander("✏️ 想加日期/文字再點開（不需要可略過）", expanded=False):
                        enable_text = st.checkbox("✒️ 啟動文字壓印", value=True, key=f"en_txt_{slot_id}")
                        final_img_to_save = base_img 
                        
                        if enable_text:
                            # 📅 功能3：讀取此版位上次存的壓印位置，換日期就不用再喬位置
                            sv_row = next((r for r in cfg_data if len(r) > 1 and r[0] == f'coupset_{slot_id}'), None)
                            sv = {}
                            if sv_row and len(sv_row) > 1:
                                try:
                                    p = sv_row[1].split("|")
                                    sv = {"x": int(float(p[0])), "y": int(float(p[1])),
                                          "size": int(float(p[2])), "rot": int(float(p[3])), "color": p[4]}
                                except Exception:
                                    sv = {}
                            def_size = max(10, min(sv.get("size", 50), 200))
                            def_rot = max(-180, min(sv.get("rot", 0), 180))
                            def_color = sv.get("color", "#FFFFFF")
                            def_x = max(0, min(sv.get("x", base_img.width // 2), base_img.width))
                            def_y = max(0, min(sv.get("y", int(base_img.height * 0.7)), base_img.height))
                            st.caption("換日期只要改下方文字再按儲存，位置/大小/顏色會自動記住。")

                            # ✨ 錨點魔法 2：文字方框與顏色並排
                            c_txt, c_col = st.columns(2)
                            with c_txt:
                                # 埋入隱形錨點供 CSS 辨識
                                st.markdown('<span class="inline-row-txt" style="display:none;"></span>', unsafe_allow_html=True)
                                text_input = st.text_area("✍️ 壓印文字（日期）", value=default_coupon_txt, key=f"txt_{slot_id}")
                            with c_col:
                                text_color = st.color_picker("🎨 顏色", def_color, key=f"col_{slot_id}")

                            c_sz, c_rot = st.columns(2)
                            c_sz.markdown('<span class="slider-pair-anchor" style="display:none;"></span>', unsafe_allow_html=True)
                            font_size = c_sz.slider("📐 大小", 10, 200, def_size, key=f"sz_{slot_id}")
                            rotation_angle = c_rot.slider("🔄 旋轉", -180, 180, def_rot, key=f"rot_{slot_id}")
                            if HAS_IMG_COORDS:
                                x_pos = max(0, min(int(st.session_state.get(f"px_{slot_id}", def_x)), base_img.width))
                                y_pos = max(0, min(int(st.session_state.get(f"py_{slot_id}", def_y)), base_img.height))
                            else:
                                c_x, c_y = st.columns(2)
                                c_x.markdown('<span class="slider-pair-anchor" style="display:none;"></span>', unsafe_allow_html=True)
                                x_pos = c_x.slider("↔️ 左右", 0, base_img.width, def_x, key=f"x_{slot_id}")
                                y_pos = c_y.slider("↕️ 上下", 0, base_img.height, def_y, key=f"y_{slot_id}")

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

                            if HAS_IMG_COORDS:
                                disp_w = 320
                                disp_img = final_img_to_save.resize((disp_w, max(1, int(final_img_to_save.height * disp_w / final_img_to_save.width))))
                                try:
                                    coords = st_image_coordinates(disp_img, key=f"clk_{slot_id}", click_and_drag=True)
                                except TypeError:
                                    coords = st_image_coordinates(disp_img, key=f"clk_{slot_id}")
                                if coords:
                                    cx = coords.get("x2", coords.get("x"))
                                    cy = coords.get("y2", coords.get("y"))
                                    if cx is not None and cy is not None:
                                        ratio = base_img.width / disp_w
                                        nx, ny = int(cx * ratio), int(cy * ratio)
                                        if nx != x_pos or ny != y_pos:
                                            st.session_state[f"px_{slot_id}"] = nx
                                            st.session_state[f"py_{slot_id}"] = ny
                                            st.rerun()
                                st.caption("位置：在圖片上按住拖曳即可（放開定位）。大小、旋轉用上方拉桿。")
                            else:
                                st.image(_draw_marker(final_img_to_save, x_pos, y_pos), width=320)
                                st.caption("紅十字＝文字位置，用上方拉桿調整位置/大小/旋轉。")
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
                                # 📅 功能3：一併記住壓印位置（下次換日期免重喬）
                                if enable_text:
                                    _save_kv(ws_cfg, f"coupset_{slot_id}", f"{x_pos}|{y_pos}|{font_size}|{rotation_angle}|{text_color}")

                                st.session_state.refresh_cfg = True
                                st.success("更新成功！")
                                st.rerun()

                st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

else:
    st.warning("⚠️ 系統尚未連線，請檢查 Secrets 中的金鑰設定。")