import os
import threading
import asyncio
from flask import Flask
from pyrogram import Client, filters, idle
from mediafire.client import MediaFireClient

# ==========================================
# 1. CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==========================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
MF_EMAIL = os.environ.get('MF_EMAIL')
MF_PASSWORD = os.environ.get('MF_PASSWORD')

# Credenciales de API de Telegram (Motor Pyrogram)
API_ID = 38106196
API_HASH = "30cfa1bb153d49728b4c060eea2e167d"

if not BOT_TOKEN:
    print("⚠️ ADVERTENCIA: BOT_TOKEN no encontrado en las variables de entorno.")

# ==========================================
# 2. SERVIDOR WEB (FLASK) - DISEÑO PROFESIONAL
# ==========================================
app_web = Flask(__name__)

@app_web.route('/')
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
                <p>El puente Telegram ➔ MediaFire está en línea y operando.</p>
            </div>
        </body>
    </html>
    """
    return html_content

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    app_web.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ==========================================
# 3. MOTOR DE TELEGRAM (PYROGRAM)
# ==========================================
bot = Client(
    "nexus_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

cola_procesamiento = asyncio.Queue()

# ==========================================
# 4. LÓGICA DE TRANSFERENCIA Y LIMPIEZA
# ==========================================
def operacion_mediafire(ruta_local, nombre_archivo):
    """ Función síncrona que se ejecuta en un hilo separado para no bloquear el bot """
    try:
        mf_client = MediaFireClient()
        mf_client.login(email=MF_EMAIL, password=MF_PASSWORD, app_id='42511')
        
        destino_mf = f"mf:/{nombre_archivo}"
        mf_client.upload_file(ruta_local, destino_mf)
        
        # Buscar el archivo recién subido
        contenido_carpeta = mf_client.get_folder_contents_iter("mf:/")
        for item in contenido_carpeta:
            if item.get('filename') == nombre_archivo:
                return f"https://www.mediafire.com/file/{item.get('quickkey')}/{nombre_archivo}/file"
        return None
    except Exception as e:
        return str(e)

async def trabajador_de_cola():
    """ Procesa los archivos uno por uno secuencialmente """
    while True:
        mensaje = await cola_procesamiento.get()
        chat_id = mensaje.chat.id
        
        msg_estado = await bot.send_message(chat_id, "🔄 Preparando entorno para la transferencia...")
        ruta_local = ""
        
        try:
            # 1. Descarga segura al disco temporal (Evita saturar la RAM)
            await msg_estado.edit_text("📥 Descargando archivo al nodo seguro por bloques...")
            ruta_local = await mensaje.download()
            nombre_archivo = os.path.basename(ruta_local)

            # 2. Subida a MediaFire (usando asyncio.to_thread para no congelar Telegram)
            await msg_estado.edit_text(f"📤 Subiendo hacia MediaFire Pro:\n`{nombre_archivo}`")
            
            resultado = await asyncio.to_thread(operacion_mediafire, ruta_local, nombre_archivo)
            
            # 3. Entrega de resultados
            if resultado and resultado.startswith("http"):
                texto_exito = f"✅ **Transferencia Completada**\n\n📄 **Archivo:** `{nombre_archivo}`\n🔗 **Link MediaFire:**\n{resultado}"
                await msg_estado.edit_text(texto_exito, disable_web_page_preview=True)
            else:
                await msg_estado.edit_text(f"⚠️ Error en la generación del link de MediaFire. Detalles:\n{resultado}")

        except Exception as e:
            await msg_estado.edit_text(f"❌ Error crítico en el proceso: {str(e)}")
            
        finally:
            # 4. Limpieza estricta: Garantiza que el disco del VPS se vacíe
            if ruta_local and os.path.exists(ruta_local):
                os.remove(ruta_local)
                print(f"🧹 Archivo temporal {ruta_local} destruido.")
            
            cola_procesamiento.task_done()

# ==========================================
# 5. RECEPCIÓN DE ARCHIVOS (INTERFAZ)
# ==========================================
@bot.on_message(filters.command("start") & filters.private)
async def cmd_start(client, message):
    await message.reply_text("¡Listo! El nodo de transferencia de archivos pesados está activo. Envíame cualquier video o documento.")

@bot.on_message((filters.video | filters.document) & filters.private)
async def recibir_archivos(client, message):
    await cola_procesamiento.put(message)
    await message.reply_text("🔍 Archivo recibido de forma segura. Añadido a la cola secuencial.")

# ==========================================
# 6. INICIO ASÍNCRONO DEL SISTEMA DUAL
# ==========================================
async def iniciar_sistema():
    # 1. Levantar la interfaz web en un hilo paralelo
    hilo_web = threading.Thread(target=run_web_server)
    hilo_web.daemon = True
    hilo_web.start()
    print("🌐 Servidor web Flask iniciado.")

    # 2. Iniciar el bot de Telegram
    await bot.start()
    print("🤖 Bot de Telegram en línea.")

    # 3. Iniciar el procesador secuencial de archivos pesados
    asyncio.create_task(trabajador_de_cola())
    print("⚙️ Motor de cola secuencial asíncrona iniciado.")

    # 4. Mantener el sistema vivo y a la escucha
    await idle()
    await bot.stop()

if __name__ == "__main__":
    if BOT_TOKEN:
        # Iniciar el bucle de eventos asíncronos nativo de Python
        loop = asyncio.get_event_loop()
        loop.run_until_complete(iniciar_sistema())
    else:
        print("❌ El sistema se detuvo porque no hay BOT_TOKEN configurado.")
