import os
import re
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import platform
app = Flask(__name__)

# Configurar ruta de Tesseract en Windows
if platform.system() == 'Windows':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# Permitir peticiones desde HTML local
CORS(app)

@app.route('/')
def index():
    return send_file('separador_resoluciones.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    if 'pdf' not in request.files:
        return jsonify({"error": "No pdf file uploaded"}), 400
        
    file = request.files['pdf']
    range_start = request.form.get('rangeStart', '')
    range_end = request.form.get('rangeEnd', '')
    global_year = request.form.get('year', '')
    
    if not global_year:
        global_year = "2024" # Default
        
    temp_path = "temp_uploaded.pdf"
    file.save(temp_path)
    
    starts = []
    blanks = []
    
    try:
        doc = fitz.open(temp_path)
        total_text_found = 0

        for i in range(len(doc)):
            page = doc[i]
            r = page.rect
            
            # REGLA CRÍTICA: Buscar siempre SOLO en el 40% superior de la página.
            # Esto evita que una palabra en medio de la resolución inicie una nueva.
            clip_rect = fitz.Rect(r.x0, r.y0, r.x1, r.y0 + (r.height * 0.40))
            
            # Texto digital extraíble (solo mitad superior)
            text = page.get_textbox(clip_rect).upper()
            
            # Check if page is blank using low DPI size heuristic
            is_blank = False
            if len(text.strip()) < 15:
                pix_small = page.get_pixmap(dpi=30)
                if len(pix_small.tobytes("png")) < 3500:
                    is_blank = True
                    print(f"Página {i+1} detectada como BLANCA por tamaño de imagen comprimida.")
                    blanks.append(i + 1)
            
            # Si la página aparentemente no tiene texto (PDF escaneado) y no es blanca
            if not is_blank and len(text.strip()) < 15:
                print(f"Página {i+1} no tiene texto digital. Intentando Leer Visualmente (OCR)...")
                try:
                    # OPTIMIZACIÓN DE LECTURA (Escala de Grises y 300 DPI)
                    pix = page.get_pixmap(dpi=300, clip=clip_rect, colorspace=fitz.csGRAY)
                    img_data = pix.tobytes("png")
                    img = Image.open(io.BytesIO(img_data))
                    
                    # Motor de reconocimiento de letras
                    text = pytesseract.image_to_string(img, lang='spa+eng', config='--psm 3').upper()
                    print(f"  → Letras extraídas visualmente: {len(text)}")
                except Exception as ex:
                    print("Error detectando texto en imagen:", ex)
                    try:
                        # Fallback simple
                        text = pytesseract.image_to_string(img).upper()
                    except:
                        pass
            
            total_text_found += len(text)
            
            is_start = False
            number = None
            year = global_year
            
            # Limpiar saltos de línea para facilitar Regex
            text_linear = re.sub(r'\s+', ' ', text)
            
            def clean_num(n):
                # Extrae puramente los dígitos (elimina espacios o guiones internos)
                return re.sub(r'[^\d]', '', n)
            
            # Buscar "RESOLUCION DIRECTORAL N 2201-2007"
            # (\d[\d\s_-]{0,6}\d|\d{1,5}) fuerza a que SEAN dígitos, pero permite espacios entre ellos (ej: "22 13")
            match = re.search(r'(?:RE[\w50]{3,10}CI[OÓ0]N(?:[\s_]+DIRECTORAL)?|R\.?[\s_]*D\.?)[\s_.,°º\'"-]*(?:N[°ºro.\s_\-]+)?(\d[\d\s_-]{0,6}\d|\d{1,5})[\s_.-]*(\d{4})?', text_linear)
            if match:
                is_start = True
                number = clean_num(match.group(1))
                if match.group(2):
                    year = match.group(2)
            else:
                match_dir = re.search(r'DIRECTORAL[\s_.,°º\'"-]*(?:N[°ºro.\s_\-]+)?(\d[\d\s_-]{0,6}\d|\d{1,5})[\s_.-]*(\d{4})?', text_linear)
                if match_dir and not is_start:
                    is_start = True
                    number = clean_num(match_dir.group(1))
                    if match_dir.group(2):
                        year = match_dir.group(2)
                elif re.search(r'RE[\w50]{3,10}CI[OÓ0]N', text_linear) and ("VISTO" in text_linear or "CONSIDERANDO" in text_linear):
                    is_start = True
                    match_num = re.search(r'(?:N|NRO)[°º.\s_\-]+(\d[\d\s_-]{0,6}\d|\d{1,5})', text_linear)
                    if match_num:
                        number = clean_num(match_num.group(1))
                    else:
                        print("Fallo detectar número exacto en OCR, buscando cualquier cifra grande...")
                        match_num = re.search(r'\b([0-9]{3,5})\b', text_linear)
                        if match_num:
                            number = match_num.group(1)
            
            if is_start:
                starts.append({
                    "page": i + 1,
                    "isStart": True,
                    "number": number,
                    "year": year
                })
                
        doc.close()
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        # Si el texto total encontrado es casi 0, significa que el PDF es escaneado
        if total_text_found < 100:
            return jsonify({
                "error": "El PDF es completamente escaneado y el motor de texto no pudo leerlo. Usará rango o fallback uniforme.",
                "starts": [],
                "blanks": blanks
            }), 400
            
        return jsonify({"starts": starts, "blanks": blanks})

    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Iniciando servidor de Análisis PDF...")
    app.run(port=5000, debug=True)
