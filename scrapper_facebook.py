# scrapper_facebook.py

import os
from playwright.sync_api import sync_playwright
from anthropic import Anthropic
import base64
from typing import Dict, Optional
from enum import Enum

class ClaudeModel(Enum):
    HAIKU = "claude-3-haiku-20240307"
    SONNET = "claude-3-sonnet-20240229"
    OPUS = "claude-3-opus-20240229"

class CostTracker:
    # Precios actualizados por 1M tokens (MTok)
    PRICING = {
        ClaudeModel.HAIKU.value: {
            "input": 0.80,        # $0.80 por MTok de input
            "output": 4.00,       # $4.00 por MTok de output
            "cache_write": 1.00,  # $1.00 por MTok de cache write
            "cache_read": 0.08    # $0.08 por MTok de cache read
        },
        ClaudeModel.SONNET.value: {
            "input": 3.00,        # $3.00 por MTok de input
            "output": 15.00,      # $15.00 por MTok de output
            "cache_write": 3.75,  # $3.75 por MTok de cache write
            "cache_read": 0.30    # $0.30 por MTok de cache read
        },
        ClaudeModel.OPUS.value: {
            "input": 15.00,       # $15.00 por MTok de input
            "output": 75.00,      # $75.00 por MTok de output
            "cache_write": 18.75, # $18.75 por MTok de cache write
            "cache_read": 1.50    # $1.50 por MTok de cache read
        }
    }
    
    @staticmethod
    def calculate_cost(model: str, input_tokens: int, output_tokens: int, 
                      cache_write_tokens: int = 0, cache_read_tokens: int = 0) -> Dict[str, float]:
        """
        Calcula el costo detallado de una llamada a la API basado en los tokens utilizados.
        
        Args:
            model: Nombre del modelo de Claude
            input_tokens: Número de tokens de entrada
            output_tokens: Número de tokens de salida
            cache_write_tokens: Número de tokens escritos en caché (opcional)
            cache_read_tokens: Número de tokens leídos del caché (opcional)
        
        Returns:
            Dictionary con el desglose de costos y totales
        """
        if model not in CostTracker.PRICING:
            raise ValueError(f"Modelo {model} no encontrado en la tabla de precios")
            
        pricing = CostTracker.PRICING[model]
        
        # Convertir tokens a millones (MTok)
        input_mtok = input_tokens / 1_000_000
        output_mtok = output_tokens / 1_000_000
        cache_write_mtok = cache_write_tokens / 1_000_000
        cache_read_mtok = cache_read_tokens / 1_000_000
        
        # Calcular costos individuales
        input_cost = input_mtok * pricing["input"]
        output_cost = output_mtok * pricing["output"]
        cache_write_cost = cache_write_mtok * pricing["cache_write"]
        cache_read_cost = cache_read_mtok * pricing["cache_read"]
        
        # Calcular costo total
        total_cost = input_cost + output_cost + cache_write_cost + cache_read_cost
        
        return {
            "model": model,
            "costs": {
                "input": round(input_cost, 7),
                "output": round(output_cost, 7),
                "cache_write": round(cache_write_cost, 7),
                "cache_read": round(cache_read_cost, 7),
                "total": round(total_cost, 7)
            },
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "cache_write": cache_write_tokens,
                "cache_read": cache_read_tokens,
                "total": input_tokens + output_tokens + cache_write_tokens + cache_read_tokens
            }
        }

class VehicleMarketplaceAnalyzer:
    def __init__(self, anthropic_api_key):
        """
        Inicializa el analizador con la API key de Anthropic
        
        Args:
            anthropic_api_key: API key de Anthropic
        """
        self.anthropic = Anthropic(api_key=anthropic_api_key)
        self.last_request_cost = None
        
    def take_screenshot(self, url, output_file="screenshot.png", width=1920, height=1080, clip_width=600):
        """
        Toma una captura de pantalla de la página del marketplace
        
        Args:
            url: URL del listado
            output_file: Nombre del archivo de salida
            width: Ancho de la ventana del navegador
            height: Alto de la ventana del navegador
            clip_width: Ancho del área de recorte
            
        Returns:
            bool: True si la captura fue exitosa, False en caso contrario
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={'width': width, 'height': height}
                )
                page = context.new_page()
                page.goto(url)
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(10000)  # Esperar 10 segundos adicionales
                try:
                    page.wait_for_selector('text=Descripción del vendedor', timeout=30000)
                except:
                    print("No se encontró el selector específico, continuando de todos modos...")
                page.screenshot(
                    path=output_file,
                    clip={"x": width - clip_width, "y": 0, "width": clip_width, "height": height}
                )
                context.close()
                browser.close()
            return True
        except Exception as e:
            print(f"Error tomando screenshot: {str(e)}")
            return False

    def encode_image(self, image_path):
        """
        Codifica la imagen en base64
        
        Args:
            image_path: Ruta al archivo de imagen
            
        Returns:
            str: Imagen codificada en base64 o None si hay error
        """
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            print(f"Error codificando imagen: {str(e)}")
            return None

    def analyze_vehicle_listing(self, image_path, phone_number):
        """
        Analiza la imagen del listado del vehículo usando Claude y rastrea los costos.
        Se sustituye la sección de teléfono por el phone_number que recibe como parámetro.

        Args:
            image_path: Ruta a la imagen del listado
            phone_number: Teléfono dinámico del comercial (ej: '+57 3183849532')

        Returns:
            Dict: Diccionario con el análisis y la información de tokens, o None si hay error
            {
                'analysis': str,
                'input_tokens': int,
                'output_tokens': int
            }
        """
        try:
            image_data = self.encode_image(image_path)
            if not image_data:
                return None

            # Ajuste: reemplazamos el teléfono estático por el phone_number
            prompt = f"""Analiza esta imagen y extrae la información siguiendo estas reglas estrictas:

