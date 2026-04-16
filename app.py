import os
import re
import uuid
import threading
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import platform
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Configurar ruta de Tesseract en Windows
if platform.system() == 'Windows':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

CORS(app)

# Configurar Gemini
gemini_model = None
api_key = os.getenv("GEMINI_API_KEY")
if api_key and api_key.strip() != "" and "aqui_va_tu_clave_de_gemini" not in api_key:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Model Gemini cargado correctamente.")
    except Exception as e:
        print("Error cargando Gemini:", e)

# Diccionario global de tareas: { task_id: { "status": "processing", "progress": 0, "starts": [], "blanks": [], "error": None } }
tasks = {}

@app.route('/')
def index():
    return send_file('separador_resoluciones.html')

def ask_gemini_for_number(img_bytes, year_context):
    if not gemini_model: return None, None
    try:
        image = Image.open(io.BytesIO(img_bytes))
        prompt = f"Analiza detalladamente este encabezado. Extrae SOLO el número de la resolución. " \
                 f"Formato estricto de respuesta sin más texto: NUM: [numero]. Por ejemplo: NUM: 1200. " \
                 f"Si ves un año, reportalo como AÑO: [año]. O si no lo hallas responde NUM: DESCONOCIDO"
        response = gemini_model.generate_content([prompt, image])
        txt = response.text.upper()
        
        num_match = re.search(r'NUM:\s*(\d[\d\s_-]*\d|\d{1,5})', txt)
        year_match = re.search(r'AÑO:\s*(\d{4})', txt)
        
        number = None
        year = None
        if num_match:
            number = re.sub(r'[^\d]', '', num_match.group(1))
        if year_match:
            year = year_match.group(1)
            
        return number, year
    except Exception as e:
        print("Gemini API falló:", e)
        return None, None

def process_pdf(task_id, temp_path, range_start, range_end, global_year):
    tasks[task_id]['status'] = 'processing'
    tasks[task_id]['progress'] = 0
    starts = []
    blanks = []
    
    try:
        doc = fitz.open(temp_path)
        total_pages = len(doc)
        total_text_found = 0

        for i in range(total_pages):
            page = doc[i]
            r = page.rect
            
            # Buscar siempre SOLO en el 40% superior de la página
            clip_rect = fitz.Rect(r.x0, r.y0, r.x1, r.y0 + (r.height * 0.40))
            
            text = page.get_textbox(clip_rect).upper()
            is_blank = False
            
            if len(text.strip()) < 15:
                pix_small = page.get_pixmap(dpi=30)
                if len(pix_small.tobytes("png")) < 3500:
                    is_blank = True
                    blanks.append(i + 1)
            
            # Si no es blanca, pasamos a procesar el OCR
            pix_ocr = None
            if not is_blank and len(text.strip()) < 15:
                pix_ocr = page.get_pixmap(dpi=300, clip=clip_rect, colorspace=fitz.csGRAY)
                img_data = pix_ocr.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                try:
                    text = pytesseract.image_to_string(img, lang='spa+eng', config='--psm 3').upper()
                except:
                    text = pytesseract.image_to_string(img).upper()
            
            total_text_found += len(text)
            
            # Reiniciar estado para cada página
            is_start = False
            number = None
            year = global_year
            
            # Fuerte indicador para la PÁGINA 1
            if i == 0:
                is_start = True
            
            # Limpiar el texto lineal
            text_linear = re.sub(r'\s+', ' ', text)
            
            def clean_num(n):
                return re.sub(r'[^\d]', '', n)
            
            # Regex ultra tolerante para caracteres rotos como 
            match1 = re.search(r'(?:RE[A-Z0-9]+CI[OÓ0]N|RESOLUCION|RESOLUCI.N)[\s_]*(?:DIRECTORAL)?[\s_.,°º\'"\-]*(?:N(?:[°ºro.\w\s_\-]+)?)?(\d[\d\s_-]{0,6}\d|\d{1,5})[\s_.-]*(\d{4})?', text_linear)
            match2 = re.search(r'DIRECTORAL[\s_.,°º\'"\-]*(?:N(?:[°ºro.\w\s_\-]+)?)?(\d[\d\s_-]{0,6}\d|\d{1,5})[\s_.-]*(\d{4})?', text_linear)
            
            # Condicion relajada de inicio de resolucion
            if match1:
                is_start = True
                number = clean_num(match1.group(1))
                if match1.group(2): year = match1.group(2)
            elif match2:
                is_start = True
                number = clean_num(match2.group(1))
                if match2.group(2): year = match2.group(2)
            elif re.search(r'(?:RE[\w50]+CI[OÓ0]N|RESOLUCI.N|DIRECTORAL|VISTO|CONSIDERANDO)', text_linear):
                is_start = True
                match_num = re.search(r'(?:N|NRO|N)[°º.\s_\-]+(\d[\d\s_-]{0,6}\d|\d{1,5})', text_linear)
                if match_num:
                    number = clean_num(match_num.group(1))
                else:
                    match_num = re.search(r'\b([0-9]{3,5})\b', text_linear)
                    if match_num: number = match_num.group(1)

            # --- GEMINI FALLBACK / ENHANCEMENT ---
            # Si parece el inicio (incluyendo siempre la página 1) pero el Regex no extrajo el numero bien, invocamos Gemini
            if is_start and (not number or len(number) < 3):
                if gemini_model:
                    if not pix_ocr: pix_ocr = page.get_pixmap(dpi=300, clip=clip_rect, colorspace=fitz.csGRAY)
                    img_data = pix_ocr.tobytes("jpeg")
                    g_num, g_year = ask_gemini_for_number(img_data, year)
                    if g_num: number = g_num
                    if g_year: year = g_year
                else:
                    print("Gemini no disponible, número no detectado con exactitud.")

            if is_start:
                starts.append({
                    "page": i + 1,
                    "isStart": True,
                    "number": number,
                    "year": year
                })

            # Actualizar progreso
            tasks[task_id]['progress'] = int(((i + 1) / total_pages) * 100)

        doc.close()
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        tasks[task_id]['starts'] = starts
        tasks[task_id]['blanks'] = blanks
        
        if total_text_found < 100 and len(starts) == 0:
            tasks[task_id]['error'] = "El PDF fue ilegible, o Gemini no esta activo para las imagenes."
            tasks[task_id]['status'] = 'failed'
        else:
            tasks[task_id]['status'] = 'completed'

    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        tasks[task_id]['status'] = 'failed'
        tasks[task_id]['error'] = str(e)


