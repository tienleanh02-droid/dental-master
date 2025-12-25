import pandas as pd

data = [
    {
        "Question": "Hình ảnh bên dưới mô tả tình trạng bệnh lý nào của nướu?",
        "Option A": "Viêm nướu do mảng bám",
        "Option B": "Quá sản lợi do thuốc Phenytoin",
        "Option C": "U nướu thai nghén",
        "Option D": "Viêm quanh răng mạn tính",
        "Correct Answer": "B",
        "Explanation": "Hình ảnh cho thấy nướu sưng to, xơ cứng, che phủ thân răng, đặc trưng của quá sản lợi do dùng thuốc chống động kinh Phenytoin.",
        "Subject": "Nha Chu",
        "Topic": "Bệnh học",
        "Source": "Carranza 11th Ed",
        "Mnemonic": "Phenytoin -> Phì đại",
        "Image Q": "gingival_overgrowth.jpg",
        "Image A": ""
    },
    {
        "Question": "Cấu trúc giải phẫu nào được đánh dấu mũi tên trong phim X-quang?",
        "Option A": "Lỗ cằm",
        "Option B": "Ống thần kinh răng dưới",
        "Option C": "Lỗ lưỡi",
        "Option D": "Hõm dưới hàm",
        "Correct Answer": "A",
        "Explanation": "Vị trí nằm giữa hai chân răng cối nhỏ hàm dưới, thấu quang tròn đều -> Lỗ cằm (Mental Foramen).",
        "Subject": "X-Quang",
        "Topic": "Giải phẫu",
        "Source": "White & Pharoah",
        "Mnemonic": "",
        "Image Q": "xray_mental_foramen.jpg",
        "Image A": "stk_lo_cam.jpg"
    }
]

df = pd.DataFrame(data)
df.to_excel("sample_data_with_images.xlsx", index=False)
print("Created sample_data_with_images.xlsx")