1. PRECIO:
- Extrae el precio numérico exacto de la imagen
- Elimina cualquier punto o coma del número
- Multiplica ese número por 1.04 para añadir el 4%
- Formatea el resultado final con puntos como separadores de miles

2. IDENTIFICACIÓN:
- Extrae la marca y modelo exactos
- Si hay variante específica del modelo, inclúyela

Usa EXACTAMENTE este formato. Cuando no encuentres un dato, omite el campo completo, desde la parte de las especificaciones del vehiculo hasta "📍Edificio Access Point - Av. Las Palmas (cita previa)" que es donde termina el mensaje:

🚘 [MARCA] [MODELO]
[INCLUIR SOLO LOS CAMPOS QUE ESTÉN PRESENTES EN LA IMAGEN, CADA UNO EN UNA NUEVA LÍNEA Y CON EL PREFIJO ➖]
➖Precio: $[PRECIO DE LA IMAGEN + 4% en formato numérico con puntos como separadores de miles]
➖Motor: [MOTOR si está disponible]
➖Modelo: [AÑO]
➖Kilómetros: [KILOMETRAJE en formato numérico]
➖Ubicación: [UBICACIÓN]
➖Otros: [INCLUIR: estado del vehículo, documentos al día, características especiales de equipamiento]

Llamada celular / WhatsApp 
📲 {phone_number}
Consigue tu vehículo ideal con @autos_st, contáctanos si deseas vender tu vehículo con nosotros.
Recuerda que con nosotros puedes sacar tu crédito fácil y rápido. Aprobación en 3 horas, certificamos las mejores tasas del mercado💸
📍Edificio Access Point - Av. Las Palmas (cita previa)

REGLAS DE VALIDACIÓN:
1. El precio DEBE ser un número
2. El kilometraje DEBE ser un número sin puntos ni texto adicional
3. El año DEBE ser un número de 4 dígitos entre 1900 y 2024
4. La ubicación DEBE ser una ciudad o zona específica

INSTRUCCIONES IMPORTANTES:
1. Solo incluir los campos con ➖ que estén presentes en la imagen
2. Todo el texto después de "Llamada celular / WhatsApp" debe incluirse EXACTAMENTE como está mostrado arriba
3. No modificar ningún emoji o formato
4. No agregar información adicional al final"""

            model = ClaudeModel.HAIKU.value
            response = self.anthropic.messages.create(
                model=model,
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data
                            }
                        }
                    ]
                }]
            )

            self.last_request_cost = CostTracker.calculate_cost(
                model=model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens
            )

            if isinstance(response.content, list) and len(response.content) > 0:
                first_block = response.content[0]
                return {
                    'analysis': first_block.text.strip(),
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                }
            else:
                print("Respuesta no reconocida:", response.content)
                return None

        except Exception as e:
            print(f"Error analizando imagen con Claude: {str(e)}")
            return None

    def get_last_request_cost(self) -> Optional[Dict]:
        """
        Retorna la información detallada de costo de la última solicitud
        
        Returns:
            Dict: Información de costos o None si no hay solicitud previa
        """
        return self.last_request_cost

def main():
    # Configurar tu API key de Anthropic
    ANTHROPIC_API_KEY = "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"
    
    # URL del marketplace a analizar
    url = "https://www.facebook.com/marketplace/item/1336536434139458/?ref=search&referral_code=null&referral_story_type=post&tracking=browse_serp%3A6becad76-e5e3-46e4-afd6-540a0b176fa7"
    
    # Inicializar el analizador
    analyzer = VehicleMarketplaceAnalyzer(ANTHROPIC_API_KEY)
    screenshot_path = "vehicle_listing.png"
    
    if analyzer.take_screenshot(url, screenshot_path):
        # Ejemplo: pasamos un teléfono dinámico
        phone_number = "+57 3009998888"
        result = analyzer.analyze_vehicle_listing(screenshot_path, phone_number)
        if result:
            print("\nAnálisis del vehículo:")
            print(result['analysis'])
            
            print("\nTokens utilizados en esta solicitud:")
            print(f"Input tokens: {result['input_tokens']:,}")
            print(f"Output tokens: {result['output_tokens']:,}")
            
            cost_info = analyzer.get_last_request_cost()
            if cost_info:
                print("\nInformación detallada de costos:")
                print(f"Modelo: {cost_info['model']}")
                print("\nCostos:")
                for category, amount in cost_info['costs'].items():
                    print(f"  {category.capitalize()}: ${amount:.7f}")
                print("\nTokens utilizados:")
                for category, count in cost_info['tokens'].items():
                    print(f"  {category.capitalize()}: {count:,}")
        else:
            print("No se pudo analizar la imagen")
    else:
        print("No se pudo tomar el screenshot")

if __name__ == "__main__":
    main()
