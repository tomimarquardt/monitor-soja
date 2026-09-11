import sqlite3
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from datetime import date

app = Flask(__name__)
CORS(app)

def consultar_historico_db(dias=30):
    try:
        conn = sqlite3.connect("soja_historico.db")
        cursor = conn.cursor()
        cursor.execute("SELECT fecha, precio FROM cotizaciones ORDER BY fecha DESC LIMIT ?", (dias,))
        filas = cursor.fetchall()
        conn.close()
        filas.reverse()
        fechas = [f[0] for f in filas]
        precios = [f[1] for f in filas]
        return fechas, precios
    except Exception as e:
        print(f"Error DB: {e}")
        return [], []

def generar_proyeccion_diaria_matba(precio_spot, dias, escenario):
    import numpy as np
    tasa = 0.0008 if escenario == "neutral" else (0.0015 if escenario == "alcista" else -0.0005)
    precios = [precio_spot * ((1 + tasa) ** i) for i in range(1, dias + 1)]
    fechas = [f"Día {i}" for i in range(1, dias + 1)]
    return fechas, precios

@app.route("/api/datos", methods=["GET"])
def obtener_datos():
    dias_hist = int(request.args.get("dias", 30))
    meses_fut = int(request.args.get("futuro", 3))
    escenario = request.args.get("escenario", "neutral")

    # 1. Scraping del precio Spot en vivo desde Pizarra BCR
    precio_bcr = None
    try:
        url = "https://www.cac.bcr.com.ar/es/precios-de-pizarra"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for fila in soup.find_all(["tr", "div"]):
                texto = fila.get_text()
                if "Soja" in texto and "$" in texto:
                    partes = texto.split("$")
                    for p in partes[1:]:
                        num_str = p.split()[0].replace(".", "").replace(",", ".")
                        try:
                            valor = float(num_str)
                            if valor > 100000:
                                precio_bcr = valor
                                break
                        except ValueError:
                            continue
                if precio_bcr:
                    break
    except Exception as e:
        print(f"Error scraping BCR: {e}")

    # 2. Guardar precio en la DB local si se obtuvo
    if precio_bcr:
        fecha_hoy = date.today().strftime("%Y-%m-%d")
        try:
            conn = sqlite3.connect("soja_historico.db")
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS cotizaciones (fecha TEXT PRIMARY KEY, precio REAL)"
            )
            cursor.execute(
                "INSERT OR REPLACE INTO cotizaciones (fecha, precio) VALUES (?, ?)",
                (fecha_hoy, precio_bcr)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error guardando DB: {e}")

    # 3. Traer datos históricos
    etiquetas_hist, valores_hist = consultar_historico_db(dias_hist)
    precio_spot = precio_bcr if precio_bcr else (valores_hist[-1] if valores_hist else 560000.0)

    if not valores_hist:
        etiquetas_hist = [date.today().strftime("%Y-%m-%d")]
        valores_hist = [precio_spot]

    # 4. Proyección
    dias_futuro = meses_fut * 30
    etiquetas_fut, valores_fut = generar_proyeccion_diaria_matba(precio_spot, dias_futuro, escenario)

    # 5. Respuesta
    contexto = {
        "fuente": "Pizarra BCR (Bolsa de Comercio de Rosario)",
        "alerta": "Mercado físico oficial de la Cámara Arbitral.",
        "detalle": f"Cotización spot extraída de Pizarra BCR: ${precio_spot:,.2f} $/Tn."
    }

    return jsonify({
        "historico": {"fechas": etiquetas_hist, "precios": valores_hist},
        "proyeccion": {"fechas": etiquetas_fut, "precios": valores_fut},
        "spot_actual": precio_spot,
        "escenario": escenario,
        "contexto": contexto
    })

if __name__ == "__main__":
    app.run(debug=True)