import streamlit as st
import pdfplumber
import easyocr
from PIL import Image
import numpy as np
import re
import pandas as pd
import fitz  # PyMuPDF
import io

st.set_page_config(page_title="ระบบรายงานจับกุมต่างด้าวแยกตาม สน.", layout="wide")

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

# รายชื่อ สน. หลักตั้งต้นตามไฟล์ Excel ตัวอย่าง
STATIONS = [
    "วัดพระยาไกร", "บางโพงพาง", "ทุ่งมหาเมฆ", "ลุมพินี", 
    "ทองหล่อ", "คลองตัน", "พระโขนง", "บางนา", "ท่าเรือ", "กก.สส.5"
]

# เริ่มต้นโครงสร้างตารางรายงานแบบไดนามิก (เป็น List เพื่อให้ง่ายต่อการแทรกแถวใหม่)
if 'report_data' not in st.session_state:
    base_list = []
    for station in STATIONS:
        base_list.append({
            'สน.': station,
            'ผู้ต้องหา (คน)': 0,
            'สัญชาติ': '-',
            'สถานที่ที่จับกุม': '-'
        })
    st.session_state.report_data = base_list

# ==========================================
# 2. ฟังก์ชันดึงและซ่อมคำผิดจาก OCR
# ==========================================
def extract_arrest_info(text):
    nationality = "ไม่พบข้อมูลสัญชาติ"
    location = "ไม่พบข้อมูลสถานที่จับกุม"
    
    clean_text = re.sub(r'\s+', ' ', text)
    
    # ดักจับสัญชาติ + ซ่อมคำเพี้ยน
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
        
    return nationality, location

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
    st.title("ระบบวิเคราะห์และกรอกสถิติเอกสารจับกุมแยกตาม สน. 👮‍♂️📊")
with col_logout:
    if st.button("ออกจากระบบ 🚪"):
        st.session_state.logged_in = False
        st.rerun()

st.write("ดึงข้อมูล จำนวน, สัญชาติ, สถานที่จับกุม ลงล็อกตาม สน. (รองรับการแตกแถวใหม่เมื่อสัญชาติซ้ำ)")
st.markdown("---")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 ส่วนอัปโหลดและวิเคราะห์ไฟล์")
    uploaded_file = st.file_uploader("อัปโหลดไฟล์ PDF หรือรูปภาพบันทึกการจับกุม", type=["pdf", "png", "jpg", "jpeg"])

    if uploaded_file is not None:
        extracted_text = ""
        file_name = uploaded_file.name
        file_type = file_name.split('.')[-1].lower()
        
        with st.spinner("🔍 AI กำลังตรวจสอบเอกสาร..."):
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
            
            nat, loc = extract_arrest_info(extracted_text)
            
            st.info(f"**📌 ข้อมูลที่ดึงได้สำเร็จ:**")
            st.markdown(f"- 🏳️‍🌈 **สัญชาติ:** {nat}")
            st.markdown(f"- 📍 **สถานที่จับกุม:** {loc}")
            
            # ตรวจหาว่าคดีนี้เป็นของ สน. ไหน
            detected_station = "ท่าเรือ"  # ค่าเริ่มต้นหากหาไม่เจอ
            for station in STATIONS:
                if station in extracted_text:
                    detected_station = station
                    break
            
            st.warning(f"ระบบจะนำข้อมูลนี้ไปกรอกให้ที่ช่องของ **สน.{detected_station}**")

            if st.button("💾 บันทึกข้อมูลเข้าตารางรายงาน"):
                current_list = st.session_state.report_data
                
                # ค้นหาตำแหน่งของ สน. นี้ในตารางปัจจุบัน
                target_indices = [i for i, row in enumerate(current_list) if row['สน.'] == detected_station]
                
                inserted = False
                if target_indices:
                    for idx in target_indices:
                        # กรณีที่ 1: แถวของ สน. นั้นยังว่างอยู่ (ยังไม่มีการบันทึกสัญชาติ) ให้กรอกทับได้เลย
                        if current_list[idx]['สัญชาติ'] == '-':
                            current_list[idx]['ผู้ต้องหา (คน)'] = 1
                            current_list[idx]['สัญชาติ'] = nat
                            current_list[idx]['สถานที่ที่จับกุม'] = loc
                            inserted = True
                            break
                        # กรณีที่ 2: มีสัญชาตินั้นอยู่แล้ว ให้บวกจำนวนผู้ต้องหาเพิ่มขึ้น 1
                        elif current_list[idx]['สัญชาติ'] == nat:
                            current_list[idx]['ผู้ต้องหา (คน)'] += 1
                            # ถ้ารวมสถานที่ใหม่เข้าไปด้วย (คั่นด้วยจุลภาค)
                            if loc not in current_list[idx]['สถานที่ที่จับกุม']:
                                current_list[idx]['สถานที่ที่จับกุม'] += f", {loc}"
                            inserted = True
                            break
                    
                    # กรณีที่ 3: สน. นี้ถูกบันทึกด้วยสัญชาติอื่นไปแล้ว (จับสัญชาติใหม่เพิ่ม) -> ให้แทรกบรรทัดใหม่!
                    if not inserted:
                        last_idx = target_indices[-1]
                        new_row = {
                            'สน.': detected_station,
                            'ผู้ต้องหา (คน)': 1,
                            'สัญชาติ': nat,
                            'สถานที่ที่จับกุม': loc
                        }
                        # แทรกแถวใหม่ต่อท้าย สน. เดิมทันที
                        current_list.insert(last_idx + 1, new_row)
                
                st.session_state.report_data = current_list
                st.success("บันทึกข้อมูลเรียบร้อยแล้ว!")
                st.rerun()

            with st.expander("🔍 ดูข้อความดิบทั้งหมด"):
                st.text(extracted_text)

with col_right:
    st.subheader("📋 ตารางแบบรายงานสรุป (อัปเดตแบบเรียลไทม์)")
    
    # แปลง List กลับเป็น DataFrame เพื่อนำมาคำนวณและแสดงผล
    df_show = pd.DataFrame(st.session_state.report_data)
    
    # คำนวณแถว "รวม" สรุปท้ายตาราง
    total_row = pd.DataFrame([{
        'สน.': 'รวม',
        'ผู้ต้องหา (คน)': df_show['ผู้ต้องหา (คน)'].sum(),
        'สัญชาติ': '',
        'สถานที่ที่จับกุม': ''
    }])
    df_final = pd.concat([df_show, total_row], ignore_index=True)
    
    # แสดงตารางบนหน้าเว็บแบบไม่มี Error index
    st.dataframe(df_final, use_container_width=True, index=False)
    
    # ปุ่มดาวน์โหลดไฟล์ Excel 
    excel_data = to_excel(df_final)
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel (.xlsx)",
        data=excel_data,
        file_name="รายงานจับกุมต่างด้าว_แยกสน.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
    
    if st.button("🗑️ รีเซ็ตข้อมูลตารางใหม่ทั้งหมด"):
        base_list = []
        for station in STATIONS:
            base_list.append({'สน.': station, 'ผู้ต้องหา (คน)': 0, 'สัญชาติ': '-', 'สถานที่ที่จับกุม': '-'})
        st.session_state.report_data = base_list
        st.rerun()
