"""
ImgBB Manager - Upload ảnh lên ImgBB miễn phí
API Key miễn phí tại: https://api.imgbb.com/
"""
import os
import base64
import requests
import streamlit as st


class ImgBBManager:
    """Quản lý upload ảnh lên ImgBB"""
    
    @staticmethod
    def get_api_key():
        """Lấy API key từ session, secrets, hoặc env var"""
        # 1. Session state (user có thể nhập trong app)
        if 'imgbb_api_key' in st.session_state and st.session_state.imgbb_api_key:
            return st.session_state.imgbb_api_key
        
        # 2. Streamlit secrets (cho cloud deployment)
        try:
            if "imgbb_api_key" in st.secrets:
                return st.secrets["imgbb_api_key"]
        except:
            pass
        
        # 3. Environment variable
        env_key = os.environ.get("IMGBB_API_KEY", "")
        if env_key:
            return env_key
        
        # 4. Không có key -> return None
        return None
    
    @staticmethod
    def upload_image(local_path, image_name=None):
        """
        Upload ảnh lên ImgBB và trả về URL
        
        Args:
            local_path: Đường dẫn file ảnh trên máy local
            image_name: Tên file (tùy chọn)
            
        Returns:
            URL công khai của ảnh hoặc None nếu lỗi
        """
        api_key = ImgBBManager.get_api_key()
        
        if not os.path.exists(local_path):
            return None
        
        if not image_name:
            image_name = os.path.basename(local_path)
        
        try:
            # Đọc file và encode base64
            with open(local_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            # Upload lên ImgBB
            url = "https://api.imgbb.com/1/upload"
            payload = {
                'key': api_key,
                'image': image_data,
                'name': image_name
            }
            
            response = requests.post(url, data=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    image_url = result['data']['url']
                    st.success(f"[IMGBB] Upload OK: {image_name}")
                    return image_url
                else:
                    st.warning(f"[IMGBB] Upload failed: {result.get('error', {}).get('message', 'Unknown')}")
            else:
                st.warning(f"[IMGBB] HTTP {response.status_code}")
            
            return None
            
        except Exception as e:
            st.error(f"[IMGBB] Lỗi upload {image_name}: {e}")
            return None
    
    @staticmethod
    def is_imgbb_url(path):
        """Kiểm tra xem path có phải URL ImgBB không"""
        if not path:
            return False
        return path.startswith('https://i.ibb.co/') or path.startswith('http')
