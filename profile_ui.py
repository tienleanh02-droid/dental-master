
# --- PROFILE UI ---
def view_profile_selector():
    st.markdown("""
    <style>
        .profile-btn {
            padding: 20px;
            font-size: 20px;
            text-align: center;
            border-radius: 10px;
            border: 2px solid #e0e0e0;
            background: white;
            cursor: pointer;
            transition: 0.3s;
        }
        .profile-btn:hover {
            border-color: #0083b0;
            background: #f0f9ff;
        }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("👋 Ai đang học đấy?")
    st.markdown("Chọn hồ sơ của bạn để bắt đầu.")

    # 1. Lấy danh sách hồ sơ
    profiles = DataManager.get_all_profiles()

    if not profiles:
        st.warning("Chưa có hồ sơ nào. Hãy tạo mới bên dưới.")

    # 2. Hiển thị các nút bấm chọn hồ sơ
    # Dùng columns để dàn ngang ra
    if profiles:
        cols = st.columns(4) # Tối đa 4 người 1 hàng
        for i, name in enumerate(profiles):
            with cols[i % 4]:
                if st.button(f"👤 {name}", key=f"login_{name}", use_container_width=True, type="secondary"):
                    st.session_state.logged_in = True
                    st.session_state.username = name
                    st.toast(f"Xin chào {name}!", icon="🎉")
                    st.rerun()

    st.divider()
    
    # 3. Tạo hồ sơ mới
    with st.expander("➕ Tạo hồ sơ mới"):
        with st.form("new_profile"):
            new_name = st.text_input("Tên của bạn:", placeholder="Ví dụ: Bác sĩ Nam")
            if st.form_submit_button("Tạo ngay", type="primary"):
                success, msg = DataManager.create_profile(new_name)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = new_name
                    st.success(f"{msg} Đang đăng nhập...")
                    st.rerun()
                else:
                    st.error(msg)
