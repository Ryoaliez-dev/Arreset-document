def extract_arrest_info(text):
    nationality = "ไม่พบข้อมูลสัญชาติ"
    location = "ไม่พบข้อมูลสถานที่จับกุม"
    arrest_date = "ไม่พบข้อมูลวันที่"
    
    # ลบช่องว่างส่วนเกิน
    clean_text = re.sub(r'\s+', ' ', text)
    
    # 1. ค้นหาสัญชาติ
    nat_match = re.search(r"สัญชาติ\s*([\u0e00-\u0e7fa-zA-Z]+)", clean_text)
    if nat_match:
        nationality = nat_match.group(1).strip()
        
        # 🔥 เพิ่มระบบตรวจจับและแก้ไขคำผิดจาก OCR อัตโนมัติที่นี่
        if nationality == "กัมขชา" or "กัมพ" in nationality:
            nationality = "กัมพูชา"
        elif "เมียน" in nationality or "เมียนม" in nationality:
            nationality = "เมียนมา"
        elif "ลาว" in nationality:
            nationality = "ลาว"
        elif "ไท" in nationality:
            nationality = "ไทย"
        
    # 2. ค้นหาสถานที่จับกุม
    loc_match = re.search(r"(?:สถานที่จับกุม|จับกุมได้ที่|บริเวณ)\s*(.+?)(?:\s+เมื่อ|วันที่|เวลา|พฤติการณ์|\n|$)", clean_text)
    if loc_match:
        location = loc_match.group(1).strip()
        
    # 3. ค้นหาวันที่จับกุม
    date_match = re.search(r"วันที่จับกุม\s*(\d{1,2}\s*[\u0e00-\u0e7f\.]+\s*\d{4})", clean_text)
    if date_match:
        arrest_date = date_match.group(1).strip()
    else:
        date_fallback = re.search(r"(\d{1,2}\s*[ก-ฮ]{1,3}\.[ค-ศ]\.?\s*\d{4})", clean_text)
        if date_fallback:
            arrest_date = date_fallback.group(1).strip()
        
    return nationality, location, arrest_date