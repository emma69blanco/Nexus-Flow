import os
import threading
import time
import re
import requests
import urllib.parse
from queue import Queue
from flask import Flask
import telebot
from bs4 import BeautifulSoup
from mediafire.client import MediaFireClient

# ==========================================
# 1. CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==========================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
MF_EMAIL = os.environ.get('MF_EMAIL')
MF_PASSWORD = os.environ.get('MF_PASSWORD')

if not BOT_TOKEN:
    print("⚠️ ADVERTENCIA: BOT_TOKEN no encontrado en las variables de entorno.")

bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None
app = Flask(__name__)

cola_procesamiento = Queue()
procesando_actualmente = False

# ==========================================
# 2. SERVIDOR WEB (FLASK) - DISEÑO PROFESIONAL
# ==========================================
@app.route('/')
def home():
    html_content = """
    <html>
        <head>
            <title>Sistema Activo - Nexus Flow</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #ffffff; color: #333333; text-align: center; padding-top: 10vh; margin: 0; }
                .status-box { border: 1px solid #e0e0e0; border-radius: 8px; padding: 40px; display: inline-block; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
                h2 { color: #2e7d32; margin-bottom: 10px; font-weight: 500; }
                p { color: #666666; font-size: 14px; }
            </style>
        </head>
        <body>
            <div class="status-box">
                <h2>🟢 Nodo de Tránsito Operativo</h2>
                <p>El puente de transferencia de archivos está activo y esperando instrucciones.</p>
            </div>
        </body>
    </html>
    """
    return html_content

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ==========================================
# 3. LÓGICA DE TRANSFERENCIA MULTI-SERVIDOR
# ==========================================
def obtener_sesion_mediafire():
    """ Inicia sesión en tu cuenta destino usando la librería oficial """
    try:
        mf_client = MediaFireClient()
        mf_client.login(email=MF_EMAIL, password=MF_PASSWORD, app_id='42511')
        return mf_client
    except Exception as e:
        print(f"Error de login MediaFire: {e}")
        return None

def extraer_enlace_directo_origen(url_origen):
    """ Obtiene el link directo real utilizando BeautifulSoup o APIs """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        
        # --- LÓGICA PARA MEDIAFIRE ---
        if "mediafire.com" in url_origen:
            res = requests.get(url_origen, headers=headers, timeout=15)
            soup = BeautifulSoup(res.content, 'html.parser')
            button = soup.find('a', {'id': 'downloadButton'})
            if button and button.get('href'):
                return button.get('href')
            return None
            
        # --- LÓGICA PARA WORKUPLOAD ---
        elif "workupload.com" in url_origen:
            session = requests.Session()
            # 1. Visitar primero para obtener cookies silenciosamente
            session.get(url_origen, headers=headers, timeout=15)
            
            # 2. Extraer ID y consultar su API interna
            file_id = url_origen.rstrip('/').split("/")[-1]
            api_url = f"https://workupload.com/api/file/getDownloadServer/{file_id}"
            
            # Es vital enviar el Referer para que la API responda
            headers['Referer'] = url_origen
            res = session.get(api_url, headers=headers, timeout=15)
            
            data = res.json()
            if 'data' in data and 'url' in data['data']:
                return data['data']['url']
            return None

        # --- OTROS ENLACES DIRECTOS ---
        return url_origen 
    except Exception as e:
        print(f"Error extrayendo enlace de origen: {e}")
        return None

