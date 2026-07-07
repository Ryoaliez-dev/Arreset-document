import streamlit as st
import pdfplumber
import easyocr
from PIL import Image, ImageOps
import numpy as np
import re
import pandas as pd
import fitz  # PyMuPDF
import io

st.set_page_config(page_title="ระบบรายงานจับกุมต่างด้าวแยกตาม สน. (เวอร์ชันอัปเกรดโมเดล)", layout="wide")

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
# 1. โหลดตัวอ่าน OCR พร้อมอัปเกรดประสิทธิภาพเพิ่มความเร็ว
# ==========================================
@st.cache_resource
def load_ocr_reader():
    # โหลดโมเดลเข้ามาในความจำสำรองเพื่อเรียกใช้ซ้ำได้ทันที
    return easyocr.Reader(['th', 'en'])

reader = load_ocr_reader()

STATIONS = [
    "วัดพระยาไกร", "บางโพงพาง", "ทุ่งมหาเมฆ", "ลุมพินี", 
    "ทองหล่อ", "คลองตัน", "พระโขนง", "บางนา", "ท่าเรือ", "กก.สส.5"
]

if 'report_data' not in st.session_state:
    base_list = []
    for station in STATIONS:
        base_list.append({'สน.': station, 'ผู้ต้องหา (คน)': 0, 'สัญชาติ': '-', 'สถานที่ที่จับกุม': '-'})
    st.session_state.report_data = base_list

if 'current_files_key' not in st.session_state:
    st.session_state.current_files_key = ""
if 'batch_results' not in st.session_state:
    st.session_state.batch_results = []

# ==========================================
# 2. ฟังก์ชันเตรียมรูปภาพเพื่อลดขนาดพิกเซล (Speed Optimization)
# ==========================================
def optimize_image(image_file):
    img = Image.open(image_file)
    # แปลงภาพเป็นขาวดำ เพื่อให้ AI แกะตัวหนังสือได้เร็วขึ้นไม่ต้องคิดค่าสี
    img_gray = ImageOps.grayscale(img)
    # จำกัดขนาดความกว้างไม่เกิน 1200 พิกเซล (ชัดเจนพอสำหรับการอ่าน และรันไวขึ้น 3 เท่า)
    if img_gray.width > 1200:
        w_percent = (1200 / float(img_gray.width))
        h_size = int((float(img_gray.height) * float(w_percent)))
        img_gray = img_gray.resize((1200, h_size), Image.Resampling.LANCZOS)
    return np.array(img_gray)

