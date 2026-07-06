import streamlit as st
import pdfplumber
import easyocr
from PIL import Image
from pdf2image import convert_from_bytes
import numpy as np
import re
import pandas as pd

st.set_page_config(page_title="ระบบวิเคราะห์และสรุปสถิติเอกสารจับกุม", layout="wide")

# ==========================================
# 1. โหลดตัวอ่าน OCR ภาษาไทย และ อังกฤษ
# ==========================================
@st.cache_resource
def load_ocr_reader():
    return easyocr.Reader(['th', 'en'])

reader = load_ocr_reader()

# ==========================================
# 2. ระบบจำข้อมูลยอดรวม (Session State)
# ==========================================
# สร้างตารางเก็บประวัติการจับกุมในหน่วยความจำของเว็บ (หากยังไม่มี)
if 'arrest_history' not in st.session_state:
    st.session_state.arrest_history = pd.DataFrame(columns=['ชื่อไฟล์', 'วันที่จับกุม', 'สัญชาติ', 'สถานที่จับกุม'])

# ==========================================
# 3. ฟังก์ชันช่วยค้นหาข้อมูล (Regex)
# ==========================================
def extract_arrest_info(text):
    nationality = "ไม่พบข้อมูลสัญชาติ"
    location = "ไม่พบข้อมูลสถานที่จับกุม"
    arrest_date = "ไม่พบข้อมูลวันที่"
    
    # 3.1 ค้นหาสัญชาติ
    nat_match = re.search(r"สัญชาติ\s*([\u0e00-\u0e7fa-zA-Z]+)", text)
    if nat_match:
        nationality = nat_match.group(1).strip()
        
    # 3.2 ค้นหาสถานที่จับกุม
    loc_match = re.search(r"(?:สถานที่จับกุม|จับกุมได้ที่|บริเวณ)\s*(.+?)(?:\s+เมื่อ|วันที่|เวลา|\n|$)", text)
    if loc_match:
        location = loc_match.group(1).strip()
        
    # 3.3 ค้นหาวันที่จับกุม (รองรับแพทเทิร์น เช่น 25 ม.ค. 2567 หรือ 25 มกราคม 2567)
    date_match = re.search(r"(?:เมื่อ)?\s*(วันที่\s*\d{1,2}\s*[\u0e00-\u0e7f]{2,15}\s*\d{4})", text)
    if date_match:
        arrest_date = date_match.group(1).strip()
    else:
        # ลองค้นหาแบบย่อย่อ เช่น \d{1,2} [ม.ค.-ธ.ค.] \d{4}
        date_match_short = re.search(r"(\d{1,2}\s*[\u0e00-\u0e7f\.]+\s*\d{4})", text)
        if date_match_short:
            arrest_date = date_match_short.group(1).strip()
        
    return nationality, location, arrest_date

# ==========================================
# 4. ส่วนหน้าตาเว็บ (UI)
# ==========================================
st.title("ระบบวิเคราะห์และสรุปสถิติเอกสารจับกุมอัตโนมัติ 👮‍♂️📊")
st.write("อัปโหลดไฟล์บันทึกการจับกุมเพื่อดึงข้อมูล และดูสถิติยอดรวมแยกตามสัญชาติ")

