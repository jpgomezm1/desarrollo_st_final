from flask import Flask, render_template, request, jsonify, url_for
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import time
import random
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import re
from datetime import datetime
import pytz

# Importar librerías para leer el archivo Excel
from werkzeug.utils import secure_filename

# Importar los scrapers
from scrapper_meli import MeliVehicleAnalyzer
from scrapper_facebook import VehicleMarketplaceAnalyzer
# NOTA: Se eliminó la importación global de scrapper_fb_images para evitar que se ejecute automáticamente.
# Se importará de forma local en la rama correspondiente de la solicitud.

# Importar la función para procesar Excel masivo
from mass_processor import process_excel_file

import logging

# Configuración básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_url_path='', static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# =====================
# Configuración general
# =====================

# API Key de Anthropic (actualiza con la tuya)
ANTHROPIC_API_KEY = "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"

# Configuración para UltraMSG (WhatsApp)
ULTRAMSG_TOKEN = "b4azkwiyillsz4dr"
ULTRAMSG_INSTANCE_ID = "instance106153"

# =====================================
# Funciones de ayuda y scraping general
# =====================================

def get_headers():
    """Genera headers aleatorios para evitar bloqueos."""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
    ]
    return {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3',
        'Connection': 'keep-alive',
    }

def extract_images_from_json(script_content):
    """Extrae URLs de imágenes desde contenido JSON encontrado en scripts."""
    try:
        data = json.loads(script_content)
        images = []
        possible_paths = [
            data.get('props', {}).get('pageProps', {}).get('initialData', {}).get('pictures', []),
            data.get('props', {}).get('pageProps', {}).get('images', []),
            data.get('images', []),
            data.get('pictures', [])
        ]
        for path in possible_paths:
            if isinstance(path, list) and path:
                images.extend([img.get('url') or img.get('src') for img in path if img])
        return images
    except:
        return []

