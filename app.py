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
st.set_page_config(page_title="Control de Vuelos NOP + Radar (SANA/SAFA)", layout="wide")

# --- ESTILOS CSS PARA TABLAS COMPACTAS Y SCROLL HORIZONTAL ---
st.markdown("""
    <style>
    .block-container { padding-top: 1.5rem; padding-bottom: 1.5rem; }
    div[data-testid="stDataFrame"] { width: 100%; overflow-x: auto; }
    div[data-testid="stTable"] { font-size: 12px; }
    th, td { padding: 4px 8px !important; white-space: nowrap !important; }
    </style>
""", unsafe_allow_html=True)

st.title("✈️ Control de Vuelos NOP + Radar en Tiempo Real (AESA SAFA/SANA)")

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

# --- GENERACIÓN DE PDF EXPORTABLE ---
def generar_pdf_objetivos(lista_vuelos):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=10)
    
    # Cabecera del Documento
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.cell(0, 8, "AESA - Inspeccion SANA / SAFA", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, f"Reporte de Objetivos Guardados - Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    # Anchos de columna para A4 Apaisado
    col_widths = [14, 10, 16, 14, 18, 12, 12, 14, 20, 50, 18, 20, 18, 18, 23]
    headers = ["Hora", "Tipo", "ARCID", "Tipo Ac", "Matricula", "ADEP", "ADES", "Prefix", "Cod Ext", "Operador", "Obj", "Insp Real", "Obj 2026", "Rest", "Ult Insp"]

    pdf.set_font("Helvetica", style="B", size=7)
    pdf.set_fill_color(220, 230, 242)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 6, h, border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", size=6.5)
    for row in lista_vuelos:
        tipo_str = "DEP (Salida)" if "⬆" in str(row.get("Tipo", "")) else "ARR (Llegada)"
        
        pdf.cell(col_widths[0], 5, str(row.get("Hora", "")), border=1, align="C")
        pdf.cell(col_widths[1], 5, "DEP" if "DEP" in tipo_str else "ARR", border=1, align="C")
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

# --- PARSER COMPLETO DEL PDF NOP ---
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
        st.warning(f"Extracción por tabla con aviso: {e}. Reintentando...")

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
    headers = {"User-Agent": "ControlVuelosTracker/1.0"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            ac_list = data.get("ac", [])
            if ac_list:
                ac = ac_list[0]
                return {
                    "hex": ac.get("hex"),
                    "callsign": ac.get("flight", "N/A").strip(),
                    "lat": ac.get("lat"),
                    "lon": ac.get("lon"),
                    "altitud_ft": ac.get("alt_baro"),
                    "velocidad_kts": ac.get("gs"),
                    "rumbo": ac.get("track"),
                    "en_vuelo": ac.get("gs", 0) > 30 if ac.get("gs") else False
                }
    except Exception as e:
        st.error(f"Error consultando telemetría para {matricula}: {e}")
    return None

# --- INICIALIZAR ESTADO DE SESIÓN ---
if "vuelos_guardados" not in st.session_state:
    st.session_state["vuelos_guardados"] = cargar_objetivos_guardados()

tab1, tab2 = st.tabs(["📋 Cargar PDF NOP y Seleccionar", "📡 Radar y Vuelos Guardados"])

with tab1:
    st.header("Cargar Listado NOP y Selección de Vuelos")
    uploaded_file = st.file_uploader("Sube el PDF NOP filtrado", type=["pdf"])
    
    if uploaded_file:
        with st.spinner("Extrayendo vuelos y calculando horas de inspección..."):
            df_vuelos, base_ap = parse_nop_pdf(uploaded_file)
            
        if not df_vuelos.empty:
            st.success(f"✅ Se extrajeron {len(df_vuelos)} vuelos. Aeropuerto base detectado: **{base_ap}**")
            st.info("ℹ️ **Cálculo de horas:** Las llegadas (⬇️) mantienen la hora del archivo. Las salidas (⬆️) tienen 1 hora restada para la inspección.")
            st.caption("Marca la casilla 'Seleccionar' en las filas que desees guardar:")
            
            edited_df = st.data_editor(
                df_vuelos,
                column_config={
                    "Seleccionar": st.column_config.CheckboxColumn(
                        "Seleccionar",
                        help="Marca para guardar este vuelo",
                        default=False,
                    ),
                    "Tipo": st.column_config.TextColumn("Tipo", help="⬆️ Salida | ⬇️ Llegada", width="small")
                },
                disabled=[col for col in df_vuelos.columns if col != "Seleccionar"],
                hide_index=True,
                use_container_width=True
            )
            
            if st.button("💾 Guardar Vuelos Seleccionados"):
                seleccionados = edited_df[edited_df["Seleccionar"] == True].to_dict("records")
                
                if seleccionados:
                    existentes = {f"{v['Hora']}_{v['ARCID']}_{v['Matricula']}": v for v in st.session_state["vuelos_guardados"]}
                    for item in seleccionados:
                        key = f"{item['Hora']}_{item['ARCID']}_{item['Matricula']}"
                        item_clean = {k: v for k, v in item.items() if k != "Seleccionar"}
                        existentes[key] = item_clean
                    
                    st.session_state["vuelos_guardados"] = list(existentes.values())
                    guardar_objetivos_disco(st.session_state["vuelos_guardados"])
                    st.success(f"¡Se han guardado {len(seleccionados)} vuelos en el sistema!")
                else:
                    st.warning("No has marcado ninguna casilla para guardar.")
        else:
            st.error("Error al extraer los datos del PDF. Verifica el archivo.")

with tab2:
    st.header("Seguimiento de Flota Guardada")
    
    with st.expander("➕ Añadir matrícula manual (opcional)"):
        col_m1, col_m2 = st.columns([3, 1])
        with col_m1:
            mat_manual = st.text_input("Matrícula:", placeholder="ej: EC-NGX")
            arcid_manual = st.text_input("ARCID / Callsign (opcional):", placeholder="ej: HRN125")
            tipo_manual = st.selectbox("Tipo de vuelo:", ["⬇️ Llegada", "⬆️ Salida"])
            hora_manual = st.text_input("Hora de inspección (HH:MM):", placeholder="ej: 14:30")
        with col_m2:
            st.write(" ")
            st.write(" ")
            if st.button("Añadir Vuelo"):
                if mat_manual:
                    nuevo_item = {
                        "Hora": hora_manual if hora_manual else "Manual",
                        "Tipo": "⬆️" if "Salida" in tipo_manual else "⬇️",
                        "ARCID": arcid_manual.upper() if arcid_manual else mat_manual.upper(),
                        "Aeronave": "N/D",
                        "Matricula": mat_manual.upper().strip(),
                        "ADEP": "N/D",
                        "ADES": "N/D",
                        "prefix3": "",
                        "Código externo": "",
                        "Operador (maestro)": "Vuelo Privado / Manual",
                        "Tipo objetivo": "Privado",
                        "Inspecciones realizadas": "-",
                        "Objetivo 2026": "-",
                        "Restantes": "-",
                        "Última inspección": "-"
                    }
                    st.session_state["vuelos_guardados"].append(nuevo_item)
                    guardar_objetivos_disco(st.session_state["vuelos_guardados"])
                    st.success(f"Añadida matrícula {mat_manual.upper()}")
                    st.rerun()

    if st.session_state["vuelos_guardados"]:
        df_guardados = pd.DataFrame(st.session_state["vuelos_guardados"])
        
        st.subheader("📋 Datos Guardados de los Vuelos Seleccionados")
        st.caption("💡 Puedes hacer doble clic sobre las celdas de Operador, Tipo Objetivo, Inspecciones, Restantes y Última inspección para editarlas directamente.")
        
        # Columnas que NO se pueden modificar para evitar desconfigurar el seguimiento ADS-B
        cols_bloqueadas = ["Hora", "Tipo", "ARCID", "Aeronave", "Matricula", "ADEP", "ADES", "prefix3", "Código externo"]
        cols_editables = [col for col in df_guardados.columns if col not in cols_bloqueadas]
        
        # Editor interactivo de datos guardados
        df_guardados_editado = st.data_editor(
            df_guardados,
            disabled=cols_bloqueadas,
            hide_index=True,
            use_container_width=True,
            key="editor_guardados"
        )
        
        col_btn_save, col_btn_pdf = st.columns([1, 1])
        with col_btn_save:
            if st.button("💾 Guardar Cambios Editados"):
                st.session_state["vuelos_guardados"] = df_guardados_editado.to_dict("records")
                guardar_objetivos_disco(st.session_state["vuelos_guardados"])
                st.success("¡Datos de inspección actualizados correctamente!")
                st.rerun()

        with col_btn_pdf:
            pdf_data = generar_pdf_objetivos(st.session_state["vuelos_guardados"])
            fecha_str = datetime.now().strftime("%Y%m%d_%H%M")
            
            st.download_button(
                label="📄 Descargar Objetivos Guardados en PDF",
                data=pdf_data,
                file_name=f"Objetivos_SANA_SAFA_{fecha_str}.pdf",
                mime="application/pdf"
            )
        
        st.markdown("---")
        st.subheader("📡 Radar de Seguimiento en Tiempo Real")
        
        opciones_rastreo = [f"{row.get('Tipo', '')} {row['Matricula']} | {row['ARCID']} | Hora insp: {row['Hora']} ({row['ADEP']} ➔ {row['ADES']})" for row in st.session_state["vuelos_guardados"]]
        
        col_sel, col_del = st.columns([4, 1])
        with col_sel:
            idx_seleccionado = st.selectbox("Selecciona un vuelo guardado para consultar su radar:", range(len(opciones_rastreo)), format_func=lambda x: opciones_rastreo[x])
        
        vuelo_target = st.session_state["vuelos_guardados"][idx_seleccionado]
        mat_target = vuelo_target["Matricula"]
        
        with col_del:
            st.write(" ")
            st.write(" ")
            if st.button("🗑️ Eliminar este vuelo"):
                vuelo_eliminado = st.session_state["vuelos_guardados"].pop(idx_seleccionado)
                guardar_objetivos_disco(st.session_state["vuelos_guardados"])
                st.success(f"Vuelo {vuelo_eliminado['Matricula']} ({vuelo_eliminado['ARCID']}) eliminado correctamente.")
                st.rerun()
        
        if st.button("📡 Rastrear Posición Actual"):
            with st.spinner(f"Consultando red ADS-B abierta para {mat_target}..."):
                pos = consultar_telemetria_adsb(mat_target)
                if pos and pos["lat"] and pos["lon"]:
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Callsign", pos["callsign"])
                    m2.metric("Altitud", f"{pos['altitud_ft']} ft" if pos['altitud_ft'] is not None else "N/A")
                    m3.metric("Velocidad", f"{pos['velocidad_kts']} kts" if pos['velocidad_kts'] is not None else "N/A")
                    m4.metric("Estado", "En Vuelo" if pos["en_vuelo"] else "En Tierra / Detectado")
                    
                    st.write(f"**Coordenadas:** Lat {pos['lat']}, Lon {pos['lon']} | **Hex Code:** `{pos['hex']}`")
                    
                    m = folium.Map(
                        location=[pos["lat"], pos["lon"]],
                        zoom_start=9,
                        tiles="CartoDB positron"
                    )

                    popup_html = f"""
                    <div style="font-family: Arial; font-size: 12px; width: 180px;">
                        <b>Matrícula:</b> {mat_target}<br>
                        <b>Callsign:</b> {pos['callsign']}<br>
                        <b>Altitud:</b> {pos['altitud_ft']} ft<br>
                        <b>Velocidad:</b> {pos['velocidad_kts']} kts<br>
                        <b>Rumbo:</b> {pos['rumbo']}°
                    </div>
                    """

                    folium.Marker(
                        location=[pos["lat"], pos["lon"]],
                        popup=folium.Popup(popup_html, max_width=200),
                        tooltip=f"✈️ {mat_target} ({pos['callsign']})",
                        icon=folium.Icon(color="red" if pos["en_vuelo"] else "blue", icon="plane", prefix="fa")
                    ).add_to(m)

                    st_folium(m, width=1100, height=500, returned_objects=[])
                else:
                    st.warning(f"La aeronave {mat_target} no está emitiendo señal ADS-B en directo en este momento.")

        st.markdown("---")
        if st.button("🗑️ Borrar Todos los Vuelos Guardados"):
            st.session_state["vuelos_guardados"] = []
            guardar_objetivos_disco([])
            st.rerun()
    else:
        st.info("No hay vuelos guardados. Ve a la pestaña anterior, sube el PDF y marca las casillas de los vuelos que desees seguir.")