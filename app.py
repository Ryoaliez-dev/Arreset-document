import streamlit as st
import pdfplumber
import easyocr
from PIL import Image
import numpy as np
import re
import pandas as pd
import fitz  # PyMuPDF
import io

st.set_page_config(page_title="ระบบรายงานจับกุมต่างด้าวประจำวัน", layout="wide")

# ==========================================
# 0. ระบบตรวจสอบการเข้าสู่ระบบ (Authentication)
# ==========================================
PASSWORD_TRUE = "Ryoarrest1966"  

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

def login_form():
    st.markdown("<h2 style='text-align: center;'>🔒 กรุณากรอกรหัสผ่านเพื่อเข้าใช้งานระบบ</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>ระบบวิเคราะห์และสรุปสถิติเอกสารจับกุมอัตโนมัติ</p>", unsafe_allow_html=True)
    
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        user_password = st.text_input("รหัสผ่านผู้ใช้งาน:", type="password")
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

# ตั้งค่าสถานีตำรวจเริ่มต้นตามไฟล์ตัวอย่างของพี่
STATIONS = [
    "วัดพระยาไกร", "บางโพงพาง", "ทุ่งมหาเมฆ", "ลุมพินี", 
    "ทองหล่อ", "คลองตัน", "พระโขนง", "บางนา", "ท่าเรือ", "กก.สส.5"
]

# สร้างโครงสร้างตารางรายงานให้ตรงตามแบบฟอร์ม Excel ของพี่เป๊ะๆ
if 'report_df' not in st.session_state:
    base_data = []
    for station in STATIONS:
        base_data.append({
            'สน.': station,
            'ผู้ต้องหา (คน)': 0,
            'สัญชาติ': '-',
            'ผู้ต้องหา พท.ตอนใน': 0,
            'ผู้ต้องหา พท.ติดชายแดน': 0,
            'สถานที่ที่จับกุม': '-',
            'จังหวัด': '-',
            'การลักลอบ เข้ามาเอง': '-',
            'การลักลอบ มีผู้นำเข้า': '-',
            'การตรวจ COVID-19': '-',
            'เดินทางมาก่อน 1963-10-01': '-',
            'หมายเหตุ': '-'
        })
    st.session_state.report_df = pd.DataFrame(base_data)

# ==========================================
# 2. ฟังก์ชันดึงข้อมูล (Regex) พร้อมระบบแก้คำผิด
# ==========================================
def extract_arrest_info(text):
    nationality = "ไม่พบข้อมูลสัญชาติ"
    location = "ไม่พบข้อมูลสถานที่จับกุม"
    arrest_date = "ไม่พบข้อมูลวันที่"
    
    clean_text = re.sub(r'\s+', ' ', text)
    
    # ดักจับสัญชาติ
    if any(k in clean_text for k in ["กัมขชำ", "กัมขชา", "กัมศูชา", "กัมพูชา"]):
        nationality = "กัมพูชา"
    elif "เมียน" in clean_text or "พม่า" in clean_text:
        nationality = "เมียนมา"
    elif "ลาว" in clean_text:
        nationality = "ลาว"
        
    # ดักจับสถานที่
    loc_match = re.search(r"(?:สถานที่จับกุม|สถานทีจับกุม|จับกุมได้ที่|บริเวณ|บริเาณ)\s*(.+?)(?:\s+เมื่อ|วันที่|วันที|เวลา|พฤติการณ์|เจ้าพนักงาน|\n|$)", clean_text)
    if loc_match:
        location = loc_match.group(1).strip()
        location = location.replace("บริเาณ", "บริเวณ").replace("ชมชน", "ชุมชน").replace("แเขวง", "แขวง")
        
    # ดักจับวันที่
    date_match = re.search(r"(?:วันที่จับกุม|วันทีจับกุม)\s*(\d{1,2}\s*[\u0e00-\u0e7f\.]+\s*\d{4})", clean_text)
    if date_match:
        arrest_date = date_match.group(1).strip()
    else:
        date_fallback = re.search(r"(\d{1,2}\s*[ก-ฮ]{1,3}\.[ก-ฮn]\.?\s*\d{4})", clean_text)
        if date_fallback:
            arrest_date = date_fallback.group(1).strip()
            
    arrest_date = arrest_date.replace("ก.n.", "ก.ค.")
        
    return nationality, location, arrest_date

# ฟังก์ชันแปลง DataFrame เป็นไฟล์ Excel
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

# ==========================================
# 3. ส่วนแสดงผลหน้าเว็บ (UI)
# ==========================================
col_title, col_logout = st.columns([9, 1])
with col_title:
    st.title("ระบบวิเคราะห์และสรุปสถิติเอกสารจับกุมอัตโนมัติ 👮‍♂️📊")
with col_logout:
    if st.button("ออกจากระบบ 🚪"):
        st.session_state.logged_in = False
        st.rerun()