def procesar_transferencia(url_origen, chat_id):
    """ Descarga al disco temporal del VPS y sube a MediaFire """
    ruta_temporal = ""
    try:
        bot.send_message(chat_id, f"🔄 Procesando origen:\n{url_origen}")
        
        # 1. Obtener Enlace Directo
        url_descarga_directa = extraer_enlace_directo_origen(url_origen)
        
        if not url_descarga_directa or url_descarga_directa == url_origen and ("mediafire.com" in url_origen or "workupload.com" in url_origen):
            bot.send_message(chat_id, "❌ Error: No se pudo extraer el enlace directo de descarga.")
            return

        # 2. Conectar a MediaFire Pro
        mf_client = obtener_sesion_mediafire()
        if not mf_client:
            bot.send_message(chat_id, "❌ Error: Fallo de autenticación. Verifica las credenciales.")
            return

        # 3. Conectar al origen
        respuesta_origen = requests.get(url_descarga_directa, stream=True, timeout=30)
        respuesta_origen.raise_for_status()
        
        # 4. Asignar nombre
        nombre_archivo = "transferencia.bin"
        if "Content-Disposition" in respuesta_origen.headers:
            matches = re.findall(r'filename="?([^"]+)"?', respuesta_origen.headers["Content-Disposition"])
            if matches:
                nombre_archivo = matches[0].strip()
        else:
            parsed_url = urllib.parse.urlparse(url_descarga_directa)
            nombre_url = os.path.basename(parsed_url.path)
            if nombre_url:
                nombre_archivo = urllib.parse.unquote(nombre_url)
            
        ruta_temporal = f"./{nombre_archivo}"

        # 5. Descarga por bloques al VPS (Optimizado para 512MB RAM)
        bot.send_message(chat_id, f"📥 Descargando temporalmente al VPS ({nombre_archivo})...")
        with open(ruta_temporal, 'wb') as f:
            for chunk in respuesta_origen.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    f.write(chunk)

        # 6. Subida final a MediaFire
        bot.send_message(chat_id, "📤 Subiendo archivo hacia MediaFire Pro...")
        destino_mf = f"mf:/{nombre_archivo}"
        mf_client.upload_file(ruta_temporal, destino_mf)

        # 7. Obtener enlace público
        link_final = None
        contenido_carpeta = mf_client.get_folder_contents_iter("mf:/")
        for item in contenido_carpeta:
            if item.get('filename') == nombre_archivo:
                link_final = f"https://www.mediafire.com/file/{item.get('quickkey')}/{nombre_archivo}/file"
                break

        if link_final:
            mensaje_exito = f"✅ **Transferencia Completada**\n\n📄 **Archivo:** {nombre_archivo}\n🔗 **Link:**\n{link_final}"
            bot.send_message(chat_id, mensaje_exito, parse_mode='Markdown', disable_web_page_preview=True)
        else:
            bot.send_message(chat_id, "⚠️ El archivo se subió, pero hubo un problema al generar el enlace de retorno.")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error crítico en el proceso: {str(e)}")
        
    finally:
        # 8. Limpieza estricta: Garantiza que el disco de Render quede en 0 bytes ocupados
        if ruta_temporal and os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)
            print(f"🧹 Archivo temporal {ruta_temporal} eliminado del sistema.")

# ==========================================
# 4. MOTOR DE COLA SECUENCIAL
# ==========================================
def trabajador_de_cola():
    global procesando_actualmente
    while True:
        if not cola_procesamiento.empty() and not procesando_actualmente:
            procesando_actualmente = True
            tarea = cola_procesamiento.get()
            
            procesar_transferencia(tarea['url'], tarea['chat_id'])
            
            cola_procesamiento.task_done()
            procesando_actualmente = False
        
        time.sleep(2)

# ==========================================
# 5. BOT DE TELEGRAM - INTERFAZ
# ==========================================
def extraer_enlaces(texto):
    patron_url = r'(https?://\S+)'
    return re.findall(patron_url, texto)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "¡Listo! El nodo Nexus Flow está activo en Render. Envíame links directamente o a través de un archivo .txt.")

@bot.message_handler(content_types=['text'])
def recibir_texto(message):
    enlaces_detectados = extraer_enlaces(message.text)
    
    if enlaces_detectados:
        for link in enlaces_detectados:
            cola_procesamiento.put({'chat_id': message.chat.id, 'url': link})
        bot.reply_to(message, f"🔍 {len(enlaces_detectados)} enlace(s) detectados. Añadidos a la cola.")

@bot.message_handler(content_types=['document'])
def recibir_documento(message):
    if message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "📄 Archivo TXT detectado. Extrayendo enlaces...")
        try:
            file_info = bot.get_file(message.document.file_id)
            archivo_descargado = bot.download_file(file_info.file_path)
            texto_archivo = archivo_descargado.decode('utf-8')
            
            enlaces_detectados = extraer_enlaces(texto_archivo)
            
            if enlaces_detectados:
                for link in enlaces_detectados:
                    cola_procesamiento.put({'chat_id': message.chat.id, 'url': link})
                bot.reply_to(message, f"✅ Lista procesada. {len(enlaces_detectados)} enlace(s) añadidos a la cola secuencial.")
            else:
                bot.reply_to(message, "⚠️ No encontré ningún enlace válido en el documento.")
        except Exception as e:
            bot.reply_to(message, f"❌ Error leyendo el archivo TXT: {str(e)}")

# ==========================================
# 6. INICIO DEL SISTEMA
# ==========================================
if __name__ == "__main__":
    hilo_web = threading.Thread(target=run_web_server)
    hilo_web.daemon = True
    hilo_web.start()

    hilo_worker = threading.Thread(target=trabajador_de_cola)
    hilo_worker.daemon = True
    hilo_worker.start()

    if bot:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
