# scrapper_fb_images.py

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import pickle
import os
import requests
import shutil
from PIL import Image
from io import BytesIO
import logging
import concurrent.futures
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import aiohttp
import asyncio
from functools import lru_cache

# Configuración del logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración de la sesión de requests con retry
def create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=100, pool_maxsize=100)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# Cache para las dimensiones de imágenes
@lru_cache(maxsize=1000)
def get_image_dimensions(img_url, session):
    """
    Obtiene las dimensiones de una imagen con cache para evitar descargas repetidas.
    """
    try:
        response = session.get(img_url, timeout=5)
        img = Image.open(BytesIO(response.content))
        return img.size
    except Exception as e:
        logger.error(f"Error obteniendo dimensiones de {img_url}: {e}")
        return None

async def check_image_dimension_async(img_url, min_dim, max_dim, session):
    """
    Verifica las dimensiones de una imagen de forma asíncrona.
    """
    try:
        async with session.get(img_url) as response:
            if response.status == 200:
                img_data = await response.read()
                img = Image.open(BytesIO(img_data))
                width, height = img.size
                if (min_dim <= width <= max_dim) or (min_dim <= height <= max_dim):
                    return img_url
    except Exception as e:
        logger.error(f"Error procesando imagen {img_url}: {e}")
    return None

async def filter_images_async(image_urls, min_dim, max_dim):
    """
    Filtra las imágenes de forma asíncrona usando aiohttp.
    """
    async with aiohttp.ClientSession() as session:
        tasks = [check_image_dimension_async(url, min_dim, max_dim, session) 
                for url in image_urls]
        results = await asyncio.gather(*tasks)
        return [url for url in results if url]

def scrape_facebook_images(target_url, min_dim=860, max_dim=980):
    """
    Versión optimizada del scraper de imágenes de Facebook Marketplace.
    """
    logger.info(f"Iniciando scraping optimizado para URL: {target_url}")
    
    # Configuración optimizada del navegador
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-images")  # Desactivar carga de imágenes para mayor velocidad
    
    prefs = {
        'profile.default_content_setting_values': {
            'images': 2,  # Deshabilitar carga de imágenes
            'notifications': 2  # Deshabilitar notificaciones
        }
    }
    options.add_experimental_option('prefs', prefs)
    
    driver = None
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        wait = WebDriverWait(driver, 10)  # Reducido de 15 a 10 segundos
        
        # Cargar la página directamente sin cookies
        driver.get(target_url)
        time.sleep(3)  # Reducido de 5 a 3 segundos
        
        # Intentar abrir la galería
        try:
            first_img = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "img")))
            driver.execute_script("arguments[0].click();", first_img)
            time.sleep(2)  # Reducido de 3 a 2 segundos
        except Exception as e:
            logger.warning(f"No se pudo abrir la galería: {e}")
        
        # Recolectar URLs de imágenes de forma optimizada
        image_urls = set()
        max_attempts = 10  # Límite de intentos para encontrar nuevas imágenes
        attempts = 0
        last_count = 0
        
        while attempts < max_attempts:
            current_imgs = driver.find_elements(By.TAG_NAME, "img")
            current_urls = {img.get_attribute("src") for img in current_imgs 
                          if img.get_attribute("src") and "scontent" in img.get_attribute("src")}
            image_urls.update(current_urls)
            
            if len(image_urls) == last_count:
                attempts += 1
            else:
                attempts = 0
            last_count = len(image_urls)
            
            try:
                next_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//div[@aria-label='Siguiente']")))
                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(1)  # Reducido de 2 a 1 segundo
            except:
                break
        
        # Filtrar imágenes de forma asíncrona
        filtered_urls = asyncio.run(filter_images_async(list(image_urls), min_dim, max_dim))
        
        result = {
            "status": "success" if filtered_urls else "error",
            "total_images": len(filtered_urls),
            "images": filtered_urls
        }
        
        logger.info(f"Scraping optimizado completado. {len(filtered_urls)} imágenes cumplen los criterios.")
        return result
        
    except Exception as e:
        logger.error(f"Error durante el scraping: {e}")
        return {
            "status": "error",
            "total_images": 0,
            "images": []
        }
    finally:
        if driver:
            driver.quit()

async def download_image_async(img_url, output_path, session):
    """
    Descarga una imagen de forma asíncrona.
    """
    try:
        async with session.get(img_url) as response:
            if response.status == 200:
                content = await response.read()
                with open(output_path, 'wb') as f:
                    f.write(content)
                return True
    except Exception as e:
        logger.error(f"Error descargando {img_url}: {e}")
    return False

async def download_images_async(result, output_folder):
    """
    Versión asíncrona de la función de descarga de imágenes.
    """
    os.makedirs(output_folder, exist_ok=True)
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for idx, img_url in enumerate(result.get("images", [])):
            output_path = os.path.join(output_folder, f"imagen_{idx + 1}.jpg")
            task = download_image_async(img_url, output_path, session)
            tasks.append(task)
        
        await asyncio.gather(*tasks)

def download_images(result, output_folder):
    """
    Wrapper sincrónico para la función de descarga asíncrona.
    """
    asyncio.run(download_images_async(result, output_folder))
    logger.info("Todas las imágenes han sido descargadas.")

if __name__ == '__main__':
    OUTPUT_FOLDER = "facebook_img"
    if os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)
    os.makedirs(OUTPUT_FOLDER)
    
    TARGET_URL = "https://www.facebook.com/marketplace/item/XXXXX"
    result = scrape_facebook_images(TARGET_URL)
    
    print("\nImágenes encontradas (filtradas por dimensiones):")
    for img_url in result.get("images", []):
        print(img_url)
    
    URLS_FILE = os.path.join(OUTPUT_FOLDER, "image_urls.txt")
    with open(URLS_FILE, "w") as f:
        for img_url in result.get("images", []):
            f.write(f"{img_url}\n")
    
    download_images(result, OUTPUT_FOLDER)