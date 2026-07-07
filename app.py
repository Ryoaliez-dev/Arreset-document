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

STATIONS = [
    "วัดพระยาไกร", "บางโพงพาง", "ทุ่งมหาเมฆ", "ลุมพินี", 
    "ทองหล่อ", "คลองตัน", "พระโขนง", "บางนา", "ท่าเรือ", "กก.สส.5"
]

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
# 2. ฟังก์ชันดึงข้อมูล (ปรับปรุงการตรวจจับสัญชาติแบบอัจฉริยะ)
# ==========================================
def extract_arrest_info(text):
    nationality = "อื่น ๆ"
    location = "ไม่พบข้อมูลสถานที่จับกุม"
    detected_count = 1
    
    clean_text = re.sub(r'\s+', '', text)
    
    if any(k in clean_text for k in ["กัมพูชา", "กัมขชา", "กัมขชำ", "กัมศูชา", "กัม"]):
        nationality = "กัมพูชา"
    elif any(k in clean_text for k in ["เมียนมา", "เมียน", "พม่า"]):
        nationality = "เมียนมา"
    elif "ลาว" in clean_text:
        nationality = "ลาว"
        
    clean_space_text = re.sub(r'\s+', ' ', text)
    loc_match = re.search(r"(?:สถานที่จับกุม|สถานทีจับกุม|จับกุมได้ที่|บริเวณ|บริเาณ)\s*(.+?)(?:\s+เมื่อ|วันที่|วันที|เวลา|พฤติการณ์|เจ้าพนักงาน|\n|$)", clean_space_text)
    if loc_match:
        location = loc_match.group(1).strip()
        location = location.replace("บริเาณ", "บริเวณ").replace("ชมชน", "ชุมชน").replace("แเขวง", "แขวง")
        
    count_match = re.search(r"(?:จำนวน|รวม|สัญชาติ[\u0e00-\u0e7f]+\s*)\s*(\d+)\s*(?:คน|ราย|นาม)", clean_space_text)
    if count_match:
        detected_count = int(count_match.group(1))
    else:
        digit_match = re.search(r"(\d+)\s*(?:คน|ราย)", clean_space_text)
        if digit_match:
            detected_count = int(digit_match.group(1))
        
    return nationality, location, detected_count

