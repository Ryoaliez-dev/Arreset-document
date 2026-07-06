import streamlit as st
import pdfplumber
import easyocr
from PIL import Image
import numpy as np
import re
import pandas as pd
import fitz  # PyMuPDF ตัวแปลง PDF เป็นภาพแบบไม่ต้องใช้ Poppler

st.set_page_config(page_title="ระบบวิเคราะห์เอกสารจับกุม (มีระบบล็อกอิน)", layout="wide")

# ==========================================
# 0. ระบบตรวจสอบการเข้าสู่ระบบ (Authentication)
# ==========================================
PASSWORD_TRUE = "Arrest1234" 

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

def login_form():
    st.markdown("<h2 style='text-align: center;'>🔒 กรุณากรอกรหัสผ่านเพื่อเข้าใช้งานระบบ</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>ระบบวิเคราะห์และสรุปสถิติเอกสารจับกุมอัตโนมัติ</p>", unsafe_allow_html=True)
    
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        user_password = st.text_input("รหัสผ่านผู้ใช้งาน:", type="Ryoarrest1996")
        if st.button("เข้าสู่ระบบ 🚀", use_container_width=True):
            if user_password == PASSWORD_TRUE:
                st.session_state.logged_in = True
                st.success("เข้าสู่ระบบสำเร็จ!")
                st.rerun()
            else:
                st.error("❌ รหัสผ่านไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง")

if not st.session_state.logged_in:
    login_form()
    st.stop()

# ==========================================
# 1. โหลดตัวอ่าน OCR ภาษาไทย และ อังกฤษ
# ==========================================
@st.cache_resource
def load_ocr_reader():
    return easyocr.Reader(['th', 'en'])

reader = load_ocr_reader()

if 'arrest_history' not in st.session_state:
    st.session_state.arrest_history = pd.DataFrame(columns=['ชื่อไฟล์', 'วันที่จับกุม', 'สัญชาติ', 'สถานที่จับกุม'])

# ==========================================
# 2. ฟังก์ชันช่วยค้นหาข้อมูล (Regex)
# ==========================================
def extract_arrest_info(text):
    nationality = "ไม่พบข้อมูลสัญชาติ"
    location = "ไม่พบข้อมูลสถานที่จับกุม"
    arrest_date = "ไม่พบข้อมูลวันที่"
    
    nat_match = re.search(r"สัญชาติ\s*([\u0e00-\u0e7fa-zA-Z]+)", text)
    if nat_match:
        nationality = nat_match.group(1).strip()
        
    loc_match = re.search(r"(?:สถานที่จับกุม|จับกุมได้ที่|บริเวณ)\s*(.+?)(?:\s+เมื่อ|วันที่|เวลา|\n|$)", text)
    if loc_match:
        location = loc_match.group(1).strip()
        
    date_match = re.search(r"(?:เมื่อ)?\s*(วันที่\s*\d{1,2}\s*[\u0e00-\u0e7f]{2,15}\s*\d{4})", text)
    if date_match:
        arrest_date = date_match.group(1).strip()
    else:
        date_match_short = re.search(r"(\d{1,2}\s*[\u0e00-\u0e7f\.]+\s*\d{4})", text)
        if date_match_short:
            arrest_date = date_match_short.group(1).strip()
        
    return nationality, location, arrest_date

# ==========================================
# 3. ส่วนหน้าตาเว็บหลัก (UI)
# ==========================================
col_title, col_logout = st.columns([9, 1])
with col_title:
    st.title("ระบบวิเคราะห์และสรุปสถิติเอกสารจับกุมอัตโนมัติ 👮‍♂️📊")
with col_logout:
    if st.button("ออกจากระบบ 🚪"):
        st.session_state.logged_in = False
        st.rerun()