st.write("แบบรายงานการจับกุมต่างด้าวหลบหนีเข้าเมือง และคนไทยเข้า - ออกประเทศโดยผิดกฎหมาย")
st.markdown("---")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 ส่วนอัปโหลดและวิเคราะห์ไฟล์")
    uploaded_file = st.file_uploader("อัปโหลดไฟล์ PDF หรือรูปภาพบันทึกการจับกุม", type=["pdf", "png", "jpg", "jpeg"])

    if uploaded_file is not None:
        extracted_text = ""
        file_name = uploaded_file.name
        file_type = file_name.split('.')[-1].lower()
        
        with st.spinner("🔍 AI กำลังแกะข้อความจากเอกสารทั้งหมด..."):
            if file_type in ["png", "jpg", "jpeg"]:
                image = Image.open(uploaded_file)
                image_np = np.array(image)
                results = reader.readtext(image_np, detail=0)
                extracted_text = " ".join(results)
                
            elif file_type == "pdf":
                pdf_bytes = uploaded_file.read()
                with pdfplumber.open(uploaded_file) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            extracted_text += text + "\n"
                
                if extracted_text.strip() == "":
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    for page_num in range(len(doc)):
                        page = doc.load_page(page_num)
                        pix = page.get_pixmap(dpi=150)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        img_np = np.array(img)
                        results = reader.readtext(img_np, detail=0)
                        extracted_text += " ".join(results) + "\n"

        if extracted_text.strip() == "":
            st.error("❌ ไม่สามารถดึงข้อความออกมาได้")
        else:
            st.success("📝 อ่านเอกสารสำเร็จ!")
            
            nat, loc, date = extract_arrest_info(extracted_text)
            
            st.info(f"**📌 ผลลัพธ์ที่ดึงได้จากไฟล์:**")
            st.markdown(f"- 🏳️‍🌈 **สัญชาติ:** {nat}")
            st.markdown(f"- 📍 **สถานที่จับกุม:** {loc}")
            
            # ตรวจหาชื่อ สน. จากข้อความดิบ (เช่น สน.ท่าเรือ)
            detected_station = "ท่าเรือ"  # ค่าเริ่มต้นหากตรวจไม่พบ
            for station in STATIONS:
                if station in extracted_text:
                    detected_station = station
                    break
            
            st.warning(f"ระบบจะนำข้อมูลนี้ไปบันทึกที่แถวของ **สน.{detected_station}**")

            if st.button("💾 บันทึกข้อมูลนี้เข้าสู่แบบฟอร์มรายงาน"):
                # ทำการอัปเดตข้อมูลลงไปในแถวของ สน. นั้นๆ ในตารางรายงาน
                df = st.session_state.report_df
                idx = df[df['สน.'] == detected_station].index
                if len(idx) > 0:
                    df.loc[idx, 'ผู้ต้องหา (คน)'] += 1
                    df.loc[idx, 'สัญชาติ'] = nat
                    df.loc[idx, 'ผู้ต้องหา พท.ตอนใน'] += 1
                    df.loc[idx, 'สถานที่ที่จับกุม'] = loc
                    df.loc[idx, 'จังหวัด'] = "กรุงเทพมหานคร" if "กรุงเทพ" in loc or "คลองเตย" in loc else "-"
                    st.session_state.report_df = df
                    st.success(f"บันทึกข้อมูลลงช่อง สน.{detected_station} เรียบร้อยแล้ว!")
                    st.rerun()

            with st.expander("🔍 ดูข้อความดิบทั้งหมดที่ระบบถอดออกมา"):
                st.text(extracted_text)

with col_right:
    st.subheader("📊 แบบฟอร์มรายงานประจำวัน (ตารางสรุป)")
    
    # คำนวณยอดรวมแถวล่างสุด
    df_to_show = st.session_state.report_df.copy()
    total_row = pd.DataFrame([{
        'สน.': 'รวม',
        'ผู้ต้องหา (คน)': df_to_show['ผู้ต้องหา (คน)'].sum(),
        'สัญชาติ': '',
        'ผู้ต้องหา พท.ตอนใน': df_to_show['ผู้ต้องหา พท.ตอนใน'].sum(),
        'ผู้ต้องหา พท.ติดชายแดน': df_to_show['ผู้ต้องหา พท.ติดชายแดน'].sum(),
        'สถานที่ที่จับกุม': '',
        'จังหวัด': '',
        'การลักลอบ เข้ามาเอง': '',
        'การลักลอบ มีผู้นำเข้า': '',
        'การตรวจ COVID-19': '',
        'เดินทางมาก่อน 1963-10-01': '',
        'หมายเหตุ': ''
    }])
    df_with_total = pd.concat([df_to_show, total_row], ignore_index=True)
    
    # แสดงตารางบนหน้าเว็บ
    st.dataframe(df_with_total, use_container_width=True, index=False)
    
    # ปุ่มดาวน์โหลดไฟล์ Excel หน้าตาตามแบบฟอร์มของพี่
    excel_data = to_excel(df_with_total)
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel รายงานประจำวัน (.xlsx)",
        data=excel_data,
        file_name="แบบรายงานการจับกุมต่างด้าว_ประจำวัน.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
    
    if st.button("🗑️ รีเซ็ตตารางรายงานทั้งหมดใหม่"):
        base_data = []
        for station in STATIONS:
            base_data.append({
                'สน.': station, 'ผู้ต้องหา (คน)': 0, 'สัญชาติ': '-', 'ผู้ต้องหา พท.ตอนใน': 0,
                'ผู้ต้องหา พท.ติดชายแดน': 0, 'สถานที่ที่จับกุม': '-', 'จังหวัด': '-',
                'การลักลอบ เข้ามาเอง': '-', 'การลักลอบ มีผู้นำเข้า': '-', 'การตรวจ COVID-19': '-',
                'เดินทางมาก่อน 1963-10-01': '-', 'หมายเหตุ': '-'
            })
        st.session_state.report_df = pd.DataFrame(base_data)
        st.rerun()