# แบ่งหน้าจอเป็น 2 ฝั่ง (ฝั่งซ้ายอัปโหลดไฟล์/ฝั่งขวาสรุปสถิติรวม)
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
                with pdfplumber.open(uploaded_file) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            extracted_text += text + "\n"
                
                if extracted_text.strip() == "":
                    pdf_bytes = uploaded_file.read()
                    images = convert_from_bytes(pdf_bytes)
                    for img in images:
                        img_np = np.array(img)
                        results = reader.readtext(img_np, detail=0)
                        extracted_text += " ".join(results) + "\n"

        if extracted_text.strip() == "":
            st.error("❌ ไม่สามารถดึงข้อความออกมาได้")
        else:
            st.success("📝 อ่านเอกสารสำเร็จ!")
            
            # ดึงข้อมูล 3 อย่าง
            nat, loc, date = extract_arrest_info(extracted_text)
            
            # แสดงผลลัพธ์ของไฟล์ปัจจุบัน
            st.info(f"**📌 ผลลัพธ์จากไฟล์: {file_name}**")
            st.markdown(f"- 📅 **วันที่จับกุม:** {date}")
            st.markdown(f"- 🏳️‍🌈 **สัญชาติ:** {nat}")
            st.markdown(f"- 📍 **สถานที่จับกุม:** {loc}")
            
            # ปุ่มบันทึกเข้าสู่ระบบสถิติรวม
            if st.button("💾 บันทึกข้อมูลนี้เข้าสู่สถิติรวม"):
                # ตรวจสอบว่าไฟล์นี้เคยถูกบันทึกไปหรือยัง เพื่อป้องกันข้อมูลซ้ำ
                if file_name not in st.session_state.arrest_history['ชื่อไฟล์'].values:
                    new_data = pd.DataFrame([{
                        'ชื่อไฟล์': file_name,
                        'วันที่จับกุม': date,
                        'สัญชาติ': nat,
                        'สถานที่จับกุม': loc
                    }])
                    st.session_state.arrest_history = pd.concat([st.session_state.arrest_history, new_data], ignore_index=True)
                    st.success("บันทึกข้อมูลเรียบร้อย!")
                    st.rerun() # สั่งรีเฟรชหน้าเว็บเพื่ออัปเดตสถิติทันที
                else:
                    st.warning("⚠️ ไฟล์นี้เคยถูกบันทึกในระบบสถิติแล้ว")

            with st.expander("🔍 ดูข้อความดิบที่ระบบถอดออกมา"):
                st.text(extracted_text)

# ฝั่งขวา: แสดงแดชบอร์ดสรุปยอดรวมของทุกไฟล์ที่เคยกดบันทึก
with col_right:
    st.subheader("📈 แดชบอร์ดสรุปยอดรวมข้อมูล")
    
    if st.session_state.arrest_history.empty:
        st.info("💡 ยังไม่มีข้อมูลในระบบ ลองอัปโหลดไฟล์ฝั่งซ้ายแล้วกดบันทึกข้อมูลดูครับ")
    else:
        # 1. แสดงจำนวนผู้ถูกจับกุมทั้งหมด
        total_arrests = len(st.session_state.arrest_history)
        st.metric(label="🚨 ยอดรวมผู้ถูกจับกุมทั้งหมด (ราย)", value=total_arrests)
        
        # 2. คำนวณและแสดง "ยอดรวมของแต่ละสัญชาติ"
        st.write("📊 **จำนวนผู้ถูกจับกุมแยกตามสัญชาติ**")
        
        # ใช้ Pandas นับจำนวนสัญชาติซ้ำ
        nationality_counts = st.session_state.arrest_history['สัญชาติ'].value_counts().reset_index()
        nationality_counts.columns = ['สัญชาติ', 'จำนวน (ราย)']
        
        # แสดงเป็นตารางสวยๆ
        st.dataframe(nationality_counts, use_container_width=True)
        
        # แถม: แสดงเป็นแผนภูมิแท่ง (Bar Chart) ให้ดูง่ายขึ้นอัตโนมัติ
        st.bar_chart(data=nationality_counts, x='สัญชาติ', y='จำนวน (ราย)')
        
        # 3. แสดงประวัติตารางรวมทั้งหมด
        with st.expander("📋 ดูตารางบันทึกประวัติทั้งหมด"):
            st.dataframe(st.session_state.arrest_history, use_container_width=True)
            
            # ปุ่มล้างข้อมูลทั้งหมดเพื่อเริ่มนับใหม่
            if st.button("🗑️ ล้างข้อมูลสถิติตั้งต้นใหม่"):
                st.session_state.arrest_history = pd.DataFrame(columns=['ชื่อไฟล์', 'วันที่จับกุม', 'สัญชาติ', 'สถานที่จับกุม'])
                st.rerun()