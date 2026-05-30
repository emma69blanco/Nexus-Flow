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

# Credenciales de API de Telegram
API_ID = 38106196
API_HASH = "30cfa1bb153d49728b4c060eea2e167d"

if not BOT_TOKEN:
    print("⚠️ ADVERTENCIA: BOT_TOKEN no encontrado en las variables de entorno.")

# ==========================================
# 2. SERVIDOR WEB (FLASK) - DISEÑO LIMPIO
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
                <p>El puente de archivos Telegram ➔ MediaFire está en línea.</p>
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

# Diccionarios para manejar el sistema de "paquetes"
temporizador_paquetes = {}
videos_por_usuario = {}

# ==========================================
# 4. LÓGICA DE MEDIAFIRE
# ==========================================
def operacion_mediafire(ruta_local, nombre_archivo):
    """ Función aislada para ejecutar la subida a MediaFire """
    try:
        mf_client = MediaFireClient()
        mf_client.login(email=MF_EMAIL, password=MF_PASSWORD, app_id='42511')
        
        # Mantenemos la carpeta destino que configuraste en tu código original
        carpeta_destino = "Subidas_Telegram"
        
        try:
            mf_client.create_folder(f"mf:/{carpeta_destino}")
        except:
            pass # Si ya existe, se ignora el error
            
        destino_mf = f"mf:/{carpeta_destino}/{nombre_archivo}"
        mf_client.upload_file(ruta_local, destino_mf)
        
        contenido_carpeta = mf_client.get_folder_contents_iter(f"mf:/{carpeta_destino}")
        for item in contenido_carpeta:
            if item.get('filename') == nombre_archivo:
                return f"https://www.mediafire.com/file/{item.get('quickkey')}/{nombre_archivo}/file"
        return None
    except Exception as e:
        return str(e)

# ==========================================
# 5. MOTOR DE PROCESAMIENTO DE PAQUETES
# ==========================================
async def procesar_paquete(chat_id):
    lista_videos = videos_por_usuario.get(chat_id, [])
    total = len(lista_videos)
    if total == 0: 
        return

    # Vaciamos la lista para próximos paquetes
    videos_por_usuario[chat_id] = []
    
    mensaje_estado = await bot.send_message(
        chat_id, 
        f"🚀 **Procesando paquete de {total} archivo(s)...**\nPor favor espera, no envíes nada más hasta recibir el reporte."
    )

    enlaces_finales = []

    for i, mensaje_video in enumerate(lista_videos, 1):
        await mensaje_estado.edit_text(f"📥 **Archivo {i}/{total}:** Descargando desde Telegram al disco del VPS...")
        ruta_local = None
        
        try:
            # Descarga gestionada por bloques directamente de Pyrogram
            ruta_local = await bot.download_media(mensaje_video)
            
            if ruta_local:
                nombre_archivo = os.path.basename(ruta_local)
                await mensaje_estado.edit_text(f"📤 **Archivo {i}/{total}:** Subiendo a MediaFire Pro...\n`{nombre_archivo}`")
                
                # Ejecutamos la subida en un hilo paralelo para no congelar Telegram
                resultado = await asyncio.to_thread(operacion_mediafire, ruta_local, nombre_archivo)
                
                if resultado and resultado.startswith("http"):
                    enlaces_finales.append(f"✅ **Archivo {i}:** {resultado}")
                else:
                    enlaces_finales.append(f"⚠️ **Archivo {i}:** Falló la generación de link.\nDetalle: {resultado}")
            else:
                enlaces_finales.append(f"❌ **Archivo {i}:** Error al descargar de Telegram.")
                
        except Exception as e:
            enlaces_finales.append(f"❌ **Archivo {i}:** Error crítico - {str(e)}")
            
        finally:
            # LIMPIEZA INMEDIATA: Garantiza que se borre antes de bajar el siguiente video
            if ruta_local and os.path.exists(ruta_local):
                os.remove(ruta_local)
                print(f"🧹 Archivo temporal {ruta_local} destruido con éxito.")

    # GENERADOR DE REPORTE FINAL
    reporte_base = "🎉 **¡PAQUETE COMPLETADO!**\n\nAquí tienes tus enlaces para guardar:\n\n"
    reporte_texto = reporte_base + "\n\n".join(enlaces_finales)

    try:
        # Sistema inteligente para evitar el límite de Telegram
        if len(reporte_texto) > 4000:
            await mensaje_estado.edit_text("📝 **El reporte es muy largo.** Generando archivo TXT seguro...")
            nombre_txt = f"reporte_enlaces_{chat_id}.txt"
            
            with open(nombre_txt, "w", encoding="utf-8") as f:
                f.write(f"🎉 ¡PAQUETE COMPLETADO!\nTotal de archivos procesados: {total}\n")
                f.write("========================================\n\n")
                for line in enlaces_finales:
                    linea_limpia = line.replace("**", "").replace("✅ ", "")
                    f.write(f"{linea_limpia}\n")
                    
            await bot.send_document(
                chat_id=chat_id,
                document=nombre_txt,
                caption=f"📦 **¡Aquí tienes tu reporte masivo!**\nSe procesaron **{total}** archivos."
            )
            if os.path.exists(nombre_txt):
                os.remove(nombre_txt)
        else:
            await bot.send_message(chat_id, reporte_texto, disable_web_page_preview=True)
            
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Error al enviar el reporte final: {e}")
        
    finally:
        await mensaje_estado.delete()

# Temporizador para agrupar múltiples envíos rápidos
async def esperar_paquete(chat_id):
    await asyncio.sleep(5)
    await procesar_paquete(chat_id)

# ==========================================
# 6. INTERFAZ DE USUARIO (COMANDOS)
# ==========================================
@bot.on_message(filters.command("start") & filters.private)
async def cmd_start(client, message):
    await message.reply_text("🟢 **¡Sistema Activo!**\nEnvíame videos o archivos pesados y los subiré directamente a tu carpeta única en MediaFire.")

@bot.on_message((filters.video | filters.document) & filters.private)
async def recibir_videos(client, message):
    chat_id = message.chat.id
    
    # Crear el espacio para el usuario si no existe
    if chat_id not in videos_por_usuario:
        videos_por_usuario[chat_id] = []
        
    videos_por_usuario[chat_id].append(message)
    
    # Cancelar el contador anterior si envía otro archivo rápido
    if chat_id in temporizador_paquetes:
        temporizador_paquetes[chat_id].cancel()
        
    # Iniciar un nuevo contador de 5 segundos
    temporizador_paquetes[chat_id] = asyncio.create_task(esperar_paquete(chat_id))

# ==========================================
# 7. INICIO ASÍNCRONO DEL SISTEMA (PARCHE APLICADO)
# ==========================================
async def iniciar_sistema():
    # 1. Servidor Web
    hilo_web = threading.Thread(target=run_web_server)
    hilo_web.daemon = True
    hilo_web.start()
    print("🌐 Servidor web Flask iniciado.")

    # 2. Iniciar Bot de Pyrogram
    await bot.start()
    print("🤖 Bot de Telegram en línea y esperando paquetes.")
    
    # 3. Mantener corriendo
    await idle()
    await bot.stop()

if __name__ == "__main__":
    if BOT_TOKEN:
        try:
            # PARCHE: asyncio.run() crea y maneja correctamente el bucle en Python 3.10+
            asyncio.run(iniciar_sistema())
        except KeyboardInterrupt:
            print("🛑 Sistema detenido manualmente.")
    else:
        print("❌ Error crítico: Falta BOT_TOKEN en las variables de entorno.")
