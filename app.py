import streamlit as st
st.set_page_config(page_title="Dental Anki Master", layout="wide", initial_sidebar_state="expanded")
import json
import os
import datetime
from datetime import timedelta
import pandas as pd
import uuid
from PIL import Image, ImageDraw, ImageOps
import io
import zipfile
import re
import streamlit.components.v1 as components
import threading
from google_db import GoogleSheetsManager

# --- MONKEY PATCH FOR streamlit-drawable-canvas ---
# Fix AttributeError: module 'streamlit.elements.image' has no attribute 'image_to_url'
# Fix AttributeError: 'int' object has no attribute 'width'
HAS_CANVAS = False
try:
    import streamlit.elements.image
    from streamlit.elements.lib.image_utils import image_to_url as new_image_to_url
    
    class MockWidth:
        def __init__(self, width):
            self.width = width

    def patched_image_to_url(image, width, clamp, channels, output_format, image_id):
        return new_image_to_url(image, MockWidth(width), clamp, channels, output_format, image_id)

    streamlit.elements.image.image_to_url = patched_image_to_url
    
    from streamlit_drawable_canvas import st_canvas
    HAS_CANVAS = True
except Exception:
    st_canvas = None  # Fallback if canvas not available

# Try-Except block for safe import
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

# --- CONFIGURATION ---
MODEL_ID = "models/gemini-3-flash-preview"

# --- HÀM PHÍM TẮT (KEYBOARD SHORTCUTS) ---
def inject_keyboard_shortcuts():
    # JavaScript logic: Lắng nghe phím 1, 2, 3, 4 và tự động click vào nút tương ứng
    js_code = """
    <script>
    const doc = window.parent.document;
    
    // Hàm tìm và click nút dựa trên text
    function clickButtonByText(texts) {
        const buttons = Array.from(doc.querySelectorAll('button'));
        for (const btn of buttons) {
            // Kiểm tra xem nút có chứa text (ví dụ: "A.", "Good") không
            // VÀ nút đó không bị disable
            if (texts.some(t => btn.innerText.includes(t)) && !btn.disabled) {
                btn.click();
                return true;
            }
        }
        return false;
    }

    // Lắng nghe sự kiện bàn phím
    if (!window.shortcut_listener_added) {
        doc.addEventListener('keydown', function(e) {
            // Chỉ bắt phím khi không gõ vào ô input (chat, text area)
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            // Phím 1: Chọn A hoặc Again
            if (e.key === '1') { clickButtonByText(['A.', 'Again']); }
            
            // Phím 2: Chọn B hoặc Hard
            if (e.key === '2') { clickButtonByText(['B.', 'Hard']); }
            
            // Phím 3: Chọn C hoặc Good
            if (e.key === '3') { clickButtonByText(['C.', 'Good']); }
            
            // Phím 4: Chọn D hoặc Easy
            if (e.key === '4') { clickButtonByText(['D.', 'Easy']); }
        });
        window.shortcut_listener_added = true;
    }
    </script>
    """
    # Nhúng code JS vào App (chiều cao 0 để ẩn đi)
    components.html(js_code, height=0)

def generate_vision_cards(api_key, image_path, subject, topic):
    if not HAS_GENAI: return []
    
    try:
        client = genai.Client(api_key=api_key)
        
        # Load Image
        image = Image.open(image_path)
        
        prompt = f"""
        Bạn là Giáo sư Nha khoa. Hãy phân tích hình ảnh này.
        Context: Môn="{subject}", Chủ đề="{topic}".
        
        Nhiệm vụ: Tạo 3 câu hỏi trắc nghiệm (Tiếng Việt) dựa trên các chi tiết lâm sàng/cận lâm sàng TRONG ẢNH.
        
        Quy tắc quan trọng về "Che đáp án":
        - Nếu ảnh có chú thích (label) dạng chữ cái hoặc mũi tên: Hãy hỏi về cấu trúc đó nhưng KHÔNG được nhắc tên nó trong câu hỏi (ví dụ: "Cấu trúc được đánh dấu mũi tên là gì?" thay vì "Mũi tên chỉ vào Gan, Gan có chức năng gì?").
        - Nếu ảnh có nhãn tên rõ ràng (ví dụ chữ "Gan" nằm ngay cạnh gan): Hãy hỏi về Chức năng, Bệnh lý hoặc Đặc điểm giải phẫu liên quan thay vì hỏi "Đây là cơ quan gì?".
        - Tuyệt đối không để lộ đáp án ngay trong câu hỏi.
        
        Output format (JSON):
        [
          {{
            "question": "Câu hỏi (Tiếng Việt)",
            "options": {{ "A": "...", "B": "...", "C": "...", "D": "..." }},
            "correct_answer": "A/B/C/D",
            "explanation": "Giải thích chi tiết (Tiếng Việt)"
          }}
        ]
        """
        
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[image, prompt],
            config={
                'response_mime_type': 'application/json'
            }
        )
        
        return json.loads(response.text)
    except Exception as e:
        st.error(f"AI Vision Error: {e}")
        return []

def generate_vision_cards_occlusion(api_key, image_path, subject, topic):
    """
    1. Ask AI to detect structures (Bounding Boxes).
    2. Generate N masked images.
    3. Return list of card data objects.
    """
    if not HAS_GENAI: return []
    
    try:
        client = genai.Client(api_key=api_key)
        image = Image.open(image_path)
        # Fix EXIF Rotation (Crucial for phone photos)
        image = ImageOps.exif_transpose(image)
        
        # 1. Detect Objects
        prompt = f"""
        Bạn là chuyên gia thị giác máy tính (OCR).
        Nhiệm vụ: Tìm vị trí khung bao (Bounding Box) của CHÍNH XÁC các dòng chữ NHÃN TÊN (Text Labels) trong ảnh.
        
        Lưu ý đặc biệt: 
        - Chỉ lấy khung bao quanh CHỮ. KHÔNG lấy khung bao quanh đường kẻ hay bộ phận cơ thể.
        - Mục tiêu là để tôi tô màu đè lên chữ đó.
        
        Trả về JSON:
        [
          {{
            "label": "Nội dung chữ (ví dụ: 'Gan')",
            "box_2d": [ymin, xmin, ymax, xmax] (Scale 0-1000, bao sát dòng chữ)
          }}
        ]
        """
        
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[image, prompt],
            config={'response_mime_type': 'application/json'}
        )
        
        items = json.loads(response.text)
        if not items: return []
        
        generated_cards = []
        all_labels = [item['label'] for item in items]
        
        # 2. Process Each Item
        width, height = image.size
        
        for item in items:
            label = item['label']
            box = item['box_2d'] # [ymin, xmin, ymax, xmax]
            
            # Convert 0-1000 to pixels
            ymin, xmin, ymax, xmax = box
            left = (xmin / 1000) * width
            top = (ymin / 1000) * height
            right = (xmax / 1000) * width
            bottom = (ymax / 1000) * height
            
            # Inflate box (PADDING) - Stronger
            padding_x = 15
            padding_y = 8
            left = max(0, left - padding_x)
            top = max(0, top - padding_y)
            right = min(width, right + padding_x)
            bottom = min(height, bottom + padding_y)
            
            # Create Masked Image
            masked_img = image.copy()
            draw = ImageDraw.Draw(masked_img)
            # Draw Orange Box
            draw.rectangle([left, top, right, bottom], fill="#FF6B6B", outline="red", width=2)
            
            # Save Masked Image
            mask_id = f"occ_{uuid.uuid4()}.png"
            mask_path = os.path.join("static", "images", mask_id)
            masked_img.save(mask_path)
            
            # Generate Distractors
            distractors = [l for l in all_labels if l != label]
            import random
            random.shuffle(distractors)
            distractors = distractors[:3]
            while len(distractors) < 3:
                distractors.append("Cấu trúc khác")
                
            options_list = [label] + distractors
            random.shuffle(options_list)
            
            opt_dict = {
                "A": options_list[0],
                "B": options_list[1],
                "C": options_list[2],
                "D": options_list[3]
            }
            try:
                correct_key = [k for k, v in opt_dict.items() if v == label][0]
            except IndexError:
                correct_key = "A" # Fallback
            
            generated_cards.append({
                "question": f"Cấu trúc/Nhãn được che (màu đỏ) là gì?",
                "options": opt_dict,
                "correct_answer": correct_key,
                "explanation": f"Đáp án là **{label}**.",
                "image_q": mask_id, # Masked Image
                "label": label      # Store for reference
            })
            
        return generated_cards

    except Exception as e:
        st.error(f"Occlusion Error: {e}")
        return []

def detect_labels_only(api_key, image_path):
    """AI tìm tọa độ nhãn để vẽ nháp lên Canvas"""
    if not HAS_GENAI: return []
    
    try:
        client = genai.Client(api_key=api_key)
        image = Image.open(image_path)
        image = ImageOps.exif_transpose(image) 
        
        prompt = """
        Bạn là chuyên gia OCR y khoa.
        Nhiệm vụ: Tìm vị trí khung bao (Bounding Box) của tất cả các NHÃN TÊN cấu trúc giải phẫu (Text Labels) trong ảnh.
        1. Chỉ bắt các dòng chữ chú thích.
        2. Trả về JSON: [{"label": "Tên", "box_2d": [ymin, xmin, ymax, xmax]}] (Scale 0-1000)
        """
        
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[image, prompt],
            config={'response_mime_type': 'application/json'}
        )
        return json.loads(response.text)
    except Exception as e:
        # st.error(f"AI Detect Error: {e}") # Suppress error to avoid breaking flow if optional
        return []

# --- SRS CONFIGURATION (Medical Mode - Ultra Safe) ---
# Default Constants (Fallback)
DEFAULT_SRS_CONFIG = {
    "LEARNING_STEPS": [1, 15, 60], # Mins
    "NEW_CARDS_PER_DAY": 20,
    "MAX_REVIEWS_PER_DAY": 9999,
    "GRADUATING_INTERVAL": 1,     # Days
    "EASY_INTERVAL": 1,           # Days
    "STARTING_EASE": 2.3,
    "FUZZ_RANGE": 0.05
}

# --- STATE INITIALIZATION ---
if 'view' not in st.session_state: st.session_state.view = 'library'
# Initialize SRS Config in Session if not exists
if 'srs_config' not in st.session_state:
    st.session_state.srs_config = DEFAULT_SRS_CONFIG.copy()
if 'selected_subject' not in st.session_state: st.session_state.selected_subject = None
if 'selected_topic' not in st.session_state: st.session_state.selected_topic = None
if 'study_queue' not in st.session_state: st.session_state.study_queue = []
if 'current_q_index' not in st.session_state: st.session_state.current_q_index = 0
if 'answered' not in st.session_state: st.session_state.answered = False
if 'session_history' not in st.session_state: st.session_state.session_history = []

# --- CSS STYLING (PREMIUM GRADIENT UI) ---
st.markdown("""
<style>
    /* ========== 1. GLOBAL THEME - PURPLE GRADIENT ========== */
    .stApp {
        font-family: 'Inter', 'Segoe UI', Roboto, sans-serif;
    }
    
    /* ========== 2. SIDEBAR - GLASS MORPHISM ========== */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f0f23 100%) !important;
        border-right: 1px solid rgba(139, 92, 246, 0.3) !important;
    }
    [data-testid="stSidebar"] .stRadio label {
        color: #e9d5ff !important;
        transition: all 0.3s ease;
    }
    [data-testid="stSidebar"] .stRadio label:hover {
        color: #c084fc !important;
        text-shadow: 0 0 10px rgba(192, 132, 252, 0.5);
    }
    
    /* ========== 3. CARDS - GLASSMORPHISM DARK ========== */
    .modern-card {
        background: linear-gradient(135deg, rgba(45, 27, 78, 0.8) 0%, rgba(76, 29, 149, 0.6) 100%) !important;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(168, 85, 247, 0.4) !important;
        border-radius: 16px;
        padding: 25px;
        box-shadow: 0 8px 32px rgba(139, 92, 246, 0.2);
        color: #f3e8ff;
        margin-bottom: 20px;
        transition: all 0.3s ease;
    }
    .modern-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 40px rgba(139, 92, 246, 0.4);
        border-color: #c084fc !important;
    }
    
    /* ========== 4. HERO BOX - VIBRANT GRADIENT ========== */
    .hero-box {
        background: linear-gradient(135deg, #2d1b4e 0%, #4c1d95 50%, #7c3aed 100%) !important;
        border: 1px solid rgba(168, 85, 247, 0.5);
        border-radius: 20px;
        padding: 35px;
        box-shadow: 0 10px 40px rgba(124, 58, 237, 0.3);
        margin-bottom: 30px;
    }
    .hero-title {
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(90deg, #c084fc, #e879f9, #f0abfc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: none;
        margin: 0;
    }
    .hero-subtitle {
        color: #ddd6fe;
        font-size: 1.15rem;
        opacity: 0.9;
        margin-top: 10px;
    }

    /* ========== 5. BUTTONS - NEON GLOW ========== */
    .stButton > button {
        border-radius: 12px;
        height: auto;
        min-height: 3em;
        font-weight: 600;
        transition: all 0.3s ease;
        background: linear-gradient(135deg, #2d1b4e 0%, #4c1d95 100%) !important;
        border: 2px solid #7c3aed !important;
        color: #e9d5ff !important;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #4c1d95 0%, #7c3aed 100%) !important;
        border-color: #a855f7 !important;
        color: #ffffff !important;
        box-shadow: 0 0 20px rgba(168, 85, 247, 0.5);
        transform: translateY(-2px);
    }
    
    /* Primary Button */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #7c3aed 0%, #a855f7 100%) !important;
        border-color: #c084fc !important;
        color: #ffffff !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #a855f7 0%, #c084fc 100%) !important;
        box-shadow: 0 0 25px rgba(192, 132, 252, 0.6);
    }

    /* ========== 6. SRS BUTTONS - DISTINCT COLORS ========== */
    .srs-btn-again button { 
        background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 100%) !important;
        border: 2px solid #dc2626 !important; 
        color: #fecaca !important; 
    }
    .srs-btn-again button:hover { 
        background: linear-gradient(135deg, #7f1d1d 0%, #dc2626 100%) !important;
        box-shadow: 0 0 15px rgba(220, 38, 38, 0.5);
    }
    
    .srs-btn-hard button { 
        background: linear-gradient(135deg, #451a03 0%, #78350f 100%) !important;
        border: 2px solid #f59e0b !important; 
        color: #fde68a !important; 
    }
    .srs-btn-hard button:hover { 
        background: linear-gradient(135deg, #78350f 0%, #f59e0b 100%) !important;
        box-shadow: 0 0 15px rgba(245, 158, 11, 0.5);
    }
    
    .srs-btn-good button { 
        background: linear-gradient(135deg, #0c4a6e 0%, #075985 100%) !important;
        border: 2px solid #0ea5e9 !important; 
        color: #bae6fd !important; 
    }
    .srs-btn-good button:hover { 
        background: linear-gradient(135deg, #075985 0%, #0ea5e9 100%) !important;
        box-shadow: 0 0 15px rgba(14, 165, 233, 0.5);
    }
    
    .srs-btn-easy button { 
        background: linear-gradient(135deg, #052e16 0%, #166534 100%) !important;
        border: 2px solid #22c55e !important; 
        color: #bbf7d0 !important; 
    }
    .srs-btn-easy button:hover { 
        background: linear-gradient(135deg, #166534 0%, #22c55e 100%) !important;
        box-shadow: 0 0 15px rgba(34, 197, 94, 0.5);
    }

    /* ========== 7. TOPIC TAGS - GRADIENT PILLS ========== */
    .topic-tag {
        display: inline-block;
        background: linear-gradient(135deg, #312e81 0%, #4338ca 100%);
        color: #c7d2fe;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
        margin: 4px;
        border: 1px solid #6366f1;
        box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
    }
    .topic-cloud {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 20px;
        background: linear-gradient(135deg, rgba(30, 27, 75, 0.8) 0%, rgba(49, 46, 129, 0.6) 100%);
        padding: 20px;
        border-radius: 16px;
        border: 1px solid rgba(99, 102, 241, 0.3);
    }
    .topic-pill {
        background: linear-gradient(135deg, #3730a3 0%, #4f46e5 100%);
        color: #e0e7ff;
        padding: 6px 14px;
        border-radius: 16px;
        font-size: 0.9em;
        border: 1px solid #4a4d55;
    }
    /* --- ANKI DESKTOP STYLE TABLE --- */
    .anki-header {
        font-weight: bold;
        background-color: #383b42; /* Darker header */
        padding: 10px 5px;
        border-bottom: 2px solid #555;
        color: #FAFAFA;
    }
    .anki-row {
        border-bottom: 1px solid #444;
        padding: 8px 5px;
        transition: background-color 0.1s;
        color: #e0e0e0;
    }
    .anki-row:hover {
        background-color: #30333d;
    }
    .anki-stat-new {
        color: #69c0ff; /* Lighter Blue */
        font-weight: bold;
    }
    .anki-stat-due {
        color: #95de64; /* Lighter Green */
        font-weight: bold;
    }
    .anki-deck-link {
        color: #FAFAFA;
        text-decoration: none;
        font-weight: 500;
        cursor: pointer;
    }
    .anki-deck-link:hover {
        text-decoration: underline;
        color: #33E3FF;
    }
    /* Buttons in table - VISIBLE in DARK MODE */
    .anki-table .stButton > button {
        background: #383b42 !important;
        border: 1px solid #555 !important;
        color: #e0e0e0 !important;
        border-radius: 8px !important;
    }
    .anki-table .stButton > button:hover {
        background: #4a4d55 !important;
        border-color: #777 !important;
        color: #fff !important;
    }
    /* Deck name buttons - left aligned, full width */
    div[data-testid="column"]:first-child .stButton > button {
        text-align: left !important;
        justify-content: flex-start !important;
        background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%) !important;
        border-left: 4px solid #3498db !important;
        font-weight: 500 !important;
        color: #ecf0f1 !important;
    }
    div[data-testid="column"]:first-child .stButton > button:hover {
        background: linear-gradient(135deg, #34495e 0%, #2c3e50 100%) !important;
        border-left-color: #5dade2 !important;
        color: #fff !important;
    }
    /* Action buttons (small icons) */
    .stButton > button[kind="secondary"] {
        background: transparent !important;
        border: none !important;
        color: #aaa !important;
    }
    .stButton > button[kind="secondary"]:hover {
        color: #fff !important;
    }
    
    /* === LEARNING VIEW: Answer Options - GREEN THEME DARK MODE === */
    [data-testid="stVerticalBlock"] .answer-option-container .stButton > button,
    .answer-option-container .stButton > button {
        text-align: left !important;
        justify-content: flex-start !important;
        padding: 16px 20px !important;
        background: linear-gradient(135deg, #1e2824 0%, #162b21 100%) !important;
        border: 3px solid #2f855a !important;
        color: #9ae6b4 !important;
        border-radius: 12px !important;
        margin-bottom: 12px !important;
        font-size: 1.05em !important;
        font-weight: 500 !important;
        box-shadow: 0 3px 8px rgba(0,0,0, 0.4) !important;
        min-height: 60px !important;
    }
    [data-testid="stVerticalBlock"] .answer-option-container .stButton > button:hover,
    .answer-option-container .stButton > button:hover {
        background: linear-gradient(135deg, #22543d 0%, #1c4532 100%) !important;
        border-color: #48bb78 !important;
        color: #ffffff !important;
        box-shadow: 0 6px 16px rgba(47, 133, 90, 0.4) !important;
        transform: translateY(-2px) !important;
    }
</style>
""", unsafe_allow_html=True)

