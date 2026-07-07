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
# 2. ฟังก์ชันดึงข้อมูลจากเอกสาร
# ==========================================
def extract_arrest_info(text):
    nationality = "ไม่พบข้อมูลสัญชาติ"
    location = "ไม่พบข้อมูลสถานที่จับกุม"
    detected_count = 1
    
    clean_text = re.sub(r'\s+', ' ', text)
    
    if any(k in clean_text for k in ["กัมขชำ", "กัมขชา", "กัมศูชา", "กัมพูชา"]):
        nationality = "กัมพูชา"
    elif "เมียน" in clean_text or "พม่า" in clean_text:
        nationality = "เมียนมา"
    elif "ลาว" in clean_text:
        nationality = "ลาว"
        
    loc_match = re.search(r"(?:สถานที่จับกุม|สถานทีจับกุม|จับกุมได้ที่|บริเวณ|บริเาณ)\s*(.+?)(?:\s+เมื่อ|วันที่|วันที|เวลา|พฤติการณ์|เจ้าพนักงาน|\n|$)", clean_text)
    if loc_match:
        location = loc_match.group(1).strip()
        location = location.replace("บริเาณ", "บริเวณ").replace("ชมชน", "ชุมชน").replace("แเขวง", "แขวง")
        
    count_match = re.search(r"(?:จำนวน|รวม|สัญชาติ[\u0e00-\u0e7f]+\s*)\s*(\d+)\s*(?:คน|ราย|นาม)", clean_text)
    if count_match:
        detected_count = int(count_match.group(1))
    else:
        digit_match = re.search(r"(\d+)\s*(?:คน|ราย)", clean_text)
        if digit_match:
            detected_count = int(digit_match.group(1))
        
    return nationality, location, detected_count

# 🔥 ฟังก์ชันสร้างไฟล์ Excel แบบล็อกตำแหน่งช่องและคอลัมน์ตรงตามแบบฟอร์มจริงของพี่เป๊ะๆ
def build_full_excel(data_list):
    columns_list = [
        'สน.', 'ผู้ต้องหา', 'สัญชาติ', 'ผู้ต้องหา พท.ตอนใน', 'ผู้ต้องหา พท.ติดชายแดน',
        'สถานที่ที่จับกุม', 'จังหวัด', 'การลักลอบ พื้นที่ช่องทาง', 'การลักลอบ เข้ามาเอง',
        'การลักลอบ มีผู้นำเข้า', 'เดินทาง มาก่อน 1 ต.ค.06', 'หมายเหตุ'
    ]
    
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
        
    # เพิ่มแถว "รวม" สรุปยอดท้ายตาราง
    body_rows.append([
        'รวม', total_count, '', total_count, 0, '', '', '', '', '', '', ''
    ])
    
    # สร้าง DataFrame ข้อมูลหลัก
    df_body = pd.DataFrame(body_rows, columns=columns_list)
    
    # สร้างโครงสร้างแถวหัวตาราง 2 ชั้นภาษาไทย เพื่อจัดล็อกคอลัมน์ให้ตรงช่องพอดี
    header_row1 = ['สน.', 'ผู้ต้องหา', 'สัญชาติ', 'ผู้ต้องหา', '', 'สถานที่ที่จับกุม', 'จังหวัด', 'การลักลอบ', '', '', 'เดินทาง', 'หมายเหตุ']
    header_row2 = ['', '( คน )', '', 'พท.ตอนใน', 'พท.ติดชายแดน', '', '', 'พื้นที่ช่องทาง', 'เข้ามาเอง', 'มีผู้นำเข้า / นายหน้า', 'มาก่อน 1 ต.ค.06', '']
    
    # รวมหัวตารางและเนื้อหาเข้าด้วยกันอย่างเป็นระบบ
    df_final