def scrape_images(url, max_retries=3, delay=1):
    """
    Extrae imágenes de la URL de Mercado Libre usando varios métodos
    y devuelve un dict con la lista de imágenes.
    """
    logger.info(f"Iniciando extracción de imágenes para URL: {url}")
    images = set()
    retries = 0
    while retries < max_retries:
        try:
            logger.info(f"Intento #{retries+1} de obtener contenido de {url}")
            response = requests.get(url, headers=get_headers(), allow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Método 1: Buscar imágenes <img> con class='ui-pdp-image'
            logger.info("Buscando <img> con class='ui-pdp-image'")
            img_elements = soup.find_all('img', class_='ui-pdp-image')
            for img in img_elements:
                src = img.get('src') or img.get('data-src')
                if src and not src.startswith('data:'):
                    images.add(src)

            # Método 2: Scripts con contenido JSON
            logger.info("Buscando scripts con contenido JSON para extraer imágenes")
            scripts = soup.find_all('script', type='application/json')
            for script in scripts:
                if script.string:
                    json_images = extract_images_from_json(script.string)
                    images.update(json_images)

            # Método 3: Atributos data-zoom
            logger.info("Buscando atributos 'data-zoom'")
            zoom_elements = soup.find_all(attrs={'data-zoom': True})
            for elem in zoom_elements:
                src = elem.get('data-zoom')
                if src:
                    images.add(src)

            if images:
                logger.info(f"Se encontraron {len(images)} imágenes en este intento.")
                break
        except requests.RequestException as e:
            logger.error(f"Error de requests: {e}")
            retries += 1
            if retries < max_retries:
                time.sleep(delay * retries)
            continue
        except Exception as e:
            logger.error(f"Error inesperado al extraer imágenes: {e}")
            break

    clean_images = []
    for img_url in images:
        if img_url and not img_url.startswith('data:'):
            full_url = urljoin(url, img_url)
            clean_images.append(full_url)
            if len(clean_images) == 20:
                break

    response_data = {
        "status": "success" if clean_images else "error",
        "total_images": len(clean_images),
        "images": clean_images,
        "execution_time": None
    }
    logger.info(f"Extracción finalizada con {len(clean_images)} imágenes limpias.")
    return response_data

# =====================================
# Funciones para enviar mensajes por WhatsApp a través de UltraMSG
# =====================================

def enviar_mensaje(token, instance_id, telefono, text):
    """Envía un mensaje de texto a través de la API de UltraMSG (WhatsApp)."""
    logger.info(f"Enviando mensaje de texto a WhatsApp {telefono}")
    url_api = f"https://api.ultramsg.com/{instance_id}/messages/chat"
    payload = {"token": token, "to": telefono, "body": text}
    try:
        response = requests.post(url_api, data=payload)
        response.raise_for_status()
        resp_json = response.json()
        if resp_json.get("error"):
            print(f"Error al enviar mensaje WhatsApp: {resp_json}")
            logger.error(f"Error al enviar mensaje WhatsApp: {resp_json}")
            return False
        print(f"Mensaje WhatsApp enviado exitosamente: {resp_json}")
        logger.info(f"Mensaje WhatsApp enviado exitosamente: {resp_json}")
        return True
    except Exception as e:
        print(f"Excepción al enviar mensaje WhatsApp: {e}")
        logger.exception(f"Excepción al enviar mensaje WhatsApp: {e}")
        return False

def enviar_imagen(token, instance_id, telefono, image_url, caption=""):
    """Envía una imagen a través de la API de UltraMSG (WhatsApp)."""
    logger.info(f"Enviando imagen a WhatsApp {telefono}, URL: {image_url}")
    url_api = f"https://api.ultramsg.com/{instance_id}/messages/image"
    payload = {"token": token, "to": telefono, "image": image_url, "caption": caption}
    try:
        response = requests.post(url_api, data=payload)
        response.raise_for_status()
        resp_json = response.json()
        if resp_json.get("error"):
            print(f"Error al enviar imagen WhatsApp: {resp_json}")
            logger.error(f"Error al enviar imagen WhatsApp: {resp_json}")
            return False
        print(f"Imagen WhatsApp enviada exitosamente: {resp_json}")
        logger.info(f"Imagen WhatsApp enviada exitosamente: {resp_json}")
        return True
    except Exception as e:
        print(f"Excepción al enviar imagen WhatsApp: {e}")
        logger.exception(f"Excepción al enviar imagen WhatsApp: {e}")
        return False

# =====================================
# Parsear texto de Claude
# =====================================

def parse_analysis_text(analysis_text):
    """
    Parsea el texto devuelto por Claude y extrae:
      - car_name
      - model
      - sale_price
      - post_price
    """
    logger.info("Iniciando parseo del texto de análisis")
    car_name = ""
    model = ""
    sale_price = None

    lines = analysis_text.splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith("🚘 "):
            car_name = line.replace("🚘 ", "").strip()
        elif "➖Modelo:" in line:
            model_part = line.split("➖Modelo:")[1].strip()
            model = model_part
        elif "➖Precio:" in line:
            price_part = line.split("➖Precio:")[1].strip()
            price_str = price_part.replace("$", "").replace(".", "").replace(",", "").strip()
            try:
                sale_price = int(price_str)
            except:
                pass

    post_price = None
    if sale_price:
        post_price = int(round(sale_price / 1.04))

    logger.info(f"Texto parseado. car_name={car_name}, model={model}, sale_price={sale_price}, post_price={post_price}")
    return {
        "car_name": car_name,
        "model": model,
        "sale_price": sale_price if sale_price else "",
        "post_price": post_price if post_price else ""
    }

# =====================================
# Buscar Franquicia en "Comerciales" basado en el número de teléfono
# =====================================

def get_franquicia_by_phone(phone_number):
    """
    Busca en 'Comerciales' la franquicia asociada a un phone.
    Se utiliza la hoja "Comerciales" y se espera encontrar una columna "Franquicia".
    """
    logger.info(f"Buscando franquicia para el teléfono {phone_number} en la hoja 'Comerciales'")
    sheet_id = "1u4cuP7lDf6hRex95rr64y5a10RvBi81Y-tLDeKOPxck"
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    credentials_path = os.path.join(os.path.dirname(__file__), "creds-carros.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
    client = gspread.authorize(creds)
    try:
        sheet = client.open_by_key(sheet_id)
        worksheet = sheet.worksheet("Comerciales")

        all_values = worksheet.get_all_values()
        if not all_values:
            print("La pestaña 'Comerciales' está vacía.")
            logger.warning("La pestaña 'Comerciales' está vacía.")
            return None

        headers = [h.strip() for h in all_values[0]]
        if "Phone" not in headers or "Franquicia" not in headers:
            print("No se encontró la columna 'Phone' o 'Franquicia' en 'Comerciales'.")
            logger.error("No se encontró la columna 'Phone' o 'Franquicia' en 'Comerciales'.")
            return None

        phone_idx = headers.index("Phone")
        franquicia_idx = headers.index("Franquicia")

        data_rows = all_values[1:] if len(all_values) > 1 else []
        for row in data_rows:
            if len(row) > phone_idx:
                phone_in_sheet = row[phone_idx].strip()
                if phone_in_sheet == phone_number:
                    if len(row) > franquicia_idx:
                        logger.info(f"Franquicia encontrada: {row[franquicia_idx].strip()}")
                        return row[franquicia_idx].strip()
        logger.info("No se encontró franquicia para ese teléfono.")
        return None
    except Exception as e:
        print(f"Error leyendo 'Comerciales' para franquicia: {e}")
        logger.exception(f"Error leyendo 'Comerciales' para franquicia: {e}")
        return None

# =====================================
# Función auxiliar para verificar si un vehículo ya fue captado
# =====================================

def check_vehicle_captado(url_to_check):
    """
    Verifica si la URL ya fue captada en la hoja 'Captaciones'.
    Retorna el nombre del comercial que captó el vehículo si es captado, de lo contrario None.
    """
    logger.info(f"Verificando si la URL ya fue captada: {url_to_check}")
    sheet_id = "1u4cuP7lDf6hRex95rr64y5a10RvBi81Y-tLDeKOPxck"
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    credentials_path = os.path.join(os.path.dirname(__file__), "creds-carros.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
    client = gspread.authorize(creds)
    try:
        sheet = client.open_by_key(sheet_id)
        worksheet = sheet.worksheet("Captaciones")
        all_values = worksheet.get_all_values()
        if not all_values:
            return None
        headers = [col.strip() for col in all_values[0]]
        if "URL" not in headers or "Status" not in headers or "Comercial" not in headers:
            return None
        url_idx = headers.index("URL")
        status_idx = headers.index("Status")
        comm_idx = headers.index("Comercial")
        data_rows = all_values[1:] if len(all_values) > 1 else []
        for row in data_rows:
            if len(row) > url_idx and row[url_idx] == url_to_check:
                if len(row) > status_idx and row[status_idx] == "Vehiculo Captado":
                    if len(row) > comm_idx:
                        return row[comm_idx]
                    else:
                        return None
        return None
    except Exception as e:
        logger.exception(f"Error al verificar captación en la hoja: {e}")
        return None

# =====================================
# Registrar en "Captaciones"
# =====================================

def process_url_in_google_sheet(url_to_check, commercial_name, phone_number,
                                date_value="", car_name="", model="",
                                source="", post_price="", sale_price=""):
    """
    Inserta/actualiza una fila en "Captaciones" con columnas:
      URL | Status | Comercial | Phone | Date | Car Name | Model | Source | Post Price | Sale Price
    """
    logger.info(f"Procesando registro en hoja 'Captaciones' para URL: {url_to_check}")
    sheet_id = "1u4cuP7lDf6hRex95rr64y5a10RvBi81Y-tLDeKOPxck"
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

    credentials_path = os.path.join(os.path.dirname(__file__), "creds-carros.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
    client = gspread.authorize(creds)

    try:
        sheet = client.open_by_key(sheet_id)
        worksheet = sheet.worksheet("Captaciones")

        all_values = worksheet.get_all_values()
        if not all_values:
            raise Exception("La hoja 'Captaciones' no tiene ni una fila de encabezados.")

        headers = [col.strip() for col in all_values[0]]
        required_cols = ["URL","Status","Comercial","Phone","Date",
                         "Car Name","Model","Source","Post Price","Sale Price"]
        for col in required_cols:
            if col not in headers:
                raise Exception(f"No se encontró la columna '{col}' en 'Captaciones'.")

        url_idx = headers.index("URL")
        status_idx = headers.index("Status")
        comm_idx = headers.index("Comercial")
        phone_idx = headers.index("Phone")
        date_idx = headers.index("Date")
        cname_idx = headers.index("Car Name")
        model_idx = headers.index("Model")
        source_idx = headers.index("Source")
        pprice_idx = headers.index("Post Price")
        sprice_idx = headers.index("Sale Price")

        data_rows = all_values[1:] if len(all_values) > 1 else []
        existing_urls = [row[url_idx] for row in data_rows if len(row) > url_idx]

        if url_to_check in existing_urls:
            row_num = existing_urls.index(url_to_check) + 2  # +2 por encabezado
            # Actualizar
            logger.info("La URL ya existe en la hoja, se actualizará la información.")
            worksheet.update_cell(row_num, date_idx+1, date_value)
            worksheet.update_cell(row_num, cname_idx+1, car_name)
            worksheet.update_cell(row_num, model_idx+1, model)
            worksheet.update_cell(row_num, source_idx+1, source)
            worksheet.update_cell(row_num, pprice_idx+1, post_price)
            worksheet.update_cell(row_num, sprice_idx+1, sale_price)

            status_cell = worksheet.cell(row_num, status_idx+1).value
            if not status_cell:
                worksheet.update_cell(row_num, status_idx+1, "Vehiculo Captado")
                worksheet.update_cell(row_num, comm_idx+1, commercial_name)
                worksheet.update_cell(row_num, phone_idx+1, phone_number)
                return "Actualizado y asignado 'Vehiculo Captado'."
            elif status_cell == "Vehiculo Captado":
                captured_by = worksheet.cell(row_num, comm_idx+1).value
                return f"El vehiculo ya fue captado por: {captured_by}"
            else:
                return f"Actualizado con estatus actual: {status_cell}."
        else:
            # Crear nueva fila
            logger.info("La URL no existe en la hoja, se creará un nuevo registro.")
            new_row = [""] * len(headers)
            new_row[url_idx] = url_to_check
            new_row[status_idx] = "Vehiculo Captado"
            new_row[comm_idx] = commercial_name
            new_row[phone_idx] = phone_number
            new_row[date_idx] = date_value
            new_row[cname_idx] = car_name
            new_row[model_idx] = model
            new_row[source_idx] = source
            new_row[pprice_idx] = post_price
            new_row[sprice_idx] = sale_price
            worksheet.append_row(new_row)
            return "Nueva URL captada y agregada."
    except Exception as e:
        logger.exception(f"Error al procesar la hoja 'Captaciones': {str(e)}")
        raise Exception(f"Error al procesar la hoja 'Captaciones': {str(e)}")

# =====================================
# Registrar en "Peticiones" (Nueva funcionalidad)
# =====================================

def log_peticion_in_google_sheet(commercial_name, date_value, hora_peticion, cost, franquicia, resultado, input_tokens, output_tokens, tiempo_ejecucion):
    """
    Inserta una nueva fila en la hoja "Uso y Costo ST Autos", pestaña "Peticiones",
    con las columnas: "Nombre Comercial", "Fecha", "Hora Peticion", "Costo Peticion", "Franquicia", "Resultado", "Input Tokens", "Output Tokens" y "Tiempo Ejecucion".

    Se requiere que 'Costo Peticion' tenga 7 decimales.
    """
    logger.info(f"Registrando petición en 'Peticiones' para comercial={commercial_name}, resultado={resultado}")
    sheet_id = "1P-tZT0Uekz96IEZ2f6UqUozWsn9X0NV77V-IVPfPlpA"
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials_path = os.path.join(os.path.dirname(__file__), "creds-carros.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
    client = gspread.authorize(creds)
    try:
        # Convertir cost a string con 7 decimales, evitando que se guarde como texto
        cost_7_decimals = f"{float(cost):.7f}"

        sheet = client.open_by_key(sheet_id)
        worksheet = sheet.worksheet("Peticiones")
        new_row = [
            commercial_name,
            date_value,
            hora_peticion,
            cost_7_decimals,
            franquicia,
            resultado,
            str(input_tokens),
            str(output_tokens),
            tiempo_ejecucion
        ]
        # Ajuste para que Google Sheets interprete el costo como número en lugar de texto
        worksheet.append_row(new_row, value_input_option='USER_ENTERED')
    except Exception as e:
        print(f"Error registrando en hoja 'Peticiones': {str(e)}")
        logger.exception(f"Error registrando en hoja 'Peticiones': {str(e)}")

# =====================================
# Rutas de Flask
# =====================================

@app.route('/')
def index():
    """Retorna la plantilla principal con el formulario."""
    logger.info("Entrando a la ruta principal /")
    return render_template('index.html')

@app.route('/mass_upload', methods=['POST'])
def mass_upload():
    """
    Procesa un archivo Excel con enlaces masivamente:
      - Nombre del comercial
      - Teléfono del comercial
      - 'massAction' = 'captar' | 'ofrecer'
      - Archivo Excel (col A: URLs)
    """
    logger.info("Entrando a la ruta /mass_upload para procesar archivo Excel masivo.")
    try:
        commercial_name = request.form.get('commercial', '').strip()
        phone_number = request.form.get('phone', '').strip()
        action = request.form.get('massAction', 'captar').strip()  # 'captar' o 'ofrecer'
        excel_file = request.files.get('excelFile')

        if not commercial_name or not phone_number:
            logger.error("Faltan datos de comercial o teléfono en /mass_upload")
            return jsonify({"status": "error", "message": "Faltan datos de comercial o teléfono"}), 400

        # Validar que el comercial exista en "Comerciales"
        franquicia = get_franquicia_by_phone('+57' + phone_number if not phone_number.startswith('+') else phone_number)
        if not franquicia:
            logger.error(f"No se encontró el teléfono {phone_number} en Comerciales en /mass_upload")
            return jsonify({
                "status": "error",
                "message": f"No se encontró el teléfono {phone_number} en Comerciales."
            }), 400

        if not excel_file:
            logger.error("No se encontró el archivo Excel en /mass_upload")
            return jsonify({"status": "error", "message": "No se encontró el archivo Excel"}), 400

        filename = secure_filename(excel_file.filename)
        if not filename:
            logger.error("Nombre de archivo no válido en /mass_upload")
            return jsonify({"status": "error", "message": "Nombre de archivo no válido"}), 400

        saved_path = os.path.join(os.getcwd(), filename)
        excel_file.save(saved_path)

        logger.info(f"Archivo Excel guardado en {saved_path}. Procesando...")
        # Procesar Excel
        urls = process_excel_file(saved_path)
        if not urls:
            logger.error("El archivo Excel no contiene URLs válidas en /mass_upload")
            return jsonify({"status": "error", "message": "El archivo Excel no contiene URLs válidas"}), 400

        # Zona horaria de Bogotá
        bogota_tz = pytz.timezone("America/Bogota")
        results = []

        for single_url in urls:
            logger.info(f"Procesando URL: {single_url}")
            start_time = time.time()
            current_datetime = datetime.now(bogota_tz)
            capture_date = current_datetime.strftime("%d/%m/%Y")
            capture_time = current_datetime.strftime("%H:%M:%S")

            single_url = single_url.strip()
            if not single_url:
                logger.warning("URL vacía detectada en el Excel.")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": "URL vacía en Excel."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            # Si la acción es "captar", se verifica si el vehículo ya fue captado
            if action == "captar":
                captured_commercial = check_vehicle_captado(single_url)
                if captured_commercial:
                    msg = f"El vehiculo ya fue captado por: {captured_commercial}"
                    result = {
                        "url": single_url,
                        "status": "success",
                        "message": msg
                    }
                    execution_time = round(time.time() - start_time, 2)
                    log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, msg, 0, 0, execution_time)
                    results.append(result)
                    continue

            # Determinar si es FB o ML
            is_facebook = "facebook.com" in single_url.lower()
            is_mercadolibre = ("mercadolibre.com" in single_url.lower() or "meli" in single_url.lower())
            source = "Facebook" if is_facebook else "Mercado Libre" if is_mercadolibre else "Desconocido"

            if not (is_facebook or is_mercadolibre):
                logger.warning(f"URL no reconocida (no FB ni ML): {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": "URL no reconocida (no es FB ni ML)."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            # Tomar screenshot y analizar
            screenshot_path = "vehicle_listing.png"
            analyzer = VehicleMarketplaceAnalyzer(ANTHROPIC_API_KEY) if is_facebook else MeliVehicleAnalyzer(ANTHROPIC_API_KEY)

            logger.info(f"Tomando screenshot de {source} - URL: {single_url}")
            if not analyzer.take_screenshot(single_url, screenshot_path):
                logger.error(f"Error al tomar screenshot de {source} para {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": f"Error al tomar screenshot de {source}."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            logger.info(f"Analizando la imagen {screenshot_path} para {single_url}")
            analysis_result = analyzer.analyze_vehicle_listing(screenshot_path, phone_number)
            if not analysis_result:
                logger.error(f"No se pudo analizar la imagen de {source} para {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": f"No se pudo analizar la imagen de {source}."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            analysis_text = analysis_result.get('analysis', '')
            parsed = parse_analysis_text(analysis_text)
            car_name = parsed["car_name"]
            model = parsed["model"]
            sale_price = parsed["sale_price"]
            post_price = parsed["post_price"]

            # =============================
            # Lógica diferenciada según acción
            # =============================
            if action == "captar":
                logger.info(f"Acción 'captar' para la URL: {single_url}")
                try:
                    msg_sheet = process_url_in_google_sheet(
                        url_to_check=single_url,
                        commercial_name=commercial_name,
                        phone_number='+57' + phone_number if not phone_number.startswith('+') else phone_number,
                        date_value=capture_date,
                        car_name=car_name,
                        model=model,
                        source=source,
                        post_price=post_price,
                        sale_price=sale_price
                    )
                    result = {
                        "url": single_url,
                        "status": "success",
                        "message": f"Captado: {msg_sheet}"
                    }
                except Exception as e:
                    logger.exception(f"Error en process_url_in_google_sheet para {single_url}: {e}")
                    result = {
                        "url": single_url,
                        "status": "error",
                        "message": str(e)
                    }
            elif action == "ofrecer":
                logger.info(f"Acción 'ofrecer' para la URL: {single_url}")
                # 1) Enviar mensaje de texto con analysis_text
                sent_ok = enviar_mensaje(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, '+57' + phone_number if not phone_number.startswith('+') else phone_number, analysis_text)
                if not sent_ok:
                    logger.error(f"Error al enviar el texto vía WhatsApp (masivo) para {single_url}")
                    result = {
                        "url": single_url,
                        "status": "error",
                        "message": "Error al enviar el texto vía WhatsApp (masivo)."
                    }
                    execution_time = round(time.time() - start_time, 2)
                    log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                    results.append(result)
                    continue
                else:
                    # 2) Enviar imágenes
                    if is_mercadolibre:
                        logger.info(f"Extrayendo y enviando imágenes de Mercado Libre para {single_url}")
                        img_result = scrape_images(single_url)
                        imgs = img_result.get("images", [])
                        for idx, image_url in enumerate(imgs, start=1):
                            image_sent = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, '+57' + phone_number if not phone_number.startswith('+') else phone_number, image_url)
                            if not image_sent:
                                print(f"Error enviando imagen (masivo) {idx} - {image_url}")
                                logger.error(f"Error enviando imagen (masivo) {idx} - {image_url}")
                    elif is_facebook:
                        logger.info(f"Extrayendo y enviando imágenes de Facebook para {single_url}")
                        from scrapper_fb_images import scrape_facebook_images
                        fb_img_result = scrape_facebook_images(single_url)
                        fb_imgs = fb_img_result.get("images", [])
                        for idx, image_url in enumerate(fb_imgs, start=1):
                            image_sent = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, '+57' + phone_number if not phone_number.startswith('+') else phone_number, image_url)
                            if not image_sent:
                                print(f"Error enviando imagen (masivo) {idx} - {image_url}")
                                logger.error(f"Error enviando imagen (masivo) {idx} - {image_url}")

                    result = {
                        "url": single_url,
                        "status": "success",
                        "message": f"Ofrecido correctamente (proceso masivo)."
                    }
            else:
                logger.warning(f"Acción desconocida (masivo): {action} para {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": f"Acción desconocida (masivo): {action}"
                }

            # =============================
            # Registrar petición
            # =============================
            if analyzer.get_last_request_cost():
                cost_value = analyzer.get_last_request_cost()["costs"]["total"]
                input_tok = analyzer.get_last_request_cost()["tokens"]["input"]
                output_tok = analyzer.get_last_request_cost()["tokens"]["output"]
            else:
                cost_value = 0.0
                input_tok = 0
                output_tok = 0

            execution_time = round(time.time() - start_time, 2)
            log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, cost_value, franquicia, result["message"], input_tok, output_tok, execution_time)
            results.append(result)

        return jsonify({"status": "ok", "results": results})

    except Exception as e:
        logger.exception(f"Excepción en /mass_upload: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/process', methods=['POST'])
def process():
    """
    Espera un payload con:
      {
        commercial: str,
        phone: str,
        action: str (captar|ofrecer),
        urls: [url1, url2, ...],
        sendToClient: bool,
        clientPhone: str (si sendToClient es True)
      }
    Procesa cada URL individualmente.
    """
    logger.info("Entrando a la ruta /process para procesar URLs individuales.")
    try:
        data = request.json
        commercial_name = data.get('commercial')
        phone_number = data.get('phone')
        action = data.get('action')
        urls = data.get('urls', [])
        send_to_client = data.get('sendToClient', False)
        client_phone = data.get('clientPhone', "").strip()

        if not urls or not isinstance(urls, list):
            logger.error("No se han proporcionado URLs válidas en /process")
            return jsonify({"status": "error", "message": "No se han proporcionado URLs válidas."}), 400

        # Anteponer +57 si no lo trae
        if phone_number and not phone_number.startswith('+'):
            phone_number = '+57' + phone_number

        if send_to_client and client_phone and not client_phone.startswith('+'):
            client_phone = '+57' + client_phone

        # Verificar que el número de teléfono (comercial) exista en la pestaña "Comerciales"
        logger.info(f"Verificando franquicia para el teléfono {phone_number}")
        franquicia = get_franquicia_by_phone(phone_number)
        if not franquicia:
            logger.error(f"No se encontró el teléfono {phone_number} en Comerciales en /process")
            return jsonify({
                "status": "error",
                "message": f"No se encontró el teléfono {phone_number} en Comerciales."
            }), 400

        # Fecha en zona horaria de Bogotá
        bogota_tz = pytz.timezone("America/Bogota")
        capture_date = datetime.now(bogota_tz).strftime("%d/%m/%Y")

        results = []

        for single_url in urls:
            logger.info(f"Procesando URL en /process: {single_url}")
            start_time = time.time()
            current_datetime = datetime.now(bogota_tz)
            capture_date = current_datetime.strftime("%d/%m/%Y")
            capture_time = current_datetime.strftime("%H:%M:%S")
            single_url = single_url.strip()
            cost_value = 0.0
            input_tok = 0
            output_tok = 0

            if not single_url:
                logger.warning("URL vacía detectada en /process.")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": "URL vacía."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            # Si la acción es "captar", se verifica si el vehículo ya fue captado
            if action == "captar":
                captured_commercial = check_vehicle_captado(single_url)
                if captured_commercial:
                    msg = f"El vehiculo ya fue captado por: {captured_commercial}"
                    result = {
                        "url": single_url,
                        "status": "success",
                        "message": msg
                    }
                    execution_time = round(time.time() - start_time, 2)
                    log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, msg, 0, 0, execution_time)
                    results.append(result)
                    continue

            # Determinar si es FB o ML
            is_facebook = "facebook.com" in single_url.lower()
            is_mercadolibre = ("mercadolibre.com" in single_url.lower() or "meli" in single_url.lower())
            source = "Facebook" if is_facebook else "Mercado Libre" if is_mercadolibre else "Desconocido"

            if not (is_facebook or is_mercadolibre):
                logger.warning(f"URL no reconocida (no FB ni ML) en /process: {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": "URL no reconocida (no es FB ni ML)."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            # Tomar screenshot y analizar
            screenshot_path = "vehicle_listing.png"
            analyzer = VehicleMarketplaceAnalyzer(ANTHROPIC_API_KEY) if is_facebook else MeliVehicleAnalyzer(ANTHROPIC_API_KEY)

            logger.info(f"Tomando screenshot de {source} - URL: {single_url}")
            if not analyzer.take_screenshot(single_url, screenshot_path):
                logger.error(f"Error al tomar screenshot de {source} en /process para {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": f"Error al tomar screenshot de {source}."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            logger.info(f"Analizando la imagen {screenshot_path} en /process para {single_url}")
            analysis_result = analyzer.analyze_vehicle_listing(screenshot_path, phone_number)
            if not analysis_result:
                logger.error(f"No se pudo analizar la imagen de {source} en /process para {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": f"No se pudo analizar la imagen de {source}."
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)
                continue

            analysis_text = analysis_result.get('analysis', '')
            parsed = parse_analysis_text(analysis_text)
            car_name = parsed["car_name"]
            model = parsed["model"]
            sale_price = parsed["sale_price"]
            post_price = parsed["post_price"]

            if action == "captar":
                logger.info(f"Acción 'captar' en /process para {single_url}")
                try:
                    msg_sheet = process_url_in_google_sheet(
                        url_to_check=single_url,
                        commercial_name=commercial_name,
                        phone_number=phone_number,
                        date_value=capture_date,
                        car_name=car_name,
                        model=model,
                        source=source,
                        post_price=post_price,
                        sale_price=sale_price
                    )
                    result = {
                        "url": single_url,
                        "status": "success",
                        "message": f"Captado: {msg_sheet}"
                    }
                except Exception as e:
                    logger.exception(f"Error en process_url_in_google_sheet: {e}")
                    result = {
                        "url": single_url,
                        "status": "error",
                        "message": str(e)
                    }
                if analyzer.get_last_request_cost():
                    cost_value = analyzer.get_last_request_cost()["costs"]["total"]
                    input_tok = analyzer.get_last_request_cost()["tokens"]["input"]
                    output_tok = analyzer.get_last_request_cost()["tokens"]["output"]
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, cost_value, franquicia, result["message"], input_tok, output_tok, execution_time)
                results.append(result)

                # ===============================
                # Enviar mensaje+imágenes también al comercial (si la captación fue exitosa)
                # ===============================
                if result["status"] == "success":
                    logger.info(f"Enviando información al comercial {phone_number} en /process para {single_url}")
                    sent_ok_commercial = enviar_mensaje(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, analysis_text)
                    if sent_ok_commercial:
                        if is_mercadolibre:
                            logger.info(f"Extrayendo y enviando imágenes de Mercado Libre al comercial para {single_url}")
                            img_result = scrape_images(single_url)
                            imgs = img_result.get("images", [])
                            for idx, image_url in enumerate(imgs, start=1):
                                image_sent_commercial = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, image_url)
                                if not image_sent_commercial:
                                    print(f"Error enviando imagen al comercial {idx} - {image_url}")
                                    logger.error(f"Error enviando imagen al comercial {idx} - {image_url}")
                        elif is_facebook:
                            logger.info(f"Extrayendo y enviando imágenes de Facebook al comercial para {single_url}")
                            from scrapper_fb_images import scrape_facebook_images
                            fb_img_result = scrape_facebook_images(single_url)
                            fb_imgs = fb_img_result.get("images", [])
                            for idx, image_url in enumerate(fb_imgs, start=1):
                                image_sent_commercial = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, image_url)
                                if not image_sent_commercial:
                                    print(f"Error enviando imagen al comercial {idx} - {image_url}")
                                    logger.error(f"Error enviando imagen al comercial {idx} - {image_url}")

                # Enviar al cliente si se marcó la opción
                if send_to_client and client_phone:
                    logger.info(f"Enviando información al cliente {client_phone} en /process para {single_url}")
                    sent_ok_client = enviar_mensaje(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, client_phone, analysis_text)
                    if sent_ok_client:
                        if is_mercadolibre:
                            logger.info(f"Extrayendo y enviando imágenes de Mercado Libre al cliente para {single_url}")
                            img_result = scrape_images(single_url)
                            imgs = img_result.get("images", [])
                            for idx, image_url in enumerate(imgs, start=1):
                                image_sent_client = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, client_phone, image_url)
                                if not image_sent_client:
                                    print(f"Error enviando imagen al cliente {idx} - {image_url}")
                                    logger.error(f"Error enviando imagen al cliente {idx} - {image_url}")
                        elif is_facebook:
                            logger.info(f"Extrayendo y enviando imágenes de Facebook al cliente para {single_url}")
                            from scrapper_fb_images import scrape_facebook_images
                            fb_img_result = scrape_facebook_images(single_url)
                            fb_imgs = fb_img_result.get("images", [])
                            for idx, image_url in enumerate(fb_imgs, start=1):
                                image_sent_client = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, client_phone, image_url)
                                if not image_sent_client:
                                    print(f"Error enviando imagen al cliente {idx} - {image_url}")
                                    logger.error(f"Error enviando imagen al cliente {idx} - {image_url}")

                # ===============================
                # Enviar SIEMPRE al comercial el mensaje final con la URL (y opcional teléfono del cliente)
                # ===============================
                final_msg_commercial = f"URL Vehiculo Procesado 🚘🔥: {single_url}"
                if send_to_client and client_phone:
                    # Se agrega el número de cliente, pero SOLO al comercial
                    final_msg_commercial += f"\nTelefono Cliente: {client_phone}"
                enviar_mensaje(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, final_msg_commercial)

            elif action == "ofrecer":
                logger.info(f"Acción 'ofrecer' en /process para {single_url}")
                sent_ok = enviar_mensaje(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, analysis_text)
                if not sent_ok:
                    logger.error(f"Error al enviar el texto vía WhatsApp en /process para {single_url}")
                    result = {
                        "url": single_url,
                        "status": "error",
                        "message": "Error al enviar el texto vía WhatsApp."
                    }
                    if analyzer.get_last_request_cost():
                        cost_value = analyzer.get_last_request_cost()["costs"]["total"]
                        input_tok = analyzer.get_last_request_cost()["tokens"]["input"]
                        output_tok = analyzer.get_last_request_cost()["tokens"]["output"]
                    execution_time = round(time.time() - start_time, 2)
                    log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, cost_value, franquicia, result["message"], input_tok, output_tok, execution_time)
                    results.append(result)
                    continue

                if is_mercadolibre:
                    logger.info(f"Extrayendo y enviando imágenes de Mercado Libre en /process para {single_url}")
                    img_result = scrape_images(single_url)
                    imgs = img_result.get("images", [])
                    for idx, image_url in enumerate(imgs, start=1):
                        image_sent = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, image_url)
                        if not image_sent:
                            print(f"Error enviando imagen {idx} - {image_url}")
                            logger.error(f"Error enviando imagen {idx} - {image_url}")
                elif is_facebook:
                    logger.info(f"Extrayendo y enviando imágenes de Facebook en /process para {single_url}")
                    from scrapper_fb_images import scrape_facebook_images
                    fb_img_result = scrape_facebook_images(single_url)
                    fb_imgs = fb_img_result.get("images", [])
                    for idx, image_url in enumerate(fb_imgs, start=1):
                        image_sent = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, image_url)
                        if not image_sent:
                            print(f"Error enviando imagen {idx} - {image_url}")
                            logger.error(f"Error enviando imagen {idx} - {image_url}")

                result = {
                    "url": single_url,
                    "status": "success",
                    "message": f"Ofrecido correctamente ({source})."
                }
                if analyzer.get_last_request_cost():
                    cost_value = analyzer.get_last_request_cost()["costs"]["total"]
                    input_tok = analyzer.get_last_request_cost()["tokens"]["input"]
                    output_tok = analyzer.get_last_request_cost()["tokens"]["output"]
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, cost_value, franquicia, result["message"], input_tok, output_tok, execution_time)
                results.append(result)

                # Enviar al cliente si se marcó la opción
                if send_to_client and client_phone:
                    logger.info(f"También enviando información al cliente {client_phone} en /process para {single_url}")
                    sent_ok_client = enviar_mensaje(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, client_phone, analysis_text)
                    if sent_ok_client:
                        if is_mercadolibre:
                            logger.info(f"Extrayendo y enviando imágenes de Mercado Libre al cliente para {single_url}")
                            img_result = scrape_images(single_url)
                            imgs = img_result.get("images", [])
                            for idx, image_url in enumerate(imgs, start=1):
                                image_sent_client = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, client_phone, image_url)
                                if not image_sent_client:
                                    print(f"Error enviando imagen al cliente {idx} - {image_url}")
                                    logger.error(f"Error enviando imagen al cliente {idx} - {image_url}")
                        elif is_facebook:
                            logger.info(f"Extrayendo y enviando imágenes de Facebook al cliente para {single_url}")
                            from scrapper_fb_images import scrape_facebook_images
                            fb_img_result = scrape_facebook_images(single_url)
                            fb_imgs = fb_img_result.get("images", [])
                            for idx, image_url in enumerate(fb_imgs, start=1):
                                image_sent_client = enviar_imagen(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, client_phone, image_url)
                                if not image_sent_client:
                                    print(f"Error enviando imagen al cliente {idx} - {image_url}")
                                    logger.error(f"Error enviando imagen al cliente {idx} - {image_url}")

                # ===============================
                # Enviar SIEMPRE al comercial el mensaje final con la URL (y opcional teléfono del cliente)
                # ===============================
                final_msg_commercial = f"URL Vehiculo Procesado 🚘🔥: {single_url}"
                if send_to_client and client_phone:
                    final_msg_commercial += f"\nTelefono Cliente: {client_phone}"
                enviar_mensaje(ULTRAMSG_TOKEN, ULTRAMSG_INSTANCE_ID, phone_number, final_msg_commercial)

            else:
                logger.warning(f"Acción desconocida en /process: {action} para {single_url}")
                result = {
                    "url": single_url,
                    "status": "error",
                    "message": f"Acción desconocida: {action}"
                }
                execution_time = round(time.time() - start_time, 2)
                log_peticion_in_google_sheet(commercial_name, capture_date, capture_time, 0.0, franquicia, result["message"], 0, 0, execution_time)
                results.append(result)

        return jsonify({
            "status": "ok",
            "results": results
        })

    except Exception as e:
        logger.exception(f"Excepción en /process: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# =====================================
# Inicialización
# =====================================

def create_required_directories():
    base_dir = os.path.dirname(__file__)
    templates_dir = os.path.join(base_dir, "templates")
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    static_dir = os.path.join(base_dir, "static")
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)

if __name__ == '__main__':
    create_required_directories()
    creds_path = os.path.join(os.path.dirname(__file__), "creds-carros.json")
    if not os.path.exists(creds_path):
        print("ADVERTENCIA: No se encuentra 'creds-carros.json'")
        print(f"Coloca el archivo en: {creds_path}")

    print("Servidor en http://localhost:8000")
    logger.info("Iniciando aplicación Flask en puerto 8000")
    app.run(debug=True, host='0.0.0.0', port=8000)
