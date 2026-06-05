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
import re
import math

# 點圖定位元件（沒裝成功就自動退回拉桿，不影響其他功能）
try:
    from streamlit_image_coordinates import streamlit_image_coordinates as st_image_coordinates
    HAS_IMG_COORDS = True
except Exception:
    HAS_IMG_COORDS = False

# 相容修補：新版 streamlit 把 image_to_url 從 streamlit.elements.image 移走，
# 導致舊版 streamlit-drawable-canvas(0.9.3) 傳 background_image 時拿不到底圖 URL → 畫布一片空白。
# 解法：把 image_to_url 補回原位置，且「直接把底圖轉成 PNG data URI」回傳，
# 完全不依賴 streamlit 內部新簽名（之前包成 LayoutConfig 反而讓底圖產生失敗），瀏覽器一定能顯示。
def _compat_image_to_url(image, width=None, clamp=False, channels="RGB",
                         output_format="PNG", image_id="", *_a, **_kw):
    try:
        img = image
        if not isinstance(img, Image.Image):
            try:
                import numpy as _np
                img = Image.fromarray(_np.asarray(img))
            except Exception:
                return ""
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        # drawable-canvas 會把畫布寬度當 width 傳進來；依此縮放底圖讓它正好鋪滿畫布
        if isinstance(width, int) and width > 0 and img.width != width:
            _h = max(1, int(round(img.height * width / img.width)))
            img = img.resize((width, _h), Image.LANCZOS)
        _buf = BytesIO()
        img.save(_buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(_buf.getvalue()).decode()
    except Exception:
        return ""

# ⚠️ 一定要「強制覆蓋」：新版 streamlit 其實還留著 image_to_url（只是換了簽名），
# 若用 hasattr 判斷就不會生效，drawable-canvas 仍拿到壞掉的新版函式 → 畫布永遠空白。
# 只覆蓋 streamlit.elements.image（drawable-canvas 專用的舊位置），不動 image_utils，
# 以免影響到一般 st.image 的顯示。
try:
    import streamlit.elements.image as _st_image_mod
    _st_image_mod.image_to_url = _compat_image_to_url
except Exception:
    pass

# 畫布直接編輯元件（Canva 式：看著底圖直接拖文字＋拉角縮放＋轉圓點旋轉；上方補丁修好底圖顯示後即可用）
try:
    from streamlit_drawable_canvas import st_canvas
    HAS_CANVAS = True
except Exception:
    HAS_CANVAS = False

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
    /* ✨ 區塊說明的小「?」popover 鈕：做成小圓鈕、不搶眼 */
    [data-testid="stPopover"] button {
        background: #F3F1EA !important; color: #8A8275 !important;
        border: 1px solid #DED8CC !important; border-radius: 50% !important;
        width: 30px !important; min-width: 30px !important; max-width: 30px !important;
        height: 30px !important; min-height: 30px !important;
        padding: 0 !important; font-size: 14px !important; font-weight: bold !important;
        display: inline-flex !important; align-items: center !important; justify-content: center !important;
        margin: -4px 0 6px 2px !important;
    }
    [data-testid="stPopover"] button:hover { background: #E6E2D8 !important; color: #4A4238 !important; }
    /* ✨ 功能卡片：整塊卡其底色＋外框，標題與內容同屬一個功能面板（沉睡客/優點分析/好評圖/VIP 一致） */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #EFEBE2 !important;
        border: 1px solid #DDD6C8 !important;
        border-radius: 14px !important;
        padding: 4px 14px 12px 14px !important;
        margin-bottom: 14px !important;
    }
    /* 卡片內的可捲動框維持白底，與卡其卡片區隔（縮圖/評價清單看得清楚） */
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF !important;
    }
    /* ✨ 勾選框文字一排不換行（回購語氣／保存截圖） */
    [data-testid="stCheckbox"] label { white-space: nowrap !important; }
    [data-testid="stCheckbox"] label p { white-space: nowrap !important; font-size: 13.5px !important; margin: 0 !important; }
    /* ✨ 折價券下載鍵：維持原本窄寬度（不套用全站 240px），讓旁邊長按提示不被擠到重疊 */
    div[data-testid="stHorizontalBlock"]:has(.coupon-dl-narrow) .stDownloadButton > button {
        width: auto !important; min-width: 84px !important; max-width: 140px !important;
        padding: 0 14px !important; white-space: nowrap !important;
    }
    /* 下載鍵欄位只取按鈕本身寬度、不留多餘空白，讓長按提示緊鄰按鈕（按鈕不被壓縮、不換行） */
    div[data-testid="stHorizontalBlock"]:has(.coupon-dl-narrow) > div[data-testid="column"]:has(.coupon-dl-narrow) {
        flex: 0 0 auto !important; width: auto !important; min-width: 0 !important;
    }
    /* 欄距收到最小，並把長按提示欄再往左挪，貼近下載鍵 */
    div[data-testid="stHorizontalBlock"]:has(.coupon-dl-narrow) { gap: 0.2rem !important; }
    div[data-testid="stHorizontalBlock"]:has(.coupon-dl-narrow) > div[data-testid="column"]:last-child {
        margin-left: -10px !important;
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
        flex: 0 0 48px !important;
        width: 48px !important;
        min-width: 48px !important;
        max-width: 48px !important;
        padding: 0 !important;
    }

    div[data-testid="stTextArea"] label, div[data-testid="stTextInput"] label, div[data-testid="stColorPicker"] label {
        font-size: 13px !important; font-weight: bold !important; color: #798571 !important;
        margin-bottom: 4px !important; padding: 0 !important; white-space: nowrap !important;
        height: 20px !important; line-height: 20px !important;
    }
    /* 壓印文字框（單行）高度 42px */
    div[data-testid="stTextInput"] input { height: 42px !important; padding: 6px 10px !important; }
    div[data-testid="stTextArea"] textarea { min-height: 42px !important; height: 42px !important; padding: 6px 10px !important; }
    /* 顏色色塊＝正方形，高度與左邊壓印文字框一致(42px)、底部對齊同一排 */
    div[data-testid="stColorPicker"] { margin-top: 0px !important; display: flex; flex-direction: column; justify-content: flex-end; align-items: flex-start;}
    div[data-testid="stColorPicker"] div[role="button"] { width: 42px !important; height: 42px !important; min-width: 42px !important; padding: 0 !important; border-radius: 6px !important; }

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
    /* 🔧 隱形排版標記（keep-row/ratio-row/trio-btn/main-stack）所在的 markdown 容器整個收掉，
       不可佔任何高度，否則會把該欄內容往下推、害同排另一欄顯得「太高」沒對齊 */
    [data-testid="stElementContainer"]:has(> div[data-testid="stMarkdown"] span.keep-row),
    [data-testid="stElementContainer"]:has(> div[data-testid="stMarkdown"] span.ratio-row),
    [data-testid="stElementContainer"]:has(> div[data-testid="stMarkdown"] span.trio-btn),
    [data-testid="stElementContainer"]:has(> div[data-testid="stMarkdown"] span.main-stack) {
        display: none !important;
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }

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
        /* 三顆大地綠按鈕（重新整理／產生好評圖／打包原圖）→ 手機維持三顆同一排，文字不換行（縮小字級塞進一行） */
        div[data-testid="stHorizontalBlock"]:has(.trio-btn) {
            flex-wrap: nowrap !important;
            gap: 0.3rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.trio-btn) > div:is([data-testid="column"],[data-testid="stColumn"]) {
            min-width: 0 !important;
            flex: 1 1 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.trio-btn) div.stButton > button {
            white-space: nowrap !important;
            font-size: 12px !important;
            padding-left: 2px !important;
            padding-right: 2px !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.trio-btn) div.stButton > button p {
            white-space: nowrap !important;
        }
        /* 第一步驟上傳區 ＋ 第二步驟結果區 → 手機上下單欄，框吃滿整個螢幕寬（恢復原本寬度） */
        div[data-testid="stHorizontalBlock"]:has(.main-stack) {
            flex-direction: column !important;
            gap: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.main-stack) > div:is([data-testid="column"],[data-testid="stColumn"]) {
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
        /* ✨ 手機版：只有「標記為 keep-row」的列維持並排，其餘欄位各自一排（自然堆疊）；
           排除外層 main-stack／coupon-grid 容器（那兩層要上下堆疊，不可被這條覆寫） */
        div[data-testid="stHorizontalBlock"]:has(.keep-row):not(:has(.main-stack)):not(:has(.coupon-grid-anchor)) {
            flex-wrap: nowrap !important;
            gap: 0.4rem !important;
            align-items: center !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.keep-row):not(:has(.main-stack)):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]) {
            min-width: 0 !important;
            flex: 1 1 0 !important;
        }
        /* ✨ 手機版：標記 ratio-row 的列維持並排，但保留各欄原本的寬度比例（如版型較寬、取幾筆較窄） */
        div[data-testid="stHorizontalBlock"]:has(.ratio-row):not(:has(.main-stack)):not(:has(.coupon-grid-anchor)) {
            flex-wrap: nowrap !important;
            gap: 0.4rem !important;
            align-items: center !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.ratio-row):not(:has(.main-stack)):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]) {
            min-width: 0 !important;
        }
        /* ✨ 手機版：分頁標籤縮小間距、字略小，三個分頁一頁就看完整 */
        [data-testid="stTabs"] button[role="tab"] { padding: 6px 6px !important; font-size: 12.5px !important; }
        [data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 4px !important; }
    }

    /* ========================================================= */
    /* ✨ 新增：按鈕統一大小 + 折價券版位色塊區隔 */
    /* ========================================================= */
    /* ✨ 按鈕統一規格：底色塊（綠）、白字、固定高度、文字置中（折價券小方塊鍵有自己的規則，不受影響） */
    .stButton > button, .stDownloadButton > button {
        background-color: #798571 !important; color: #FFFFFF !important;
        border: none !important; border-radius: 6px !important;
        height: 42px !important; min-height: 42px !important;
        /* 按鈕填滿所在欄位（在欄位排版裡才會整齊對齊）；不另設固定寬避免跑版 */
        width: 100% !important; max-width: 100% !important;
        font-size: 14px !important; font-weight: 600 !important;
        padding: 0 14px !important;
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
    /* ✨ 側邊欄折疊標題（💡 開啟太慢…）：字加大、一排不換行、上下＋左右都置中 */
    [data-testid="stSidebar"] div[data-testid="stExpander"] > details > summary {
        display: flex !important; align-items: center !important; justify-content: center !important;
        min-height: 46px !important; padding-top: 0 !important; padding-bottom: 0 !important;
        position: relative !important;
    }
    /* 展開箭頭改絕對定位（不佔 flex 空間），標題文字才能在整個方框內真正左右置中 */
    [data-testid="stSidebar"] div[data-testid="stExpander"] > details > summary svg {
        position: absolute !important; left: 12px !important; top: 50% !important;
        transform: translateY(-50%) !important;
    }
    /* 標題文字框絕對定位、鋪滿整個方框後置中：徹底不受左側箭頭佔位影響，真正上下左右置中 */
    [data-testid="stSidebar"] div[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] {
        position: absolute !important; left: 0 !important; right: 0 !important;
        top: 0 !important; bottom: 0 !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
        text-align: center !important; margin: 0 !important; pointer-events: none !important;
    }
    [data-testid="stSidebar"] div[data-testid="stExpander"] summary p {
        font-size: 15px !important; font-weight: bold !important; white-space: nowrap !important;
        line-height: 1.2 !important; margin: 0 !important; text-align: center !important;
        color: #4A4238 !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
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

def img_to_chunks_compact(img, maxpx=2000, quality=95):
    """素材用：base64 切塊（高畫質，版型A拼接清晰；仍壓縮避免雲端肥大）。"""
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((maxpx, maxpx), Image.Resampling.LANCZOS)
    buffered = BytesIO()
    img.save(buffered, format="JPEG", quality=quality, subsampling=0)  # subsampling=0：文字邊緣更銳利
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
    # 📐 對齊：日期/時間/天數/次數欄靠右，其餘文字欄靠左；皆靠上＋自動換行展開
    try:
        n = len(rows)
        for i, name in enumerate(df.columns):
            col = chr(ord('A') + i)
            ws.format(f"{col}1:{col}{n}", {
                "horizontalAlignment": "RIGHT" if _col_align_right(name) else "LEFT",
                "verticalAlignment": "TOP", "wrapStrategy": "WRAP"})
    except Exception:
        pass
    try:
        return f"{doc.url}#gid={ws.id}"
    except Exception:
        return None

def _col_align_right(name):
    """欄位名稱含 日期/時間/天數/次數/數量/金額/互動 → 靠右（數字、日期慣例）；其餘靠左。"""
    return any(k in str(name) for k in ["日期", "時間", "天數", "次數", "數量", "金額", "互動"])

def _strip_md(text):
    """移除 Markdown 標記（**粗體**、*斜體*、# 標題、` 程式碼、條列符號），給 Excel／試算表用純文字。"""
    s = str(text)
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r'(?<!\*)\*(?!\*)', '', s)
    s = re.sub(r'^#{1,6}\s*', '', s, flags=re.M)
    s = s.replace("`", "")
    s = re.sub(r'^\s*[-•*]\s+', '', s, flags=re.M)
    return s.strip()

# 顧客評價原圖要備份到的 Google Drive 資料夾（需先把此資料夾分享給服務帳號 client_email）
DRIVE_FOLDER_ID = "1ZamXtEG9tiG6HTQJXTD6e_am6u3B4bGz"

@st.cache_resource(show_spinner=False)
def _drive_service():
    """建立 Google Drive API 連線（用與試算表相同的服務帳號金鑰），快取重用。"""
    scope = ["https://www.googleapis.com/auth/drive"]
    creds = None
    try:
        if "type" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets), scope)
    except Exception:
        pass
    if not creds:
        kp = os.path.join(os.path.dirname(__file__), "google_key.json")
        if os.path.exists(kp):
            creds = ServiceAccountCredentials.from_json_keyfile_name(kp, scope)
    if not creds:
        raise RuntimeError("找不到金鑰")
    import httplib2
    from googleapiclient.discovery import build
    return build("drive", "v3", http=creds.authorize(httplib2.Http()), cache_discovery=False)

