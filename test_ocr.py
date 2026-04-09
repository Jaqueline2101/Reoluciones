import time
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

print("Iniciando prueba de Tesseract...")
start = time.time()
img = Image.new('RGB', (800, 400), color = (255, 255, 255))
text = pytesseract.image_to_string(img)
print(f"Prueba completada en {time.time() - start:.2f} segundos. Resultado: '{text.strip()}'")
