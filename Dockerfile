# Usa la versión de Python que necesites
FROM python:3.11

# Define el directorio de trabajo dentro del contenedor
WORKDIR /code

# Copia los archivos de dependencias primero para optimizar caché
COPY ./requirements.txt /code/requirements.txt

# Instala las dependencias
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copia el resto de los archivos del proyecto
COPY . .

# Define la variable de entorno FLASK_APP
ENV FLASK_APP=carros_ui.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=8000

# Expone el puerto para Flask
EXPOSE 8000

# Comando para ejecutar la aplicación
CMD ["flask", "run"]