def _safe_filename(s):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", str(s)).strip()
    return (s[:80] or "未命名")

def section_block(emoji, title, desc=""):
    """大區塊標題：左色條標題＋旁邊原生「?」說明（hover 顯示，與『保存截圖』的 ? 一致）。"""
    st.subheader(f"{emoji} {title}", help=(desc or None), anchor=False)

def upload_img_to_drive(img, filename, folder_id=DRIVE_FOLDER_ID):
    """把 PIL 圖片上傳到指定 Google Drive 資料夾；回傳 (True, 連結) 或 (False, 錯誤訊息)。"""
    try:
        from googleapiclient.http import MediaIoBaseUpload
        buf = BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        buf.seek(0)
        svc = _drive_service()
        f = svc.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=MediaIoBaseUpload(buf, mimetype="image/png", resumable=False),
            fields="id, webViewLink", supportsAllDrives=True).execute()
        return True, f.get("webViewLink")
    except Exception as e:
        return False, str(e)

def _review_spec(content):
    """從評價內容抓出『規格』。整串都算規格（含中括號與顏色），不是只有【】內的字。
    容錯：半形或全形冒號（規格: / 規格：）、規格可能不在第一行（跨行搜尋）。
    取『規格:』後面到第一個分隔符（｜ / | / 逗號 / 換行）為止的完整文字。抓不到回空字串。"""
    s = str(content)
    m = re.search(r'規格\s*[：:]\s*([^\n]+)', s)
    if not m:
        return ""
    val = m.group(1)
    # 切到最早出現的分隔符（避免把後面重複或別欄的字也吃進來）
    idxs = [val.find(c) for c in ["｜", "|", "，", ","] if c in val]
    if idxs:
        val = val[:min(idxs)]
    return _spec_no_color(val)

