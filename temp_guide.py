
def view_user_guide():
    st.title("❓ Hướng dẫn sử dụng")
    
    with st.expander("📚 Cách sử dụng Thư viện", expanded=True):
        st.markdown("""
        1. **Lọc thẻ:** Sử dụng bộ lọc Môn học và Chủ đề để tìm kiếm nhanh.
        2. **Xem trước:** Bấm vào thẻ để xem chi tiết câu hỏi và đáp án.
        3. **Chỉnh sửa:** Bấm nút **Chỉnh sửa** để cập nhật nội dung sai sót.
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
        3. Nhập tên nhãn cho vùng đó.
        4. AI sẽ tự động tạo thẻ điền khuyết với ảnh đã che.
        """)
