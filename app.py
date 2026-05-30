import os
import threading
import time
import re
import requests
from queue import Queue
from flask import Flask
import telebot

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

# Cola global para asegurar el procesamiento secuencial (uno por uno)
cola_procesamiento = Queue()
procesando_actualmente = False

# ==========================================
# 2. SERVIDOR WEB (FLASK) - KEEP ALIVE
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
# 3. LÓGICA DE TRANSFERENCIA (CORE BRIDGE)
# ==========================================
def obtener_sesion_mediafire():
    """ Inicia sesión en MediaFire Pro obteniendo cookies y tokens previos """
    sesion = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        # Visitar primero para obtener cookies
        res_get = sesion.get("https://www.mediafire.com/login", headers=headers, timeout=15)
        
        login_url = "https://www.mediafire.com/dynamic/login.php"
        payload = {
            'login_email': MF_EMAIL,
            'login_pass': MF_PASSWORD,
            'submit_login': '1'
        }
        
        # Extraer token de seguridad dinámico si existe
        token_match = re.search(r'name="security_token"\s+value="([^"]+)"', res_get.text)
        if token_match:
            payload['security_token'] = token_match.group(1)
            
        respuesta = sesion.post(login_url, data=payload, headers=headers, timeout=15)
        
        if "user" in respuesta.text.lower() or "myfiles" in respuesta.url:
            return sesion
        return None
    except Exception as e:
        print(f"Error crítico en login MediaFire: {e}")
        return None

def extraer_enlace_directo_origen(url_origen):
    """ Obtiene el link directo, con soporte para descargas """
    try:
        # Soporte para extraer el botón directo si el origen es de MediaFire
        if "mediafire.com" in url_origen:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            res = requests.get(url_origen, headers=headers, timeout=15)
            match = re.search(r'id="downloadButton"\s+href="([^"]+)"', res.text)
            if match:
                return match.group(1)
                
        # Para otros enlaces que ya sean directos, se retorna tal cual
        return url_origen 
    except Exception:
        return None

def procesar_transferencia(url_origen, chat_id):
    """ Maneja la descarga y subida por bloques simultáneos """
    try:
        bot.send_message(chat_id, f"🔄 Iniciando procesamiento de:\n{url_origen}")
        
        url_descarga_directa = extraer_enlace_directo_origen(url_origen)
        if not url_descarga_directa:
            bot.send_message(chat_id, "❌ Error: No se pudo resolver el enlace de origen.")
            return

        sesion_mf = obtener_sesion_mediafire()
        if not sesion_mf:
            bot.send_message(chat_id, "❌ Error: Fallo de autenticación en MediaFire Pro. Revisa el correo/contraseña.")
            return

        respuesta_origen = requests.get(url_descarga_directa, stream=True, timeout=30)
        respuesta_origen.raise_for_status()
        
        nombre_archivo = "transferencia_bridge.bin"
        if "Content-Disposition" in respuesta_origen.headers:
            matches = re.findall("filename=(.+)", respuesta_origen.headers["Content-Disposition"])
            if matches: nombre_archivo = matches[0].strip('"').strip("'")

        # Generador de bloques por flujo constante (8MB)
        def generador_streaming():
            for chunk in respuesta_origen.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    yield chunk

        api_upload_url = "https://www.mediafire.com/api/1.5/upload/simple.php"
        upload_headers = {
            'x-filename': nombre_archivo,
            'x-filesize': respuesta_origen.headers.get('Content-Length', '0')
        }
        
        bot.send_message(chat_id, "⚡ Transfiriendo archivo en tránsito continuo (sin guardar en disco VPS)...")
        
        respuesta_subida = sesion_mf.post(api_upload_url, headers=upload_headers, data=generador_streaming())
        
        if respuesta_subida.status_code == 200:
            datos_mf = respuesta_subida.json()
            # MediaFire devuelve el key del archivo subido en 'quickkey'
            key = datos_mf.get('response', {}).get('quickkey', '')
            if not key:
                key = datos_mf.get('quickkey', 'DESCONOCIDO')
                
            link_final = f"https://www.mediafire.com/file/{key}/{nombre_archivo}"
            
            mensaje_exito = f"✅ **Transferencia Completada**\n\n📄 **Archivo:** {nombre_archivo}\n🔗 **Link MediaFire:**\n{link_final}"
            bot.send_message(chat_id, mensaje_exito, parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "⚠️ El archivo pasó, pero hubo un error obteniendo el link público.")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Error crítico en el puente: {str(e)}")

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
# 5. BOT DE TELEGRAM - INTERFAZ DE USUARIO
# ==========================================
def extraer_enlaces(texto):
    patron_url = r'(https?://\S+)'
    return re.findall(patron_url, texto)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "¡Listo! El nodo de transferencia está activo en Render. Envíame links directamente o a través de un archivo .txt.")

@bot.message_handler(content_types=['text'])
def recibir_texto(message):
    enlaces_detectados = extraer_enlaces(message.text)
    
    if enlaces_detectados:
        for link in enlaces_detectados:
            cola_procesamiento.put({'chat_id': message.chat.id, 'url': link})
        bot.reply_to(message, f"🔍 {len(enlaces_detectados)} enlace(s) detectados. Añadidos a la cola.")
    else:
        pass

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
# 6. INICIO DEL SISTEMA (HILOS DUALES)
# ==========================================
if __name__ == "__main__":
    hilo_web = threading.Thread(target=run_web_server)
    hilo_web.daemon = True
    hilo_web.start()
    print("🌐 Servidor web Flask iniciado.")

    hilo_worker = threading.Thread(target=trabajador_de_cola)
    hilo_worker.daemon = True
    hilo_worker.start()
    print("⚙️ Motor de cola secuencial iniciado.")

    if bot:
        print("🤖 Bot de Telegram en línea y esperando comandos.")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    else:
        print("❌ El sistema se detuvo porque no hay BOT_TOKEN.")
