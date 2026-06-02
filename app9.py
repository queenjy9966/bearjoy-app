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
    .block-container { padding-top: 2.5rem !important; padding-bottom: 1rem !important; }
    
    [data-testid="stSidebar"] { background-color: #F0EDE5 !important; }
    .stButton>button { background-color: #798571 !important; color: white !important; border-radius: 6px !important; }
    [data-testid="stImage"] { display: flex; justify-content: center; }
    
    .main-title-box {
        background: linear-gradient(135deg, #E6E2D8 0%, #F5F3ED 100%); 
        padding: 12px 15px; border-radius: 6px; text-align: center; margin-bottom: 10px; 
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
    }
    .main-title-text { color: #4A4238; margin: 0; padding: 0; font-weight: bold; font-size: 22px; letter-spacing: 1px; }
    .sub-title-text { color: #4A4238; font-weight: bold; font-size: 15px; margin: 0; }
    
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
        margin-bottom: 5px !important;
        gap: 6px !important;
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
    
    /* ✨ 完美小正方形操控按鈕 */
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(n+2) div.stButton > button {
        background: transparent !important;
        border: 1px solid #D0CCC1 !important;
        border-radius: 6px !important;
        color: #798571 !important;
        font-size: 19px !important;
        font-weight: bold !important;
        padding: 0 !important;
        width: 40px !important; min-width: 40px !important; max-width: 40px !important;
        height: 40px !important; min-height: 40px !important; max-height: 40px !important;
        display: flex !important; justify-content: center !important; align-items: center !important;
        margin: 0 !important;
        box-shadow: none !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(n+2) div.stButton > button:hover {
        background: #E3DFD5 !important; color: #4A4238 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(4) div.stButton > button {
        color: #A94442 !important; border-color: #E6C5A8 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.inline-row-btn):not(:has(.coupon-grid-anchor)) > div:is([data-testid="column"],[data-testid="stColumn"]):nth-child(4) div.stButton > button:hover {
        background: #F8E3D0 !important;
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
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 雲端引擎與【無損高畫質儲存技術】
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

def img_to_chunks_compact(img, maxpx=1280, quality=80):
    """素材用：較小檔的 base64 切塊，避免雲端肥大。"""
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

# ==========================================
# ✨ 銷售加值工具：AI 分析、好評圖
# ==========================================
def gemini_generate(api_key, contents):
    """呼叫 Gemini，自動換模型重試；失敗回傳 None。"""
    try:
        client = genai.Client(api_key=api_key)
    except Exception:
        return None
    for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        for _ in range(3):
            try:
                time.sleep(2)
                resp = client.models.generate_content(model=model_name, contents=contents)
                return resp.text
            except Exception:
                continue
    return None

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
    """回傳一張內容圖（米底），之後再縮放置中到目標尺寸。"""
    BW, pad = 1000, 50
    if template == "quote":
        title_font = get_chinese_font(52)
        body_font = get_chinese_font(40)
        acc_font = get_chinese_font(30)
        star_font = get_chinese_font(34)
        quote_font = get_chinese_font(120)
        blocks = [(_mask_account(a), _wrap_cjk(b, 20)) for a, b in reviews]
        top = 150
        H = top + sum(70 + len(wl) * 56 + 110 for _, wl in blocks) + pad
        img = Image.new("RGB", (BW, H), "#FAF8F5")
        d = ImageDraw.Draw(img)
        t = "顧客真實心得"
        d.text(((BW - _text_w(d, t, title_font)) / 2, 50), t, font=title_font, fill="#4A4238")
        y = top
        for acc, wl in blocks:
            d.text((pad, y - 30), "“", font=quote_font, fill="#D8CFBE")
            ty = y + 60
            for line in wl:
                d.text(((BW - _text_w(d, line, body_font)) / 2, ty), line, font=body_font, fill="#4A4238")
                ty += 56
            stars = "★ ★ ★ ★ ★"
            d.text(((BW - _text_w(d, stars, star_font)) / 2, ty + 6), stars, font=star_font, fill="#E0A96D")
            acc_t = f"—— @{acc}"
            d.text(((BW - _text_w(d, acc_t, acc_font)) / 2, ty + 50), acc_t, font=acc_font, fill="#A0998C")
            y = ty + 110
        return img
    else:
        title_font = get_chinese_font(50)
        star_font = get_chinese_font(38)
        acc_font = get_chinese_font(28)
        body_font = get_chinese_font(34)
        blocks = [(_mask_account(a), _wrap_cjk(b, 26)) for a, b in reviews]
        top = 200
        H = top + sum(64 + len(wl) * 48 + 40 for _, wl in blocks) + pad
        img = Image.new("RGB", (BW, H), "#FAF8F5")
        d = ImageDraw.Draw(img)
        title, stars = "BearJoy 顧客真實好評", "★ ★ ★ ★ ★"
        d.text(((BW - _text_w(d, title, title_font)) / 2, 55), title, font=title_font, fill="#4A4238")
        d.text(((BW - _text_w(d, stars, star_font)) / 2, 125), stars, font=star_font, fill="#E0A96D")
        y = top
        for acc, wl in blocks:
            cb = y + 64 + len(wl) * 48 + 10
            try:
                d.rounded_rectangle([pad, y, BW - pad, cb], radius=22, fill="#FFFFFF", outline="#E6E2D8", width=2)
            except Exception:
                d.rectangle([pad, y, BW - pad, cb], fill="#FFFFFF", outline="#E6E2D8")
            d.text((pad + 30, y + 18), f"@{acc}", font=acc_font, fill="#A0998C")
            ty = y + 64
            for line in wl:
                d.text((pad + 30, ty), line, font=body_font, fill="#4A4238")
                ty += 48
            y = cb + 32
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
    with st.expander("💡 開啟太慢 / 看到休眠畫面?點我"):
        st.markdown("""
**為什麼有時要等一下下?**
本系統用的是免費雲端,超過約 **7 天**沒人開會自動「休眠」。再打開時要按一下「喚醒」、等 30 秒～1 分鐘,這是**正常現象,不是當機**。

**想要每次秒開(常用時再開)**
到 **cron-job.org** 把「保持 BearJoy 客服清醒」這個任務的開關切 **ON**,它會定時戳網址讓系統不睡。不常用時再切 **OFF** 即可。

**⭐ 正確開啟順序(很重要)**
1. 先用手機打開本網頁、按「喚醒」讓它醒著
2. **再**去 cron-job.org 把開關切 ON
3. (pinger 只能維持清醒,叫不醒睡著的,所以要先喚醒)

**小提醒**
cron-job.org 左邊的方框是「選取框」,**不是開關**!要開/關請點該任務的 **EDIT → Enabled** 切換後存檔。
        """)
        st.caption("建議間隔:每 6 小時或每天 1 次就夠,又省又不會休眠。")

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
        
        tab1, tab2, tab3 = st.tabs(["✦ 批次評價處理", "✦ VIP 顧客管理", "✦ 好評洞察 / 素材"])

        with tab1:
            col_up, col_res = st.columns([1, 1.5], gap="large")
            with col_up:
                files = st.file_uploader("上傳顧客好評截圖", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
                is_vip_check = st.checkbox("🌟 套用 VIP 老客專屬語氣")
                # 🎁 功能1：讀取上次儲存的回購碼範例（存在「系統設定」工作表）
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
                repurchase_code = st.text_input("🎁 回購優惠碼（選填，會附在私訊結尾）", value=_saved_code, placeholder="例如 BEARJOY50")
                repurchase_offer = st.text_input("　└ 優惠說明（選填）", value=_saved_offer, placeholder="例如 全館滿299折20")
                if st.button("💾 把目前回購碼設為預設範例"):
                    try:
                        cfg_ws = get_or_create_ws(doc, "系統設定")
                        _save_kv(cfg_ws, "repurchase_code", repurchase_code.strip())
                        _save_kv(cfg_ws, "repurchase_offer", repurchase_offer.strip())
                        st.session_state.saved_repurchase = (repurchase_code.strip(), repurchase_offer.strip())
                        st.success("已儲存為預設，下次打開會自動帶入 ✅")
                    except Exception as e:
                        st.error(f"儲存失敗：{e}")
                save_screenshots = st.checkbox("💾 同時保存原始評價截圖（供日後做素材）", value=True,
                                               help="會把你上傳的截圖存到雲端「評價截圖素材」工作表，之後做素材用。會多花一點同步時間。")
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
                                except Exception:
                                    pass
                            
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
                            if len(ws_vip.get_all_values()) == 0: ws_vip.append_row(["客戶帳號", "首次互動", "最後互動", "互動次數"])
                            vip_records = ws_vip.get_all_records()
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
                    if len(data) > 1: st.dataframe(pd.DataFrame(data[1:], columns=data[0]), use_container_width=True)
                    else: st.info("目前 VIP 名單尚無資料，趕快去解析第一筆評價吧！")

                    # 💤 功能3：沉睡客喚回——找出好久沒回來的老客，一鍵生成喚回訊息
                    if len(data) > 1:
                        st.divider()
                        st.markdown("#### 💤 沉睡客喚回")
                        st.caption("找出好久沒回來的老客，生成專屬喚回訊息＋優惠碼，貼到蝦皮聊聊就能發。喚回舊客成本遠低於找新客！建議 45～90 天較合理，剛買沒多久的客人不算沉睡。")
                        days = st.number_input("幾天沒互動就算沉睡客?", min_value=14, max_value=365, value=60, step=1, key="sleep_days")
                        wb_code = st.text_input("喚回專屬優惠碼（選填）", placeholder="例如 COMEBACK50", key="wb_code")
                        df_vip = pd.DataFrame(data[1:], columns=data[0])
                        today = datetime.now()
                        sleepers = []
                        for _, r in df_vip.iterrows():
                            last = str(r.get("最後互動", "")).strip()
                            try:
                                gap = (today - datetime.strptime(last, "%Y-%m-%d")).days
                                if gap >= days:
                                    sleepers.append((str(r.get("客戶帳號", "")), last, gap))
                            except Exception:
                                continue
                        if sleepers:
                            sleepers.sort(key=lambda x: -x[2])
                            st.write(f"共找到 **{len(sleepers)}** 位沉睡客（依沉睡天數排序）：")
                            coupon_line = f"為感謝您的支持，送上專屬優惠碼 👉 {wb_code.strip()} 🎁\n" if wb_code.strip() else ""
                            for acc, last, gap in sleepers:
                                msg = (f"親愛的 {acc}，\n\n"
                                       f"好久不見了，BearJoy Sharon 一直記得您 🥰\n"
                                       f"最近上了新品與優惠，特別想第一個和您分享！\n"
                                       f"{coupon_line}"
                                       f"期待您再回來逛逛 ❤️\n\n—— BearJoy Sharon")
                                with st.expander(f"💤 {acc}（已 {gap} 天沒互動，最後 {last}）"):
                                    st.code(msg, language="text")
                        else:
                            st.success("太棒了！目前沒有沉睡客 🎉")
                except Exception as e:
                    st.error(f"讀取失敗：{e}")

        with tab3:
            # 📊 功能2：好評關鍵字洞察
            st.subheader("📊 顧客最愛優點分析")
            st.caption("從你所有評價紀錄中，統整顧客最常稱讚的優點，直接拿去寫蝦皮標題與賣點。")
            if st.button("🔍 開始分析顧客最愛優點"):
                if not api_key:
                    st.error("需要 API 金鑰才能分析。")
                else:
                    try:
                        hist = get_or_create_ws(doc, "回覆紀錄").get_all_records()
                        reviews = [str(r.get("原始評價內容", "")).strip() for r in hist
                                   if str(r.get("原始評價內容", "")).strip() and str(r.get("原始評價內容", "")).strip() != "解析失敗"]
                        if not reviews:
                            st.info("目前還沒有評價紀錄可分析，先去處理幾筆好評吧！")
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
                            else:
                                st.error("分析失敗，請稍後再試（可能是 AI 額度或網路問題）。")
                    except Exception as e:
                        st.error(f"分析失敗：{e}")
            if st.session_state.get("insight_result"):
                st.markdown(st.session_state.insight_result)

            # 🖼️ 功能4：一鍵生成顧客好評圖（多尺寸、兩種版型）
            st.divider()
            st.markdown("#### 🖼️ 一鍵生成「顧客好評圖」")
            st.caption("挑最新幾筆好評做成漂亮好評圖，放蝦皮置頂、IG、FB、TikTok、LINE 等。社會證明能提升新客下單意願。")
            c_n, c_tpl = st.columns(2)
            rev_n = c_n.number_input("要放幾筆好評?", min_value=1, max_value=12, value=3, step=1, key="rev_img_n")
            template_label = c_tpl.selectbox("版型", ["版型A：好評卡片牆", "版型B：大字引用感"], key="rev_tpl")
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
            if st.button("✨ 產生好評圖"):
                try:
                    hist = get_or_create_ws(doc, "回覆紀錄").get_all_values()
                    rows = [r for r in hist[1:] if len(r) > 2 and r[2].strip() and r[2].strip() != "解析失敗"]
                    rows = rows[::-1][:int(rev_n)]
                    reviews = [(r[1], r[2]) for r in rows]
                    if not reviews:
                        st.info("還沒有評價可以做圖，先處理幾筆好評吧！")
                    else:
                        tpl = "quote" if template_label.startswith("版型B") else "cards"
                        card = make_review_image(reviews, size=target_size, template=tpl)
                        st.image(card, use_container_width=True)
                        st.caption("💡 手機版：可直接「長按上方圖片」儲存，或按下方按鈕下載到手機。")
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
                st.markdown(f"<p class='sub-title-text' style='margin-bottom:5px;'>🎟️ 折價券版位 {display_num}</p>", unsafe_allow_html=True)
                
                base_img = None
                existing_row = next((r for r in cfg_data if len(r) > 0 and r[0] == f'coupon_{slot_id}'), None)
                if existing_row and len(existing_row) > 1:
                    try:
                        chunks = [c for c in existing_row[1:] if c] 
                        base_img = base64_chunks_to_img(chunks)
                        st.image(base_img, width=300)
                        st.markdown("<p style='font-size:12px; color:#8C877D; margin-top:2px; margin-bottom:5px;'>💡 <b>手機版：請直接「長按圖片」即可儲存。</b></p>", unsafe_allow_html=True)
                    except Exception: st.warning("圖片載入異常，請重新上傳")
                else:
                    st.info("此版位目前為空，請先上傳底圖。")
                
                # ✨ 錨點魔法 1：下載鈕與操控按鈕
                c_dl, c_up, c_down, c_del = st.columns(4) 
                with c_dl:
                    # 埋入隱形錨點供 CSS 辨識
                    st.markdown('<span class="inline-row-btn" style="display:none;"></span>', unsafe_allow_html=True)
                    if base_img:
                        buf = BytesIO()
                        # ✨ 畫質升級：無損 PNG 下載
                        base_img.save(buf, format="PNG")
                        st.download_button(label=f"💻 下載", data=buf.getvalue(), file_name=f"BearJoy_Coupon_{display_num}.png", mime="image/png", key=f"dl_btn_{slot_id}")
                    else:
                        st.markdown("<div style='height:40px;'></div>", unsafe_allow_html=True)
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
                
                new_file = st.file_uploader(f"更換版位 {display_num} 圖片", type=["png", "jpg", "jpeg"], key=f"up_file_{slot_id}", label_visibility="collapsed")
                
                if new_file:
                    base_img = Image.open(new_file)
                
                if base_img:
                    with st.expander(f"✨ 開啟壓印控制台", expanded=bool(new_file)):
                        if not new_file:
                            st.caption("⚠️ 目前使用的是舊圖，建議上傳「乾淨空白底圖」再重新壓印字體。")
                        
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
                            st.caption("💡 換日期超簡單：直接改下方「壓印文字」的日期 → 按儲存即可，位置/大小/顏色會自動記住。")

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
                                # 📅 功能3：一併記住壓印位置（下次換日期免重喬）
                                if enable_text:
                                    _save_kv(ws_cfg, f"coupset_{slot_id}", f"{x_pos}|{y_pos}|{font_size}|{rotation_angle}|{text_color}")

                                st.session_state.refresh_cfg = True
                                st.success("更新成功！")
                                st.rerun()

                st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

else:
    st.warning("⚠️ 系統尚未連線，請檢查 Secrets 中的金鑰設定。")