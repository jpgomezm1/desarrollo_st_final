# 🚗 Flask Carros UI

Este proyecto es una aplicación Flask que permite extraer y procesar información de vehículos desde diferentes plataformas.

## 🚀 Instalación y Configuración

### **1. Clonar el repositorio**
```bash
 git clone https://github.com/jpgomezm1/desarrollo_st_final.git
 cd desarollo_st_final
```

### **2. Crear y activar un entorno virtual (opcional pero recomendado)**
#### **Windows**
```bash
python -m venv venv
venv\Scripts\activate
```
#### **Mac/Linux**
```bash
python3 -m venv venv
source venv/bin/activate
```

### **3. Instalar dependencias**
```bash
pip install -r requirements.txt
```

### **4. Ejecutar la aplicación localmente**
```bash
flask run --host=0.0.0.0 --port=8000
```

---

## 🐳 Despliegue con Docker

### **1. Construir la imagen Docker**
```bash
docker build -t carros_ui .
```

### **2. Ejecutar el contenedor**
```bash
docker run -d -p 8000:8000 carros_ui
```
La aplicación estará disponible en `http://localhost:8000`.

---

## 📦 Despliegue con Docker Compose
Si prefieres ejecutar todo con un solo comando, usa `docker-compose`.

### **1. Construir y levantar los contenedores**
```bash
docker-compose up -d --build
```

### **2. Detener los contenedores**
```bash
docker-compose down
```

---

## ✨ Notas
- Asegúrate de tener `Python 3.11` o superior instalado.
- Para ejecutar con Docker, necesitas instalar [Docker](https://www.docker.com/) en tu sistema.
- Si usas Docker Compose, necesitas `docker-compose` instalado.

¡Listo! Ahora cualquier persona puede seguir estas instrucciones para ejecutar el proyecto. 🚀