def _spec_no_color(val):
    """規格去顏色：款式多在中括號 [..] 內，括號後通常是顏色 → 截到最後一個 ] 為止，
    讓「[三層款…]黑色」「[三層款…]粉色」合併成同一款，不會分太細。沒有中括號就原樣。"""
    val = str(val).strip().rstrip("，,、 ")
    if "]" in val:
        val = val[:val.rfind("]") + 1]
    return val[:40]

def _mat_meta(row_id):
    """解析評價截圖素材 id：『YYYYMMDD_HHMMSS_帳號|||規格』→ (日期, 帳號, 規格)。舊資料沒有規格回空。"""
    s = str(row_id)
    spec = ""
    if "|||" in s:
        s, spec = s.split("|||", 1)
    parts = s.split("_")
    date = parts[0] if parts else ""
    acc = "_".join(parts[2:]) if len(parts) > 2 else (parts[-1] if parts else "")
    return date, acc, spec.strip()

def _excel_align_left_top(ws):
    """openpyxl 對齊：依表頭判斷，日期/時間/天數/次數欄靠右，其餘靠左；皆靠上＋自動換行。"""
    try:
        from openpyxl.styles import Alignment
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        right_cols = {i + 1 for i, h in enumerate(headers) if _col_align_right(h)}
        for row in ws.iter_rows():
            for c in row:
                horiz = "right" if c.column in right_cols else "left"
                c.alignment = Alignment(horizontal=horiz, vertical="top", wrap_text=True)
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
    # ✨ 畫質升級：內部渲染整體放大 1.5×（版面比例不變、只是更密），縮到目標尺寸後截圖更銳利、不糊
    BW, pad, gap = 2400, 27, 21
    title_font = get_chinese_font(100)
    star_font = get_chinese_font(70)
    top = 345  # 標題＋五星留足空間，圖片從這裡才開始（標題與星星不擁擠）
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
    d.text(((BW - _text_w(d, title, title_font)) / 2, 63), title, font=title_font, fill="#4A4238")
    d.text(((BW - _text_w(d, stars, star_font)) / 2, 225), stars, font=star_font, fill="#E0A96D")
    for im, x, y, sw, sh in placed:
        try:
            d.rounded_rectangle([x - 5, y - 5, x + sw + 5, y + sh + 5], radius=18, outline="#E6E2D8", width=5)
        except Exception:
            d.rectangle([x - 5, y - 5, x + sw + 5, y + sh + 5], outline="#E6E2D8")
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

