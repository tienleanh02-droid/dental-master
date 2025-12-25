import streamlit as st
try:
    from google import genai
    st.write("Imported 'google.genai' successfully!")
    st.write(f"Version: {genai.__version__}")
except ImportError as e:
    st.error(f"Import Error: {e}")
except Exception as e:
    st.error(f"Error: {e}")

st.title("Minimal Test")
st.button("Click me")