@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'pdf' not in request.files:
         return jsonify({"error": "No pdf file uploaded"}), 400
        
    file = request.files['pdf']
    range_start = request.form.get('rangeStart', '')
    range_end = request.form.get('rangeEnd', '')
    global_year = request.form.get('year', '')
    
    if not global_year: global_year = "2024"
        
    task_id = str(uuid.uuid4())
    temp_path = f"temp_{task_id}.pdf"
    file.save(temp_path)
    
    tasks[task_id] = {
        "status": "queued",
        "progress": 0,
        "starts": [],
        "blanks": [],
        "error": None
    }
    
    # Inicia proceso en segundo plano
    thread = threading.Thread(target=process_pdf, args=(task_id, temp_path, range_start, range_end, global_year))
    thread.daemon = True
    thread.start()
    
    return jsonify({"task_id": task_id}), 202

@app.route('/api/status/<task_id>', methods=['GET'])
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(tasks[task_id])

@app.route('/api/extract_name', methods=['POST'])
def extract_name():
    if 'image' not in request.files:
         return jsonify({"error": "No image uploaded"}), 400
    
    file = request.files['image']
    img_bytes = file.read()
    
    img = Image.open(io.BytesIO(img_bytes)).convert("L")
    
    try:
        text = pytesseract.image_to_string(img, lang='spa+eng', config='--psm 3').upper()
    except:
        text = pytesseract.image_to_string(img).upper()
        
    text_linear = re.sub(r'\s+', ' ', text)
    
    def clean_num(n):
        return re.sub(r'[^\d]', '', n)
    
    number = None
    year = "2024" # Default guess
    
    match1 = re.search(r'(?:RE[A-Z0-9]+CI[OÓ0]N|RESOLUCION|RESOLUCI.N)[\s_]*(?:DIRECTORAL)?[\s_.,°º\'"\-]*(?:N(?:[°ºro.\w\s_\-]+)?)?(\d[\d\s_-]{0,6}\d|\d{1,5})[\s_.-]*(\d{4})?', text_linear)
    match2 = re.search(r'DIRECTORAL[\s_.,°º\'"\-]*(?:N(?:[°ºro.\w\s_\-]+)?)?(\d[\d\s_-]{0,6}\d|\d{1,5})[\s_.-]*(\d{4})?', text_linear)
    match3 = re.search(r'(?:N|NRO|N)[°º.\s_\-]+(\d[\d\s_-]{0,6}\d|\d{1,5})', text_linear)
    
    if match1:
        number = clean_num(match1.group(1))
        if match1.group(2): year = match1.group(2)
    elif match2:
        number = clean_num(match2.group(1))
        if match2.group(2): year = match2.group(2)
    elif match3:
        number = clean_num(match3.group(1))

    # Forzar Gemini si el número es dudoso
    if not number or len(number) < 3:
        if gemini_model:
            g_num, g_year = ask_gemini_for_number(img_bytes, year)
            if g_num: number = g_num
            if g_year: year = g_year

    return jsonify({"number": number or "", "year": year})

if __name__ == '__main__':
    print("Iniciando servidor de Análisis PDF (Modo Interactivo + Gemini AI)...")
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
