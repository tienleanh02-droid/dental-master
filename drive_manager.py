"""
Google Drive Manager - Upload và quản lý ảnh trên Google Drive
Sử dụng cùng Service Account với Google Sheets
"""
import os
import ssl

# GLOBAL SSL BYPASS - Cho mạng có vấn đề SSL
os.environ['PYTHONHTTPSVERIFY'] = '0'
os.environ['CURL_CA_BUNDLE'] = ''

# Tắt SSL verification cho requests library
try:
    import requests
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except:
    pass

import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
import json
import httplib2

# Workaround cho lỗi SSL trên một số mạng
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except:
    pass




class GoogleDriveManager:
    """Quản lý upload và lấy URL ảnh từ Google Drive"""
    
    SCOPES = [
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/drive'
    ]
    
    # Tên thư mục chứa ảnh trên Drive
    IMAGES_FOLDER_NAME = "Dental_Anki_Images"
    
    _drive_service = None
    _folder_id = None
    
    @staticmethod
    def _get_credentials():
        """Lấy credentials từ file local hoặc Streamlit secrets"""
        # 1. Ưu tiên Local
        if os.path.exists("credentials.json"):
            try:
                return service_account.Credentials.from_service_account_file(
                    "credentials.json",
                    scopes=GoogleDriveManager.SCOPES
                )
            except Exception:
                pass
        
        # 2. Streamlit Cloud Secrets
        try:
            if "gcp_service_account" in st.secrets:
                key_dict = dict(st.secrets["gcp_service_account"])
                return service_account.Credentials.from_service_account_info(
                    key_dict,
                    scopes=GoogleDriveManager.SCOPES
                )
        except:
            pass
        
        return None
    
    @staticmethod
    @st.cache_resource(ttl=3600)
    def get_drive_service():
        """Khởi tạo Google Drive API service"""
        creds = GoogleDriveManager._get_credentials()
        if not creds:
            return None
        try:
            # Tạo httplib2 với SSL verification tắt để bypass lỗi mạng
            import ssl
            import google_auth_httplib2
            
            # Tạo http object với SSL disabled
            http = httplib2.Http(disable_ssl_certificate_validation=True)
            
            # Wrap với credentials
            authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
            
            return build('drive', 'v3', http=authorized_http)
        except ImportError:
            # Fallback nếu không có google_auth_httplib2
            try:
                return build('drive', 'v3', credentials=creds)
            except Exception as e2:
                st.error(f"Lỗi khởi tạo Drive API (fallback): {e2}")
                return None
        except Exception as e:
            st.error(f"Lỗi khởi tạo Drive API: {e}")
            return None
    
    @staticmethod
    def get_or_create_folder():
        """Lấy folder đã được share với Service Account, trả về folder_id"""
        if GoogleDriveManager._folder_id:
            return GoogleDriveManager._folder_id
        
        service = GoogleDriveManager.get_drive_service()
        if not service:
            return None
        
        folder_name = GoogleDriveManager.IMAGES_FOLDER_NAME
        
        try:
            # Tìm folder đã được share với Service Account (sharedWithMe)
            # Ưu tiên tìm folder có tên đúng
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = service.files().list(
                q=query, 
                spaces='drive', 
                fields='files(id, name, owners)',
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            folders = results.get('files', [])
            
            if folders:
                GoogleDriveManager._folder_id = folders[0]['id']
                st.info(f"[DRIVE] Đã tìm thấy folder: {folders[0]['name']}")
                return GoogleDriveManager._folder_id
            
            # Nếu không tìm thấy folder có tên đúng, tìm bất kỳ folder nào được share
            query_any = "mimeType='application/vnd.google-apps.folder' and trashed=false and sharedWithMe=true"
            results_any = service.files().list(
                q=query_any, 
                spaces='drive', 
                fields='files(id, name)',
                pageSize=10
            ).execute()
            folders_any = results_any.get('files', [])
            
            if folders_any:
                # Lấy folder đầu tiên được share
                GoogleDriveManager._folder_id = folders_any[0]['id']
                st.info(f"[DRIVE] Sử dụng folder được share: {folders_any[0]['name']}")
                return GoogleDriveManager._folder_id
            
            st.error("[DRIVE] Không tìm thấy folder nào được share với Service Account. Vui lòng share folder từ Drive cá nhân.")
            return None
            
        except Exception as e:
            st.error(f"Lỗi tìm folder Drive: {e}")
            return None
    
    @staticmethod
    def _make_public(file_id):
        """Chia sẻ file/folder công khai để ai cũng xem được"""
        service = GoogleDriveManager.get_drive_service()
        if not service:
            return
        
        try:
            permission = {
                'type': 'anyone',
                'role': 'reader'
            }
            service.permissions().create(fileId=file_id, body=permission).execute()
        except Exception:
            pass  # Bỏ qua lỗi quyền
    
    @staticmethod
    def upload_image(local_path, image_name=None):
        """
        Upload ảnh lên Drive và trả về URL công khai
        
        Args:
            local_path: Đường dẫn file ảnh trên máy local
            image_name: Tên file trên Drive (nếu None, dùng tên gốc)
            
        Returns:
            URL công khai của ảnh hoặc None nếu lỗi
        """
        service = GoogleDriveManager.get_drive_service()
        if not service:
            return None
        
        folder_id = GoogleDriveManager.get_or_create_folder()
        if not folder_id:
            return None
        
        if not os.path.exists(local_path):
            return None
        
        if not image_name:
            image_name = os.path.basename(local_path)
        
        try:
            # Kiểm tra file đã tồn tại chưa
            existing_url = GoogleDriveManager.find_image_by_name(image_name)
            if existing_url:
                return existing_url
            
            # Xác định MIME type
            ext = os.path.splitext(local_path)[1].lower()
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            mime_type = mime_types.get(ext, 'image/jpeg')
            
            # Upload với flag hỗ trợ shared folders
            file_metadata = {
                'name': image_name,
                'parents': [folder_id]
            }
            media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
            
            uploaded_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True
            ).execute()
            
            file_id = uploaded_file.get('id')
            
            if file_id:
                # Chia sẻ công khai
                GoogleDriveManager._make_public(file_id)
                url = f"https://drive.google.com/uc?export=view&id={file_id}"
                st.success(f"[DRIVE] Upload thành công: {image_name}")
                return url
            else:
                st.warning(f"[DRIVE] Upload không trả về file_id: {image_name}")
                return None
            
        except Exception as e:
            st.error(f"Lỗi upload ảnh {image_name}: {e}")
            return None
    
    @staticmethod
    def find_image_by_name(image_name):
        """Tìm ảnh theo tên trong folder và trả về URL nếu tồn tại"""
        service = GoogleDriveManager.get_drive_service()
        if not service:
            return None
        
        folder_id = GoogleDriveManager.get_or_create_folder()
        if not folder_id:
            return None
        
        try:
            query = f"name='{image_name}' and '{folder_id}' in parents and trashed=false"
            results = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
            files = results.get('files', [])
            
            if files:
                file_id = files[0]['id']
                return f"https://drive.google.com/uc?export=view&id={file_id}"
            return None
            
        except Exception:
            return None
    
    @staticmethod
    def is_drive_url(path):
        """Kiểm tra xem path có phải URL Drive không"""
        if not path:
            return False
        return path.startswith('https://drive.google.com/') or path.startswith('http')