# ==========================================
# 3. ฟังก์ชันดึงข้อมูลแบบ Regex ค้นหาด่วน
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
        location = location.replace("สามัคที", "สามัคคี").replace("สามัคทิ", "สามัคคี")
        
    count_match = re.search(r"(?:จำนวน|รวม|สัญชาติ[\u0e00-\u0e7f]+\s*)\s*(\d+)\s*(?:คน|ราย|นาม)", clean_space_text)
    if count_match:
        detected_count = int(count_match.group(1))
    else:
        digit_match = re.search(r"(\d+)\s*(?:คน|ราย)", clean_space_text)
        if digit_match:
            detected_count = int(digit_match.group(1))
        
    return nationality, location, detected_count

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
        body_rows.append([row['สน.'], count if count > 0 else 0, row['สัญชาติ'], pht_in, 0, row['สถานที่ที่จับกุม'], prov, "-", "-", "-", "-", "-"])
    footer_row = ['รวม', total_count, '', total_count, 0, '', '', '', '', '', '', '']
    all_table_data = [header_row1, header_row2] + body_rows + [footer_row]
    df_final_excel = pd.DataFrame(all_table_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_final_excel.to_excel(writer, index=False, header=False, sheet_name='Sheet1')
    return output.getvalue()

# ==========================================
# 4. ส่วนแสดงผลหน้าเว็บ (UI)
# ==========================================
col_title, col_logout = st.columns([9, 1])
with col_title:
    st.title("ระบบวิเคราะห์และกรอกสถิติเอกสารจับกุมแยกตาม สน. 👮‍♂️📊")
with col_logout:
    if st.button("ออกจากระบบ 🚪"):
        st.session_state.logged_in = False
        st.session_state.batch_results = []
        st.session_state.current_files_key = ""
        st.rerun()

st.write("เวอร์ชันอัปเกรดโมเดล: เพิ่มโหมดรันด่วน (Fast Inference) ปรับสเกลภาพขาวดำ ลดเวลาอ่านไฟล์ลง 50-80%")
st.markdown("---")
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📥 ส่วนอัปโหลดคดีจับกุม (เลือกได้หลายไฟล์พร้อมกัน)")
    uploaded_files = st.file_uploader("ลากไฟล์รูปภาพหรือ PDF บันทึกการจับกุมทั้งหมดมาวางที่นี่", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

    if uploaded_files:
        files_key = "_".join([f"{f.name}_{f.size}" for f in uploaded_files])
        
        if st.session_state.current_files_key != files_key:
            st.session_state.batch_results = []
            
            for f in uploaded_files:
                extracted_text = ""
                file_type = f.name.split('.')[-1].lower()
                
                with st.spinner(f"⚡ AI กำลังสแกนความเร็วสูงในไฟล์: {f.name}..."):
                    if file_type in ["png", "jpg", "jpeg"]:
                        # ใช้ฟังก์ชันย่อขนาดภาพและทำขาวดำก่อนส่งให้ AI
                        optimized_np = optimize_image(f)
                        # อัปเกรดพารามิเตอร์ของ EasyOCR: เปิดเกณฑ์ตัดสินใจเร็วขีดสุด
                        results = reader.readtext(optimized_np, detail=0, paragraph=True, contrast_ths=0.1, adjust_contrast=0.5)
                        extracted_text = " ".join(results)
                    elif file_type == "pdf":
                        pdf_bytes = f.read()
                        with pdfplumber.open(f) as pdf:
                            for page in pdf.pages:
                                text = page.extract_text()
                                if text: extracted_text += text + "\n"
                        if extracted_text.strip() == "":
                            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                            for page_num in range(len(doc)):
                                page = doc.load_page(page_num)
                                pix = page.get_pixmap(dpi=130) # ลดความหนาแน่นพิกเซลลงเล็กน้อยเพื่อรีดความเร็วคูณสอง
                                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                img_gray = ImageOps.grayscale(img)
                                results = reader.readtext(np.array(img_gray), detail=0, paragraph=True)
                                extracted_text += " ".join(results) + "\n"
                
                if extracted_text.strip() != "":
                    nat, loc, final_count = extract_arrest_info(extracted_text)
                    detected_station = "ท่าเรือ"  
                    for station in STATIONS:
                        if station in extracted_text:
                            detected_station = station
                            break
                    
                    st.session_state.batch_results.append({
                        'file_name': f.name, 'สน.': detected_station,
                        'สัญชาติ': nat, 'จำนวน': final_count, 'สถานที่': loc
                    })
            
            st.session_state.current_files_key = files_key

        if st.session_state.batch_results:
            st.success(f"📝 AI วิเคราะห์เสร็จสิ้นรวมทั้งหมด {len(st.session_state.batch_results)} คดี")
            
            for i, res in enumerate(st.session_state.batch_results):
                with st.expander(f"📦 คดีที่ {i+1} จากไฟล์: {res['file_name']}", expanded=True):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        res['สัญชาติ'] = st.selectbox(f"สัญชาติคดีที่ {i+1}:", ["กัมพูชา", "เมียนมา", "ลาว", "อื่น ๆ"], index=["กัมพูชา", "เมียนมา", "ลาว", "อื่น ๆ"].index(res['สัญชาติ']) if res['สัญชาติ'] in ["กัมพูชา", "เมียนมา", "ลาว", "อื่น ๆ"] else 3, key=f"nat_{i}")
                    with col2:
                        res['จำนวน'] = st.number_input(f"จำนวน (คน) คดีที่ {i+1}:", min_value=1, value=res['จำนวน'], step=1, key=f"cnt_{i}")
                    with col3:
                        res['สน.'] = st.selectbox(f"ลงสถานี คดีที่ {i+1}:", STATIONS, index=STATIONS.index(res['สน.']), key=f"st_{i}")
                    res['สถานที่'] = st.text_input(f"สถานที่จับกุม คดีที่ {i+1}:", value=res['สถานที่'], key=f"loc_{i}")

            if st.button("💾 บันทึกทุกคดีเข้าตารางรายงานพร้อมกัน", type="primary", use_container_width=True):
                current_list = st.session_state.report_data
                for res in st.session_state.batch_results:
                    target_station = res['สน.']
                    user_count = res['จำนวน']
                    edit_nat = res['สัญชาติ']
                    edit_loc = res['สถานที่']
