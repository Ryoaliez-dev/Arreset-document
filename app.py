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

# 🔥 ฟังก์ชันจัดหน้าสร้างหัวตาราง Excel 2 ชั้นให้ถูกต้องตามแบบฟอร์มจริงของพี่
def build_full_excel(data_list):
    # 1. สร้างหัวตาราง 2 ชั้นแรกเลียนแบบไฟล์ต้นฉบับ
    header_rows = [
        {
            'C0': 'สน.', 'C1': 'ผู้ต้องหา', 'C2': 'สัญชาติ', 'C3': 'ผู้ต้องหา', 'C4': '', 
            'C5': 'สถานที่ที่จับกุม', 'C6': 'จังหวัด', 'C7': 'การลักลอบ', 'C8': '', 'C9': '', 
            'C10': 'เดินทาง', 'C11': 'หมายเหตุ'
        },
        {
            'C0': '', 'C1': '( คน )', 'C2': '', 'C3': 'พท.ตอนใน', 'C4': 'พท.ติดชายแดน', 
            'C5': '', 'C6': '', 'C7': 'พื้นที่ช่องทาง', 'C8': 'เข้ามาเอง', 'C9': 'มีผู้นำเข้า / นายหน้า', 
            'C10': 'มาก่อน 1 ต.ค.06', 'C11': ''
        }
    ]
    
    total_count = 0
    body_rows = []
    
    # 2. นำข้อมูลแต่ละ สน. มาหยอดลงไป
    for row in data_list:
        count = row['ผู้ต้องหา (คน)']
        total_count += count
        
        is_empty = (row['สัญชาติ'] == '-')
        pht_in = count if not is_empty else 0
        prov = "กรุงเทพมหานคร" if not is_empty else "-"
        
        body_rows.append({
            'C0': row['สน.'],
            'C1': count if count > 0 else 0,
            'C2': row['สัญชาติ'],
            'C3': pht_in,
            'C4': 0,
            'C5': row['สถานที่ที่จับกุม'],
            'C6': prov,
            'C7': "-", 'C8': "-", 'C9': "-", 'C10': "-", 'C11': "-"
        })
        
    # 3. เพิ่มแถว "รวม" สรุปยอดท้ายตาราง
    footer_row = {
        'C0': 'รวม', 'C1': total_count, 'C2': '', 'C3': total_count, 'C4': 0,
        'C5': '', 'C6': '', 'C7': '', 'C8': '', 'C9': '', 'C10': '', 'C11': ''
    }
    
    # รวมแถวทั้งหมดเข้าด้วยกัน
    all_rows = header_rows + body_rows + [footer_row]
    
    # แปลงเป็น DataFrame โดยไม่ใช้หัวคอลัมน์ภาษาอังกฤษเดิมติดไป
    df = pd.DataFrame(all_rows)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # กำหนด header=False เพื่อให้ระบบใช้หัวตาราง 2 ชั้นที่เราเขียนขึ้นเองในแถวแรก
        df.to_excel(writer, index=False, header=False, sheet_name='Sheet1')
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
                    doc = fitz.open(stream