# --- DATA MANAGER ---
# --- DATA MANAGER (ĐÃ SỬA LỖI ID MA) ---
# --- DATA MANAGER (AUTO-CLEAN MODE) ---
# --- DATA MANAGER (PROFILE MODE) ---
import shutil
class DataManager:
    # Thư mục gốc chứa dữ liệu các users
    BASE_DIR = 'user_profiles' 

    @staticmethod
    def init_storage():
        """Tạo thư mục gốc nếu chưa có"""
        if not os.path.exists(DataManager.BASE_DIR):
            os.makedirs(DataManager.BASE_DIR)

    @staticmethod
    def get_user_folder(username):
        return os.path.join(DataManager.BASE_DIR, username)

    @staticmethod
    def get_files(username):
        """Lấy đường dẫn file data và progress của user"""
        folder = DataManager.get_user_folder(username)
        return os.path.join(folder, 'data.json'), os.path.join(folder, 'progress.json')

    @staticmethod
    def create_profile(username):
        """Tạo hồ sơ mới (Tạo thư mục rỗng)"""
        username = username.strip()
        if not username: return False, "Tên không được để trống"
        
        folder = DataManager.get_user_folder(username)
        if os.path.exists(folder):
            return False, "Tên này đã có người dùng."
        
        try:
            os.makedirs(folder)
            # Tạo file rỗng ban đầu
            with open(os.path.join(folder, 'data.json'), 'w', encoding='utf-8') as f:
                json.dump([], f)
            with open(os.path.join(folder, 'progress.json'), 'w', encoding='utf-8') as f:
                json.dump({}, f)
                
            return True, "Tạo hồ sơ thành công!"
        except Exception as e:
            return False, f"Lỗi tạo hồ sơ: {str(e)}"

    @staticmethod
    def delete_profile(username):
        """Xóa vĩnh viễn hồ sơ và dữ liệu của user"""
        folder = DataManager.get_user_folder(username)
        if not os.path.exists(folder):
            return False, "Không tìm thấy hồ sơ người dùng."
        
        try:
            shutil.rmtree(folder)
            return True, f"Đã xóa hoàn toàn hồ sơ: {username}"
        except Exception as e:
            return False, f"Lỗi không thể xóa: {str(e)}"

    @staticmethod
    def get_all_profiles():
        """Liệt kê danh sách người dùng"""
        DataManager.init_storage()
        return [name for name in os.listdir(DataManager.BASE_DIR) if os.path.isdir(os.path.join(DataManager.BASE_DIR, name))]

    # --- CÁC HÀM LOAD/SAVE CẢI TIẾN (SESSION STATE CACHE) ---
    @staticmethod
    def load_data(username, force_refresh=False):
        """Load data với Session State Cache - CHỈ GỌI API 1 LẦN DUY NHẤT"""
        cache_key = f"cached_data_{username}"
        
        # Nếu đã có trong Session và không yêu cầu refresh -> Dùng cache (SIÊU NHANH)
        if cache_key in st.session_state and not force_refresh:
            return st.session_state[cache_key]
        
        # Nếu chưa có hoặc cần refresh -> Tải từ Cloud/Local
        data = []
        is_cloud_active = False
        try:
            if GoogleSheetsManager.get_client():
                is_cloud_active = True
                cloud_data = GoogleSheetsManager.load_user_data_cloud(username)
                if cloud_data: 
                    data = cloud_data
        except Exception:
            pass

        # Fallback to Local
        if not data:
            local_data_file, _ = DataManager.get_files(username)
            if os.path.exists(local_data_file):
                try:
                    with open(local_data_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except: 
                    data = []

        # Auto-Migrate
        if is_cloud_active and not st.session_state.get(f"migrated_data_{username}") and data:
            # Đánh dấu đã migrate để không lặp lại
            st.session_state[f"migrated_data_{username}"] = True
            # Chạy ngầm
            t = threading.Thread(target=GoogleSheetsManager.save_user_data_cloud, args=(username, data))
            t.start()
        
        # LƯU VÀO SESSION STATE
        st.session_state[cache_key] = data
        return data

    @staticmethod
    def save_data(username, data):
        # 0. CẬP NHẬT SESSION CACHE (Quan trọng để UI luôn hiện đúng)
        cache_key = f"cached_data_{username}"
        st.session_state[cache_key] = data
        
        # 1. Lưu Local (Backup an toàn - Blocking để đảm bảo data không mất)
        data_file, _ = DataManager.get_files(username)
        try:
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except: pass

        # 2. Cloud - KHÔNG TỰ ĐỘNG SYNC NỮA (User bấm nút Sync khi muốn)
            
            
    @staticmethod
    def load_progress(username, force_refresh=False):
        """Load progress với Session State Cache - CHỈ GỌI API 1 LẦN DUY NHẤT"""
        cache_key = f"cached_progress_{username}"
        
        # Nếu đã có trong Session và không yêu cầu refresh -> Dùng cache (SIÊU NHANH)
        if cache_key in st.session_state and not force_refresh:
            return st.session_state[cache_key]
        
        # Nếu chưa có hoặc cần refresh -> Tải từ Cloud/Local
        progress = {}
        is_cloud_active = False
        try:
            if GoogleSheetsManager.get_client():
                is_cloud_active = True
                cloud_prog = GoogleSheetsManager.load_progress_cloud(username)
                if cloud_prog: 
                    progress = cloud_prog
        except: pass

        # Fallback to Local
        if not progress:
            _, prog_file = DataManager.get_files(username)
            if os.path.exists(prog_file):
                try:
                    with open(prog_file, 'r', encoding='utf-8') as f:
                        progress = json.load(f)
                except: progress = {}

        # Auto-Migrate - BỎ ĐI (User sẽ bấm nút Sync thủ công)
        
        # LƯU VÀO SESSION STATE
        st.session_state[cache_key] = progress
        return progress

    @staticmethod
    def save_progress(username, progress):
        # 0. CẬP NHẬT SESSION CACHE
        cache_key = f"cached_progress_{username}"
        st.session_state[cache_key] = progress
        
        # 1. Local (Nhanh)
        _, prog_file = DataManager.get_files(username)
        try:
            with open(prog_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)
        except: pass

        # 2. Cloud - KHÔNG TỰ ĐỘNG SYNC (User bấm nút Sync khi muốn)
    
    @staticmethod
    def sync_to_cloud(username):
        """ĐỒNG BỘ THỦ CÔNG - Gọi khi user bấm nút Sync"""
        try:
            if not GoogleSheetsManager.get_client():
                return False, "Không kết nối được Cloud"
            
            # Sync Data
            data = st.session_state.get(f"cached_data_{username}", [])
            if data:
                GoogleSheetsManager.save_user_data_cloud(username, data)
            
            # Sync Progress
            progress = st.session_state.get(f"cached_progress_{username}", {})
            if progress:
                GoogleSheetsManager.save_progress_cloud(username, progress)
            
            return True, "Đồng bộ thành công!"
        except Exception as e:
            return False, f"Lỗi: {e}"

    @staticmethod
    @st.cache_data
    def load_config():
        # Config chung (legacy - không dùng cho API key nữa)
        if not os.path.exists('config.json'): return {}
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}

    @staticmethod
    def load_user_api_key(username):
        """Load API key riêng cho từng profile - PERSISTENT"""
        key_file = os.path.join("user_profiles", username, "api_key.txt")
        if os.path.exists(key_file):
            try:
                with open(key_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except: pass
        return ""
    
    @staticmethod
    def save_user_api_key(username, api_key):
        """Lưu API key riêng cho từng profile - PERSISTENT"""
        user_dir = os.path.join("user_profiles", username)
        os.makedirs(user_dir, exist_ok=True)
        key_file = os.path.join(user_dir, "api_key.txt")
        try:
            with open(key_file, 'w', encoding='utf-8') as f:
                f.write(api_key)
            return True
        except:
            return False

    @staticmethod
    def resolve_system_prompt(subject):
        """Resolves the best matching system prompt for a given subject path."""
        prompts = DataManager.load_prompts()
        system_prompt = ""
        
        # Check explicit path and parents
        if subject:
            parts = subject.split('/')
            for i in range(len(parts), 0, -1):
                key = "/".join(parts[:i])
                if key in prompts:
                    system_prompt = prompts[key]
                    break
        
        # Fallback to User Defined Default
        if not system_prompt and "DEFAULT" in prompts:
            system_prompt = prompts["DEFAULT"]
            
        # Fallback to Hardcoded Default
        if not system_prompt:
            system_prompt = f"""
        VAI TRÒ (ROLE):
        Bạn là Giảng viên/Chuyên gia Phẫu thuật Nha chu & Implant.

        Sứ mệnh: Chuyển hóa dữ liệu lâm sàng/hình ảnh thành Tiên lượng răng (Prognosis), đánh giá Rủi ro Mất răng và lập kế hoạch Can thiệp Phẫu thuật chính xác (Bone grafting, CLS, flap design).

        PHẠM VI KIẾN THỨC (SYLLABUS):
        Bám sát 5 module cốt lõi:
        1. Chẩn đoán & Phân loại: Phân loại Bệnh Nha chu (AAP 2017), Phân loại Tổn thương Chẽ (Furcation Classification).
        2. Tiên lượng & Theo dõi: Đánh giá tiên lượng từng răng, Chỉ số Bám dính Lâm sàng (CAL).
        3. Phẫu thuật Xoang & Ghép: Các kỹ thuật làm dài thân răng (CL), kỹ thuật vạt (flap design), ghép xương và màng chắn.
        4. Nha chu quanh Implant: Chẩn đoán và điều trị Viêm quanh Implant (Peri-implantitis).
        5. Dược lý Nha chu: Phác đồ kháng sinh và kháng viêm hỗ trợ.

        QUY TRÌNH TƯ DUY ĐA CHẾ ĐỘ (MULTI-MODE PROTOCOL):
        
        CHẾ ĐỘ 1: KHAI THÁC ỨNG DỤNG TỪ HÌNH ẢNH/LÝ THUYẾT (Visual-to-Action)
        (Dùng khi người dùng hỏi về hình ảnh hoặc tình huống lâm sàng mô tả)
        - Bước 1: Nhận diện Thông số "Sống còn" (PD, CAL, Tiêu xương Ngang/Dọc, Khoảng sinh học).
        - Bước 2: Phân tích Ý nghĩa Điều trị & Tiên lượng.
          + Nếu CAL > 5mm và Tổn thương Dọc -> GTR, Papilla Preservation.
          + Nếu Tổn thương Chẽ độ III -> Tiên lượng xấu -> Nhổ/Hemisection/Tunnelization.
        - Bước 3: Tổng hợp thành Quy tắc "Nếu - Thì".

        CHẾ ĐỘ 2: TƯ DUY CA BỆNH & LẬP KẾ HOẠCH (Surgical Reasoning)
        (Dùng khi hỏi về ca bệnh cụ thể)
        - Quy trình: Đánh giá mô mềm -> Thiết kế vạt -> Vệ sinh bề mặt -> Ghép -> Đóng vạt.
        - Phản biện Socratic: Tại sao chọn kỹ thuật A thay vì B?
        - Cây quyết định: Mất răng có tiêu xương -> Ghép xương trước -> Implant sau.

        CHẾ ĐỘ 3: LUYỆN THI & TÌM BẪY (Exam Mode)
        (Dùng khi người dùng làm câu hỏi trắc nghiệm)
        - Phân tích: Tại sao đáp án này đúng về mặt tiên lượng nha chu?
        - Cảnh báo Bẫy: 
          + Bẫy Thuật ngữ (PD vs CAL).
          + Bẫy Quy trình (Ghép xương cho Chẽ độ III).
          + Bẫy Phân loại (Grade vs Stage).

        NGUYÊN TẮC GIAO TIẾP:
        - Luôn hỏi ngược lại: "Bạn đã đo CAL chưa?" nếu thiếu thông tin.
        - Sử dụng thuật ngữ tiếng Việt chuẩn (Mức xương rìa, Tổn thương chẽ...).
        - Ưu tiên kiến thức trong file/câu hỏi hiện tại (CONTEXT) để đảm bảo điểm số thi cử.
        """
        return system_prompt

    @staticmethod
    def save_config(config):
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    # --- PROMPTS MANAGEMENT ---
    @staticmethod
    def load_prompts():
        if not os.path.exists('prompts.json'):
            return {}
        try:
            with open('prompts.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}

    @staticmethod
    def save_prompts(prompts):
        with open('prompts.json', 'w', encoding='utf-8') as f:
            json.dump(prompts, f, indent=2, ensure_ascii=False)

            
    # --- IMPORT EXCEL ---
    @staticmethod
    def import_from_excel(file, current_data=[]):
        try:
            df = pd.read_excel(file)
            new_cards = []
            
            # Tạo "Hàng rào bảo vệ": Lấy danh sách câu hỏi đang có trong kho
            existing_questions = {card['question'].strip().lower() for card in current_data}
            count_skipped = 0
            
            for _, row in df.iterrows():
                q_raw = str(row.get('Question', ''))
                # Clean "Câu X", "Question Y" prefixes
                # Regex: Start with Câu/Question/Bài + space + number + colon/dot + space
                q_clean_display = re.sub(r'^(?:Câu|Question|Bài|Case)\s*\d+[:.]\s*', '', q_raw, flags=re.IGNORECASE).strip()
                q_clean_dedup = q_clean_display.lower()
                
                # --- CHẶN CỬA: Nếu trùng với kho hiện tại -> Bỏ qua ngay ---
                if not q_clean_dedup or q_clean_dedup in existing_questions:
                    count_skipped += 1
                    continue
                
                # Nếu là câu mới -> Cho phép vào
                card = {
                    "id": str(uuid.uuid4()), 
                    "question": q_clean_display, # Lưu bản đã clean
                    "options": {
                        "A": str(row.get('Option A', '')),
                        "B": str(row.get('Option B', '')),
                        "C": str(row.get('Option C', '')),
                        "D": str(row.get('Option D', ''))
                    },
                    "correct_answer": str(row.get('Correct Answer', 'A')).strip().upper(),
                    "explanation": str(row.get('Explanation', '')),
                    "source": str(row.get('Source', '')), 
                    "mnemonic": str(row.get('Mnemonic', '')),
                    "subject": str(row.get('Subject', 'Chung')),
                    "topic": str(row.get('Topic', 'Tổng hợp')),
                    "tags": [],
                    "chat_history": [],
                    "image_q": str(row.get('Image Q', '')).strip(),
                    "image_a": str(row.get('Image A', '')).strip()
                }
                 # Fix lỗi NaN của pandas nếu ô trống
                if card['image_q'] == 'nan': card['image_q'] = ""
                if card['image_a'] == 'nan': card['image_a'] = ""

                new_cards.append(card)
                
                # Thêm vào danh sách check để chặn trùng ngay trong chính file đang import
                existing_questions.add(q_clean_dedup)
                
            return new_cards, None, count_skipped
        except Exception as e:
            return [], str(e), 0

    # --- BACKUP RIÊNG LẺ ---
    @staticmethod
    def create_backup(username):
        """Backup dữ liệu của riêng user này"""
        folder = DataManager.get_user_folder(username)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Zip toàn bộ folder của user
            for root, dirs, files in os.walk(folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    zip_file.write(file_path, file) # Lưu phẳng vào zip
            
            # Backup luôn folder ảnh chung (static/images)
            # Vì ảnh dùng chung ID nên cứ backup hết cho an toàn
            images_dir = "static/images"
            if os.path.exists(images_dir):
                for root, dirs, files in os.walk(images_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zip_file.write(file_path, os.path.join("images", file))
        buffer.seek(0)
        return buffer

    @staticmethod
    def restore_backup(uploaded_zip, username):
        """Giải nén file ZIP và ghi đè dữ liệu cũ CỦA USER"""
        try:
             folder = DataManager.get_user_folder(username)
             with zipfile.ZipFile(uploaded_zip, 'r') as z:
                z.extractall(path=folder) # Extract vào folder của user
                return True, "Khôi phục dữ liệu thành công!"
        except Exception as e:
            return False, str(e)

# ... (SRSEngine and Views remain unchanged) ...

# --- TREE / HIERARCHY HELPER ---
class TreeHelper:
    @staticmethod
    def get_all_subjects(data):
        return sorted(list({c['subject'] for c in data}))

    @staticmethod
    def build_tree(data):
        """
        Builds a nested dictionary from subject paths.
        Example: "A/B", "A/C" -> {'A': {'B': {}, 'C': {}}}
        Leaf nodes are empty dicts for now, or we can store simple marker.
        Actually, we need to distinguish between a 'Folder' and a 'Real Subject' that has cards.
        But for simplicity, any node can be a subject if it matches a card's subject string.
        """
        tree = {}
        # 1. Collect all subject strings
        subjects = TreeHelper.get_all_subjects(data)
        
        for sub in subjects:
            parts = [p.strip() for p in sub.split('/') if p.strip()]
            current = tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        return tree

    @staticmethod
    def count_cards_recursive(data, prefix_path):
        """Count cards that start with this prefix path"""
        count = 0
        prefix_path = prefix_path.strip()
        for c in data:
            if c['subject'] == prefix_path or c['subject'].startswith(prefix_path + '/'):
                count += 1
        return count

# --- MAIN ---
def main():
    # Load Persistent Config
    config = DataManager.load_config()
    
    # Initialize Session State API Key from Config if not already set
    if 'api_key' not in st.session_state:
        st.session_state.api_key = config.get('api_key', '')

    with st.sidebar:
        st.title("🦷 Dental Master")
        
        # --- API KEY MANAGE ---
        with st.expander("🔑 Cấu hình API Key", expanded=not st.session_state.api_key):
            new_key = st.text_input("Gemini API Key", value=st.session_state.api_key, type="password")
            if st.button("Lưu Key"):
                st.session_state.api_key = new_key
                config['api_key'] = new_key
                DataManager.save_config(config)
                st.success("Đã lưu API Key!")
                st.rerun()
        
        st.divider()
        
        if st.button("📚 Thư viện", use_container_width=True):
            st.session_state.view = 'library'
            st.session_state.selected_subject = None
            st.rerun()
        
        if st.button("📥 Import Data", use_container_width=True):
            st.session_state.view = 'import'
            st.rerun()

        # Nút Quản lý ở sidebar luôn cho tiện
        if st.button("⚙️ Quản lý & Cấu hình", use_container_width=True):
            st.session_state.view = 'manage'
            st.rerun()
            
        st.markdown("---")
        st.caption(f"Phiên bản v2.2 | SRS Medical Mode")

        # --- SLIDE VISION MENU ---
        if st.button("👁️ Slide Vision", use_container_width=True):
            st.session_state.view = 'vision'
            st.rerun()
        
        # --- CLOUD SYNC BUTTON ---
        st.markdown("---")
        st.markdown("**☁️ Cloud Sync**")
        if GoogleSheetsManager.get_client():
            if st.button("🔄 Đồng bộ lên Cloud", use_container_width=True, type="primary"):
                with st.spinner("Đang đồng bộ..."):
                    success, msg = DataManager.sync_to_cloud(username)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
        else:
            st.caption("⚠️ Cloud chưa kết nối")

# --- AI ASSISTANT (New SDK) ---
def ask_professor(api_key, context, user_question, chat_history=[]):
    if not HAS_GENAI:
        return "⚠️ Thư viện `google-genai` chưa được cài đặt."
    if not api_key:
        return "⚠️ Vui lòng nhập API Key ở thanh bên trái."
    
    try:
        client = genai.Client(api_key=api_key)
        
        # --- PROMPT RESOLUTION LOGIC ---
        # 1. Get Subject/Topic from context
        subject = context.get('subject', '')
        
        # 3. Find Best Match
        system_prompt = DataManager.resolve_system_prompt(subject)

        # Append Context Information (Always)
        system_prompt += f"""
        THÔNG TIN CÂU HỎI HIỆN TẠI (CONTEXT):
        - Câu hỏi: {context['question']}
        - Các đáp án: {context['options']}
        - Đáp án đúng: {context['correct_answer']}
        - Giải thích gốc: {context['explanation']}
        - Mẹo nhớ: {context.get('mnemonic', 'Không có')}
        - Nguồn: {context.get('source', 'Không có')}
        """
        
        # Construct content with history
        contents = [system_prompt]
        
        # Add history
        for msg in chat_history:
            role = "admin" if msg['role'] == "assistant" else "user" # Map assistant to model if needed, but 'model' or 'user' roles. 
            # Note: Gemini often uses 'user' and 'model'. Let's map accordingly.
            # Assuming 'assistant' is the model.
            
            # Simple Text concatenation for now as it's most robust with simple list
            prefix = "Người dùng hỏi: " if msg['role'] == "user" else "Giáo sư trả lời: "
            contents.append(f"{prefix}{msg['content']}")

        # Add current question
        contents.append(f"Người dùng hỏi: {user_question}")
        
        final_prompt = "\n\n".join(contents)

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=final_prompt
            # Note: For structred chat, we should use chat objects, but concatenated prompt works well for context here.
        )
        return response.text
    except Exception as e:
        return f"Lỗi API: {str(e)}"

# --- MOCK EXAM ---
def view_mock_exam(data, username):
    st.title("🏆 Phòng Thi Giả Lập (Mock Exam)")
    
    # --- MÀN HÌNH 1: CẤU HÌNH ĐỀ THI ---
    if 'exam_session' not in st.session_state:
        st.markdown("Chọn thông số để tạo đề thi thử ngẫu nhiên.")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            # Lọc môn học
            subjects = sorted(list({c['subject'] for c in data}))
            selected_subs = st.multiselect("Môn thi:", subjects, default=subjects)
        with c2:
            num_q = st.number_input("Số lượng câu hỏi:", min_value=5, max_value=100, value=20)
        with c3:
            minutes = st.number_input("Thời gian (phút):", min_value=5, max_value=180, value=15)
            
        if st.button("🚀 Bắt đầu làm bài", type="primary"):
            # 1. Lọc câu hỏi
            # Filter: Only cards with valid options (exclude placeholders)
            pool = [c for c in data if c['subject'] in selected_subs and c.get('options') and not c.get('is_placeholder')]
            if len(pool) < num_q:
                st.error(f"Kho câu hỏi chỉ có {len(pool)} câu (yêu cầu {num_q}). Hãy giảm số lượng.")
            else:
                # 2. Random đề
                import random
                exam_questions = random.sample(pool, num_q)
                
                # 3. Khởi tạo Session Thi
                st.session_state.exam_session = {
                    "questions": exam_questions,
                    "user_answers": {}, # Lưu đáp án: {card_id: "A"}
                    "start_time": datetime.datetime.now(),
                    "duration": minutes,
                    "submitted": False
                }
                st.rerun()

    # --- MÀN HÌNH 2: ĐANG LÀM BÀI ---
    else:
        session = st.session_state.exam_session
        
        # 1. Header: Đồng hồ & Nộp bài
        elapsed = datetime.datetime.now() - session['start_time']
        remaining = timedelta(minutes=session['duration']) - elapsed
        
        # Nếu hết giờ -> Tự động nộp
        if remaining.total_seconds() <= 0 and not session['submitted']:
            session['submitted'] = True
            st.toast("HẾT GIỜ! Hệ thống đã tự động nộp bài.", icon="⏰")
            st.rerun()

        col_timer, col_submit = st.columns([3, 1])
        with col_timer:
            if not session['submitted']:
                # Hiển thị đồng hồ đếm ngược (LIVE JS)
                remaining_seconds = int(remaining.total_seconds())
                if remaining_seconds < 0: remaining_seconds = 0
                
                # Container cho timer
                timer_html = f"""
                <div id="countdown_timer" style="
                    font-size: 3em; 
                    font-weight: bold; 
                    color: #FF4B4B; 
                    text-align: center;
                    font-family: monospace;
                    margin-bottom: 20px;
                ">
                    Loading...
                </div>
                <script>
                (function() {{
                    var timeLeft = {remaining_seconds};
                    var timerElement = document.getElementById("countdown_timer");
                    
                    function formatTime(seconds) {{
                        var m = Math.floor(seconds / 60);
                        var s = seconds % 60;
                        return (m < 10 ? "0" + m : m) + ":" + (s < 10 ? "0" + s : s);
                    }}
                    
                    // Update immediately
                    if (timerElement) timerElement.innerHTML = formatTime(timeLeft);
                    
                    var countdown = setInterval(function() {{
                        timeLeft--;
                        if (timeLeft <= 0) {{
                            clearInterval(countdown);
                            if (timerElement) timerElement.innerHTML = "00:00";
                            // Optional: Trigger reload if needed, but user might be working
                        }} else {{
                            if (timerElement) timerElement.innerHTML = formatTime(timeLeft);
                        }}
                    }}, 1000);
                }})();
                </script>
                """
                st.components.v1.html(timer_html, height=100)
            else:
                st.success("🏁 ĐÃ NỘP BÀI")
                
                # --- SCORE CALCULATION & DASHBOARD ---
                total_q = len(session['questions'])
                correct_count = 0
                for q in session['questions']:
                    qid = q['id']
                    user_ans = session['user_answers'].get(qid, None)
                    if user_ans == q['correct_answer']:
                        correct_count += 1
                
                score_pct = int((correct_count / total_q) * 100) if total_q > 0 else 0
                
                # Metric Row
                m1, m2, m3 = st.columns(3)
                m1.metric("Điểm số", f"{correct_count}/{total_q}")
                m2.metric("Tỷ lệ đúng", f"{score_pct}%")
                
                grade = ""
                if score_pct >= 90: grade = "Xuất sắc! 🏆"
                elif score_pct >= 80: grade = "Giỏi! 🌟"
                elif score_pct >= 65: grade = "Khá 👍"
                elif score_pct >= 50: grade = "Đạt (Trung bình) 👌"
                else: grade = "Cần cố gắng hơn 💪"
                
                m3.metric("Đánh giá", grade)
                
                # Progress Bar color
                bar_color = "green" if score_pct >= 50 else "red"
                st.progress(score_pct / 100, text=f"Kết quả: {score_pct}%")
                st.divider()

        with col_submit:
            if not session['submitted']:
                if st.button("Nộp bài sớm", type="primary"):
                    session['submitted'] = True
                    st.rerun()
            else:
                if st.button("Thoát phòng thi"):
                    del st.session_state.exam_session
                    st.rerun()

        st.divider()

        # 2. Danh sách câu hỏi (Dạng cuộn)
        # NẾU CHƯA NỘP: Hiện câu hỏi + Radio Button
        # NẾU ĐÃ NỘP: Hiện Kết quả chấm điểm
        
        score = 0
        
        for i, q in enumerate(session['questions']):
            # CLEAN PREFIX manually (Quick Fix for legacy data)
            # Regex removes "Câu X:" or "Question Y." from the start
            q_display = re.sub(r'^(?:Câu|Question|Bài|Case)\s*\d+[:.]\s*', '', q.get('question', ''), flags=re.IGNORECASE).strip()
            
            st.markdown(f"**Câu {i+1}:** {q_display}")
            
            # Xử lý hình ảnh nếu có
            if q.get('image_q'):
                img_path = os.path.join("static", "images", q['image_q'])
                if os.path.exists(img_path):
                    # Default view: Moderate size
                    st.image(img_path, width=350) 
                    # Zoom feature
                    with st.expander("🔍 Phóng to ảnh (Zoom)"):
                        st.image(img_path, width=700) # Moderate zoom, not full width

            options = ["A", "B", "C", "D"]
            opts = q.get('options', {})
            labels = [f"{opt}. {opts.get(opt, '')}" for opt in options]
            
            qid = q['id']
            # Lấy đáp án đã chọn (nếu có)
            prev_choice = session['user_answers'].get(qid, None)
            
            if not session['submitted']:
                # CHẾ ĐỘ LÀM BÀI
                choice = st.radio(
                    f"Chọn đáp án (Câu {i+1}):", 
                    options, 
                    index=options.index(prev_choice) if prev_choice else None,
                    format_func=lambda x: f"{x}. {opts.get(x, '')}",
                    key=f"exam_q_{i}",
                    horizontal=True,
                    label_visibility="collapsed"
                )
                # Lưu đáp án ngay khi chọn
                if choice:
                    session['user_answers'][qid] = choice
            else:
                # CHẾ ĐỘ XEM KẾT QUẢ
                user_ans = session['user_answers'].get(qid, "Chưa làm")
                correct_ans = q['correct_answer']
                
                # Chấm điểm
                if user_ans == correct_ans:
                    score += 1
                    st.success(f"✅ Bạn chọn: {user_ans}. Chính xác!")
                else:
                    st.error(f"❌ Bạn chọn: {user_ans}. Đáp án đúng: {correct_ans}")
                    st.info(f"💡 Giải thích: {q['explanation']}")
            
            st.markdown("---")

        # 3. Tổng kết điểm (Nếu đã nộp)
        if session['submitted']:
            total = len(session['questions'])
            percent = int((score / total) * 100)
            
            if percent >= 90: msg = "Xuất sắc! 🥇"
            elif percent >= 70: msg = "Khá tốt! 🥈"
            elif percent >= 50: msg = "Đạt yêu cầu. 🥉"
            else: msg = "Cần ôn lại gấp! 💀"
            
            st.sidebar.title("📊 KẾT QUẢ")
            st.sidebar.metric("Điểm số", f"{score}/{total}")
            st.sidebar.progress(percent / 100)
            st.sidebar.write(msg)

# --- VIEWS ---
def view_manage_library(data, username):
    st.title("🛠️ Quản lý & Cấu hình")
    
    # SỬA DÒNG NÀY (Thêm tab thứ 6 - AI Prompts)
    tab1, tab6, tab2, tab3, tab4, tab5 = st.tabs(["📁 Quản lý Chủ đề", "🤖 AI Prompts", "⚙️ Cấu hình SRS", "📖 Hướng dẫn Y khoa", "📝 Quản lý Thẻ", "📦 Backup & Restore"])
    
    with tab6:
        st.subheader("🤖 Cấu hình Prompt cho AI")
        st.info("Tại đây bạn có thể thiết lập vai trò (Prompt) riêng cho từng Môn học.")
        
        # Load prompts
        prompts = DataManager.load_prompts()
        
        # Get subjects locally to populate dropdown
        all_subjects = sorted(list({c['subject'] for c in data}))
        if not all_subjects: all_subjects = ["(Chưa có môn học nào)"]
        
        # UI: Select Subject
        selected_subject_p = st.selectbox("Chọn Môn học để cấu hình:", ["(Mặc định)"] + all_subjects)
        
        # Determine Current Prompt Key
        p_key = "DEFAULT" if selected_subject_p == "(Mặc định)" else selected_subject_p
        
        # Default System Prompt (Hardcoded fallback)
        default_system_prompt = """VAI TRÒ (ROLE):
Bạn là Giảng viên/Chuyên gia Y khoa.

NHIỆM VỤ:
- Giải thích câu hỏi trắc nghiệm.
- Phân tích đáp án đúng/sai.
- Cung cấp mẹo nhớ (Mnemonic).
- Giữ giọng văn sư phạm, chuyên nghiệp."""

        # Get existing or inherited prompt
        current_val = prompts.get(p_key, "")
        
        if not current_val:
            # If no explicit set, show what would be used (Inheritance logic simulation)
            if p_key == "DEFAULT":
                placeholder = default_system_prompt
                help_txt = "Đây là prompt mặc định cứng của hệ thống."
            else:
                # Try to find parent
                parent_val = None
                # Checking parents (simple path splitting)
                parts = p_key.split('/')
                for i in range(len(parts)-1, 0, -1):
                    parent_key = "/".join(parts[:i])
                    if parent_key in prompts:
                        parent_val = prompts[parent_key]
                        break
                
                if parent_val:
                    placeholder = parent_val
                    help_txt = f"Đang thừa kế từ: {parent_key}"
                else: 
                    # Checking DEFAULT
                    if "DEFAULT" in prompts:
                        placeholder = prompts["DEFAULT"]
                        help_txt = "Đang thừa kế từ cấu hình Mặc định (User define)."
                    else:
                        placeholder = default_system_prompt
                        help_txt = "Đang dùng prompt mặc định gốc của hệ thống."
        else:
            placeholder = current_val
            help_txt = "Đang dùng cấu hình riêng cho môn này."

        st.caption(f"ℹ️ {help_txt}")
        
        # Editor
        new_prompt = st.text_area("Nội dung Prompt:", value=current_val, placeholder=str(placeholder), height=300)
        
        col_save, col_clear = st.columns([0.2, 0.8])
        
        if col_save.button("💾 Lưu Cấu hình", type="primary"):
            if not new_prompt.strip():
                # If saving empty, it means we might want to delete (revert to inherit)
                 if p_key in prompts:
                     del prompts[p_key]
                     DataManager.save_prompts(prompts)
                     st.success(f"Đã xóa cấu hình riêng cho '{p_key}'. Giờ sẽ dùng cơ chế thừa kế.")
                     st.rerun()
            else:
                prompts[p_key] = new_prompt
                DataManager.save_prompts(prompts)
                st.success(f"Đã lưu prompt cho '{p_key}'!")
                st.rerun()
                
        if col_clear.button("🗑️ Xóa/Đặt lại về mặc định"):
            if p_key in prompts:
                del prompts[p_key]
                DataManager.save_prompts(prompts)
                st.success("Đã reset!")
                st.rerun()
            else:
                st.info("Hiện chưa có cấu hình riêng nào để xóa.")
    
    with tab5:
        st.subheader("📦 Sao lưu và Khôi phục dữ liệu")
        st.info("Hãy thường xuyên tải bản sao lưu để tránh mất dữ liệu khi gặp sự cố.")
        
        col_b1, col_b2 = st.columns(2)
        
        # --- PHẦN 1: TẢI VỀ (BACKUP) ---
        with col_b1:
            st.markdown("#### ⬇️ Sao lưu (Export)")
            st.write("Tải xuống gói dữ liệu gồm: Câu hỏi, Tiến độ học và Hình ảnh.")
            
            # Tạo tên file có ngày giờ (VD: dental_backup_2023-10-27.zip)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
            file_name = f"dental_backup_{timestamp}.zip"
            
            # Nút tải xuống
            # Lưu ý: Mỗi lần bấm nút này, code sẽ chạy hàm create_backup()
            btn = st.download_button(
                label="📥 Tải xuống bản Backup (.zip)",
                data=DataManager.create_backup(username),
                file_name=file_name,
                mime="application/zip",
                type="primary"
            )
            
        # --- PHẦN 2: KHÔI PHỤC (RESTORE) ---
        with col_b2:
            st.markdown("#### ⬆️ Khôi phục (Import)")
            st.warning("⚠️ Cảnh báo: Hành động này sẽ GHI ĐÈ toàn bộ dữ liệu hiện tại.")
            
            uploaded_zip = st.file_uploader("Chọn file Backup (.zip) để khôi phục:", type="zip")
            
            if uploaded_zip:
                if st.button("🚨 Xác nhận Khôi phục", type="secondary"):
                    success, msg = DataManager.restore_backup(uploaded_zip, username)
                    if success:
                        st.success(msg)
                        st.toast("Dữ liệu đã được khôi phục!", icon="✅")
                        # Reload lại trang sau 2 giây
                        import time
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Lỗi: {msg}")

    with tab1:
        # --- ANKI-STYLE TREE ORGANIZER ---
        st.markdown("### 🗂️ Quản lý Thư mục")
        
        # Initialize session state for selections and edit mode
        if 'folder_selections' not in st.session_state:
            st.session_state.folder_selections = set()
        if 'editing_folder' not in st.session_state:
            st.session_state.editing_folder = None
        if 'moving_folder' not in st.session_state:
            st.session_state.moving_folder = None
        
        # Get all unique subjects
        all_subjects = sorted(list({c['subject'] for c in data}))
        
        # --- TOOLBAR ---
        tool_c1, tool_c2, tool_c3 = st.columns([2, 2, 2])
        
        with tool_c1:
            # CREATE NEW FOLDER
            with st.popover("➕ Tạo thư mục mới"):
                new_folder_name = st.text_input("Tên thư mục:", key="new_folder_input", placeholder="VD: Nha khoa")
                parent_options = ["(Root - Gốc)"] + all_subjects
                new_folder_parent = st.selectbox("Thư mục cha:", parent_options, key="new_folder_parent")
                
                if st.button("✅ Tạo", key="btn_create_folder", type="primary"):
                    if new_folder_name.strip():
                        # Determine full path
                        if new_folder_parent == "(Root - Gốc)":
                            folder_path = new_folder_name.strip()
                        else:
                            folder_path = f"{new_folder_parent}/{new_folder_name.strip()}"
                        
                        # Check if already exists
                        if any(c['subject'] == folder_path for c in data):
                            st.warning(f"Thư mục '{folder_path}' đã tồn tại!")
                        else:
                            # Create placeholder card for this folder
                            import uuid
                            placeholder_card = {
                                'id': str(uuid.uuid4()),
                                'subject': folder_path,
                                'topic': '_folder_placeholder',
                                'question': f'[Thư mục: {new_folder_name.strip()}]',
                                'answer': 'Đây là thư mục. Hãy thêm thẻ vào đây.',
                                'options': {'A': '', 'B': '', 'C': '', 'D': ''},
                                'correct_answer': 'A',
                                'explanation': '',
                                'is_placeholder': True
                            }
                            data.append(placeholder_card)
                            DataManager.save_data(username, data)
                            st.success(f"✅ Đã tạo thư mục '{new_folder_name}'!")
                            st.rerun()
                    else:
                        st.error("Tên không được để trống!")
        
        with tool_c2:
            # BULK DELETE
            selected_count = len(st.session_state.folder_selections)
            if selected_count > 0:
                if st.button(f"🗑️ Xóa {selected_count} mục đã chọn", type="secondary", use_container_width=True):
                    # Delete all cards in selected subjects
                    to_delete = st.session_state.folder_selections
                    original_len = len(data)
                    # Delete cards matching selected subjects OR their children
                    data[:] = [c for c in data if not any(
                        c['subject'] == s or c['subject'].startswith(s + '/') 
                        for s in to_delete
                    )]
                    deleted = original_len - len(data)
                    DataManager.save_data(username, data)
                    st.session_state.folder_selections = set()
                    st.toast(f"Đã xóa {deleted} thẻ!", icon="🗑️")
                    st.rerun()
        
        with tool_c3:
            # CLEAR SELECTION
            if selected_count > 0:
                if st.button("❌ Bỏ chọn tất cả", use_container_width=True):
                    st.session_state.folder_selections = set()
                    st.rerun()
        
        st.divider()
        
        # --- TREE DISPLAY ---
        if not all_subjects:
            st.info("📭 Chưa có dữ liệu. Hãy Import thẻ để bắt đầu.")
        else:
            # Build tree structure for display
            tree = TreeHelper.build_tree(data)
            
            def render_tree_row(node, path="", level=0):
                """Render each folder/subject as an interactive row."""
                for name in sorted(node.keys()):
                    full_path = f"{path}/{name}" if path else name
                    children = node[name]
                    has_children = len(children) > 0
                    
                    # Count cards in this subject (and children)
                    card_count = sum(1 for c in data if c['subject'] == full_path or c['subject'].startswith(full_path + '/'))
                    
                    # ROW LAYOUT
                    indent = "　" * level  # Full-width space for visual indent
                    icon = "📁" if has_children else "📘"
                    
                    # Check if this row is being edited
                    is_editing = st.session_state.editing_folder == full_path
                    is_moving = st.session_state.moving_folder == full_path
                    
                    with st.container(border=True):
                        # NORMAL MODE
                        if not is_editing and not is_moving:
                            row_c1, row_c2, row_c3, row_c4, row_c5 = st.columns([0.5, 5, 1, 1, 1])
                            
                            with row_c1:
                                # Checkbox
                                is_selected = full_path in st.session_state.folder_selections
                                if st.checkbox("Select", value=is_selected, key=f"chk_{full_path}", label_visibility="collapsed"):
                                    st.session_state.folder_selections.add(full_path)
                                else:
                                    st.session_state.folder_selections.discard(full_path)
                            
                            with row_c2:
                                st.markdown(f"{indent}{icon} **{name}** `({card_count} thẻ)`")
                            
                            with row_c3:
                                # RENAME
                                if st.button("✏️", key=f"rename_{full_path}", help="Đổi tên"):
                                    st.session_state.editing_folder = full_path
                                    st.rerun()
                            
                            with row_c4:
                                # MOVE
                                if st.button("↗️", key=f"move_{full_path}", help="Di chuyển"):
                                    st.session_state.moving_folder = full_path
                                    st.rerun()
                            
                            with row_c5:
                                # DELETE SINGLE
                                if st.button("🗑️", key=f"del_{full_path}", help="Xóa"):
                                    # Delete this subject and children
                                    data[:] = [c for c in data if not (c['subject'] == full_path or c['subject'].startswith(full_path + '/'))]
                                    DataManager.save_data(username, data)
                                    st.toast(f"Đã xóa '{name}'!", icon="🗑️")
                                    st.rerun()
                        
                        # EDIT MODE (Rename)
                        elif is_editing:
                            edit_c1, edit_c2, edit_c3 = st.columns([5, 1, 1])
                            with edit_c1:
                                new_name = st.text_input("Tên mới:", value=name, key=f"edit_input_{full_path}", label_visibility="collapsed")
                            with edit_c2:
                                if st.button("💾", key=f"save_rename_{full_path}", help="Lưu"):
                                    if new_name.strip() and new_name != name:
                                        # Rename: Replace old path segment with new name
                                        old_prefix = full_path
                                        # Get parent path
                                        if '/' in full_path:
                                            parent = full_path.rsplit('/', 1)[0]
                                            new_prefix = f"{parent}/{new_name.strip()}"
                                        else:
                                            new_prefix = new_name.strip()
                                        
                                        # Update all cards
                                        for card in data:
                                            if card['subject'] == old_prefix:
                                                card['subject'] = new_prefix
                                            elif card['subject'].startswith(old_prefix + '/'):
                                                card['subject'] = new_prefix + card['subject'][len(old_prefix):]
                                        
                                        DataManager.save_data(username, data)
                                        st.toast(f"Đã đổi tên '{name}' → '{new_name}'!", icon="✅")
                                    
                                    st.session_state.editing_folder = None
                                    st.rerun()
                            with edit_c3:
                                if st.button("❌", key=f"cancel_rename_{full_path}", help="Hủy"):
                                    st.session_state.editing_folder = None
                                    st.rerun()
                        
                        # MOVE MODE
                        elif is_moving:
                            move_c1, move_c2, move_c3 = st.columns([5, 1, 1])
                            with move_c1:
                                # Target selection
                                target_options = ["(Root - Gốc)"] + [s for s in all_subjects if s != full_path and not s.startswith(full_path + '/')]
                                target = st.selectbox("Di chuyển đến:", target_options, key=f"move_target_{full_path}", label_visibility="collapsed")
                            with move_c2:
                                if st.button("✅", key=f"confirm_move_{full_path}", help="Xác nhận"):
                                    # Move logic
                                    source_basename = full_path.split('/')[-1]
                                    target_prefix = "" if target == "(Root - Gốc)" else target
                                    
                                    for card in data:
                                        if card['subject'] == full_path or card['subject'].startswith(full_path + '/'):
                                            if card['subject'] == full_path:
                                                suffix = ""
                                            else:
                                                suffix = card['subject'][len(full_path):]
                                            
                                            if target_prefix:
                                                card['subject'] = f"{target_prefix}/{source_basename}{suffix}"
                                            else:
                                                card['subject'] = f"{source_basename}{suffix}"
                                    
                                    DataManager.save_data(username, data)
                                    st.toast(f"Đã di chuyển '{name}'!", icon="✅")
                                    st.session_state.moving_folder = None
                                    st.rerun()
                            with move_c3:
                                if st.button("❌", key=f"cancel_move_{full_path}", help="Hủy"):
                                    st.session_state.moving_folder = None
                                    st.rerun()
                    
                    # Render children (always expanded for now)
                    if has_children:
                        render_tree_row(children, full_path, level + 1)
            
            render_tree_row(tree)



    with tab2:
        st.subheader("⚙️ Cấu hình SRS (Medical Mode)")
        st.markdown("Tinh chỉnh các thông số để phù hợp với tốc độ học của bạn.")
        
        cfg = st.session_state.srs_config
        
        with st.form("srs_config_form"):
            c1, c2 = st.columns(2)
            with c1:
                new_learning_steps = st.text_input("Learning Steps (phút):", 
                                                   value=", ".join(map(str, cfg['LEARNING_STEPS'])),
                                                   help="Các mốc thời gian ôn tập trong ngày đầu tiên. Ví dụ: '1, 10' nghĩa là học xong 1 phút hỏi lại, 10 phút sau hỏi lại tiếp.")
                new_cards_limit = st.number_input("Số từ mới tối đa/ngày:", value=cfg['NEW_CARDS_PER_DAY'], min_value=0, help="Giới hạn số lượng thẻ mới học mỗi ngày để tránh quá tải.")
                max_reviews = st.number_input("Số review tối đa/ngày:", value=cfg['MAX_REVIEWS_PER_DAY'], min_value=0, help="Giới hạn số thẻ ôn tập lại. Nên để cao (9999) để không bỏ sót bài cũ.")
            
            with c2:
                grad_ivl = st.number_input("Graduating Interval (ngày):", value=cfg['GRADUATING_INTERVAL'], min_value=1, help="Số ngày chờ sau khi hoàn thành Learning Steps.")
                easy_ivl = st.number_input("Easy Interval (ngày):", value=cfg['EASY_INTERVAL'], min_value=1, help="Số ngày chờ nếu chọn Easy ngay lần đầu.")
                start_ease = st.number_input("Starting Ease:", value=cfg['STARTING_EASE'], min_value=1.3, step=0.1, help="Hệ số nhân khó dễ ban đầu. Cao hơn = Dễ hơn (lâu lặp lại hơn).")
                
            if st.form_submit_button("💾 Lưu cấu hình"):
                try:
                    # Parse steps
                    steps = [int(x.strip()) for x in new_learning_steps.split(",") if x.strip().isdigit()]
                    if not steps: steps = [1, 15, 60] # Fallback
                    
                    st.session_state.srs_config.update({
                        "LEARNING_STEPS": steps,
                        "NEW_CARDS_PER_DAY": int(new_cards_limit),
                        "MAX_REVIEWS_PER_DAY": int(max_reviews),
                        "GRADUATING_INTERVAL": int(grad_ivl),
                        "EASY_INTERVAL": int(easy_ivl),
                        "STARTING_EASE": float(start_ease)
                    })
                    st.success("✅ Đã lưu cấu hình mới!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi nhập liệu: {e}")

    with tab3:
        st.subheader("📖 Hướng dẫn Cấu hình SRS")
        
        st.markdown("""
        **Nguyên lý:** Chế độ Y khoa ưu tiên **độ chính xác** cao hơn tốc độ. 
        Mọi thiết lập mặc định đều nhắm tới việc ngăn chặn "học trước quên sau".
        
        <style>
            .guide-table {width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.95em;}
            .guide-table th, .guide-table td {border: 1px solid #e0e0e0; padding: 8px; text-align: left; vertical-align: middle;}
            .guide-table th {background-color: #f0f2f6; font-weight: 600; color: #333;}
            .guide-table td code {background-color: #e9ecef; padding: 2px 5px; border-radius: 4px; color: #d63384; font-weight: bold;}
        </style>
        
        <table class="guide-table">
            <thead>
                <tr>
                    <th style="width: 20%;">Thông số</th>
                    <th style="width: 25%;">Ý nghĩa & Gợi ý</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>Learning Steps</strong><br><code>1, 15, 60</code> (phút)</td>
                    <td>Chuỗi thời gian ôn tập <strong>ngay trong ngày đầu</strong>.<br>Bạn phải vượt qua đủ 3 mốc (1p, 15p, 60p) mới được tính là "Thuộc bài".</td>
                </tr>
                <tr>
                    <td><strong>New Cards/Day</strong><br><code>20</code> thẻ</td>
                    <td>Số lượng thẻ mới mỗi ngày.<br><em>Lưu ý:</em> 20 thẻ Y khoa rất nặng, tương đương 100 từ vựng thường.</td>
                </tr>
                <tr>
                    <td><strong>Max Reviews/Day</strong><br><code>9999</code> thẻ</td>
                    <td>Giới hạn số thẻ ôn tập mỗi ngày.<br>Nên để tối đa để <strong>không bao giờ bỏ sót</strong> bài cũ cần ôn.</td>
                </tr>
                <tr>
                    <td><strong>Graduating Interval</strong><br><code>1</code> ngày</td>
                    <td>Khoảng cách ôn lần tiếp theo sau khi "Thuộc bài".<br>Mặc định <strong>1 ngày</strong> để kiểm tra lại ngay hôm sau cho chắc chắn.</td>
                </tr>
                <tr>
                    <td><strong>Easy Interval</strong><br><code>1</code> ngày</td>
                    <td>Khoảng cách nếu chọn <strong>"Easy" (Dễ)</strong> ngay lần đầu.<br>Vẫn giữ <strong>1 ngày</strong> để tránh ảo tưởng năng lực (hôm nay thấy dễ, mai lại quên).</td>
                </tr>
                <tr>
                    <td><strong>Starting Ease</strong><br><code>2.3</code> (230%)</td>
                    <td>Tốc độ giãn cách các lần ôn sau.<br>Ví dụ 2.5: Lần 1 cách 1 ngày -> Lần 2 cách 2.5 ngày -> Lần 3 cách 6 ngày...</td>
                </tr>
            </tbody>
        </table>
        
        <div style="background-color: #f0f9ff; border: 1px solid #bae7ff; padding: 10px; border-radius: 5px;">
            <strong>💡 Chiến thuật:</strong>
            <ul style="margin: 5px 0 0 20px;">
                <li>Ưu tiên nút <b>Good</b> (Tốt). Chỉ chọn <b>Easy</b> nếu kiến thức quá hiển nhiên.</li>
                <li>Nếu hơi quên, hãy mạnh dạn chọn <b>Again</b> (Học lại).</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    with tab4:
        st.subheader("📝 Quản lý Thẻ (Card Manager)")
        st.info("Chỉnh sửa nội dung, thay đổi hình ảnh hoặc xoá thẻ khỏi thư viện.")
        
        # --- BULK ACTION ---
        with st.expander("🗑️ Xóa hàng loạt (Bulk Delete)", expanded=False):
            if not data:
                st.warning("Kho dữ liệu trống.")
            else:
                # Prepare DataFrame
                df = pd.DataFrame(data)
                # Keep relevant columns
                display_cols = ['id', 'question', 'subject', 'topic']
                df_display = df[display_cols].copy()
                df_display.insert(0, "select", False) # Checkbox column
                
                edited_df = st.data_editor(
                    df_display, 
                    hide_index=True,
                    column_config={
                        "select": st.column_config.CheckboxColumn("Chọn", help="Tích để xóa"),
                        "id": st.column_config.TextColumn("ID", disabled=True),
                        "question": st.column_config.TextColumn("Câu hỏi", disabled=True, width="large"),
                        "subject": st.column_config.TextColumn("Môn", disabled=True),
                        "topic": st.column_config.TextColumn("Chủ đề", disabled=True),
                    },
                    key="bulk_delete_editor"
                )
                
                # Logic Delete
                selected_rows = edited_df[edited_df['select'] == True]
                count_sel = len(selected_rows)
                
                if count_sel > 0:
                    st.warning(f"Bạn đang chọn {count_sel} thẻ để xóa vĩnh viễn.")
                    if st.button(f"🗑️ Xác nhận Xóa {count_sel} thẻ", type="primary"):
                        ids_to_delete = selected_rows['id'].tolist()
                        
                        # 1. Remove from Data
                        new_data = [d for d in data if d['id'] not in ids_to_delete]
                        data[:] = new_data # In-place update for reference safety
                        
                        # 2. Remove from Progress
                        prog = DataManager.load_progress(username)
                        for pid in ids_to_delete:
                            if pid in prog: del prog[pid]
                        DataManager.save_progress(username, prog)
                        
                        DataManager.save_data(username, data)
                        st.success(f"✅ Đã xóa {count_sel} thẻ thành công!")
                        st.rerun()

        # --- REPAIR TOOLS ---
        with st.expander("🛠️ Công cụ Sửa lỗi (Repair Tools)", expanded=False):
            st.info("Sử dụng công cụ này nếu câu hỏi bị lặp từ (ví dụ: 'Câu 1: Câu 10...') do nhập liệu sai.")
            if st.button("🧹 Quét và Xóa Prefix 'Câu X:' thừa", type="primary"):
                count_fixed = 0
                for card in data:
                    q_raw = card.get('question', '')
                    # Regex to find prefix at start: "Câu 12: ", "Question 5.", "Bài 1 "
                    # We keep the REST of the string.
                    cleaned = re.sub(r'^(?:Câu|Question|Bài|Case)\s*\d+[:.]\s*', '', q_raw, flags=re.IGNORECASE).strip()
                    
                    if len(cleaned) > 0 and cleaned != q_raw:
                        card['question'] = cleaned
                        count_fixed += 1
                
                if count_fixed > 0:
                    DataManager.save_data(username, data)
                    st.success(f"Đã sửa {count_fixed} câu hỏi!")
                    st.rerun()
                else:
                    st.success("Không tìm thấy lỗi nào cần sửa. Dữ liệu đã sạch!")

        st.divider()
        
        # 1. Filter
        if not data:
            st.warning("Kho dữ liệu trống.")
        else:
            all_subjects = sorted(list({c['subject'] for c in data}))
            col_f1, col_f2 = st.columns(2)
            sel_sub = col_f1.selectbox("Lọc theo Môn:", ["Tất cả"] + all_subjects)
            
            if sel_sub != "Tất cả":
                 all_topics = sorted(list({c['topic'] for c in data if c['subject'] == sel_sub}))
                 sel_top = col_f2.selectbox("Lọc theo Chủ đề:", ["Tất cả"] + all_topics)
            else:
                 sel_top = "Tất cả"
                 col_f2.selectbox("Lọc theo Chủ đề:", ["(Chọn môn trước)"], disabled=True)

            # 2. List Cards
            filtered_cards = [
                c for c in data 
                if (sel_sub == "Tất cả" or c['subject'] == sel_sub) and 
                   (sel_top == "Tất cả" or c['topic'] == sel_top)
            ]
            
            st.write(f"Tìm thấy **{len(filtered_cards)}** thẻ.")
            
            for i, card in enumerate(filtered_cards):
                # Skip placeholder cards
                if card.get('is_placeholder'):
                    continue
                    
                # Use Expander for each card
                with st.expander(f"📌 {card.get('question', 'N/A')[:80]}...", expanded=False):
                    with st.form(key=f"edit_form_{card['id']}"):
                        # Text Fields
                        new_q = st.text_area("Câu hỏi:", value=card.get('question', ''))
                        c1, c2 = st.columns(2)
                        opts = card.get('options', {})
                        new_opt_a = c1.text_input("A:", value=opts.get('A',''))
                        new_opt_b = c2.text_input("B:", value=opts.get('B',''))
                        new_opt_c = c1.text_input("C:", value=opts.get('C',''))
                        new_opt_d = c2.text_input("D:", value=opts.get('D',''))
                        
                        c3, c4 = st.columns(2)
                        correct = card.get('correct_answer', 'A')
                        new_ans = c3.selectbox("Đáp án đúng:", ["A", "B", "C", "D"], index=["A","B","C","D"].index(correct) if correct in ["A","B","C","D"] else 0)
                        new_sub = c4.text_input("Môn học:", value=card.get('subject', ''))
                        new_top = c4.text_input("Chủ đề:", value=card.get('topic', ''))
                        
                        new_expl = st.text_area("Giải thích:", value=card.get('explanation', ''))
                        new_mnem = st.text_input("Mẹo nhớ:", value=card.get('mnemonic', ''))
                        new_src = st.text_input("Nguồn:", value=card.get('source', ''))
                        
                        # Image Management (Outside Form? Streamlit doesn't support file_uploader inside form well, but let's try or move out)
                        # Actually file_uploader IS supported inside form, but reset is tricky.
                        # Let's use checkboxes for deletion logic.
                        
                        st.markdown("---")
                        st.markdown("**🖼️ Quản lý Hình ảnh**")
                        
                        # Image Q
                        col_img_q, col_img_a = st.columns(2)
                        with col_img_q:
                            st.caption("Ảnh Câu hỏi (Image Q)")
                            if card.get('image_q') and os.path.exists(os.path.join("static", "images", card['image_q'])):
                                st.image(os.path.join("static", "images", card['image_q']), width=150)
                                del_img_q = st.checkbox("🗑️ Xóa ảnh câu hỏi", key=f"del_q_{card['id']}")
                            else:
                                del_img_q = False
                                st.caption("(Chưa có ảnh)")
                        
                        with col_img_a:
                            st.caption("Ảnh Giải thích (Image A)")
                            if card.get('image_a') and os.path.exists(os.path.join("static", "images", card['image_a'])):
                                st.image(os.path.join("static", "images", card['image_a']), width=150)
                                del_img_a = st.checkbox("🗑️ Xóa ảnh giải thích", key=f"del_a_{card['id']}")
                            else:
                                del_img_a = False
                                st.caption("(Chưa có ảnh)")
                        
                        # Note: We cannot put file_uploader inside a form with clear_on_submit=False cleanly if we want to keep text edits.
                        # Compromise: Users must save text changes first, then use a separate uploader outside? 
                        # OR keep it simple: Use file uploader here.
                        
                        st.markdown("---")
                        c_del, c_save = st.columns([1, 4])
                        delete_btn = c_del.form_submit_button("🗑️ XÓA THẺ", type="secondary")
                        save_btn = c_save.form_submit_button("💾 LƯU THAY ĐỔI", type="primary")
                    
                    # File Uploaders (Outside Form to avoid rerun issues? No, let's put them just below form for 'Edit Image' action)
                    # Actually, if we want to upload new image, we should do it in the form submit logic?
                    # Streamlit forms collect all data on submit.
                    # But file_uploader inside form resets after submit. Use session state?
                    # Simplest approach: Separate Image Uploader Expanders.
                    
                    if save_btn:
                        # Update Text Data
                        card['question'] = new_q
                        card['options']['A'] = new_opt_a
                        card['options']['B'] = new_opt_b
                        card['options']['C'] = new_opt_c
                        card['options']['D'] = new_opt_d
                        card['correct_answer'] = new_ans
                        card['subject'] = new_sub
                        card['topic'] = new_top
                        card['explanation'] = new_expl
                        card['mnemonic'] = new_mnem
                        card['source'] = new_src
                        
                        # Handle Deletion of Images
                        if del_img_q: card['image_q'] = ""
                        if del_img_a: card['image_a'] = ""
                        
                        DataManager.save_data(username, data)
                        st.success("Đã lưu thông tin!")
                        st.rerun()

                    if delete_btn:
                        # Remove card
                        data.remove(card)
                        # Remove progress
                        prog = DataManager.load_progress(username)
                        if str(card['id']) in prog:
                            del prog[str(card['id'])]
                            DataManager.save_progress(username, prog)
                        
                        DataManager.save_data(username, data)
                        st.toast("Đã xoá thẻ thành công!", icon="🗑️")
                        st.rerun()
                    # Image Uploaders (Standalone - NO EXPANDER to avoid nesting error)
                    st.markdown("---")
                    st.markdown("**🖼️ Thay đổi / Upload ảnh mới**")
                    
                    up_q = st.file_uploader("Chọn ảnh câu hỏi mới:", key=f"up_q_{card['id']}", type=['png','jpg','jpeg'])
                    if up_q:
                        if st.button("Lưu ảnh câu hỏi", key=f"save_img_q_{card['id']}"):
                            img_name = f"up_q_{uuid.uuid4()}.png"
                            target_path = os.path.join("static", "images", img_name)
                            process_and_save_image(up_q, target_path)
                            
                            card['image_q'] = img_name
                            DataManager.save_data(username, data)
                            st.success("Đã cập nhật ảnh câu hỏi!")
                            st.rerun()
                            
                    up_a = st.file_uploader("Chọn ảnh giải thích mới:", key=f"up_a_{card['id']}", type=['png','jpg','jpeg'])
                    if up_a:
                        if st.button("Lưu ảnh giải thích", key=f"save_img_a_{card['id']}"):
                            img_name = f"up_a_{uuid.uuid4()}.png"
                            target_path = os.path.join("static", "images", img_name)
                            process_and_save_image(up_a, target_path)
                            
                            card['image_a'] = img_name
                            DataManager.save_data(username, data)
                            st.success("Đã cập nhật ảnh giải thích!")
                            st.rerun()

# --- HELPER: IMAGE PROCESSING ---
def process_and_save_image(uploaded_file, target_path, max_dimension=1024):
    """
    Saves an uploaded image to target_path with resizing if dimensions exceed max_dimension.
    Maintains aspect ratio and quality.
    """
    try:
        image = Image.open(uploaded_file)
        
        # Orient correctly based on EXIF (crucial for phone photos)
        image = ImageOps.exif_transpose(image)
        
        # Calculate new size
        width, height = image.size
        if width > max_dimension or height > max_dimension:
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Save
        image.save(target_path)
        return True
    except Exception as e:
        print(f"Error processing image: {e}")
        # Fallback: Save directly if PIL fails
        with open(target_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return False

def view_library(data, username):
    # --- MOTIVATING DASHBOARD ---
    
    # Calculate Stats
    cfg = SRSEngine.get_config()
    NEW_CARDS_PER_DAY = cfg['NEW_CARDS_PER_DAY']
    progress = DataManager.load_progress(username)
    new_c, due_c, next_due = SRSEngine.get_counts(data, progress)
    
    # --- HERO: Streak & Stats ---
    st.markdown("""
    <style>
        .motivation-box {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 25px;
            border-radius: 15px;
            color: white;
            text-align: center;
            margin-bottom: 20px;
        }
        .motivation-title {
            font-size: 1.8em;
            font-weight: bold;
            margin-bottom: 10px;
        }
        .stat-row {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin-top: 15px;
        }
        .stat-item {
            background: rgba(255,255,255,0.2);
            padding: 10px 25px;
            border-radius: 25px;
            font-weight: 600;
        }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
    <div class="motivation-box">
        <div class="motivation-title">🎯 Hôm nay học gì?</div>
        <div style="opacity: 0.9;">Mỗi ngày một chút, bạn sẽ tiến bộ!</div>
        <div class="stat-row">
            <div class="stat-item">🔵 {new_c} Mới</div>
            <div class="stat-item">🟢 {due_c} Cần ôn</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- BIG STUDY BUTTON ---
    total_to_study = due_c + min(new_c, NEW_CARDS_PER_DAY)
    if total_to_study > 0:
        if st.button(f"🚀 HỌC NGAY ({total_to_study} thẻ)", type="primary", use_container_width=True):
            queue = SRSEngine.get_queue(data, progress)
            if queue:
                st.session_state.study_queue = queue
                st.session_state.current_q_index = 0
                st.session_state.view = 'learning'
                st.rerun()
            else:
                st.success("🎉 Bạn đã hoàn thành hôm nay!")
    else:
        st.success("🎉 Tuyệt vời! Bạn đã hoàn thành tất cả bài học hôm nay!")
        if next_due:
            st.info(f"⏳ Bài tiếp theo lúc: {next_due.strftime('%H:%M')}")
    
    st.divider()
    
    # --- TOOLBAR ---
    tool_c1, tool_c2 = st.columns([8, 2])
    with tool_c1:
        st.markdown("### 📚 Thư viện")
    with tool_c2:
        if st.button("⚙️ Quản lý", use_container_width=True):
            st.session_state.view = 'manage'
            st.rerun()
    
    # --- TREE ---
    tree = TreeHelper.build_tree(data)
    
    if not tree:
        st.info("📭 Thư viện trống. Hãy Import thẻ để bắt đầu!")
        if st.button("📥 Đi tới Import"):
            st.session_state.view = 'import'
            st.rerun()
        return
    
    # DECK LIST VIEW (when no subject selected)
    if st.session_state.selected_subject is None:
        # UNIFIED TABLE (No separate boxes)
        with st.container(border=True):
            # Header
            hdr1, hdr2, hdr3 = st.columns([6, 1, 1])
            with hdr1: st.markdown("**Deck**")
            with hdr2: st.markdown("**Due**")
            with hdr3: st.markdown("**New**")
            st.markdown("<hr style='margin: 5px 0; border: none; border-top: 1px solid #ddd;'>", unsafe_allow_html=True)
            
            def render_deck(node, path="", level=0):
                """Render decks with collapsible folders."""
                for name in sorted(node.keys()):
                    full_path = f"{path}/{name}" if path else name
                    children = node[name]
                    has_children = len(children) > 0
                    
                    # Count stats
                    d_count = 0
                    n_count = 0
                    for c in data:
                        if c['subject'] == full_path or c['subject'].startswith(full_path + '/'):
                            pid = str(c['id'])
                            prog = progress.get(pid, {})
                            if prog.get('state', 'new') == 'new': 
                                n_count += 1
                            elif prog.get('due'):
                                try:
                                    if datetime.datetime.fromisoformat(prog['due']) <= datetime.datetime.now(): 
                                        d_count += 1
                                except: pass
                    
                    # Stats display - use styled badges instead of emojis
                    stats_html = ""
                    if d_count > 0:
                        stats_html += f"<span style='background:#27ae60;color:white;padding:2px 8px;border-radius:10px;font-size:0.8em;margin-left:5px;'>{d_count} due</span>"
                    if n_count > 0:
                        stats_html += f"<span style='background:#3498db;color:white;padding:2px 8px;border-radius:10px;font-size:0.8em;margin-left:5px;'>{n_count} new</span>"
                    
                    if has_children:
                        # FOLDER: Use expander (collapsible)
                        folder_label = f"📁 {name}"
                        with st.expander(folder_label, expanded=False):
                            # Show stats inside expander
                            if stats_html:
                                st.markdown(f"<div style='margin-bottom:10px;'>{stats_html}</div>", unsafe_allow_html=True)
                            # Button to study this folder
                            if st.button(f"📖 Học {name}", key=f"study_{full_path}", type="primary"):
                                st.session_state.selected_subject = full_path
                                st.rerun()
                            # Render children inside
                            render_deck(children, full_path, level + 1)
                    else:
                        # LEAF: Simple clickable row
                        c1, c2, c3 = st.columns([6, 1, 1])
                        with c1:
                            if st.button(f"📖 {name}", key=f"leaf_{full_path}", use_container_width=True):
                                st.session_state.selected_subject = full_path
                                st.rerun()
                        with c2:
                            if d_count > 0:
                                st.markdown(f"<span style='background:#27ae60;color:white;padding:3px 10px;border-radius:12px;font-weight:bold;display:inline-block;'>{d_count}</span>", unsafe_allow_html=True)
                            else:
                                st.markdown("<span style='color:#ccc;'>-</span>", unsafe_allow_html=True)
                        with c3:
                            if n_count > 0:
                                st.markdown(f"<span style='background:#3498db;color:white;padding:3px 10px;border-radius:12px;font-weight:bold;display:inline-block;'>{n_count}</span>", unsafe_allow_html=True)
                            else:
                                st.markdown("<span style='color:#ccc;'>-</span>", unsafe_allow_html=True)
            
            render_deck(tree)



    # 3. Hiển thị chi tiết Chủ đề - GIAO DIỆN GỘP (AGGREGATED UI) - CLEAN
    elif st.session_state.selected_topic is None:
        # BREADCRUMB
        st.caption(f"🏠 Thư viện / {st.session_state.selected_subject}")
        if st.button("⬅️ Quay lại", type="secondary"):
            st.session_state.update(selected_subject=None)
            st.rerun()
            
        current_sub = st.session_state.selected_subject
        
        # Calculate Logic
        topics = {}
        for card in data:
            s_name = card['subject']
            if s_name == current_sub or s_name.startswith(current_sub + '/'):
                t_name = card['topic']
                if t_name not in topics: topics[t_name] = []
                topics[t_name].append(card)
        
        all_subject_cards = []
        
        # 3.1 SETUP PANEL (Compact)
        with st.expander("⚙️ Tùy chọn chủ đề (Topic Filter)"):
             topic_list = list(topics.keys())
             selected_topics = st.multiselect("Lọc chủ đề:", options=topic_list, default=topic_list)
             st.info(f"Đang chọn {len(selected_topics)}/{len(topic_list)} chủ đề")
        
        # Default to all if nothing selected (or use selection)
        # Re-calc based on selection (if user didn't open expander, selected_topics might be unset, but streamlit handles this)
        if 'selected_topics' not in locals(): selected_topics = list(topics.keys())
        
        for t in selected_topics:
            all_subject_cards.extend(topics[t])

        # 3.2 MAIN STUDY AREA (Center, Big)
        st.markdown(f"<h1 style='text-align: center; color: #0083b0;'>{current_sub.split('/')[-1]}</h1>", unsafe_allow_html=True)
        st.caption("Version: Cloud_Fix_v2 (Auto-Create DB & Cached Mode)")
        
        # Stats
        progress = DataManager.load_progress(username)
        due_count = 0
        new_count = 0
        for card in all_subject_cards:
            pid = str(card['id'])
            prog = progress.get(pid, {})
            if prog.get('state', 'new') == 'new': new_count += 1
            elif prog.get('due'):
                try:
                    import datetime
                    due_dt = datetime.datetime.fromisoformat(prog['due'])
                    if due_dt <= datetime.datetime.now(): due_count += 1
                except: pass
        
                # Badges and Buttons
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            st.markdown(f"""
            <div style="display: flex; justify-content: center; gap: 20px; margin-bottom: 20px;">
                <span style="background: #e3f2fd; color: #1565c0; padding: 5px 15px; border-radius: 15px; font-weight: bold;">{new_count} Mới</span>
                <span style="background: #e8f5e9; color: #2e7d32; padding: 5px 15px; border-radius: 15px; font-weight: bold;">{due_count} Cần ôn</span>
            </div>
            """, unsafe_allow_html=True)
            
            # PRIMARY COLOR BUTTONS (Red/Blue)
            if st.button(f"🚀 BẮT ĐẦU HỌC NGAY", key="btn_learn_main", type="primary", use_container_width=True):
                 cfg = SRSEngine.get_config()
                 NEW_PER_DAY = cfg['NEW_CARDS_PER_DAY']
                 new_to_learn = min(new_count, NEW_PER_DAY)
                 queue = SRSEngine.get_queue(all_subject_cards, progress)
                 if not queue:
                     st.warning("🎉 Bạn đã hoàn thành bài học hôm nay!")
                 else:
                     st.session_state.study_queue = queue
                     st.session_state.current_q_index = 0
                     st.session_state.view = 'learning'
                     st.session_state.selected_topic = "All" 
                     st.rerun()

def view_import(data, username):
    st.title("🧙‍♂️ Import Wizard")
    st.info("Upload file Excel (.xlsx) để thêm câu hỏi. Cột yêu cầu: Question, Option A/B/C/D, Correct Answer, Explanation, Subject, Topic.")
    st.markdown("🆕 **Cột hỗ trợ mới:** 'Source', 'Mnemonic', 'Image Q' (Tên ảnh câu hỏi), 'Image A' (Tên ảnh giải thích).")

    uploaded_file = st.file_uploader("1. Chọn file Excel", type=['xlsx'])
    uploaded_images = st.file_uploader("2. Upload ảnh minh họa (Chọn nhiều ảnh)", type=['png', 'jpg', 'jpeg', 'webp'], accept_multiple_files=True)
    
    if uploaded_file:
        new_cards, error, skipped = DataManager.import_from_excel(uploaded_file, data)
        if error:
            st.error(f"Lỗi đọc file: {error}")
        else:
            st.success(f"Tìm thấy {len(new_cards)} câu hỏi hợp lệ. (Đã bỏ qua {skipped} câu trùng)")
            
            # Save Images
            if uploaded_images:
                images_dir = "static/images"
                if not os.path.exists(images_dir):
                    os.makedirs(images_dir)
                
                saved_count = 0
                for img_file in uploaded_images:
                    target_path = os.path.join(images_dir, img_file.name)
                    process_and_save_image(img_file, target_path)
                    saved_count += 1
                st.info(f"📸 Đã lưu {saved_count} file ảnh vào thư mục hệ thống.")

            preview_tree = {}
            preview_tree = {}
            for card in new_cards:
                sub = card['subject']
                top = card['topic']
                if sub not in preview_tree: preview_tree[sub] = set()
                preview_tree[sub].add(top)
            
            for sub, tops in preview_tree.items():
                with st.expander(f"📁 {sub} ({len(tops)} Topics)", expanded=True):
                    for t in tops:
                        st.write(f"- 📄 {t}")
            
            if st.button("Confirm Import", type="primary"):
                data.extend(new_cards)
                DataManager.save_data(username, data)
                st.toast("Import thành công!", icon="✅")
                st.session_state.view = 'library'
                st.rerun()

# --- SRS ENGINE ---
# --- SRS ENGINE (Medical Mode) ---
# --- SRS ENGINE (Medical Mode) ---
class SRSEngine:
    @staticmethod
    def get_config():
        # Fallback if request comes when user session not fully ready (rare in this app)
        return st.session_state.get('srs_config', {
            "LEARNING_STEPS": [1, 15, 60],
            "NEW_CARDS_PER_DAY": 20,
            "MAX_REVIEWS_PER_DAY": 9999,
            "GRADUATING_INTERVAL": 1,
            "EASY_INTERVAL": 1,
            "STARTING_EASE": 2.3,
            "FUZZ_RANGE": 0.05
        })

    @staticmethod
    def calculate(card_prog, rating):
        # Progress Schema: {state, step_index, due, interval, ease, lapses}
        import random
        
        # Load Config
        cfg = SRSEngine.get_config()
        LEARNING_STEPS = cfg['LEARNING_STEPS']
        GRADUATING_INTERVAL = cfg['GRADUATING_INTERVAL']
        EASY_INTERVAL = cfg['EASY_INTERVAL']
        STARTING_EASE = cfg['STARTING_EASE']
        FUZZ_RANGE = cfg['FUZZ_RANGE']

        now = datetime.datetime.now()
        state = card_prog.get("state", "new")
        step_index = card_prog.get("step_index", 0)
        interval = card_prog.get("interval", 0)
        ease = card_prog.get("ease", STARTING_EASE)
        lapses = card_prog.get("lapses", 0)
        
        # --- LOGIC A: LEARNING / RELEARNING ---
        if state in ["new", "learning", "relearning"]:
            # Rule: Once touched, it is no longer "new" (unless it graduates to review directly)
            if state == "new" and rating != 4:
                state = "learning"
                
            if rating == 1: # Again
                step_index = 0
                next_due = now + timedelta(minutes=LEARNING_STEPS[0])
                state = "learning" # Ensure state is learning
            elif rating == 2: # Hard
                # Repeat current step
                current_step_min = LEARNING_STEPS[step_index] if step_index < len(LEARNING_STEPS) else LEARNING_STEPS[0]
                next_due = now + timedelta(minutes=current_step_min)
                state = "learning" # Ensure state is learning
            elif rating == 3: # Good
                if step_index < len(LEARNING_STEPS) - 1:
                    # Advance step
                    step_index += 1
                    next_due = now + timedelta(minutes=LEARNING_STEPS[step_index])
                    state = "learning"
                else:
                    # Graduate
                    state = "review"
                    interval = GRADUATING_INTERVAL
                    next_due = now + timedelta(days=interval)
            elif rating == 4: # Easy
                # Instant Graduate
                state = "review"
                interval = EASY_INTERVAL
                # If Easy, verify tomorrow (Safety 1st)
                next_due = now + timedelta(days=interval)
        
        # --- LOGIC B: REVIEW ---
        else: # state == "review"
            if rating == 1: # Lapse
                state = "relearning"
                step_index = 0
                lapses += 1
                interval = 1 # Reset interval to 1 day (or keep some %? Medical mode says safety 1st)
                next_due = now + timedelta(minutes=LEARNING_STEPS[0])
            elif rating == 2: # Hard
                interval = max(1, interval * 1.2)
                next_due = now + timedelta(days=interval)
            elif rating == 3: # Good
                interval = max(1, interval * ease)
                next_due = now + timedelta(days=interval)
            elif rating == 4: # Easy
                interval = max(1, interval * ease * 1.3)
                ease += 0.15
                next_due = now + timedelta(days=interval)
            
            # Apply Fuzz to Reviews > 2 days
            if state == "review" and interval > 2:
                fuzz = random.uniform(1.0 - FUZZ_RANGE, 1.0 + FUZZ_RANGE)
                interval = round(interval * fuzz, 2)
                # Recalculate due with fuzz
                next_due = now + timedelta(days=interval)

        # Enforce Ease Floor
        if ease < 1.3: ease = 1.3
        
        # Track First Learned Date (for Daily Limits)
        first_learned = card_prog.get("first_learned", None)
        if state != "new" and first_learned is None:
             first_learned = now.isoformat()

        return {
            "state": state,
            "step_index": step_index,
            "due": next_due.isoformat(),
            "interval": interval,
            "ease": ease,
            "lapses": lapses,
            "repetitions": card_prog.get("repetitions", 0) + 1,
            "first_learned": first_learned
        }

    @staticmethod
    def get_due_text(due_str):
        if not due_str: return "Now"
        due = datetime.datetime.fromisoformat(due_str)
        now = datetime.datetime.now()
        
        if due <= now: return "Now"
        
        diff = due - now
        total_seconds = int(diff.total_seconds())
        
        if total_seconds < 60: return "1m"
        if total_seconds < 3600: return f"{total_seconds // 60}m"
        if total_seconds < 86400: return f"{total_seconds // 3600}h"
        return f"{diff.days}d"
    
    @staticmethod
    def get_button_label(card_prog, rating):
        # Simulate logic to peek future due
        sim_res = SRSEngine.calculate(card_prog, rating)
        due_str = sim_res['due']
        due_dt = datetime.datetime.fromisoformat(due_str)
        now = datetime.datetime.now()
        
        diff = due_dt - now
        total_seconds = int(diff.total_seconds())
        
        time_label = "Now"
        if total_seconds < 60: time_label = "<1m"
        elif total_seconds < 3600: time_label = f"{total_seconds // 60}m"
        elif total_seconds < 86400: time_label = f"{total_seconds // 3600}h"
        else: time_label = f"{diff.days}d"
        
        return time_label

    @staticmethod
    def get_time_label(interval_days):
        if interval_days == 0: return "<10m"
        if interval_days == 1: return "1d"
        return f"{int(interval_days)}d"

    @staticmethod
    def get_queue(data, progress):
        import random
        # Load Config
        cfg = SRSEngine.get_config()
        NEW_CARDS_PER_DAY = cfg['NEW_CARDS_PER_DAY']
        
        now = datetime.datetime.now()
        
        due_learning = []
        due_review = []
        new_cards = []
        
        # Filter Logic
        # Filter Logic
        learned_today_count = 0
        now_date = now.date()
        
        for card in data:
            pid = str(card['id']) # Fix: Ensure ID is string for JSON lookup
            prog = progress.get(pid, {})
            state = prog.get("state", "new")
            due_str = prog.get("due", None)
            first_learned = prog.get("first_learned", None)
            
            # Count how many new cards were introduced today
            if first_learned:
                try:
                    fl_date = datetime.datetime.fromisoformat(first_learned).date()
                    if fl_date == now_date:
                        learned_today_count += 1
                except: passed

            if state == "new":
                new_cards.append(card)
            else:
                if due_str:
                    try:
                        due_dt = datetime.datetime.fromisoformat(due_str)
                        if due_dt <= now:
                            if state in ["learning", "relearning"]:
                                due_learning.append(card)
                            elif state == "review":
                                due_review.append(card)
                    except: pass
        
        # Calculate Remaining Limit
        remaining_new = max(0, NEW_CARDS_PER_DAY - learned_today_count)
        selected_new = new_cards[:remaining_new]
        
        # Interleave
        final_queue = due_learning + due_review + selected_new
        random.shuffle(final_queue)
        
        return final_queue

    @staticmethod
    def get_counts(data, progress):
        # Load Config
        cfg = SRSEngine.get_config()
        NEW_CARDS_PER_DAY = cfg['NEW_CARDS_PER_DAY']
        
        now = datetime.datetime.now()
        new_count = 0
        due_count = 0
        next_due_min = None
        
        for card in data:
            pid = str(card['id']) # Fix: Ensure ID is string
            prog = progress.get(pid, {})
            state = prog.get("state", "new")
            due_str = prog.get("due", None)
            
            if state == "new":
                new_count += 1
            elif due_str:
                due_dt = datetime.datetime.fromisoformat(due_str)
                if due_dt <= now:
                    due_count += 1
                else:
                    # Check for nearest future due
                    if next_due_min is None or due_dt < next_due_min:
                        next_due_min = due_dt
                        
        return new_count, due_count, next_due_min

def view_learning(data, progress, username):
    inject_keyboard_shortcuts()
    queue = st.session_state.study_queue
    if not queue:
        st.warning("Danh sách học trống.")
        if st.button("Về thư viện"):
            st.session_state.view = 'library'
            st.rerun()
        return

    if st.session_state.current_q_index >= len(queue):
        st.success("🎉 Bạn đã hoàn thành bài học này!")
        if st.button("Quay về thư viện"):
            st.session_state.view = 'library'
            st.session_state.selected_topic = None
            st.rerun()
        return

    q = queue[st.session_state.current_q_index]
    # Get progress for this card
    card_prog = progress.get(q['id'], {"interval": 0, "repetitions": 0, "ease_factor": 2.5})

    # Thanh Header: Nút thoát to hơn, nằm riêng dòng trên cùng
    if st.button("⬅️ Quay về Thư viện", type="secondary", help="Dừng bài học và quay lại chọn bài khác"):
        # Reset all learning state
        st.session_state.view = 'library'
        st.session_state.selected_subject = None
        st.session_state.selected_topic = None
        st.session_state.study_queue = []
        st.session_state.current_q_index = 0
        st.session_state.answered = False
        st.rerun()
    
    # Progress Bar ngay dưới
    st.progress((st.session_state.current_q_index + 1) / len(queue), text=f"Tiến độ: Câu {st.session_state.current_q_index + 1}/{len(queue)}")

    # --- EDIT MODE LOGIC ---
    is_editing = st.session_state.get('editing_card_id') == q['id']
    
    if is_editing:
        with st.container(border=True):
            st.markdown("### ✏️ Chỉnh sửa thẻ")
            new_q_text = st.text_area("Câu hỏi", value=q['question'], height=100)
            
            # Options
            c_opt_1, c_opt_2 = st.columns(2)
            opts = q.get('options', {})
            new_opt_A = c_opt_1.text_input("A", value=opts.get('A', ''))
            new_opt_B = c_opt_2.text_input("B", value=opts.get('B', ''))
            new_opt_C = c_opt_1.text_input("C", value=opts.get('C', ''))
            new_opt_D = c_opt_2.text_input("D", value=opts.get('D', ''))
            
            # Correct Answer & Explanation
            c_ans_1, c_ans_2 = st.columns([1, 2])
            new_correct = c_ans_1.selectbox("Đáp án đúng", ["A", "B", "C", "D"], index=["A","B","C","D"].index(q['correct_answer']) if q['correct_answer'] in ["A","B","C","D"] else 0)
            new_explain = c_ans_2.text_area("Giải thích", value=q.get('explanation', ''), height=68)
            
            # Image Handler
            st.markdown("#### 🖼️ Hình ảnh")
            if q.get('image_q'):
                 st.image(os.path.join("static", "images", q['image_q']), width=200, caption="Ảnh hiện tại")
                 if st.checkbox("Xóa ảnh hiện tại?"):
                     q['temp_delete_img'] = True
            
            uploaded_file = st.file_uploader("Thay thế/Thêm ảnh mới (Copy-Paste Supported via Drag & Drop)", type=['png', 'jpg', 'jpeg'])
            
            c_act_1, c_act_2 = st.columns([1, 1])
            if c_act_1.button("💾 Lưu thay đổi", type="primary"):
                # Save logic
                q['question'] = new_q_text
                q['options'] = {'A': new_opt_A, 'B': new_opt_B, 'C': new_opt_C, 'D': new_opt_D}
                q['correct_answer'] = new_correct
                q['explanation'] = new_explain
                
                # Image Logic
                if q.get('temp_delete_img'):
                    q['image_q'] = ""
                
                if uploaded_file:
                    # Save new image
                    file_ext = os.path.splitext(uploaded_file.name)[1]
                    new_filename = f"user_upload_{uuid.uuid4().hex}{file_ext}"
                    save_path = os.path.join("static", "images", new_filename)
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    q['image_q'] = new_filename
                
                # Persist to JSON
                # Need to find 'q' in 'data' list and update it. 
                # q here is a reference to item in queue, which is ref to data item? 
                # Queue items are usually refs. Let's verify.
                # Yes, in Python dicts are ref.
                DataManager.save_data(username, data) # username is current_user string now
                
                st.session_state.editing_card_id = None
                st.success("Đã lưu!")
                st.rerun()
                
            if c_act_2.button("Hủy"):
                st.session_state.editing_card_id = None
                st.rerun()

    # Layout chính: Card câu hỏi ở giữa (Read Only View)
    else:
        # Edit Button overlay (using columns for layout)
        c_layout_card, c_layout_edit = st.columns([8, 1])
        with c_layout_edit:
            if st.button("✏️", help="Chỉnh sửa nội dung thẻ này", key=f"btn_edit_{q['id']}"):
                st.session_state.editing_card_id = q['id']
                st.rerun()
        
        st.markdown(f"""
        <div class="modern-card" style="text-align: center; border-left: 5px solid #0083b0;">
            <span class="topic-tag">{q['topic']}</span>
            <div style="font-size: 1.3em; font-weight: 600; margin-bottom: 20px; margin-top: 10px;">{q['question']}</div>
            <div style="color: gray; font-size: 0.9em; font-style: italic;">{q['subject']}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Image Q Display
    if 'image_q' in q and q['image_q']:
        img_path = os.path.join("static", "images", q['image_q'])
        if os.path.exists(img_path):
            with st.expander("🖼️ Ảnh minh họa (Click để xem)", expanded=True):
                # Optimize display: Don't stretch small images. Use fixed reasonable max width.
                col_img_1, col_img_2, col_img_3 = st.columns([1, 4, 1])
                with col_img_2:
                    st.image(img_path, width=600)
    
    # Câu trả lời - UI xanh lá thu hút
    st.markdown('''
    <style>
        .answer-header {
            background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
            color: white;
            padding: 10px 20px;
            border-radius: 10px;
            font-weight: bold;
            font-size: 1.1em;
            margin-bottom: 15px;
            text-align: center;
        }
    </style>
    <div class="answer-header">📝 Chọn đáp án</div>
    ''', unsafe_allow_html=True)
    
    answered = st.session_state.answered
    opts = q.get('options', {})
    
    # LOGIC: If NOT answered, show Buttons. If answered, show Styled Results.
    if not answered:
        def handle_choice(key):
            st.session_state.answered = True
            st.session_state.selected_option = key
        
        # Layout 2x2 với CSS màu tím/violet
        st.markdown('''
        <style>
            /* Target ALL answer option buttons */
            div[data-testid="column"] .stButton > button {
                background: linear-gradient(135deg, #2d1b4e 0%, #4c1d95 50%, #7c3aed 100%) !important;
                border: 2px solid #a855f7 !important;
                color: #e9d5ff !important;
                border-radius: 12px !important;
                padding: 16px 20px !important;
                font-size: 1em !important;
                font-weight: 500 !important;
                text-align: left !important;
                justify-content: flex-start !important;
                min-height: 55px !important;
                box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3) !important;
            }
            div[data-testid="column"] .stButton > button:hover {
                background: linear-gradient(135deg, #4c1d95 0%, #7c3aed 50%, #a855f7 100%) !important;
                border-color: #c084fc !important;
                color: #ffffff !important;
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(167, 139, 250, 0.5) !important;
            }
        </style>
        ''', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button(f"A. {opts.get('A', '')}", key="opt_a", use_container_width=True): 
                handle_choice("A")
                st.rerun()
            if st.button(f"B. {opts.get('B', '')}", key="opt_b", use_container_width=True): 
                handle_choice("B")
                st.rerun()
        with col2:
            if st.button(f"C. {opts.get('C', '')}", key="opt_c", use_container_width=True): 
                handle_choice("C")
                st.rerun()
            if st.button(f"D. {opts.get('D', '')}", key="opt_d", use_container_width=True): 
                handle_choice("D")
                st.rerun()

    else:
        # Result Mode
        correct_code = q['correct_answer']
        chosen_code = st.session_state.selected_option
        
        # Helper to generate style
        for key, text in opts.items():
            bg_color = "#f0f2f6" # Default Gray
            border_color = "#e0e0e0"
            text_prefix = ""
            
            if key == correct_code:
                bg_color = "#d4edda" # Green
                border_color = "#c3e6cb"
                if key == chosen_code: text_prefix = "✅ " # Correctly chosen
            
            if key == chosen_code and key != correct_code:
                bg_color = "#f8d7da" # Red
                border_color = "#f5c6cb"
                text_prefix = "❌ "
            
            # Render HTML Block
            st.markdown(f"""
            <div style="
                padding: 12px;
                margin-bottom: 8px;
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
                color: #333;
                font-weight: 500;
            ">
                {text_prefix}<b>{key}.</b> {text}
            </div>
            """, unsafe_allow_html=True)

        # Feedback Message
        if chosen_code == correct_code:
            st.success("✅ Chính xác!")
        else:
            st.error(f"❌ Sai rồi. Đáp án đúng là {correct_code}.")

        with st.expander("Giải thích chi tiết", expanded=True):
            st.write(q['explanation'])
            
            # Image A Display
            if 'image_a' in q and q['image_a']:
                img_path_a = os.path.join("static", "images", q['image_a'])
                if os.path.exists(img_path_a):
                     st.image(img_path_a, caption="Hình ảnh giải thích", use_container_width=True)
                else:
                     st.caption("(Ảnh giải thích không tìm thấy)")
            
            if 'source' in q and q['source']:
                st.markdown(f"""
                <div style="margin-top: 10px; font-size: 0.9em; color: gray;">
                    📖 <i>Source: {q['source']}</i>
                </div>
                """, unsafe_allow_html=True)
            
            if 'mnemonic' in q and q['mnemonic']:
                 st.info(f"💡 Mẹo nhớ: {q['mnemonic']}")
        
        # SRS Buttons with Time Labels
        def srs_next(rating):
            new_p = SRSEngine.calculate(card_prog, rating)
            progress[str(q['id'])] = new_p # Fix: Use string ID key
            DataManager.save_progress(username, progress) # SAVE IMMEDIATELY
            
            # Debug/Feedback Toast
            if rating == 4: # Easy
                 st.toast(f"🎉 Quá dễ! Hẹn gặp lại sau {SRSEngine.get_due_text(new_p['due'])}", icon="😎")
            elif rating == 1: # Again
                 st.toast(f"Đừng lo! Sẽ ôn lại sau {SRSEngine.get_due_text(new_p['due'])}", icon="🔄")
                 # FIX: Re-queue card immediately so it appears again in this session
                 st.session_state.study_queue.append(q)
            else:
                 st.toast(f"Đã ghi nhận! Lần tới: {SRSEngine.get_due_text(new_p['due'])}", icon="✅")

            st.session_state.current_q_index += 1
            st.session_state.answered = False

        # Dynamic Labels using get_button_label
        lbl_again = SRSEngine.get_button_label(card_prog, 1)
        lbl_hard = SRSEngine.get_button_label(card_prog, 2)
        lbl_good = SRSEngine.get_button_label(card_prog, 3)
        lbl_easy = SRSEngine.get_button_label(card_prog, 4)

        # SRS Buttons with proper styling and borders - using on_click for reliable save
        st.markdown("---")
        st.markdown("**Đánh giá độ khó:**")
        
        cols = st.columns(4)
        with cols[0]:
            st.markdown('<div class="srs-btn-again">', unsafe_allow_html=True)
            st.button(f"Again\n({lbl_again})", key="btn_again", use_container_width=True, on_click=lambda: srs_next(1))
            st.markdown('</div>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown('<div class="srs-btn-hard">', unsafe_allow_html=True)
            st.button(f"Hard\n({lbl_hard})", key="btn_hard", use_container_width=True, on_click=lambda: srs_next(2))
            st.markdown('</div>', unsafe_allow_html=True)
        with cols[2]:
            st.markdown('<div class="srs-btn-good">', unsafe_allow_html=True)
            st.button(f"Good\n({lbl_good})", key="btn_good", use_container_width=True, on_click=lambda: srs_next(3))
            st.markdown('</div>', unsafe_allow_html=True)
        with cols[3]:
            st.markdown('<div class="srs-btn-easy">', unsafe_allow_html=True)
            st.button(f"Easy\n({lbl_easy})", key="btn_easy", use_container_width=True, on_click=lambda: srs_next(4))
            st.markdown('</div>', unsafe_allow_html=True)

    # --- AI Chat Interface ---
    st.markdown("---")
    
    # Initialize Persistent Chat History for this card
    if "chat_history" not in q:
        q["chat_history"] = []

    with st.expander("👨‍⚕️ Lịch sử trò chuyện với Giáo sư", expanded=True):
        
        # 1. SPLIT HISTORY INTO SEGMENTS
        segments = []
        current_segment = []
        for msg in q["chat_history"]:
            if msg.get("role") == "separator":
                if current_segment:
                    segments.append(current_segment)
                    current_segment = []
                # Keep separator? No, just use it to split.
            else:
                current_segment.append(msg)
        if current_segment:
            segments.append(current_segment)
            
        # If empty initially
        if not segments and not q["chat_history"]:
             segments = [[]]
        elif not segments and q["chat_history"]: # No separators yet, just one big segment
             segments = [q["chat_history"]]
             
        # Normalize: Logic above might be slightly off if starts with separator, but generally ok.
        # Better logic:
        # Re-scan to be sure
        segments = []
        temp = []
        for msg in q["chat_history"]:
            if msg.get("role") == "separator":
                segments.append(temp)
                temp = []
            else:
                temp.append(msg)
        segments.append(temp)
        
        # 2. RENDER SEGMENTS
        # Render old segments (collapsed)
        for i, seg in enumerate(segments[:-1]):
            if not seg: continue # Skip empty segments
            
            # Find Title (First user message)
            title = f"Đoạn chat #{i+1}"
            for m in seg:
                if m["role"] == "user":
                    # Truncate
                    txt = m["content"]
                    if len(txt) > 50: txt = txt[:47] + "..."
                    title = f"❓ {txt}"
                    break
            
            with st.expander(title, expanded=False):
                for msg in seg:
                     with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
        
        # Render current segment (active)
        active_segment = segments[-1]
        
        # Title for active segment? No, just render openly.
        if len(segments) > 1:
            st.caption("👇 Đoạn chat hiện tại (Context đang kích hoạt)")
        
        # Calculate start index of active segment in the main list for deletion mapping
        # This is tricky because indices shift. 
        # Easier strategy for deletion: Rerender the whole list logic but visuals differ.
        # Let's simple render loop but track "real_index" in q["chat_history"]
        
        real_idx = 0
        for i, seg in enumerate(segments):
            is_active = (i == len(segments) - 1)
            
            # Helper to check if segment has content
            if not seg and not is_active: 
                # Advance real_idx for separator if exists
                if real_idx < len(q["chat_history"]) and q["chat_history"][real_idx].get("role") == "separator":
                    real_idx += 1
                continue

            # Skip rendering old segments here (already done above in Expanders for better control)
            # BUT we need to advance real_idx!
            if not is_active:
                real_idx += len(seg)
                if real_idx < len(q["chat_history"]) and q["chat_history"][real_idx].get("role") == "separator":
                    real_idx += 1
                continue

            # Render ACTIVE ONLY
            # Container
            with st.container():
                for msg in seg:
                    with st.chat_message(msg["role"]):
                        col_c, col_d = st.columns([0.9, 0.1])
                        col_c.markdown(msg["content"])
                        
                        # Use valid key based on real_idx
                        if col_d.button("🗑️", key=f"del_{q['id']}_{real_idx}", help="Xóa tin nhắn này"):
                            q["chat_history"].pop(real_idx)
                            # Sync
                            for card in data:
                                if card['id'] == q['id']:
                                    card['chat_history'] = q['chat_history']
                                    break
                            DataManager.save_data(username, data)
                            st.rerun()
                    
                    real_idx += 1

        # 3. CONTROLS (NEW THREAD)
        col_new, col_dummy = st.columns([0.3, 0.7])
        if col_new.button("➕ Tạo đoạn chat mới", help="Bắt đầu hội thoại mới (AI sẽ quên ngữ cảnh cũ)"):
            q["chat_history"].append({"role": "separator", "content": "--- New Session ---"})
            # Sync
            for card in data:
                if card['id'] == q['id']:
                    card['chat_history'] = q['chat_history']
                    break
            DataManager.save_data(username, data)
            st.rerun()

        # 4. CHAT INPUT
        if prompt := st.chat_input("Hỏi giáo sư về câu này..."):
            # Update Session
            q["chat_history"].append({"role": "user", "content": prompt})
            
            # Sync
            for card in data:
                if card['id'] == q['id']:
                    card['chat_history'] = q['chat_history']
                    break
            DataManager.save_data(username, data)
            
            st.rerun() # Rerun to show user message immediately in correct segment logic

        # 5. AI RESPONSE (TRIGGERED AFTER RERUN usually, but here we do blocking call for simplicity or handle 'last message user' state)
        # Check if last message is user -> Trigger AI
        if q["chat_history"] and q["chat_history"][-1]["role"] == "user":
             with st.chat_message("assistant"):
                with st.spinner("Giáo sư đang suy nghĩ..."):
                    context = q
                    # Only pass ACTIVE SEGMENT history
                    # Re-calculate active segment
                    current_hist = []
                    # Get messages after last separator
                    for m in reversed(q["chat_history"][:-1]): # Exclude just added prompt for search
                        if m.get("role") == "separator": break
                        current_hist.insert(0, m)
                    
                    # Call API
                    response = ask_professor(st.session_state.get("api_key"), context, q["chat_history"][-1]["content"], chat_history=current_hist)
                    st.markdown(response)
                    
                    # Save
                    q["chat_history"].append({"role": "assistant", "content": response})
                    for card in data:
                        if card['id'] == q['id']:
                            card['chat_history'] = q['chat_history']
                    DataManager.save_data(username, data)
                    st.rerun()

# --- AI VISION ---
def view_ai_vision(data, username):
    st.title("✨ AI Vision Creator v2.2 (Smart Mode)")
    st.markdown("Quy trình tối ưu: **AI vẽ nháp ➡️ Bác sĩ chỉnh sửa ➡️ Tạo thẻ**.")
    
    # 1. Inputs chung
    col1, col2 = st.columns(2)
    with col1:
        existing_subjects = sorted(list({card['subject'] for card in data})) if data else ["Chung"]
        subject = st.selectbox("Môn học:", existing_subjects + ["➕ Tạo mới..."])
        if subject == "➕ Tạo mới...": subject = st.text_input("Nhập tên môn mới:", value="Giải Phẫu")
            
    with col2:
        if subject in existing_subjects:
            existing_topics = sorted(list({card['topic'] for card in data if card['subject'] == subject}))
        else: existing_topics = []
        topic = st.selectbox("Chủ đề:", existing_topics + ["➕ Tạo mới..."])
        if topic == "➕ Tạo mới...": topic = st.text_input("Nhập tên chủ đề mới:", value="Sọ Mặt")

    uploaded_img = st.file_uploader("Upload Ảnh:", type=['png', 'jpg', 'jpeg'])

    # State quản lý Canvas
    if 'canvas_init_json' not in st.session_state: st.session_state.canvas_init_json = None
    if 'ai_detected_labels' not in st.session_state: st.session_state.ai_detected_labels = []
    
    # Reset khi upload ảnh mới
    if uploaded_img:
        img_hash = hash(uploaded_img.name)
        if 'current_img_hash' not in st.session_state or st.session_state.current_img_hash != img_hash:
            st.session_state.current_img_hash = img_hash
            st.session_state.canvas_init_json = None
            st.session_state.ai_detected_labels = []

    if uploaded_img:
        # Xử lý ảnh hiển thị (Resize về 700px width)
        bg_image = Image.open(uploaded_img)
        bg_image = ImageOps.exif_transpose(bg_image)
        w, h = bg_image.size
        new_w = 700
        new_h = int(h * (new_w / w))
        bg_image_resized = bg_image.resize((new_w, new_h))
        
        # NÚT GỌI AI QUÉT SƠ BỘ
        st.info("💡 Bấm nút dưới để AI tự động tìm và vẽ các hộp che cho bạn.")
        if st.button("🤖 AI Quét & Vẽ nháp", type="primary"):
            if not st.session_state.get('api_key'):
                st.error("Thiếu API Key.")
            else:
                with st.spinner("AI đang tìm nhãn..."):
                    # Save temp
                    bg_image.save("temp_ai_scan.png")
                    detected_items = detect_labels_only(st.session_state.api_key, "temp_ai_scan.png")
                    
                    if detected_items:
                        canvas_objects = []
                        labels_list = []
                        
                        # Chuyển đổi tọa độ AI (0-1000) -> Pixel Canvas
                        for item in detected_items:
                            ymin, xmin, ymax, xmax = item['box_2d']
                            left = xmin * (new_w / 1000)
                            top = ymin * (new_h / 1000)
                            width = (xmax - xmin) * (new_w / 1000)
                            height = (ymax - ymin) * (new_h / 1000)
                            
                            # Padding & Object
                            pad = 5
                            canvas_objects.append({
                                "type": "rect",
                                "left": max(0, left - pad),
                                "top": max(0, top - pad),
                                "width": width + pad*2,
                                "height": height + pad*2,
                                "fill": "rgba(255, 107, 107, 0.3)",
                                "stroke": "#ff0000",
                                "strokeWidth": 2
                            })
                            labels_list.append(item['label'])
                        
                        st.session_state.canvas_init_json = {"objects": canvas_objects, "background": ""}
                        st.session_state.ai_detected_labels = labels_list
                        st.rerun()
                    else:
                        st.warning("AI không tìm thấy nhãn nào. Bạn hãy tự vẽ nhé.")

        st.divider()
        st.markdown("### ✍️ Chỉnh sửa trên Canvas")
        
        # Mode control
        c_mode = st.radio(
            "Chế độ thao tác:", 
            ["🖐️ Di chuyển/Sửa (Transform)", "✏️ Vẽ hộp mới (Draw Rect)"], 
            horizontal=True,
            help="Chọn 'Vẽ hộp mới' để vẽ thêm vùng che. Chọn 'Di chuyển' để sửa kích thước/vị trí."
        )
        
        real_mode = "transform" if "Transform" in c_mode else "rect"
        
        st.caption("Kéo/thả để sửa hộp. Bấm `Delete` để xóa hộp sai. Vẽ thêm nếu thiếu.")

        # VÙNG VẼ (CANVAS)
        canvas_result = st_canvas(
            fill_color="rgba(255, 107, 107, 0.3)",
            stroke_width=2,
            stroke_color="#ff0000",
            background_image=bg_image_resized,
            initial_drawing=st.session_state.canvas_init_json, 
            update_streamlit=True,
            height=new_h,
            width=new_w,
            drawing_mode=real_mode, # Dynamic Mode
            key="hybrid_canvas",
        )

        # XỬ LÝ & LƯU THẺ
        if canvas_result.json_data is not None:
            objects = canvas_result.json_data["objects"]
            
            if len(objects) > 0:
                st.subheader(f"Đang có {len(objects)} vùng chọn")
                
                with st.form("hybrid_save_form"):
                    final_labels = []
                    ai_labels = st.session_state.ai_detected_labels
                    
                    for i, obj in enumerate(objects):
                        default_val = ai_labels[i] if i < len(ai_labels) else ""
                        lbl = st.text_input(f"🏷️ Nhãn cho vùng {i+1}:", value=default_val, key=f"l_{i}")
                        final_labels.append({"label": lbl, "obj": obj})
                    
                    # DEBUG: Live Count
                    valid_labels = [x['label'] for x in final_labels if x['label'].strip()]
                    st.caption(f"📊 Hệ thống đã nhận: {len(valid_labels)}/{len(objects)} nhãn hợp lệ.")
                    if len(valid_labels) < len(objects):
                        st.warning("⚠️ Một số vùng chọn chưa có tên nhãn. Thẻ tương ứng sẽ bị bỏ qua.")
                    else:
                        st.success("✅ Tất cả vùng chọn đã có nhãn.")
                    
                    if st.form_submit_button("💾 Xác nhận & Lưu thẻ"):
                        # Lưu ảnh gốc full size
                        orig_img_id = f"manual_orig_{uuid.uuid4()}.png"
                        if not os.path.exists("static/images"): os.makedirs("static/images")
                        orig_path = os.path.join("static", "images", orig_img_id)
                        with open(orig_path, "wb") as f:
                            f.write(uploaded_img.getbuffer())

                        # Cắt ảnh tạo Mask
                        pil_image = Image.open(orig_path)
                        pil_image = ImageOps.exif_transpose(pil_image)
                        orig_w, orig_h = pil_image.size
                        scale_x = orig_w / new_w
                        scale_y = orig_h / new_h

                        # --- LOGIC TẠO ĐÁP ÁN THÔNG MINH ---
                        # 1. Thu thập tất cả các nhãn (để làm đáp án nhiễu)
                        all_labels = [item['label'].strip() for item in final_labels if item['label'].strip()]
                        
                        count = 0
                        import random
                        
                        for i, item in enumerate(final_labels):
                            label_text = item['label'].strip()
                            if not label_text: continue 
                            
                            obj = item['obj']
                            # Tọa độ thực trên ảnh gốc
                            left = int(obj['left'] * scale_x)
                            top = int(obj['top'] * scale_y)
                            width = int(obj['width'] * scale_x)
                            height = int(obj['height'] * scale_y)
                            
                            # Vẽ Mask đỏ
                            masked_img = pil_image.copy()
                            draw = ImageDraw.Draw(masked_img)
                            draw.rectangle([left, top, left+width, top+height], fill="#FF6B6B", outline="red", width=5)
                            
                            mask_id = f"occ_hybrid_{uuid.uuid4()}.png"
                            masked_img.save(os.path.join("static", "images", mask_id))
                            
                            # TẠO ĐÁP ÁN TRẮC NGHIỆM
                            # Lấy các nhãn khác để làm nhiễu
                            distractors = [l for l in all_labels if l != label_text]
                            
                            # Nếu không đủ 3 đáp án nhiễu, thêm đáp án giả
                            while len(distractors) < 3:
                                distractors.append("Cấu trúc không xác định")
                                distractors.append("Chưa có dữ liệu")
                                distractors = list(set(distractors)) # De-duplicate
                                if len(distractors) < 3: distractors.append(f"Cấu trúc khác {len(distractors)}")
                            
                            # Chọn 3 đáp án nhiễu ngẫu nhiên
                            final_distractors = random.sample(distractors, 3)
                            
                            # Trộn 4 đáp án
                            options_list = [label_text] + final_distractors
                            random.shuffle(options_list)
                            
                            # Map về A, B, C, D
                            opt_keys = ["A", "B", "C", "D"]
                            final_options = {k: v for k, v in zip(opt_keys, options_list)}
                            
                            # Tìm đáp án đúng là chữ cái nào
                            correct_char = [k for k, v in final_options.items() if v == label_text][0]
                            
                            # Tạo Card
                            card = {
                                "id": str(uuid.uuid4()),
                                "question": f"Cấu trúc bị che (màu đỏ) là gì? (#{i+1})", 
                                "options": final_options,
                                "correct_answer": correct_char,
                                "explanation": f"Đáp án: **{label_text}**" + (f"\n(Hình ảnh gốc nằm ở mặt sau thẻ)" if orig_img_id else ""),
                                "subject": subject, "topic": topic,
                                "image_q": mask_id, "image_a": orig_img_id,
                                "tags": ["Hybrid Occlusion"], "chat_history": []
                            }
                            data.append(card)
                            count += 1
                        
                        if count > 0:
                            DataManager.save_data(username, data)
                            st.success(f"✅ Đã tạo {count} thẻ thành công!")
                            st.session_state.canvas_init_json = None # Reset
                            st.session_state.ai_detected_labels = []
                            st.rerun()
                        else:
                            st.error("Vui lòng nhập tên cho ít nhất 1 nhãn.")

# --- MAIN ---

# --- PROFILE SELECTOR VIEW (MOBILE FRIENDLY) ---
def view_profile_selector():
    st.markdown("""
    <style>
        .big-btn {
            padding: 15px 20px;
            font-size: 18px !important;
            border-radius: 12px;
            border: 2px solid #e0e0e0;
            background: white;
            text-align: left;
            margin-bottom: 10px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .big-btn:hover {
            border-color: #0083b0;
            background: #f0f9ff;
        }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("👋 Xin chào!")
    st.caption("Version: Per_Profile_API_v16")
    st.subheader("Chọn người học để bắt đầu:")

    # Cloud Check
    is_cloud = GoogleSheetsManager.get_client() is not None
    if is_cloud:
        st.success("🟢 Đã kết nối Cloud (Google Sheets)", icon="☁️")
    else:
        st.warning("⚪ Chỉ dùng Offline (Chưa cấu hình Cloud)", icon="💾")

    # 1. Lấy danh sách hồ sơ (Vẫn ưu tiên Local List để hiển thị nhanh, 
    # nhưng nếu Cloud có user mới mà Local chưa có thì sao?
    # Tạm thời Logic tạo user yêu cầu tạo Local folder. 
    # Đồng bộ 2 chiều danh sách user phức tạp hơn, ta giữ cơ chế Local Folder làm 'Anchor'.
    # Tuy nhiên, nếu user dùng máy mới tinh, Local Folder trống trơn.
    # => Ta nên "Scan" Cloud Users nếu Local trống.
    
    profiles = DataManager.get_all_profiles()
    
    # Auto-fetch users from cloud if local is empty? 
    # (Optional enhancement, skipped for simplicity/safety)

    if not profiles:
        st.info("Chưa có hồ sơ nào trên máy này.")

    # 2. Hiển thị LIST VERTICAL (Tối ưu cho Mobile)
    st.markdown("---")
    
    for name in profiles:
        # Container cho mỗi User --> Trông giống Card trên Mobile
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                if st.button(f"👤 {name}", key=f"login_{name}", use_container_width=True):
                    st.session_state.logged_in = True
                    st.session_state.username = name
                    st.rerun()
            with c2:
                if st.button("🗑️", key=f"del_{name}", help="Xóa", use_container_width=True):
                     st.session_state[f"confirm_del_{name}"] = True
            
            # Confirm Delete Logic
            if st.session_state.get(f"confirm_del_{name}", False):
                st.warning(f"Xóa vĩnh viễn {name}?")
                ca, cb = st.columns(2)
                if ca.button("Đúng", key=f"y_{name}"):
                    DataManager.delete_profile(name)
                    del st.session_state[f"confirm_del_{name}"]
                    st.rerun()
                if cb.button("Khoan", key=f"n_{name}"):
                    del st.session_state[f"confirm_del_{name}"]
                    st.rerun()

    st.markdown("---")
    
    # 3. Tạo hồ sơ mới (Luôn hiển thị rõ ràng)
    with st.container(border=True):
        st.markdown("#### ➕ Thêm người mới")
        new_name = st.text_input("Nhập tên:", placeholder="Ví dụ: Bác sĩ A", label_visibility="collapsed")
        if st.button("Tạo ngay", type="primary", use_container_width=True):
            success, msg = DataManager.create_profile(new_name)
            if success:
                st.session_state.logged_in = True
                st.session_state.username = new_name
                st.success("Tạo thành công!")
                st.rerun()
            else:
                st.error(msg)

# --- MAIN ---
def main():
    # 1. Kiểm tra trạng thái
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = ""

    # 2. Nếu chưa chọn Profile -> Hiện màn hình chọn
    if not st.session_state.logged_in:
        view_profile_selector()
        return

    # 3. Đã chọn Profile -> Vào App
    current_user = st.session_state.username

    # Load Persistent Config
    config = DataManager.load_config()
    
    # Initialize Session State API Key from PROFILE (không dùng chung nữa)
    if 'api_key' not in st.session_state:
        st.session_state.api_key = DataManager.load_user_api_key(current_user)

    with st.sidebar:
        st.title("🦷 Dental Master")
        st.info(f"Đang dùng hồ sơ: **{current_user}**")
        
        if st.button("🔄 Đổi người dùng"):
            st.session_state.logged_in = False
            st.session_state.username = ""
            # Clear API key khi đổi user
            if 'api_key' in st.session_state:
                del st.session_state['api_key']
            st.rerun()
        
        # --- API KEY MANAGE (Per-Profile) ---
        with st.expander("🔑 Cấu hình API Key", expanded=not st.session_state.api_key):
            st.caption("API Key được lưu riêng cho profile này")
            new_key = st.text_input("Gemini API Key", value=st.session_state.api_key, type="password")
            if st.button("Lưu Key"):
                st.session_state.api_key = new_key
                DataManager.save_user_api_key(current_user, new_key)
                st.success("Đã lưu API Key cho profile này!")
                st.rerun()
        
        st.divider()
        
        # --- CLOUD SYNC BUTTON ---
        st.markdown("**☁️ Cloud Sync**")
        if GoogleSheetsManager.get_client():
            if st.button("🔄 Đồng bộ lên Cloud", use_container_width=True, type="primary"):
                with st.spinner("Đang đồng bộ..."):
                    success, msg = DataManager.sync_to_cloud(current_user)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
        else:
            st.caption("⚠️ Cloud chưa kết nối")
        
        st.divider()

    # 4. Chạy logic hiển thị chính (Sidebar & Views)
    run_app_dispatch(current_user)



# --- SLIDE VISION (New Feature) ---

VISION_ADDON_PROMPT = """
[SLIDE VISION + TEXT MODE — BOARD-STYLE CASE GENERATION]
Bạn phải tuân thủ toàn bộ VAI TRÒ/EBM/OUTPUT DISCIPLINE của prompt môn học phía trên.
Dưới đây là luật bổ sung dành riêng cho Slide Vision.

Tôi gửi bạn nhiều trang, mỗi trang gồm:
- PAGE_KEY (ví dụ P9)
- PAGE_TEXT_CONTEXT (văn bản trích từ slide)
- PAGE_IMAGE (ảnh ROI của slide)

YÊU CẦU CỐT LÕI:
1) Mỗi câu hỏi phải dựa trên PAGE_IMAGE là chính. PAGE_TEXT_CONTEXT chỉ dùng để:
   - bổ sung triệu chứng/tiền sử/diễn tiến
   - tạo clinical vignette giống đề thi
2) KHÔNG được dùng chữ trên slide để “đọc đáp án” (tiêu đề/label có thể lộ chẩn đoán).
   Nếu text có vẻ lộ chẩn đoán, hãy bỏ qua phần đó.
3) Nếu dữ kiện (ảnh+text) chưa đủ chẩn đoán xác định:
   - đặt câu hỏi dạng định hướng/đề nghị xét nghiệm/sinh thiết/chẩn đoán phân biệt
   - confidence < 0.5
   - không bịa bệnh cụ thể.

BẮT BUỘC tạo đúng {num_q} câu MCQ tiếng Việt.
Phân bổ ưu tiên (có thể điều chỉnh):
- Spot: 40%
- Synthesis (>=2 trang): 40%
- DDx: 20%

BẮT BUỘC “CHAINED OUTPUT”:
Trước khi viết câu hỏi, bạn phải tạo ra 2 phần:
A) clinical_scenario: tóm tắt ca theo kiểu đề thi (tuổi/giới/triệu chứng/diễn tiến/khám) 
   - Ưu tiên lấy từ PAGE_TEXT_CONTEXT nếu có
   - Nếu thiếu, được phép giả định hợp lý nhưng phải ghi rõ là “giả định hợp lý” trong scenario
B) image_findings: các dấu hiệu hình ảnh then chốt (>=3 bullet) mô tả cụ thể

Sau đó mới viết question/options/explanation.

OUTPUT JSON (chỉ JSON):
[
  {{
    "question_type": "spot|synthesis|ddx",
    "clinical_scenario": "...",
    "image_findings": ["...","...","..."],
    "question": "...",
    "options": {{"A":"...","B":"...","C":"...","D":"..."}},
    "correct_answer": "A|B|C|D",
    "explanation": "A) Dấu hiệu hình ảnh then chốt: ...\\nB) Lập luận chọn đáp án đúng: ...\\nC) Bẫy & vì sao 1–2 đáp án nhiễu sai: ...\\nD) Professor’s note (WHO/NCCN/molecular/marker nếu liên quan thật): ...",
    "mnemonic": "... (optional)",
    "ref_page_keys": ["P9"] hoặc ["P9","P10"],
    "primary_ref_page_key": "P9",
    "confidence": 0.0-1.0
  }}
]

QUAN TRỌNG:
1. CHỈ được dùng các `PAGE_KEY` mà tôi đã cung cấp bên trên (Ví dụ P9, P10...).
2. TUYỆT ĐỐI KHÔNG bịa ra key mới (Ví dụ P12, P13 nếu tôi không gửi).
3. Nếu không chắc chắn ảnh nào, dùng key của ảnh đầu tiên.
"""

class PDFProcessor:
    @staticmethod
    def render_page_assets(doc, page_idx, dpi_full=150, dpi_roi=200, mask_header_footer=True):
        """
        Renders Full Page and ROI (Auto-Crop) for a specific page index.
        Returns: dict {'full': PIL.Image, 'roi': PIL.Image, 'is_auto_roi': bool}
        """
        try:
            page = doc.load_page(page_idx)
            
            # 1. Full Page Render
            pix_full = page.get_pixmap(dpi=dpi_full)
            img_full = Image.frombytes("RGB", [pix_full.width, pix_full.height], pix_full.samples)
            
            # Mask Title/Footer on Full Image if requested
            if mask_header_footer:
                img_full = PDFProcessor.apply_mask(img_full)
            
            # 2. Auto-Crop Logic
            best_rect = None
            best_area = 0.0
            
            # A) Try PyMuPDF embedded images (High Precision)
            image_list = page.get_images(full=True)
            for img in image_list:
                xref = img[0]
                rects = page.get_image_rects(xref)
                for r in rects:
                    area = r.get_area()
                    page_area = page.rect.get_area()
                    # Heuristic: >5% and <95% (skip full backgrounds)
                    if area > best_area and area > (page_area * 0.05) and area < (page_area * 0.98):
                        best_area = area
                        best_rect = r
                        
            is_auto_roi = False
            img_roi = None
            
            # Default: Full Page
            roi_coords = {'l': 0.0, 't': 0.0, 'r': 0.0, 'b': 0.0}
            
            if best_rect:
                # Render ROI directly from PDF
                zoom = dpi_roi / 72
                mat = fitz.Matrix(zoom, zoom)
                pix_roi = page.get_pixmap(matrix=mat, clip=best_rect)
                img_roi = Image.frombytes("RGB", [pix_roi.width, pix_roi.height], pix_roi.samples)
                is_auto_roi = True
                
                # Calculate normalized coords for slider initialization
                # Sliders are usually "Margin" (Left Margin, Right Margin...)
                # l = x0/W, t = y0/H, r = 1 - x1/W, b = 1 - y1/H
                W, H = page.rect.width, page.rect.height
                roi_coords['l'] = max(0.0, best_rect.x0 / W)
                roi_coords['t'] = max(0.0, best_rect.y0 / H)
                roi_coords['r'] = max(0.0, 1.0 - (best_rect.x1 / W))
                roi_coords['b'] = max(0.0, 1.0 - (best_rect.y1 / H))
                
            else:
                # B) Fallback: Content Detection (White Trimming via PIL)
                # Render full at ROI DPI (masked)
                zoom = dpi_roi / 72
                mat = fitz.Matrix(zoom, zoom)
                pix_fallback = page.get_pixmap(matrix=mat)
                img_fallback = Image.frombytes("RGB", [pix_fallback.width, pix_fallback.height], pix_fallback.samples)
                if mask_header_footer:
                     img_fallback_masked = PDFProcessor.apply_mask(img_fallback.copy())
                else:
                     img_fallback_masked = img_fallback
                
                # Try to find bounding box of non-white content
                bbox = ImageOps.invert(img_fallback_masked.convert("L")).getbbox()
                if bbox:
                    img_roi = img_fallback_masked.crop(bbox)
                    is_auto_roi = True # It is "auto" cropped, just different method
                    
                    # Bbox is (left, top, right, bottom) in pixels
                    # Calculate normalized margins
                    fw, fh = img_fallback.size
                    roi_coords['l'] = bbox[0] / fw
                    roi_coords['t'] = bbox[1] / fh
                    roi_coords['r'] = 1.0 - (bbox[2] / fw)
                    roi_coords['b'] = 1.0 - (bbox[3] / fh)
                else:
                    img_roi = img_fallback_masked
                    is_auto_roi = False
                    # Coords remain 0,0,0,0
                
            return {
                "full": img_full,
                "roi": img_roi,
                "is_auto_roi": is_auto_roi,
                "roi_coords": roi_coords
            }
            
        except Exception as e:
            print(f"Error rendering assets for page {page_idx}: {e}")
            return None

    @staticmethod
    def render_manual_crop(doc, page_idx, roi_coords, dpi_full=150, mask_header_footer=True):
        """
        Renders a specific page and crops it according to normalized coords (percentages).
        roi_coords: {'l': 0.1, 't': 0.1, 'r': 0.0, 'b': 0.0} (Margins)
        """
        try:
            page = doc.load_page(page_idx)
            
            # Full Render
            pix_full = page.get_pixmap(dpi=dpi_full)
            img_full = Image.frombytes("RGB", [pix_full.width, pix_full.height], pix_full.samples)
            
            if mask_header_footer:
                img_full = PDFProcessor.apply_mask(img_full)
                
            # Crop
            l, t, r, b = roi_coords['l'], roi_coords['t'], roi_coords['r'], roi_coords['b']
            w, h = img_full.size
            
            # Convert percentage margins to coords
            x0 = int(w * l)
            y0 = int(h * t)
            x1 = int(w * (1 - r))
            y1 = int(h * (1 - b))
            
            # Clamp
            x0 = max(0, x0); y0 = max(0, y0); x1 = min(w, x1); y1 = min(h, y1)
            
            if x0 >= x1 or y0 >= y1:
                 return img_full # Error fallback
            
            img_roi = img_full.crop((x0, y0, x1, y1))
            return img_roi
            
        except Exception as e:
            print(f"Manual render error: {e}")
            return None

    @staticmethod
    def apply_mask(pil_image):
        """Masks top 10% and bottom 15% to hide titles/footers."""
        w, h = pil_image.size
        draw = ImageDraw.Draw(pil_image)
        
        top_h = int(h * 0.10)
        bot_h = int(h * 0.85)
        
        draw.rectangle([(0, 0), (w, top_h)], fill="white")
        draw.rectangle([(0, bot_h), (w, h)], fill="white")
        
        return pil_image

    @staticmethod
    def sanitize_slide_text(text: str) -> str:
        """
        Cleans extracted PDF text to remove noise, page numbers, and potential spoilers.
        """
        if not text: return ""
        
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            # 1. Skip empty or very short lines (likely page numbers or noise)
            if len(line) < 4:
                continue
                
            # 2. Skip obvious titles (All Caps short lines might be titles, but maybe keep for context?)
            # Let's clean repeated spaces
            line = re.sub(r'\s+', ' ', line)
            
            # 3. Skip lines that look like file paths or urls (optional)
            if "http" in line or ".com" in line:
                 continue
                 
            cleaned_lines.append(line)
            
        # Join
        full_text = " ".join(cleaned_lines)
        
        # 4. Hard truncate to 1500 chars to save tokens (approx 300-400 tokens)
        if len(full_text) > 1500:
            full_text = full_text[:1500] + "..."
            
        return full_text

def view_slide_vision(data, current_user):
    st.title("👁️ Slide Vision (Visual MCQ Generator)")
    
    if not HAS_PYMUPDF:
        st.error("⚠️ Thư viện `pymupdf` chưa được cài đặt. Vui lòng chạy lệnh sau trong terminal:")
        st.code("pip install pymupdf")
        return

    if not HAS_GENAI:
        st.error("⚠️ Thư viện `google-genai` chưa được cài đặt.")
        return

    # --- STATE MANAGEMENT ---
    if 'vision_step' not in st.session_state: st.session_state.vision_step = 1
    if 'selected_indices' not in st.session_state: st.session_state.selected_indices = []
    
    # --- STEP 1: UPLOAD & CONFIG ---
    if st.session_state.vision_step == 1:
        st.info("Bước 1: Upload tài liệu & Chọn phạm vi kiến thức.")
        
        uploaded_pdf = st.file_uploader("Chọn file PDF bài giảng (Slide):", type=['pdf'])
        
        c1, c2 = st.columns(2)
        # Subject Selection
        subjects = sorted(list({c['subject'] for c in data}))
        subject_mode = c1.radio("Chế độ môn học:", ["Chọn có sẵn", "Tạo mới"], horizontal=True)
        if subject_mode == "Chọn có sẵn":
            target_subject = c1.selectbox("Chọn Môn (Deck):", subjects) if subjects else ""
        else:
            target_subject = c1.text_input("Nhập tên môn mới (Ví dụ: Nha chu/Phẫu thuật):")
            
        target_topic = c2.text_input("Nhập tên Chủ đề (Topic):", value="Visual Diagnosis")
        
        # Page Range
        page_range_str = st.text_input("Phạm vi trang (Ví dụ: 1-10, 15, 20-25):", value="1-10")
        
        if uploaded_pdf and target_subject and target_topic:
            if st.button("🔍 Phân tích sơ bộ (Pass 1)", type="primary"):
                # Parse Range
                indices = []
                try:
                    parts = page_range_str.split(',')
                    for part in parts:
                        part = part.strip()
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            indices.extend(range(start-1, end)) # 0-indexed internally
                        else:
                            indices.append(int(part)-1)
                    
                    # Store in session
                    st.session_state.pdf_bytes = uploaded_pdf.getvalue()
                    st.session_state.target_subject = target_subject
                    st.session_state.target_topic = target_topic
                    st.session_state.process_indices = [i for i in indices if i >= 0] # Validate
                    st.session_state.vision_step = 2
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Lỗi đọc phạm vi trang: {e}")

    # --- STEP 2: SCREENING (PASS 1) ---
    elif st.session_state.vision_step == 2:
        st.success(f"Đang xử lý {len(st.session_state.process_indices)} trang...")
        
        # Init manual crops if not exists
        if 'manual_roi_map' not in st.session_state: st.session_state.manual_roi_map = {}

        try:
            # Check cached thumbnails (Reuse existing function for Low DPI UI only)
            if 'thumbnails' not in st.session_state:
                # We can use PDFProcessor.render_pages which returns list of images
                # But that function was removed/replaced? 
                # Wait, I replaced PDFProcessor.render_pages with render_page_assets.
                # So I must update this to use render_page_assets or restore a simple render helper.
                # Let's use loop.
                doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                thumbs = []
                for idx in st.session_state.process_indices:
                    page = doc.load_page(idx)
                    pix = page.get_pixmap(dpi=72)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    thumbs.append(img)
                doc.close()
                st.session_state.thumbnails = thumbs
            
            st.markdown("### Chọn các trang giá trị để tạo câu hỏi:")
            
            # Form to keep selection
            with st.form("page_selection"):
                cols = st.columns(3)
                selected_flags = []
                
                for i, img in enumerate(st.session_state.thumbnails):
                    real_page_num = st.session_state.process_indices[i] + 1
                    col_idx = i % 3
                    with cols[col_idx]:
                        st.image(img, caption=f"Page {real_page_num}", use_container_width=True)
                        val = st.checkbox(f"Chọn {real_page_num}", value=True, key=f"p_{real_page_num}")
                        selected_flags.append(val)
                
                st.divider()
                c1, c2 = st.columns(2)
                num_q = c1.number_input("Số lượng câu hỏi:", min_value=1, max_value=20, value=5)
                # mask_on only applies to full page now
                mask_on = c2.checkbox("Mask Title/Footer (Full Page)", value=True)
                if st.form_submit_button("Tiếp tục (Review Crop) ➡️"):
                    # Collect selected indices
                    final_list = []
                    for i, is_selected in enumerate(selected_flags):
                        if is_selected:
                            final_list.append(st.session_state.process_indices[i])
                            
                    if not final_list:
                        st.error("Vui lòng chọn ít nhất 1 trang.")
                    else:
                        st.session_state.final_indices = final_list
                        st.session_state.num_q = num_q
                        st.session_state.mask_on = mask_on
                        
                        # ALways go to Review Step (Step 2.5)
                        st.session_state.vision_step = 2.5
                        st.rerun()
            
            if st.button("⬅️ Quay lại"):
               st.session_state.vision_step = 1
               if 'thumbnails' in st.session_state: del st.session_state.thumbnails
               st.rerun()

        except Exception as e:
            st.error(f"Lỗi xử lý PDF: {e}")
            if st.button("Reset"):
                st.session_state.vision_step = 1
                if 'thumbnails' in st.session_state: del st.session_state.thumbnails
                st.rerun()

    # --- STEP 2.5: REVIEW & ADJUST CROPS ---
    elif st.session_state.vision_step == 2.5:
        st.info("🔍 Preview & Edit: Hệ thống đã Auto-Crop. Bạn có thể chọn từng trang bên dưới để chỉnh lại nếu cần.")
        
        c_nav_1, c_nav_2 = st.columns([2, 1])
        with c_nav_2:
            if st.button("🚀 Bắt đầu tạo câu hỏi (Generation)", type="primary"):
                st.session_state.vision_step = 3
                st.rerun()
        
        st.divider()
        
        # Selector for page
        page_options = [f"P{idx+1}" for idx in st.session_state.final_indices]
        selected_p_key = st.selectbox("Chọn trang để xem/sửa (Review):", page_options)
        
        # Parse current selection
        current_p_num = int(selected_p_key[1:])
        current_idx = current_p_num - 1
        
        # Render FULL page for editing
        # We need a doc handle. 
        # Ideally cache this doc or open/close. Open/close is safer for Streamlit.
        doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
        
        # Check if we have manual config for this page
        # manual_roi_map[PAGE_KEY] = [top, bottom, left, right] (percentages? or pixels?)
        # User asked for "4 sliders theo % (Left/Top/Right/Bottom)"
        
        if selected_p_key not in st.session_state.manual_roi_map:
             # AUTO-INITIALIZE: Run Auto-Crop once to get suggestions
             result = PDFProcessor.render_page_assets(
                 doc, current_idx, dpi_full=72, dpi_roi=72, mask_header_footer=st.session_state.mask_on
             )
             if result and 'roi_coords' in result:
                 st.session_state.manual_roi_map[selected_p_key] = result['roi_coords']
                 # st.toast(f"Đã áp dụng khung Auto cho {selected_p_key}")
             else:
                 # Fallback Default
                 st.session_state.manual_roi_map[selected_p_key] = {"t":0.1, "b":0.1, "l":0.0, "r":0.0}
             
        current_crop = st.session_state.manual_roi_map[selected_p_key]
        
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("**Cấu hình Crop (%)**")
            top_p = st.slider("Top (%)", 0, 50, int(current_crop['t']*100), key="s_top")
            bot_p = st.slider("Bottom (%)", 0, 50, int(current_crop['b']*100), key="s_bot")
            left_p = st.slider("Left (%)", 0, 50, int(current_crop['l']*100), key="s_left")
            right_p = st.slider("Right (%)", 0, 50, int(current_crop['r']*100), key="s_right")
            
            # Save to state immediately on change
            st.session_state.manual_roi_map[selected_p_key] = {
                "t": top_p/100, "b": bot_p/100, "l": left_p/100, "r": right_p/100
            }

        with c2:
            try:
                # Render preview
                # Simple crop on full image
                page = doc.load_page(current_idx)
                # Get full pixmap
                pix = page.get_pixmap(dpi=100) # Medium DPI for preview
                img_preview = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                w, h = img_preview.size
                
                # Draw Box
                t = int(h * (top_p/100))
                b = int(h * (1 - bot_p/100))
                l = int(w * (left_p/100))
                r = int(w * (1 - right_p/100))
                
                draw = ImageDraw.Draw(img_preview)
                # Draw red rectangle
                draw.rectangle([l, t, r, b], outline="red", width=3)
                
                st.image(img_preview, caption=f"Preview {selected_p_key}", use_container_width=True)
                
            except Exception as e:
                st.error(f"Preview error: {e}")
        
        doc.close()
        
        st.divider()
        if st.button("✅ Hoàn tất Crop -> Tạo câu hỏi"):
            st.session_state.vision_step = 3
            st.rerun()

    # --- STEP 3: GENERATION (PASS 2) ---
    elif st.session_state.vision_step == 3:
        st.info("🤖 AI đang “soi” hình và soạn đề... (Vui lòng chờ 30-60s)")
        
        try:
            # 1. Prepare Assets (Full + ROI) for selected pages
            target_indices = st.session_state.final_indices
            
            # Map PAGE_KEY -> Assets
            if 'page_assets' not in st.session_state: st.session_state.page_assets = {}
            
            # Use single doc handle
            doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            
            # Temporary list for AI input
            ai_roi_images = []
            ai_labels = []
            
            for idx in target_indices:
                p_key = f"P{idx+1}"
                
                # Check Manual
                if p_key in st.session_state.manual_roi_map:
                    # Manual Render
                    page = doc.load_page(idx)
                    
                    # Full (Masked if requested)
                    pix_full = page.get_pixmap(dpi=150)
                    img_full = Image.frombytes("RGB", [pix_full.width, pix_full.height], pix_full.samples)
                    
                    if st.session_state.mask_on:
                        img_full = PDFProcessor.apply_mask(img_full.copy())
                        
                    # ROI Crop from Full (Coordinates are normalized 0-1)
                    cfg = st.session_state.manual_roi_map[p_key]
                    w, h = img_full.size
                    l = int(w * cfg['l'])
                    t = int(h * cfg['t'])
                    r = int(w * (1 - cfg['r']))
                    b = int(h * (1 - cfg['b']))
                    
                    # Clamp
                    l = max(0, l); t = max(0, t); r = min(w, r); b = min(h, b)
                    if l >= r or t >= b:
                        img_roi = img_full # Error fallback
                    else:
                        img_roi = img_full.crop((l, t, r, b))
                    
                    st.session_state.page_assets[p_key] = {
                        "full": img_full,
                        "roi": img_roi,
                        "source": "manual",
                        "pdf_page": idx+1
                    }
                else:
                    # Auto Render (uses render_page_assets)
                    assets = PDFProcessor.render_page_assets(
                        doc, idx, dpi_full=150, dpi_roi=200, mask_header_footer=st.session_state.mask_on
                    )
                    if assets:
                        st.session_state.page_assets[p_key] = {
                            "full": assets['full'],
                            "roi": assets['roi'],
                            "source": "auto" if assets['is_auto_roi'] else "fallback",
                            "pdf_page": idx+1,
                            "roi_coords": assets['roi_coords']
                        }
                    else:
                        st.error(f"Failed to process page {idx+1}")
                        continue
                
                # EXTRACT TEXT CONTEXT
                try:
                    raw_text = doc.load_page(idx).get_text("text")
                    clean_text = PDFProcessor.sanitize_slide_text(raw_text)
                except:
                    clean_text = ""
                        
                # Prepare for AI
                img_check = st.session_state.page_assets[p_key]['roi']
                if img_check.width < 1 or img_check.height < 1:
                    # Fallback if ROI is broken
                    img_check = st.session_state.page_assets[p_key]['full']
                    # CRITICAL: Update session state so Step 4 doesn't crash
                    st.session_state.page_assets[p_key]['roi'] = img_check
                
                ai_roi_images.append(img_check)
                
                # New Label Format with Text Context
                label_str = f"PAGE_KEY={p_key} PDF_PAGE={idx+1}\n"
                if clean_text:
                    label_str += f'PAGE_TEXT_CONTEXT:\n"""{clean_text}"""\n'
                else:
                    label_str += 'PAGE_TEXT_CONTEXT: (No text extracted)\n'
                
                ai_labels.append(label_str)
            
            doc.close()
            
            # 2. Prepare Prompt
            subject_prompt = DataManager.resolve_system_prompt(st.session_state.target_subject)
            full_prompt = subject_prompt + "\n\n" + VISION_ADDON_PROMPT.format(num_q=st.session_state.num_q)
            
            # 3. Call AI
            client = genai.Client(api_key=st.session_state.api_key)
            
            contents = [full_prompt]
            for i, label in enumerate(ai_labels):
                contents.append(label)
                contents.append(ai_roi_images[i])
            
            # Request JSON
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=contents,
                config={'response_mime_type': 'application/json'}
            )
            
            # 4. Parse JSON
            try:
                raw_json = response.text
                # Clean up if AI returns markdown code block
                raw_json = raw_json.strip()
                if raw_json.startswith("```json"):
                    raw_json = raw_json[7:]
                if raw_json.endswith("```"):
                    raw_json = raw_json[:-3]
                raw_json = raw_json.strip()
                
                # Fix trailing commas (Common AI Error)
                raw_json = re.sub(r',(\s*[\]\}])', r'\1', raw_json)

                generated_cards = json.loads(raw_json)
                
                # --- DEDUPLICATION CHECK ---
                from difflib import SequenceMatcher
                for card in generated_cards:
                    q_new = card.get('question', '')
                    best_sim = 0.0
                    best_match_q = ""
                    
                    # Compare with existing library (data)
                    for existing_card in data:
                        q_old = existing_card.get('question', '')
                        # Quick length check optimization
                        if abs(len(q_new) - len(q_old)) > len(q_new)*0.5:
                            continue
                            
                        sim = SequenceMatcher(None, q_new, q_old).ratio()
                        if sim > best_sim:
                            best_sim = sim
                            best_match_q = q_old
                            
                    if best_sim > 0.88:
                        card['is_duplicate'] = True
                        card['duplicate_score'] = best_sim
                        card['duplicate_of'] = best_match_q
                
                st.session_state.generated_cards = generated_cards
                # No need for hq_images_map anymore, we have page_assets[KEY]
                st.session_state.vision_step = 4
                st.rerun()
            except json.JSONDecodeError:
                st.error("AI trả về định dạng không hợp lệ. Hãy thử lại.")
                st.code(response.text)
                
        except Exception as e:
             st.error(f"Lỗi Generation: {e}")
             if st.button("Thử lại"):
                 st.rerun()

    # --- STEP 4: REVIEW & SAVE ---
    elif st.session_state.vision_step == 4:
        st.success(f"🎉 Đã tạo {len(st.session_state.generated_cards)} thẻ!")
        
        selected_cards_indices = []
        
        for i, g_card in enumerate(st.session_state.generated_cards):
            # Header color based on duplicate status
            head_str = f"Câu {i+1}: {g_card.get('question_type','?').upper()} - {g_card.get('question', '')}"
            if g_card.get('is_duplicate'):
                head_str = f"⚠️ [DUPLICATE] {head_str}"
                
            with st.expander(head_str, expanded=not g_card.get('is_duplicate')):
                # Duplicate Warning
                if g_card.get('is_duplicate'):
                     st.warning(f"Cảnh báo: Câu này giống {(g_card.get('duplicate_score',0)*100):.1f}% với câu trong thư viện: '{g_card.get('duplicate_of','...')}'")
                
                c1, c2 = st.columns([1, 2])
                
                # Logic to find images using KEYS
                ref_keys = g_card.get('ref_page_keys', [])
                p_key = g_card.get('primary_ref_page_key')
                
                # Ensure primary is in list and at front if valid
                valid_keys = []
                # First add primary
                if p_key and p_key in st.session_state.page_assets:
                    valid_keys.append(p_key)
                
                # Add others
                for k in ref_keys:
                    if k in st.session_state.page_assets and k not in valid_keys:
                        valid_keys.append(k)
                
                # Fallback if no valid keys
                if not valid_keys:
                     available_keys = list(st.session_state.page_assets.keys())
                     if available_keys: valid_keys = [available_keys[0]]

                with c1:
                    if valid_keys:
                        # Display images
                        # If multiple, use columns row
                        if len(valid_keys) > 1:
                            cols = st.columns(len(valid_keys))
                            for idx, k in enumerate(valid_keys):
                                asset = st.session_state.page_assets[k]
                                with cols[idx]:
                                    st.image(asset['roi'], caption=f"Source: {k}", use_container_width=True)
                                    with st.popover(f"🔍 Debug {k}"):
                                         st.image(asset['full'], use_container_width=True)
                                    
                                    # INLINE EDIT CROP
                                    with st.popover(f"✂️ Sửa Crop {k}"):
                                        st.caption(f"Kéo thanh trượt để chỉnh khung hình (Real-time Preview)")
                                        cur_c = asset.get('roi_coords', {'l':0.0,'t':0.0,'r':0.0,'b':0.0})
                                        
                                        # Sliders - Check for changes
                                        # Use a form? No, we want instant feedback on release.
                                        n_top = st.slider(f"Top (%)", 0, 50, int(cur_c['t']*100), key=f"re_t_{i}_{k}")
                                        n_bot = st.slider(f"Bottom (%)", 0, 50, int(cur_c['b']*100), key=f"re_b_{i}_{k}")
                                        n_left = st.slider(f"Left (%)", 0, 50, int(cur_c['l']*100), key=f"re_l_{i}_{k}")
                                        n_right = st.slider(f"Right (%)", 0, 50, int(cur_c['r']*100), key=f"re_r_{i}_{k}")
                                        
                                        # Check if changed
                                        new_vals = {"t":n_top/100, "b":n_bot/100, "l":n_left/100, "r":n_right/100}
                                        has_changed = (
                                            abs(new_vals['t'] - cur_c['t']) > 0.001 or
                                            abs(new_vals['b'] - cur_c['b']) > 0.001 or
                                            abs(new_vals['l'] - cur_c['l']) > 0.001 or
                                            abs(new_vals['r'] - cur_c['r']) > 0.001
                                        )
                                        
                                        if has_changed:
                                            # Update immediately
                                            try:
                                                doc_edit = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                                                p_idx = asset['pdf_page'] - 1
                                                
                                                new_roi = PDFProcessor.render_manual_crop(
                                                    doc_edit, p_idx, new_vals, 
                                                    dpi_full=72, 
                                                    mask_header_footer=st.session_state.mask_on
                                                )
                                                
                                                if new_roi:
                                                    st.session_state.page_assets[k]['roi'] = new_roi
                                                    st.session_state.page_assets[k]['roi_coords'] = new_vals
                                                    st.session_state.page_assets[k]['source'] = 'manual_post_edit'
                                                    st.rerun() # Refresh UI to show new crop
                                                
                                                doc_edit.close()
                                            except Exception as ex:
                                                st.error(f"Err: {ex}")
                                        
                                        # Show current crop preview (small) inside popover?
                                        # Not strictly necessary if main image updates, but explicit is nice.
                                        # st.image(asset['roi'], caption="Preview", width=200)

                        else:
                             # Single Image Case
                             k = valid_keys[0]
                             asset = st.session_state.page_assets[k]
                             st.image(asset['roi'], caption=f"Source: {k} (Page {asset['pdf_page']})", use_container_width=True)
                             
                             # INLINE EDIT CROP (Single)
                             with st.popover(f"✂️ Sửa Crop {k}"):
                                st.caption(f"Kéo thanh trượt để chỉnh (Real-time)")
                                cur_c = asset.get('roi_coords', {'l':0.0,'t':0.0,'r':0.0,'b':0.0})
                                
                                n_top = st.slider(f"Top (%)", 0, 50, int(cur_c['t']*100), key=f"re_t_{i}_{k}_s")
                                n_bot = st.slider(f"Bottom (%)", 0, 50, int(cur_c['b']*100), key=f"re_b_{i}_{k}_s")
                                n_left = st.slider(f"Left (%)", 0, 50, int(cur_c['l']*100), key=f"re_l_{i}_{k}_s")
                                n_right = st.slider(f"Right (%)", 0, 50, int(cur_c['r']*100), key=f"re_r_{i}_{k}_s")
                                
                                new_vals = {"t":n_top/100, "b":n_bot/100, "l":n_left/100, "r":n_right/100}
                                has_changed = (
                                    abs(new_vals['t'] - cur_c['t']) > 0.001 or
                                    abs(new_vals['b'] - cur_c['b']) > 0.001 or
                                    abs(new_vals['l'] - cur_c['l']) > 0.001 or
                                    abs(new_vals['r'] - cur_c['r']) > 0.001
                                )
                                
                                if has_changed:
                                    try:
                                        doc_edit = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                                        p_idx = asset['pdf_page'] - 1
                                        
                                        new_roi = PDFProcessor.render_manual_crop(
                                            doc_edit, p_idx, new_vals, 
                                            dpi_full=72, 
                                            mask_header_footer=st.session_state.mask_on
                                        )
                                        
                                        if new_roi:
                                            st.session_state.page_assets[k]['roi'] = new_roi
                                            st.session_state.page_assets[k]['roi_coords'] = new_vals
                                            st.session_state.page_assets[k]['source'] = 'manual_post_edit'
                                            st.rerun()
                                        doc_edit.close()
                                    except Exception as ex:
                                        st.error(f"Err: {ex}")

                             with st.popover("🛠️ Debug Assets"):
                                 st.write(f"Source Type: **{asset['source'].upper()}**")
                                 st.image(asset['full'], caption="Full Context", use_container_width=True)
                                 st.image(asset['roi'], caption="ROI", use_container_width=True)
                    else:
                        st.error(f"Missing Assets")

                with c2:
                     # New Fields
                     if g_card.get('clinical_scenario'):
                         st.info(f"**📝 Clinical Scenario:**\n\n{g_card['clinical_scenario']}")
                     
                     if g_card.get('image_findings'):
                         st.markdown("**🔍 Image Findings:**")
                         for f in g_card.get('image_findings', []):
                             st.markdown(f"- {f}")
                             
                     st.write(f"**❓ {g_card.get('question')}**")
                     st.json(g_card.get('options', {}), expanded=False)
                     st.write(f"✅: {g_card.get('correct_answer')}")
                     with st.popover("💡 Giải thích"):
                        st.write(g_card.get('explanation'))
                        if g_card.get('mnemonic'):
                            st.write(f"**🧠 Mnemonic:** {g_card['mnemonic']}")
                
                # Checkbox (Default False if Duplicate)
                is_dup = g_card.get('is_duplicate', False)
                if st.checkbox("Lưu thẻ này", value=(not is_dup), key=f"save_g_{i}"):
                    selected_cards_indices.append(i)

        if st.button(f"💾 Lưu {len(selected_cards_indices)} thẻ đã chọn", type="primary"):
            cards_to_save = []
            images_dir = "static/images"
            if not os.path.exists(images_dir): os.makedirs(images_dir)
            
            for i in selected_cards_indices:
                g_card = st.session_state.generated_cards[i]
                
                # Resolve Asset again
                p_key = g_card.get('primary_ref_page_key')
                if not p_key or p_key not in st.session_state.page_assets:
                     available_keys = list(st.session_state.page_assets.keys())
                     if available_keys: p_key = available_keys[0]
                
                asset = st.session_state.page_assets.get(p_key)
                img_q_Name = ""
                img_a_Name = ""
                
                if asset:
                    # Save ROI as Question Image
                    unique_id = uuid.uuid4().hex[:8]
                    fname_roi = f"slide_{p_key}_roi_{unique_id}.png"
                    asset['roi'].save(os.path.join(images_dir, fname_roi))
                    img_q_Name = fname_roi
                    
                    # Save Full as Answer Image (Context) - Optional but recommended
                    fname_full = f"slide_{p_key}_full_{unique_id}.png"
                    asset['full'].save(os.path.join(images_dir, fname_full))
                    img_a_Name = fname_full
                
                # Create Card Object
                new_card = {
                    "id": str(uuid.uuid4()),
                    "question": g_card.get('question', ''),
                    "options": g_card.get('options', {}),
                    "correct_answer": g_card.get('correct_answer', ''),
                    "explanation": g_card.get('explanation', ''),
                    "subject": st.session_state.target_subject,
                    "topic": st.session_state.target_topic,
                    "mnemonic": g_card.get('mnemonic', ''),
                    "clinical_scenario": g_card.get('clinical_scenario', ''),
                    "image_findings": g_card.get('image_findings', []),
                    "ref_page_keys": g_card.get('ref_page_keys', []),
                    "is_duplicate": g_card.get('is_duplicate', False),
                    "duplicate_of": g_card.get('duplicate_of', ''),
                    "source": "Slide Vision AI",
                    "image_q": img_q_Name,
                    "image_a": img_a_Name,
                    "tags": ["SlideVision", g_card.get('question_type', 'spot')],
                    "review_history": [],
                    "srs_state": {
                        "ease_factor": 2.5,
                        "interval": 0,
                        "due_date": datetime.datetime.now().isoformat()
                    }
                }
                cards_to_save.append(new_card)

            
            
            data.extend(cards_to_save)
            DataManager.save_data(current_user, data)
            st.success("✅ Đã lưu xong!")
            # Reset state
            del st.session_state.vision_step
            if 'thumbnails' in st.session_state: del st.session_state.thumbnails
            st.session_state.view = 'library'
            st.rerun()
            
        if st.button("Làm lại từ đầu"):
            st.session_state.vision_step = 1
            if 'thumbnails' in st.session_state: del st.session_state.thumbnails
            st.rerun()

def view_user_guide():
    st.title("❓ Hướng dẫn sử dụng")
    
    with st.expander("📚 Cách sử dụng Thư viện", expanded=True):
        st.markdown("""
        1. **Lọc thẻ:** Sử dụng bộ lọc Môn học và Chủ đề để tìm kiếm nhanh.
        2. **Xem trước:** Bấm vào thẻ để xem chi tiết câu hỏi và đáp án.
        3. **Chỉnh sửa:** Bấm trực tiếp vào thẻ để cập nhật nội dung hoặc xóa.
        """)
        
    with st.expander("🧠 Cách học với SRS (Spaced Repetition)", expanded=True):
        st.markdown("""
        - Hệ thống sử dụng thuật toán lặp lại ngắt quãng thông minh.
        - **Again (Học lại):** Quên hoặc trả lời sai. Sẽ hỏi lại ngay.
        - **Hard (Khó):** Nhớ mang máng. Ôn lại sớm (1.2x).
        - **Good (Tốt):** Nhớ rõ. Ôn lại theo lịch chuẩn (2.5x).
        - **Easy (Dễ):** Quá dễ. Dãn cách dài ra (1.3x Ease).
        """)
        
    with st.expander("✨ AI Vision Creator", expanded=True):
        st.markdown("""
        1. Upload ảnh sơ đồ/giải phẫu/X-quang.
        2. Vẽ hình chữ nhật bao quanh vùng cần che.
        3. Nhập tên nhãn cho vùng đó (AI sẽ tự động sinh đáp án nhiễu).
        4. Bấm Lưu để tạo thẻ trắc nghiệm thông minh.
        """)

    with st.expander("👁️ Slide Vision (Mới)", expanded=True):
        st.markdown("""
        1. **Upload PDF Slide**: Chọn file bài giảng.
        2. **Pass 1 - Chọn Trang**: Hệ thống hiện thumbnail các trang, bạn chọn các trang có hình ảnh giá trị.
        3. **Pass 2 - Generate**: AI sẽ "xem" hình (chất lượng cao) và tạo câu hỏi chẩn đoán hình ảnh.
        4. **Lưu**: Chọn các câu ưng ý và lưu vào kho.
        """)

def run_app_dispatch(current_user):
    # Update Sidebar Menu to Radio for better navigation
    with st.sidebar:
        # Mapping View -> Menu Index
        menu_options = ["📚 Thư viện", "🧠 Bắt đầu học", "🏆 Thi Thử (Mock Exam)", "👁️ Slide Vision", "✨ AI Vision Creator", "⚙️ Quản lý", "📥 Import Data", "❓ User Guide"]
        
        view_to_menu = {
            'library': "📚 Thư viện", 
            'learning': "🧠 Bắt đầu học", 
            'mock_exam': "🏆 Thi Thử (Mock Exam)", 
            'vision': "👁️ Slide Vision",
            'ai_vision_v2': "✨ AI Vision Creator", 
            'manage': "⚙️ Quản lý", 
            'import': "📥 Import Data",
            'user_guide': "❓ User Guide"
        }
        
        menu_to_view = {v: k for k, v in view_to_menu.items()}

        # Callback Function
        def on_menu_change():
            selected_menu = st.session_state.sidebar_nav
            new_view = menu_to_view.get(selected_menu, 'library')
            
            # Logic "Start Learning"
            if new_view == 'learning':
                if not st.session_state.get('study_queue'):
                    st.warning("Hàng đợi trống! Hãy vào Thư viện chọn bài.")
                    st.session_state.view = 'library'
                else:
                    st.session_state.view = 'learning'
            else:
                st.session_state.view = new_view
        
        # Sync Initial State (View -> Menu)
        current_view = st.session_state.get('view', 'library')
        default_menu = view_to_menu.get(current_view, "📚 Thư viện")
        
        # Initialize widget key if not exist or update it if view changed externally
        if 'sidebar_nav' not in st.session_state:
            st.session_state.sidebar_nav = default_menu
        else:
            if st.session_state.sidebar_nav != default_menu:
                 st.session_state.sidebar_nav = default_menu
        
        st.radio(
            "Menu Context",
            menu_options,
            key="sidebar_nav", # Use key for bi-directional sync
            label_visibility="collapsed",
            on_change=on_menu_change
        )
            
        st.markdown("---")
        st.caption(f"Phiên bản v2.6 | SRS Medical Mode")
        
    data = DataManager.load_data(current_user)
    progress = DataManager.load_progress(current_user)

    if st.session_state.view == 'library':
        view_library(data, current_user)
    elif st.session_state.view == 'manage':
        view_manage_library(data, current_user)
    elif st.session_state.view == 'import':
        view_import(data, current_user)
    elif st.session_state.view == 'learning':
        view_learning(data, progress, current_user)
    elif st.session_state.view == 'vision':
        view_slide_vision(data, current_user)
    elif st.session_state.view == 'ai_vision_v2': 
        view_ai_vision(data, current_user)
    elif st.session_state.view == 'mock_exam':
        view_mock_exam(data, current_user)
    elif st.session_state.view == 'user_guide':
        view_user_guide()

if __name__ == "__main__":
    main()