st.write("ยินดีต้อนรับเข้าสู่ระบบจัดการข้อมูลความปลอดภัย")
st.markdown("---")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 ส่วนอัปโหลดและวิเคราะห์ไฟล์")
    uploaded_file = st.file_uploader("อัปโหลดไฟล์ PDF หรือรูปภาพบันทึกการจับกุม", type=["pdf", "png", "jpg", "jpeg"])

    if uploaded_file is not None:
        extracted_text = ""
        file_name = uploaded_file.name
        file_type = file_name.split('.')[-1].lower()
        
        with st.spinner("🔍 AI กำลังแกะข้อความจากเอกสาร..."):
            if file_type in ["png", "jpg", "jpeg"]:
                image = Image.open(uploaded_file)
                image_np = np.array(image)
                results = reader.readtext(image_np, detail=0)
                extracted_text = " ".join(results)
                
            elif file_type == "pdf":
                # อ่านไฟล์เก็บไว้ในหน่วยความจำ
                pdf_bytes = uploaded_file.read()
                
                # วิธีที่ 1: ดึงข้อความจากดิจิทัล PDF ปกติก่อน
                with pdfplumber.open(uploaded_file) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            extracted_text += text + "\n"
                
                # วิธีที่ 2: ถ้าไม่มีข้อความเลย (เป็น PDF สแกน) แปลงหน้า PDF เป็นภาพด้วย PyMuPDF แล้วทำ OCR
                if extracted_text.strip() == "":
                    st.info("ℹ️ ตรวจพบว่าเป็น PDF รูปภาพ/สแกน ระบบกำลังประมวลผลด้วย OCR...")
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    
                    for page_num in range(len(doc)):
                        page = doc.load_page(page_num)
                        pix = page.get_pixmap(dpi=150) # ปรับความคมชัดระดับกำลังดีสำหรับทำ OCR
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        
                        img_np = np.array(img)
                        results = reader.readtext(img_np, detail=0)
                        extracted_text += " ".join(results) + "\n"

        if extracted_text.strip() == "":
            st.error("❌ ไม่สามารถดึงข้อความออกมาได้")
        else:
            st.success("📝 อ่านเอกสารสำเร็จ!")
            
            nat, loc, date = extract_arrest_info(extracted_text)
            
            st.info(f"**📌 ผลลัพธ์จากไฟล์: {file_name}**")
            st.markdown(f"- 📅 **วันที่จับกุม:** {date}")
            st.markdown(f"- 🏳️‍🌈 **สัญชาติ:** {nat}")
            st.markdown(f"- 📍 **สถานที่จับกุม:** {loc}")
            
            if st.button("💾 บันทึกข้อมูลนี้เข้าสู่สถิติรวม"):
                if file_name not in st.session_state.arrest_history['ชื่อไฟล์'].values:
                    new_data = pd.DataFrame([{
                        'ชื่อไฟล์': file_name,
                        'วันที่จับกุม': date,
                        'สัญชาติ': nat,
                        'สถานที่จับกุม': loc
                    }])
                    st.session_state.arrest_history = pd.concat([st.session_state.arrest_history, new_data], ignore_index=True)
                    st.success("บันทึกข้อมูลเรียบร้อย!")
                    st.rerun()
                else:
                    st.warning("⚠️ ไฟล์นี้เคยถูกบันทึกในระบบสถิติแล้ว")

            with st.expander("🔍 ดูข้อความดิบที่ระบบถอดออกมา"):
                st.text(extracted_text)

with col_right:
    st.subheader("📈 แดชบอร์ดสรุปยอดรวมข้อมูล")
    
    if st.session_state.arrest_history.empty:
        st.info("💡 ยังไม่มีข้อมูลในระบบ ลองอัปโหลดไฟล์ฝั่งซ้ายแล้วกดบันทึกข้อมูลดูครับ")
    else:
        total_arrests = len(st.session_state.arrest_history)
        st.metric(label="🚨 ยอดรวมผู้ถูกจับกุมทั้งหมด (ราย)", value=total_arrests)
        
        st.write("📊 **จำนวนผู้ถูกจับกุมแยกตามสัญชาติ**")
        nationality_counts = st.session_state.arrest_history['สัญชาติ'].value_counts().reset_index()
        nationality_counts.columns = ['สัญชาติ', 'จำนวน (ราย)']
        
        st.dataframe(nationality_counts, use_container_width=True)
        st.bar_chart(data=nationality_counts, x='สัญชาติ', y='จำนวน (ราย)')
        
        with st.expander("📋 ดูตารางบันทึกประวัติทั้งหมด"):
            st.dataframe(st.session_state.arrest_history, use_container_width=True)
            if st.button("🗑️ ล้างข้อมูลสถิติตั้งต้นใหม่"):
                st.session_state.arrest_history = pd.DataFrame(columns=['ชื่อไฟล์', 'วันที่จับกุม', 'สัญชาติ', 'สถานที่จับกุม'])
                st.rerun()