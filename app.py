import streamlit as st
import pandas as pd
import pdfplumber
import pypdf
import re
import requests
import json
import os
from datetime import datetime, timedelta
from collections import Counter
import folium
from streamlit_folium import st_folium
from fpdf import FPDF

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Gestor de Registros", layout="wide")

# --- ESTILOS CSS PARA TABLAS COMPACTAS Y SCROLL HORIZONTAL ---
st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 1.5rem; }
    div[data-testid="stDataFrame"] { width: 100%; overflow-x: auto; }
    div[data-testid="stTable"] { font-size: 12px; }
    th, td { padding: 4px 8px !important; white-space: nowrap !important; }
    </style>
""", unsafe_allow_html=True)

st.title("📊 Gestor de Registros y Consultas")

STORAGE_FILE = "saved_targets.json"

# --- FUNCIONES DE PERSISTENCIA EN DISCO ---
def cargar_objetivos_guardados():
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_objetivos_disco(lista_objetivos):
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(lista_objetivos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Error guardando datos: {e}")

# --- AJUSTE DE HORA SEGÚN TIPO DE VUELO ---
def ajustar_hora(hora_str, es_salida):
    if not re.match(r'^\d{2}:\d{2}$', str(hora_str).strip()):
        return hora_str
    if es_salida:
        try:
            t = datetime.strptime(hora_str.strip(), "%H:%M")
            t_menos_1h = t - timedelta(hours=1)
            return t_menos_1h.strftime("%H:%M")
        except Exception:
            return hora_str
    return hora_str

# --- GENERACIÓN DE PDF EXPORTABLE "POSIBLES OBJETIVOS" ---
def generar_pdf_objetivos(lista_vuelos):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=10)

    # Anchos de columna para A4 Apaisado (~277mm de área imprimible)
    col_widths = [14, 10, 16, 14, 18, 12, 12, 14, 20, 50, 18, 20, 18, 18, 23]
    headers = ["Hora", "Tipo", "ARCID", "Aeronave", "Matricula", "ADEP", "ADES", "prefix3", "Cod Ext", "Operador (maestro)", "Tipo obj", "Insp Real", "Obj 2026", "Rest", "Ult Insp"]

    # Cabecera directa de la tabla (sin títulos o logos adicionales)
    pdf.set_font("Helvetica", style="B", size=7)
    pdf.set_fill_color(230, 230, 230)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 6, h, border=1, align="C", fill=True)
    pdf.ln()

    # Filas de datos
    pdf.set_font("Helvetica", size=6.5)
    for row in lista_vuelos:
        tipo_str = "DEP" if "⬆" in str(row.get("Tipo", "")) else "ARR"
        
        pdf.cell(col_widths[0], 5, str(row.get("Hora", "")), border=1, align="C")
        pdf.cell(col_widths[1], 5, tipo_str, border=1, align="C")
        pdf.cell(col_widths[2], 5, str(row.get("ARCID", ""))[:10], border=1, align="C")
        pdf.cell(col_widths[3], 5, str(row.get("Aeronave", ""))[:8], border=1, align="C")
        pdf.cell(col_widths[4], 5, str(row.get("Matricula", ""))[:10], border=1, align="C")
        pdf.cell(col_widths[5], 5, str(row.get("ADEP", ""))[:4], border=1, align="C")
        pdf.cell(col_widths[6], 5, str(row.get("ADES", ""))[:4], border=1, align="C")
        pdf.cell(col_widths[7], 5, str(row.get("prefix3", ""))[:8], border=1, align="C")
        pdf.cell(col_widths[8], 5, str(row.get("Código externo", ""))[:10], border=1, align="C")
        pdf.cell(col_widths[9], 5, str(row.get("Operador (maestro)", ""))[:32], border=1, align="L")
        pdf.cell(col_widths[10], 5, str(row.get("Tipo objetivo", ""))[:10], border=1, align="C")
        pdf.cell(col_widths[11], 5, str(row.get("Inspecciones realizadas", "")), border=1, align="C")
        pdf.cell(col_widths[12], 5, str(row.get("Objetivo 2026", "")), border=1, align="C")
        pdf.cell(col_widths[13], 5, str(row.get("Restantes", "")), border=1, align="C")
        pdf.cell(col_widths[14], 5, str(row.get("Última inspección", "")), border=1, align="C")
        pdf.ln()

    return bytes(pdf.output())

# --- PARSER DEL PDF ---
def parse_nop_pdf(uploaded_file):
    raw_records = []
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 5:
                            continue
                        
                        clean_row = [str(cell).replace('\n', ' ').strip() if cell is not None else '' for cell in row]
                        
                        if re.match(r'^\d{2}:\d{2}$', clean_row[0]):
                            while len(clean_row) < 14:
                                clean_row.append("")
                                
                            raw_records.append({
                                "Hora_Orig": clean_row[0],
                                "ARCID": clean_row[1],
                                "Aeronave": clean_row[2],
                                "Matricula": clean_row[3],
                                "ADEP": clean_row[4],
                                "ADES": clean_row[5],
                                "prefix3": clean_row[6],
                                "Código externo": clean_row[7],
                                "Operador (maestro)": clean_row[8],
                                "Tipo objetivo": clean_row[9],
                                "Inspecciones realizadas": clean_row[10],
                                "Objetivo 2026": clean_row[11],
                                "Restantes": clean_row[12],
                                "Última inspección": clean_row[13]
                            })
    except Exception as e:
        st.warning(f"Aviso en procesamiento secundario: {e}")

    if not raw_records:
        uploaded_file.seek(0)
        reader = pypdf.PdfReader(uploaded_file)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
            
        lines = full_text.split('\n')
        for line in lines:
            line_str = line.strip()
            match = re.search(r'(\d{2}:\d{2})\s+([A-Z0-9]+)\s+([A-Z0-9]+)\s+([A-Z0-9-]+)\s+([A-Z]{4})\s+([A-Z]{4})', line_str)
            if match:
                hora, arcid, aeronave, matricula, adep, ades = match.groups()
                raw_records.append({
                    "Hora_Orig": hora,
                    "ARCID": arcid,
                    "Aeronave": aeronave,
                    "Matricula": matricula,
                    "ADEP": adep,
                    "ADES": ades,
                    "prefix3": "",
                    "Código externo": "",
                    "Operador (maestro)": "",
                    "Tipo objetivo": "",
                    "Inspecciones realizadas": "",
                    "Objetivo 2026": "",
                    "Restantes": "",
                    "Última inspección": ""
                })

    if not raw_records:
        return pd.DataFrame(), None

    aeropuertos = []
    for r in raw_records:
        if len(r["ADEP"]) == 4:
            aeropuertos.append(r["ADEP"])
        if len(r["ADES"]) == 4:
            aeropuertos.append(r["ADES"])
            
    base_airport = Counter(aeropuertos).most_common(1)[0][0] if aeropuertos else "LEMD"

    final_records = []
    for r in raw_records:
        es_salida = (r["ADEP"] == base_airport)
        flecha = "⬆️" if es_salida else "⬇️"
        hora_calculada = ajustar_hora(r["Hora_Orig"], es_salida)
        
        final_records.append({
            "Seleccionar": False,
            "Hora": hora_calculada,
            "Tipo": flecha,
            "ARCID": r["ARCID"],
            "Aeronave": r["Aeronave"],
            "Matricula": r["Matricula"],
            "ADEP": r["ADEP"],
            "ADES": r["ADES"],
            "prefix3": r["prefix3"],
            "Código externo": r["Código externo"],
            "Operador (maestro)": r["Operador (maestro)"],
            "Tipo objetivo": r["Tipo objetivo"],
            "Inspecciones realizadas": r["Inspecciones realizadas"],
            "Objetivo 2026": r["Objetivo 2026"],
            "Restantes": r["Restantes"],
            "Última inspección": r["Última inspección"]
        })

    df = pd.DataFrame(final_records)
    df = df[df["Matricula"].str.contains(r'[A-Z0-9]', na=False)]
    df = df.drop_duplicates(subset=["Hora", "ARCID", "Matricula"]).reset_index(drop=True)
    return df, base_airport

# --- CONSULTA TELEMETRÍA ADS-B ABIERTA ---
def consultar_telemetria_adsb(matricula):
    url = f"https://api.adsb.lol/v2/reg/{matricula.strip().upper()}"
    headers = {"User-Agent": "SystemDataLookup/1.0"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            ac_list = data.get("ac", [])
            if ac_list:
                ac = ac_list[0]
                return {
                    "hex": ac.get("hex"),
                    "callsign": ac.get("flight