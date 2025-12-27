from google import genai
import os
import json

# Load config to get API Key if possible, else use the one in file
try:
    with open("config.json", "r") as f:
        config = json.load(f)
        api_key = config.get("api_key")
except:
    api_key = "" # Fallback to user's hardcoded key

print(f"Using API Key: {api_key[:5]}...{api_key[-5:] if api_key else ''}")

if not api_key:
    print("Error: No API Key found.")
    exit()

try:
    client = genai.Client(api_key=api_key)
    print("Đang lấy danh sách model (Google GenAI V2 SDK)...")
    
    # List models method for V2 SDK
    # Creating a paginator or list
    pager = client.models.list() 
    
    print(f"{'Name':<40} | {'Display Name'}")
    print("-" * 60)
    
    found = False
    for m in pager:
        # Filter for gemini models to keep it clean
        if "gemini" in m.name:
            print(f"{m.name:<40} | {m.display_name}")
            found = True
            
    if not found:
        print("Không thấy model Gemini nào. Kiểm tra lại Key hoặc quyền truy cập.")
        
except Exception as e:
    print(f"Lỗi: {e}")
    print("Có thể thư viện mới chưa hỗ trợ list_models hoặc API Key sai.")