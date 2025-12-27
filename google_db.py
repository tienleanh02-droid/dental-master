import streamlit as st
import gspread
from gspread.exceptions import SpreadsheetNotFound
# from oauth2client.service_account import ServiceAccountCredentials (Deprecate)
import json
import os

class GoogleSheetsManager:
    """
    Quản lý kết nối Google Sheets để lưu trữ dữ liệu người dùng.
    Hỗ trợ cả môi trường Local (credentials.json) và Streamlit Cloud (st.secrets).
    """
    
    SCOPE = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Tên file Google Sheet (Kho lưu trữ trung tâm)
    SPREADSHEET_NAME = "Dental_Anki_Master_DB"

    @staticmethod
    @st.cache_resource(ttl=3600)
    def get_client():
        """Xác thực và trả về gspread client (Sử dụng native gspread auth)."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 1. Ưu tiên Local (credentials.json) để tránh lỗi secrets.toml thiếu trên PC
        if os.path.exists("credentials.json"):
            try:
                return gspread.service_account(filename="credentials.json", scopes=scopes)
            except Exception as e:
                # st.error(f"Lỗi đọc file credentials.json: {e}")
                pass

        # 2. Sau đó mới thử Streamlit Secrets (Cloud)
        try:
            if "gcp_service_account" in st.secrets:
                try:
                    # Tạo dict credentials từ secrets
                    key_dict = dict(st.secrets["gcp_service_account"])
                    return gspread.service_account_from_dict(key_dict, scopes=scopes)
                except Exception:
                    pass
        except:
             pass
            
        return None

    @staticmethod
    @st.cache_resource(ttl=3600)
    def _get_sheet_cached():
        """Cache kết nối vào File Sheet để không phải tìm lại (TIẾT KIỆM 1-2s)"""
        client = GoogleSheetsManager.get_client()
        if not client: return None
        try:
            return client.open(GoogleSheetsManager.SPREADSHEET_NAME)
        except SpreadsheetNotFound:
            return None
            
    @staticmethod
    def get_or_create_spreadsheet():
        """Tìm file Sheet DB (ưu tiên Cache), nếu chưa có thì tạo mới."""
        client = GoogleSheetsManager.get_client()
        if not client: return None, "Chưa cấu hình Google Service Account."
        
        # 1. Thử lấy từ Cache Resource
        sheet = GoogleSheetsManager._get_sheet_cached()
        if sheet: return sheet, "OK"
        
        # 2. Nếu Cache miss (lần đầu hoặc lỗi), thử mở thủ công & Tạo
        try:
            # Re-try open (để chắc chắn)
            sheet = client.open(GoogleSheetsManager.SPREADSHEET_NAME)
            return sheet, "OK"
        except SpreadsheetNotFound:
            try:
                # Tạo mới nếu chưa có
                sheet = client.create(GoogleSheetsManager.SPREADSHEET_NAME)
                # Chia sẻ lại cho email chính của user (nếu cần - ở đây service account là chủ)
                # sheet.share('your_email@gmail.com', perm_type='user', role='owner') 
                # (Tính năng share này cần user nhập email, tạm bỏ qua để đơn giản)
                
                # Tạo các worksheet cơ bản
                # 1. Users (Danh sách người dùng)
                # 2. Config (Cấu hình chung)
                ws_users = sheet.sheet1
                ws_users.update_title("Users_List")
                ws_users.append_row(["Username", "Created_At", "Last_Login"])
                
                return sheet, "Đã khởi tạo Database mới trên Google Sheets!"
            except Exception as e:
                return None, f"Lỗi tạo file Sheet: {e}"

    @staticmethod
    def sanitize_username(username):
        """Chuyển tên user thành tên Sheet hợp lệ (không dấu, không ký tự lạ)"""
        # Đơn giản hóa: Giữ nguyên để dễ đọc, gspread xử lý được unicode tên sheet
        # Nhưng tốt nhất nên đảm bảo unique
        return username.strip()

    @staticmethod
    def load_user_data_cloud(username):
        """Tải dữ liệu thẻ (Cards) của user từ Sheet"""
        sh, msg = GoogleSheetsManager.get_or_create_spreadsheet()
        if not sh: return []
        
        try:
            ws_name = f"Data_{username}"
            
            try:
                ws = sh.worksheet(ws_name)
                # Lấy tất cả records
                records = ws.get_all_records()
                
                # Convert options/srs_state/tags từ chuỗi JSON về object
                clean_data = []
                for r in records:
                    try:
                        # Các trường dạng JSON string cần parse lại
                        if 'options' in r and isinstance(r['options'], str):
                            r['options'] = json.loads(r['options'])
                        if 'srs_state' in r and isinstance(r['srs_state'], str):
                            r['srs_state'] = json.loads(r['srs_state'])
                        if 'tags' in r and isinstance(r['tags'], str):
                            r['tags'] = json.loads(r['tags'])
                        if 'chat_history' in r and isinstance(r['chat_history'], str):
                            r['chat_history'] = json.loads(r['chat_history'])
                        if 'image_findings' in r and isinstance(r['image_findings'], str):
                            r['image_findings'] = json.loads(r['image_findings'])
                        
                        clean_data.append(r)
                    except:
                         continue # Bỏ qua dòng lỗi
                return clean_data
                
            except gspread.WorksheetNotFound:
                return [] # Chưa có data
                
        except Exception as e:
            # st.error(f"Cloud Load Error: {e}")
            return []

    @staticmethod
    def save_user_data_cloud(username, data):
        """Lưu toàn bộ data user lên Sheet (Cơ chế Ghi đè an toàn)"""
        import streamlit as st
        st.warning(f"[DEBUG] save_user_data_cloud called for user: {username}, data count: {len(data) if data else 0}")
        
        sh, msg = GoogleSheetsManager.get_or_create_spreadsheet()
        if not sh: 
            st.error(f"[DEBUG] get_or_create_spreadsheet FAILED: {msg}")
            return False 
        
        try:
            ws_name = f"Data_{username}"
            
            # --- PRE-PROCESS DATA FOR SHEET ---
            # Gspread cần list of lists hoặc list of dicts. 
            # Các field phức tạp (dict/list) phải chuyển thành JSON string
            
            rows_to_save = []
            if not data:
                return True # Không có gì để lưu
                
            # Lấy headers từ phần tử đầu tiên (đảm bảo đủ cột)
            # Hoặc define cứng các cột quan trọng
            
            # Deep copy để không sửa data gốc trên RAM
            import copy
            data_copy = copy.deepcopy(data)
            
            # --- UPLOAD IMAGES TO IMGBB (Thay thế Drive vì SA không có quota) ---
            try:
                from imgbb_manager import ImgBBManager
                
                image_fields = ['image_q', 'image_a']
                images_uploaded = 0
                
                for item in data_copy:
                    for field in image_fields:
                        img_value = item.get(field, '')
                        if img_value and not ImgBBManager.is_imgbb_url(img_value):
                            # Đây là tên file local, cần upload
                            local_path = os.path.join("static", "images", img_value)
                            if os.path.exists(local_path):
                                imgbb_url = ImgBBManager.upload_image(local_path, img_value)
                                if imgbb_url:
                                    item[field] = imgbb_url
                                    images_uploaded += 1
                
                if images_uploaded > 0:
                    st.info(f"[SYNC] Đã upload {images_uploaded} ảnh lên ImgBB")
            except Exception as e:
                st.warning(f"[SYNC] Lỗi upload ảnh (bỏ qua): {e}")
            
            # Helper function to recursively sanitize NaN/Infinity values
            def sanitize_value(val):
                if isinstance(val, float) and (val != val or val == float('inf') or val == float('-inf')):
                    return None
                elif isinstance(val, dict):
                    return {k: sanitize_value(v) for k, v in val.items()}
                elif isinstance(val, list):
                    return [sanitize_value(item) for item in val]
                return val
            
            for item in data_copy:
                # Stringify complex fields
                for k, v in item.items():
                    # Sanitize NaN/Infinity values (including nested)
                    v = sanitize_value(v)
                    if isinstance(v, (dict, list)):
                        item[k] = json.dumps(v, ensure_ascii=False)
                    else:
                        item[k] = v
                rows_to_save.append(item)
            
            import streamlit as st
            st.info(f"[DEBUG] Preparing to save {len(rows_to_save)} rows to {ws_name}")
            
            # --- GHI DỮ LIỆU ---
            try:
                ws = sh.worksheet(ws_name)
                st.info(f"[DEBUG] Found existing worksheet: {ws_name}")
                ws.clear() # Xóa cũ
            except gspread.WorksheetNotFound:
                st.info(f"[DEBUG] Creating new worksheet: {ws_name}")
                ws = sh.add_worksheet(title=ws_name, rows=1000, cols=20)
                
            # Gspread update (dùng list of dicts thì cần set header)
            if rows_to_save:
                # Lấy keys làm header
                headers = list(rows_to_save[0].keys())
                
                # Chuẩn bị matrix
                matrix = [headers]
                for row_dict in rows_to_save:
                    row_val = [row_dict.get(h, "") for h in headers]
                    matrix.append(row_val)
                
                st.info(f"[DEBUG] Matrix size: {len(matrix)} rows x {len(headers)} cols")
                ws.update(matrix)
                st.success(f"[DEBUG] Update successful!")
                
            return True
        except Exception as e:
            import streamlit as st
            import traceback
            error_msg = f"Cloud Save Error: {e}\n{traceback.format_exc()}"
            st.error(error_msg)
            return False

    @staticmethod
    def load_progress_cloud(username):
        """Load progress SRS (Dictionary)"""
        sh, msg = GoogleSheetsManager.get_or_create_spreadsheet()
        if not sh: return {}
        
        try:
            ws_name = f"Prog_{username}"
            
            try:
                ws = sh.worksheet(ws_name)
                # Giả sử cell A1 chứa toàn bộ JSON progress (cách lười nhưng hiệu quả cho data < 50k ký tự)
                # Hoặc cell A1...
                val = ws.acell('A1').value
                if val:
                    return json.loads(val)
                return {}
            except gspread.WorksheetNotFound:
                return {}
        except:
             return {}

    @staticmethod
    def save_progress_cloud(username, progress):
        sh, msg = GoogleSheetsManager.get_or_create_spreadsheet()
        if not sh: return False
        
        try:
            ws_name = f"Prog_{username}"
            
            try:
                ws = sh.worksheet(ws_name)
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title=ws_name, rows=5, cols=2)
            
            # Dump to string
            prog_str = json.dumps(progress, ensure_ascii=False)
            
            # Check length limit (50k chars per cell)
            if len(prog_str) > 49000:
                # Nếu quá dài, phải chia nhỏ (chưa implement)
                st.warning("Cảnh báo: Progress quá lớn để lưu vào 1 cell Cloud.")
                return False
                
            ws.update_acell('A1', prog_str)
            return True
        except Exception as e:
            st.error(f"Save Progress Cloud Error: {e}")
            return False