def _stamp_coupon(base_img, text, color, size, cx, cy, rot):
    """在底圖 (cx,cy) 壓上旋轉文字，回傳 (RGB圖, 文字寬, 文字高)。壓印預覽與儲存共用。"""
    preview = base_img.copy().convert("RGBA")
    font = get_chinese_font(size)
    dd = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    try:
        bb = dd.multiline_textbbox((0, 0), text, font=font, align="center")
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
    except Exception:
        tw, th = 200, 100
    lw, lh = max(2, int(tw * 2.5)), max(2, int(th * 2.5))
    layer = Image.new('RGBA', (lw, lh), (255, 255, 255, 0))
    ld = ImageDraw.Draw(layer)
    try:
        ld.multiline_text((lw / 2 - tw / 2, lh / 2 - th / 2), text, fill=color, font=font, align="center")
    except Exception:
        ld.text((lw / 2 - tw / 2, lh / 2 - th / 2), text, fill=color, font=font)
    rl = layer.rotate(-rot, expand=True, resample=Image.BICUBIC)
    preview.alpha_composite(rl, (int(cx - rl.width / 2), int(cy - rl.height / 2)))
    return preview.convert("RGB"), tw, th

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
        # 字體大小與「✅ 系統已安全連線」一致(15px)，文字上下左右置中於白色框中
        st.markdown("""
        <div style='font-size:15px; color:#4A4238; line-height:1.75; text-align:center;
                    display:flex; flex-direction:column; justify-content:center; align-items:center;'>
            <p style='margin:0 0 12px 0;'><b>為什麼要等一下?</b><br>
            免費雲端超過約 7 天沒人開會自動休眠。再開時按「喚醒」等 30 秒～1 分鐘即可,屬正常現象、不是當機。</p>
            <p style='margin:0 0 12px 0;'><b>想每次秒開</b><br>
            到 cron-job.org 把「保持 BearJoy 客服清醒」開關切 ON,定時戳網址讓系統不睡;不常用再切 OFF。</p>
            <p style='margin:0 0 12px 0;'><b>正確開啟順序</b><br>
            1. 先用手機開本頁、按「喚醒」<br>2. 再去 cron-job.org 切 ON<br>3. pinger 只能維持清醒、叫不醒睡著的</p>
            <p style='margin:0 0 12px 0;'><b>小提醒</b><br>
            左邊方框是「選取框」不是開關。開關請點 EDIT → Enabled 切換後存檔。</p>
            <p style='margin:0;'><b>建議間隔:每 6 小時或每天 1 次就夠,又省又不休眠。</b></p>
        </div>
        """, unsafe_allow_html=True)

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
                # 手機版：上傳區與結果區改成上下單欄，框各自吃滿整個螢幕寬（電腦版維持左右並排）
                st.markdown('<span class="main-stack" style="display:none"></span>', unsafe_allow_html=True)
                st.markdown("##### ① 上傳好評截圖")
                files = st.file_uploader("上傳顧客好評截圖", type=["png", "jpg", "jpeg"], accept_multiple_files=True, label_visibility="collapsed")

                st.markdown("##### ② 回覆設定")
                cck1, cck2, _cksp = st.columns([1, 1.25, 1.4], vertical_alignment="center")
                cck1.markdown('<span class="ratio-row" style="display:none"></span>', unsafe_allow_html=True)
                is_vip_check = cck1.checkbox("🌟 回購語氣")
                save_screenshots = cck2.checkbox("💾 保存截圖", value=True,
                                                 help="會把你上傳的截圖存到雲端「評價截圖素材」工作表，之後做素材用。會多花一點同步時間。")
                save_to_drive = st.checkbox("☁️ 同時備份原圖到 Google Drive 資料夾", value=False,
                                            help="把上傳的評價原圖存到指定 Drive 資料夾，檔名＝「日期 評價圖-規格」。"
                                                 "註：個人 Gmail＋服務帳號因 Google 限制無法直接存（服務帳號無儲存空間），"
                                                 "需改用 Apps Script 中轉才會成功；目前評價原圖已備份在「評價截圖素材」分頁。")
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
                with st.expander("🎁 回購優惠碼（選填）", expanded=bool(_saved_code)):
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
                    (顧客購買的規格/款式：蝦皮評價幾乎都會在帳號下方或評價區顯示「規格」「分類」或商品變體，務必逐字「完整讀出」，例如「[三層款 可拆卸 十合一]黑色」「[旗艦款 壓縮 七合一]」「筷子瀝水架三格掛勾款[304接水盤]」等，含中括號與顏色都要。先在整張圖找有沒有「規格」「分類」字樣，找到就照抄。只有當圖片真的完全找不到任何規格/分類/款式字樣時，才寫「無」。不可漏抓。)
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
                                    ws_mat.append_row([f"{now.strftime('%Y%m%d_%H%M%S')}_{acc}|||{_review_spec(rev)}"] + img_to_chunks_compact(img.copy()))
                                except Exception as e:
                                    st.caption(f"⚠️ 此筆截圖素材保存略過（不影響回覆）：{e}")

                            # ☁️ 備份原圖到 Google Drive 資料夾，檔名＝「日期 評價圖-規格」
                            if save_to_drive:
                                _spec_for_name = _review_spec(rev) or (spec if spec and spec != "無" else acc)
                                _fname = f"{now.strftime('%Y%m%d')} 評價圖-{_safe_filename(_spec_for_name)}.png"
                                ok_d, info_d = upload_img_to_drive(img.copy(), _fname)
                                if not ok_d:
                                    st.caption(f"⚠️ 此筆未能備份到 Drive（不影響回覆）：{str(info_d)[:90]}")
                            
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
                            # 📐 VIP 名單對齊：帳號靠左；首次/最後互動日期、互動次數靠右（統一，不再忽左忽右）
                            try:
                                ws_vip.format("A:A", {"horizontalAlignment": "LEFT", "verticalAlignment": "TOP"})
                                ws_vip.format("B:D", {"horizontalAlignment": "RIGHT", "verticalAlignment": "TOP"})
                            except Exception:
                                pass
                            msg = f"🎉 完美同步！新增 {len(new_rows)} 筆紀錄"
                            if dup_count:
                                msg += f"（已自動略過 {dup_count} 筆重複評價，不重複計算互動次數）"
                            top_success_msg.success(msg)
                        except Exception as e:
                            st.error(f"雲端同步失敗：請確認試算表格式是否正確。({e})")

        with tab2:
            with st.container(border=True):
                section_block("👑", "VIP 顧客戰情室", "所有與你互動過的顧客名單與互動次數。最多顯示 5 筆，其餘用表格右側滾輪查看。")
                if doc:
                    try:
                        vip_ws = get_or_create_ws(doc, "VIP名單")
                        data = vip_ws.get_all_values()
                        if len(data) > 1:
                            st.caption(f"目前共 {len(data) - 1} 位 VIP 顧客")
                            # ✨ 固定高度＝表頭＋5 列：最多呈現 5 筆，其餘在框內用右側滾輪捲動，不會把整頁撐長
                            st.dataframe(pd.DataFrame(data[1:], columns=data[0]), use_container_width=True, height=213)
                        else: st.info("目前 VIP 名單尚無資料，趕快去解析第一筆評價吧！")

                        # 💤 功能3：沉睡客喚回——找出好久沒回來的老客，一鍵生成喚回訊息
                        if len(data) > 1:
                            section_block("💤", "沉睡客喚回", "找出好久沒回來的老客，生成專屬喚回訊息＋優惠碼，貼到蝦皮聊聊就能發。建議 30～90 天；想測試可先把天數設小一點看效果。")
                            c_days, c_code = st.columns(2)
                            c_days.markdown('<span class="keep-row" style="display:none"></span>', unsafe_allow_html=True)
                            days = c_days.number_input("幾天沒互動就算沉睡客?", min_value=1, max_value=365, value=30, step=1, key="sleep_days")
                            wb_code = c_code.text_input("喚回專屬優惠碼（選填）", placeholder="例如 COMEBACK50", key="wb_code")
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
                                    cdl1.markdown('<span class="keep-row" style="display:none"></span>', unsafe_allow_html=True)
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

            # 📊 大區塊一：顧客最愛優點分析
            with st.container(border=True):
                section_block("📊", "顧客最愛優點分析", "選規格 → 統整該款顧客最愛優點，直接拿去寫蝦皮標題與賣點。")
                _specs_all = sorted({_review_spec(r[2]) for r in review_pool if _review_spec(r[2])})
                fic1, fic2 = st.columns(2)
                sel_specs = fic1.multiselect("選規格（可複選＝合併；可打字搜尋；留空＝全部）",
                                             _specs_all, key="insight_specs")
                kw = fic2.text_input("或用關鍵字一次分析", placeholder="例：三層 → 所有含三層的款",
                                     key="insight_kw").strip()
                if st.button("🔍 開始分析", use_container_width=True):
                    if not api_key:
                        st.error("需要 API 金鑰才能分析。")
                    else:
                        try:
                            if sel_specs:
                                reviews = [r[2] for r in review_pool if _review_spec(r[2]) in sel_specs]
                                used_label = "、".join(sel_specs)
                            elif kw:
                                reviews = [r[2] for r in review_pool if kw.lower() in _review_spec(r[2]).lower() and _review_spec(r[2])]
                                used_label = f"關鍵字「{kw}」"
                            else:
                                reviews = [r[2] for r in review_pool]
                                used_label = "全部"
                            if not reviews:
                                st.info("找不到符合的評價可分析（換個關鍵字或規格試試）。")
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
                                    st.session_state.insight_spec_used = used_label
                                else:
                                    st.error("分析失敗，請稍後再試（可能是 AI 額度或網路問題）。")
                        except Exception as e:
                            st.error(f"分析失敗：{e}")
                if st.session_state.get("insight_result"):
                    _used = st.session_state.get("insight_spec_used", "全部")
                    st.markdown(f"<p style='font-size:12px;color:#A39C90;margin:6px 0 2px 2px;'>分析範圍：{_used}</p>", unsafe_allow_html=True)
                    with st.container(border=True):
                        st.markdown(st.session_state.insight_result)
                    # 第一欄＝規格（哪一款），分析內容整段放同一格
                    df_insight = pd.DataFrame([{
                        "規格": st.session_state.get("insight_spec_used", "全部"),
                        "顧客優點分析": _strip_md(st.session_state.insight_result),
                    }])
                    cin1, cin2 = st.columns(2)
                    cin1.markdown('<span class="keep-row" style="display:none"></span>', unsafe_allow_html=True)
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

            # 🖼️ 大區塊二：一鍵生成顧客好評圖
            with st.container(border=True):
                section_block("🖼️", "一鍵生成「顧客好評圖」", "貼蝦皮置頂、IG、FB、LINE，提升新客下單信任感。")
                SIZE_PRESETS = {
                    "正方形 1:1（IG / 蝦皮 1080×1080）": (1080, 1080),
                    "直式 9:16（限動・Reels 1080×1920）": (1080, 1920),
                    "橫式（FB貼文 1200×630）": (1200, 630),
                    "LINE 圖文（1040×1040）": (1040, 1040),
                    "自訂尺寸…": None,
                }
                # 版型 + 自動取幾筆：同一排（手機版維持並排；幾筆較窄）；圖片尺寸自己一排
                c_tpl, c_n = st.columns([2, 1])
                c_tpl.markdown('<span class="ratio-row" style="display:none"></span>', unsafe_allow_html=True)
                template_label = c_tpl.selectbox("版型", [
                    "版型A：真實截圖拼接",
                    "版型B：文字精選卡",
                    "版型C：大字引用感",
                ], key="rev_tpl")
                rev_n = c_n.number_input("或 取幾筆", min_value=1, max_value=12, value=3, step=1,
                                         key="rev_img_n", help="與『手動勾選評價』二擇一：沒手動勾選時，才會自動取最新這幾筆")
                size_label = st.selectbox("圖片尺寸", list(SIZE_PRESETS.keys()), key="rev_size")
                target_size = SIZE_PRESETS[size_label]
                if target_size is None:
                    cw, ch = st.columns(2)
                    cust_w = cw.number_input("寬 (px)", 300, 4000, 1080, 20, key="rev_cw")
                    cust_h = ch.number_input("高 (px)", 300, 4000, 1080, 20, key="rev_ch")
                    target_size = (int(cust_w), int(cust_h))

                # 只顯示「當前版型」對應的挑選區，畫面更乾淨
                mat_pool = []
                pool_for_img = review_pool  # 版型B/C 做圖用的評價範圍，下方規格/關鍵字篩選會覆蓋它
                if template_label.startswith("版型A"):
                    if "mat_pool" not in st.session_state or st.session_state.get("refresh_mat_pool"):
                        try:
                            _mat = get_or_create_ws(doc, "評價截圖素材").get_all_values()
                            _mat = [r for r in _mat if len(r) > 1 and r[0]]
                            st.session_state.mat_pool = list(reversed(_mat))[:40]
                        except Exception:
                            st.session_state.mat_pool = []
                        st.session_state.refresh_mat_pool = False
                    mat_pool = st.session_state.mat_pool
                    # 帳號→規格 對照（給舊截圖沒存規格時補規格）
                    acc2spec = {}
                    for rr in review_pool:
                        sp = _review_spec(rr[2])
                        if sp and rr[1] not in acc2spec:
                            acc2spec[rr[1]] = sp
                    def _mat_spec(r):
                        _, a, sp = _mat_meta(r[0])
                        return _spec_no_color(sp) if sp else acc2spec.get(a, "")
                    # 🔎 規格/關鍵字篩選（與「顧客最愛優點分析」一致）：選項用全部規格清單，4 個款都會出現
                    ma_specs = st.multiselect("選規格（可複選；留空＝全部）",
                                              _specs_all, key="matimg_specs")
                    ma_kw = st.text_input("或用關鍵字篩選", placeholder="例：三層", key="matimg_kw").strip()
                    # 🔍 AI 補抓規格：對「無規格」的舊截圖，用 AI 直接從圖片讀出規格並補進素材
                    _no_spec = [r for r in mat_pool if not _mat_spec(r)]
                    if _no_spec and st.button(f"🔍 AI 補抓規格（{len(_no_spec)} 張沒規格的截圖）", key="ai_fill_spec"):
                        if not api_key:
                            st.error("需要 API 金鑰才能補抓。")
                        else:
                            try:
                                ws_mat2 = get_or_create_ws(doc, "評價截圖素材")
                                idmap = {rr[0]: i + 1 for i, rr in enumerate(ws_mat2.get_all_values()) if rr and rr[0]}
                                done = 0
                                with st.spinner(f"AI 正在從圖片補抓 {len(_no_spec)} 張的規格…"):
                                    for r in _no_spec:
                                        try:
                                            im = base64_chunks_to_img([c for c in r[1:] if c])
                                            sp = (gemini_generate(api_key, ["只回答這張蝦皮評價截圖中顧客購買的『規格/分類/款式』，例如：[三層款 可拆卸 十合一]。要含中括號內款式，但『不要顏色』（不要黑色/粉色那種）。找不到就只回『無』。只回規格本身，不要任何多餘文字。", im]) or "").strip()
                                            sp = _spec_no_color(sp.splitlines()[0].strip()) if sp else ""
                                            if sp and sp != "無" and idmap.get(r[0]):
                                                base = r[0].split("|||")[0]
                                                ws_mat2.update_cell(idmap[r[0]], 1, f"{base}|||{sp}")
                                                done += 1
                                            time.sleep(2)
                                        except Exception:
                                            continue
                                st.session_state.refresh_mat_pool = True
                                st.success(f"已補抓 {done} 張的規格 ✅ 自動重新整理中…")
                                st.rerun()
                            except Exception as e:
                                st.error(f"補抓失敗：{e}")
                    def _mat_match(r):
                        sp = _mat_spec(r)
                        if ma_specs:
                            return sp in ma_specs
                        if ma_kw:
                            return bool(sp) and ma_kw.lower() in sp.lower()
                        return True
                    mat_filtered = [(i, r) for i, r in enumerate(mat_pool) if _mat_match(r)]
                    with st.expander("🖼️ 挑選要拼接的截圖（不挑＝用最新幾張）", expanded=True):
                        if not mat_filtered:
                            st.caption("這個規格／關鍵字下沒有截圖，換個條件；或先到「批次評價處理」勾『💾 保存截圖』。")
                        else:
                            st.caption(f"符合 {len(mat_filtered)} 張。勾選想要的；框內可上下捲動。")
                            thumbs = st.session_state.setdefault("_mat_thumbs", {})
                            with st.container(height=330):
                                cols = st.columns(3)
                                for n, (idx, r) in enumerate(mat_filtered):
                                    with cols[n % 3]:
                                        th = thumbs.get(r[0])
                                        if th is None:
                                            try:
                                                im = base64_chunks_to_img([c for c in r[1:] if c]); im.thumbnail((400, 400)); th = im
                                            except Exception:
                                                th = False
                                            thumbs[r[0]] = th
                                        if th:
                                            st.image(th, use_container_width=True)
                                        _sp = _mat_spec(r)
                                        st.checkbox(f"選 ［{_sp or '無規格'}］", key=f"matpick_{idx}")
                else:
                    # 🔎 規格/關鍵字篩選（與「顧客最愛優點分析」一致）：先縮小要做圖的評價範圍
                    img_specs = st.multiselect("選規格（可複選；留空＝全部）", _specs_all, key="revimg_specs")
                    img_kw = st.text_input("或用關鍵字篩選", placeholder="例：三層", key="revimg_kw").strip()
                    if img_specs:
                        pool_for_img = [r for r in review_pool if _review_spec(r[2]) in img_specs]
                    elif img_kw:
                        pool_for_img = [r for r in review_pool if img_kw.lower() in _review_spec(r[2]).lower() and _review_spec(r[2])]
                    else:
                        pool_for_img = review_pool
                    with st.expander("✋ 自己挑要放哪幾筆好評（每筆顯示完整內容）", expanded=False):
                        if pool_for_img:
                            st.caption(f"符合 {len(pool_for_img)} 筆。勾選想要的；框內可上下捲動。")
                            with st.container(height=360):
                                for i, r in enumerate(pool_for_img):
                                    spec = _review_spec(r[2])
                                    st.checkbox(f"#{i + 1}　{r[1]}　［{spec or '無規格'}］", key=f"revpick_{i}")
                                    _content = str(r[2]).replace("<", "&lt;").replace(">", "&gt;")
                                    st.markdown(
                                        f"<div style='font-size:13px;color:#4A4238;line-height:1.5;margin:-6px 0 10px 26px;'>{_content}</div>",
                                        unsafe_allow_html=True)
                        elif img_specs or img_kw:
                            st.caption("這個規格／關鍵字下沒有評價，換一個條件試試。")
                        else:
                            st.caption("目前沒有可挑選的文字評價，先去「批次評價處理」處理幾筆吧。")

                rcol, gcol, zcol = st.columns(3)
                rcol.markdown('<span class="trio-btn" style="display:none"></span>', unsafe_allow_html=True)
                if rcol.button("🔄 重新整理", use_container_width=True, key="refresh_pool_all"):
                    st.session_state.refresh_mat_pool = True
                    st.session_state.refresh_review_pool = True
                    st.rerun()
                gen_clicked = gcol.button("✨ 產生好評圖", use_container_width=True)
                zip_clicked = zcol.button("📦 打包原圖", use_container_width=True)
                if gen_clicked:
                    try:
                        card = None
                        if template_label.startswith("版型A"):
                            # 版型A：用實際評價截圖拼接；有勾選就用勾的，沒勾就用最新幾張
                            sel_idx = [i for i, _ in mat_filtered if st.session_state.get(f"matpick_{i}")]
                            chosen = [mat_pool[i] for i in sel_idx] if sel_idx else [r for _, r in mat_filtered][:int(rev_n)]
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
                            picked = [i for i in range(len(pool_for_img)) if st.session_state.get(f"revpick_{i}")]
                            if picked:
                                rows = [pool_for_img[i] for i in picked]
                            else:
                                spec_rows = [r for r in pool_for_img if _review_spec(r[2])]
                                rows = (spec_rows or pool_for_img)[:int(rev_n)]
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

                # 📥 打包下載評價原圖（按鈕在上方與「產生好評圖」同排，給美編用）
                if zip_clicked:
                    try:
                        import zipfile
                        mat = get_or_create_ws(doc, "評價截圖素材").get_all_values()
                        mat = [r for r in mat if len(r) > 1 and r[0]]
                        if not mat:
                            st.info("還沒有已保存的評價原圖。請先到「批次評價處理」勾『💾 保存截圖』並處理幾筆。")
                        else:
                            # 帳號 → 規格 對照（從回覆紀錄取，用來命名）
                            acc2spec = {}
                            for r in review_pool:
                                sp = _review_spec(r[2])
                                if sp and r[1] not in acc2spec:
                                    acc2spec[r[1]] = sp
                            zbuf = BytesIO()
                            used = {}
                            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
                                for r in mat:
                                    try:
                                        im = base64_chunks_to_img([c for c in r[1:] if c])
                                    except Exception:
                                        continue
                                    date, acc, spec = _mat_meta(r[0])
                                    base = f"{date} 評價圖-{_safe_filename(_spec_no_color(spec) if spec else (acc2spec.get(acc) or acc))}"
                                    k = used.get(base, 0); used[base] = k + 1
                                    fname = f"{base}.png" if k == 0 else f"{base}_{k + 1}.png"
                                    ib = BytesIO(); im.convert("RGB").save(ib, format="PNG")
                                    zf.writestr(fname, ib.getvalue())
                            st.success(f"已打包 {sum(used.values())} 張原圖 ✅")
                            st.download_button("💾 下載 ZIP", data=zbuf.getvalue(),
                                               file_name=f"BearJoy_評價原圖_{datetime.now().strftime('%Y%m%d')}.zip",
                                               mime="application/zip")
                    except Exception as e:
                        st.error(f"打包失敗：{e}")

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
                    c_dl, c_hint = st.columns([0.8, 1.7], gap="small")
                    with c_dl:
                        # 埋入錨點，讓此下載鍵維持原本窄寬度（不套用全站 240px 統一寬）；keep-row 讓手機版維持並排
                        st.markdown('<span class="coupon-dl-narrow" style="display:none;"></span><span class="keep-row" style="display:none;"></span>', unsafe_allow_html=True)
                        buf = BytesIO()
                        # ✨ 畫質升級：無損 PNG 下載
                        base_img.save(buf, format="PNG")
                        st.download_button(label="💻 下載", data=buf.getvalue(), file_name=f"BearJoy_Coupon_{display_num}.png", mime="image/png", key=f"dl_btn_{slot_id}")
                    with c_hint:
                        st.markdown("<p style='font-size:13px; color:#8A8275; margin:0; height:38px; display:flex; align-items:center; white-space:nowrap;'>💡 長按圖片可儲存</p>", unsafe_allow_html=True)

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
                                text_input = st.text_input("✍️ 壓印文字（日期）", value=default_coupon_txt, key=f"txt_{slot_id}")
                            with c_col:
                                text_color = st.color_picker("🎨 顏色", def_color, key=f"col_{slot_id}")

                            # 操作方式：🎨 畫布直接編輯（Canva 式）／三模式拖曳／拉桿
                            x_pos = max(0, min(int(st.session_state.get(f"px_{slot_id}", def_x)), base_img.width))
                            y_pos = max(0, min(int(st.session_state.get(f"py_{slot_id}", def_y)), base_img.height))
                            use_canvas = HAS_CANVAS  # Canva 式畫布（手機可用就用這個；按「編輯文字」才開）
                            if use_canvas or HAS_IMG_COORDS:
                                font_size = max(10, min(int(st.session_state.get(f"csz_{slot_id}", def_size)), 200))
                                rotation_angle = max(-180, min(int(st.session_state.get(f"crot_{slot_id}", def_rot)), 180))
                            else:
                                c_sz, c_rot = st.columns(2)
                                c_sz.markdown('<span class="slider-pair-anchor" style="display:none;"></span>', unsafe_allow_html=True)
                                font_size = c_sz.slider("📐 大小", 10, 200, def_size, key=f"sz_{slot_id}")
                                rotation_angle = c_rot.slider("🔄 旋轉", -180, 180, def_rot, key=f"rot_{slot_id}")
                                cx2, cy2 = st.columns(2)
                                cx2.markdown('<span class="slider-pair-anchor" style="display:none;"></span>', unsafe_allow_html=True)
                                x_pos = cx2.slider("↔️ 左右", 0, base_img.width, x_pos, key=f"x_{slot_id}")
                                y_pos = cy2.slider("↕️ 上下", 0, base_img.height, y_pos, key=f"y_{slot_id}")

                            final_img_to_save, text_w, text_h = _stamp_coupon(
                                base_img, text_input, text_color, font_size, x_pos, y_pos, rotation_angle)

                            editor_shown = False
                            if use_canvas:
                                if st.session_state.get("edit_slot") != slot_id:
                                    # 未編輯此版位：顯示靜態預覽（「編輯文字」鈕在下方與確認儲存併排）
                                    editor_shown = True
                                    st.image(final_img_to_save, width=320)
                                else:
                                    disp_w = 340
                                    cscale = disp_w / base_img.width
                                    disp_h = max(1, int(base_img.height * cscale))
                                    bg = base_img.convert("RGB").resize((disp_w, disp_h), Image.LANCZOS)
                                    init = {"version": "4.4.0", "objects": [{
                                        "type": "i-text", "text": text_input or "日期",
                                        "left": float(x_pos * cscale), "top": float(y_pos * cscale),
                                        "originX": "center", "originY": "center",
                                        "fontSize": max(10, int(font_size * cscale)), "fill": text_color,
                                        "angle": float(rotation_angle), "fontFamily": "sans-serif", "editable": False,
                                    }]}
                                    canvas_ok = False
                                    try:
                                        cres = st_canvas(background_image=bg, initial_drawing=init,
                                                         drawing_mode="transform", update_streamlit=False,
                                                         height=disp_h, width=disp_w, display_toolbar=False,
                                                         key=f"cv_{slot_id}")
                                        canvas_ok = True
                                    except Exception as _ce:
                                        cres = None
                                        st.warning(f"⚠️ 畫布無法載入（{type(_ce).__name__}），改用拖曳編輯。")
                                    if canvas_ok:
                                        editor_shown = True
                                        st.caption("🎨 拖曳文字＝移動、拉四角＝縮放、轉上方圓點＝旋轉（放開後不閃）。調好按下方「✅ 確認儲存」。")
                                        if cres is not None and getattr(cres, "json_data", None):
                                            objs = cres.json_data.get("objects", [])
                                            if objs:
                                                o = objs[0]
                                                sx = float(o.get("scaleX", 1) or 1)
                                                ang = float(o.get("angle", 0) or 0)
                                                lx, ty2 = o.get("left"), o.get("top")
                                                ofs = float(o.get("fontSize", font_size * cscale) or (font_size * cscale))
                                                if lx is not None and ty2 is not None:
                                                    x_pos = max(0, min(int(lx / cscale), base_img.width))
                                                    y_pos = max(0, min(int(ty2 / cscale), base_img.height))
                                                font_size = max(10, min(int(round(ofs * sx / cscale)), 200))
                                                rotation_angle = max(-180, min(int(round(((ang + 180) % 360) - 180)), 180))
                                                st.session_state[f"px_{slot_id}"] = x_pos
                                                st.session_state[f"py_{slot_id}"] = y_pos
                                                st.session_state[f"csz_{slot_id}"] = font_size
                                                st.session_state[f"crot_{slot_id}"] = rotation_angle
                                        final_img_to_save, text_w, text_h = _stamp_coupon(
                                            base_img, text_input, text_color, font_size, x_pos, y_pos, rotation_angle)
                            if (not editor_shown) and HAS_IMG_COORDS:
                                edit_mode = st.radio("操作", ["✋ 移動", "🔍 放大縮小", "🔄 旋轉"],
                                                     horizontal=True, key=f"mode_{slot_id}", label_visibility="collapsed")
                                hint = {"✋ 移動": "在圖上按住拖曳 → 文字移到放開處",
                                        "🔍 放大縮小": "從文字往外拖＝放大、往中心拖＝縮小",
                                        "🔄 旋轉": "往哪個方向拖，文字就轉向那邊"}.get(edit_mode, "")
                                st.caption(f"目前：{edit_mode}　·　{hint}")
                                disp_w = 320
                                disp_img = final_img_to_save.resize((disp_w, max(1, int(final_img_to_save.height * disp_w / final_img_to_save.width))))
                                try:
                                    coords = st_image_coordinates(disp_img, key=f"clk_{slot_id}", click_and_drag=True)
                                except TypeError:
                                    coords = st_image_coordinates(disp_img, key=f"clk_{slot_id}")
                                if coords:
                                    rx = coords.get("x2", coords.get("x"))
                                    ry = coords.get("y2", coords.get("y"))
                                    if rx is not None and ry is not None:
                                        ratio = base_img.width / disp_w
                                        cxd, cyd = x_pos / ratio, y_pos / ratio
                                        changed = False
                                        if "移動" in edit_mode:
                                            nx, ny = int(rx * ratio), int(ry * ratio)
                                            if nx != x_pos or ny != y_pos:
                                                st.session_state[f"px_{slot_id}"] = nx
                                                st.session_state[f"py_{slot_id}"] = ny
                                                changed = True
                                        elif "放大" in edit_mode:
                                            d = math.hypot(rx - cxd, ry - cyd) * ratio
                                            ns = max(10, min(int(d / 2), 200))
                                            if ns != font_size:
                                                st.session_state[f"csz_{slot_id}"] = ns
                                                changed = True
                                        else:
                                            ang = math.degrees(math.atan2(ry - cyd, rx - cxd))
                                            nr = max(-180, min(int(round(ang)), 180))
                                            if nr != rotation_angle:
                                                st.session_state[f"crot_{slot_id}"] = nr
                                                changed = True
                                        if changed:
                                            st.rerun()
                            elif not editor_shown:
                                st.session_state[f"px_{slot_id}"] = x_pos
                                st.session_state[f"py_{slot_id}"] = y_pos
                                st.image(final_img_to_save, width=320)
                        else:
                            st.markdown("**👇 原始圖片預覽:**")
                            st.image(base_img, width=300)
                            
                        # 編輯文字 / 完成編輯 ＋ 確認儲存：縮窄併排同一排（僅畫布模式才有編輯鈕）
                        if enable_text and base_img and use_canvas:
                            _bc1, _bc2 = st.columns(2)
                            _bc1.markdown('<span class="keep-row" style="display:none"></span>', unsafe_allow_html=True)
                            if st.session_state.get("edit_slot") == slot_id:
                                if _bc1.button("↩ 完成編輯", key=f"endcv_{slot_id}", use_container_width=True):
                                    st.session_state.edit_slot = None
                                    st.rerun()
                            else:
                                if _bc1.button("🎨 編輯文字", key=f"startcv_{slot_id}", use_container_width=True):
                                    st.session_state.edit_slot = slot_id
                                    st.rerun()
                            save_clicked = _bc2.button("✅ 確認儲存", type="primary", use_container_width=True, key=f"btn_save_{slot_id}")
                        else:
                            save_clicked = st.button("✅ 確認儲存", type="primary", use_container_width=True, key=f"btn_save_{slot_id}")
                        if save_clicked:
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