# 🔥 ฟังก์ชันสร้างไฟล์ Excel เวอร์ชันคอลัมน์ครบถ้วน ไม่ทำให้ตารางหน้าเว็บพัง
def build_full_excel(data_list):
    header_row1 = ['สน.', 'ผู้ต้องหา', 'สัญชาติ', 'ผู้ต้องหา', '', 'สถานที่ที่จับกุม', 'จังหวัด', 'การลักลอบ', '', '', 'เดินทาง', 'หมายเหตุ']
    header_row2 = ['', '( คน )', '', 'พท.ตอนใน', 'พท.ติดชายแดน', '', '', 'พื้นที่ช่องทาง', 'เข้ามาเอง', 'มีผู้นำเข้า / นายหน้า', 'มาก่อน 1 ต.ค.06', '']
    
    body_rows = []
    total_count = 0
    
    for row in data_list:
        count = row['ผู้ต้องหา (คน)']
        total_count += count
        
        is_empty = (row['สัญชาติ'] == '-')
        pht_in = count if not is_empty else 0
        prov = "กรุงเทพมหานคร" if not is_empty else "-"
        
        body_rows.append([
            row['สน.'],
            count if count > 0 else 0,
            row['สัญชาติ'],
            pht_in,
            0,
            row['สถานที่ที่จับกุม'],
            prov,
            "-", "-", "-", "-", "-"
        ])
        
    footer_row = ['รวม', total_count, '', total_count, 0, '', '', '', '', '', '', '']
    
    all_table_data = [header_row1, header_row2] + body_rows + [footer_row]
    df_final_excel = pd.DataFrame(all_table_data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_final_excel.to_excel(writer, index=False, header=False, sheet_name='Sheet1')
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

st.write("ระบบดึงสัญชาติและจำนวนคนอัตโนมัติ พร้อมแตกแถวใหม่เมื่อตรวจเจอหลายสัญชาติใน สน. เดียวกัน")
st.markdown("---")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 ส่วนอัปโหลดและวิเคราะห์ไฟล์")
    uploaded_file = st.file_uploader("อัปโหลดไฟล์ PDF หรือรูปภาพบันทึกการจับกุม", type=["pdf", "png", "jpg", "jpeg"])

    if uploaded_file is not None:
        extracted_text = ""
        file_name = uploaded_file.name
        file_type = file_name.split('.')[-1].lower()
        
        with st.spinner("🔍 AI กำลังวิเคราะห์เอกสาร..."):
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
            
            nat, loc, final_count = extract_arrest_info(extracted_text)
            
            st.info(f"**📌 ตรวจสอบและยืนยันข้อมูลความถูกต้องก่อนบันทึก:**")
            
            edit_nat = st.selectbox("🏳️‍🌈 ยืนยันสัญชาติที่ตรวจพบ:", ["กัมพูชา", "เมียนมา", "ลาว", "อื่น ๆ"], index=["กัมพูชา", "เมียนมา", "ลาว", "อื่น ๆ"].index(nat) if nat in ["กัมพูชา", "เมียนมา", "ลาว", "อื่น ๆ"] else 3)
            user_count = st.number_input("🔢 จำนวนผู้ต้องหาในคดีนี้ (คน):", min_value=1, value=final_count, step=1)
            edit_loc = st.text_input("📍 สถานที่จับกุม:", value=loc)
            
            detected_station = "ท่าเรือ"  
            for station in STATIONS:
                if station in extracted_text:
                    detected_station = station
                    break
            
            st.warning(f"ระบบจะนำข้อมูลจำนวน **{user_count} คน** สัญชาติ **{edit_nat}** ไปบันทึกที่ช่องของ **สน.{detected_station}**")

            if st.button("💾 บันทึกข้อมูลเข้าตารางรายงาน"):
                current_list = st.session_state.report_data
                target_indices = [i for i, row in enumerate(current_list) if row['สน.'] == detected_station]
                
                inserted = False
                if target_indices:
                    for idx in target_indices:
                        if current_list[idx]['สัญชาติ'] == '-':
                            current_list[idx]['ผู้ต้องหา (คน)'] = user_count
                            current_list[idx]['สัญชาติ'] = edit_nat
                            current_list[idx]['สถานที่ที่จับกุม'] = edit_loc
                            inserted = True
                            break
                        elif current_list[idx]['สัญชาติ'] == edit_nat:
                            current_list[idx]['ผู้ต้องหา (คน)'] += user_count
                            if edit_loc not in current_list[idx]['สถานที่ที่จับกุม']:
                                current_list[idx]['สถานที่ที่จับกุม'] += f", {edit_loc}"
                            inserted = True
                            break
                    
                    if not inserted:
                        last_idx = target_indices[-1]
                        new_row = {
                            'สน.': detected_station,
                            'ผู้ต้องหา (คน)': user_count,
                            'สัญชาติ': edit_nat,
                            'สถานที่ที่จับกุม': edit_loc
                        }
                        current_list.insert(last_idx + 1, new_row)
                
                st.session_state.report_data = current_list
                st.success(f"บันทึกข้อมูลสำเร็จ!")
                st.rerun()

with col_right:
    st.subheader("📋 ตารางแสดงผลบนหน้าเว็บ")
    
    # แยกโครงสร้างตารางบนหน้าเว็บให้แปลงเป็น DataFrame และบวกแถวรวมอย่างปลอดภัย ไม่ชนกับระบบ Excel
    df_show = pd.DataFrame(st.session_state.report_data)
    
    # คำนวณยอดรวมยอดผู้ต้องหาทั้งหมดเพื่อนำไปโชว์
    sum_value = df_show['ผู้ต้องหา (คน)'].sum()
    
    # สร้างแถวรวมสำหรับแสดงบนหน้าเว็บให้โครงสร้างคอลลัมน์เท่ากันเป๊ะ
    total_row_web = pd.DataFrame([{
        'สน.': 'รวม', 
        'ผู้ต้องหา (คน)': sum_value, 
        'สัญชาติ': '', 
        'สถานที่ที่จับกุม': ''
    }])
    df_final = pd.concat([df_show, total_row_web], ignore_index=True)
    
    # บรรทัดที่ 248 เดิม (แก้ไขให้ทำงานได้อย่างเสถียรแล้ว)
    st.dataframe(df_final, use_container_width=True)
    
    # 📥 ปุ่มดาวน์โหลด Excel ฟอร์มจริง คอลัมน์ครบถ้วนตรงช่อง
    try:
        excel_data = build_full_excel(st.session_state.report_data)
        st.download_button(
            label="📥 ดาวน์โหลดไฟล์ Excel สำหรับส่งรายงาน (.xlsx)",
            data=excel_data,
            file_name="แบบรายงานการจับกุมต่างด้าว_ฟอร์มจริง.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการเตรียมไฟล์ดาวน์โหลด: {e}")
    
    # 🗑️ ปุ่มรีเซ็ตข้อมูลสีแดงแถบกว้าง
    if st.button("🗑️ รีเซ็ตข้อมูลตารางใหม่ทั้งหมด", type="primary", use_container_width=True):
        base_list = []
        for station in STATIONS:
            base_list.append({'สน.': station, 'ผู้ต้องหา (คน)': 0, 'สัญชาติ': '-', 'สถานที่ที่จับกุม': '-'})
        st.session_state.report_data = base_list
        st.rerun()
