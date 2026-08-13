import streamlit as st
import pandas as pd
import pdfplumber
import pypdf
import re
import requests
import json
import streamlit.components.v1 as components

# Configuración de página
st.set_page_config(page_title="Cruce Objetivos - Control de Vuelos", layout="wide")

st.title("✈️ Control de Vuelos NOP + Radar en Tiempo Real")

# --- PERSISTENCIA LOCAL EN EL NAVEGADOR (localStorage) ---
def guardar_seleccion_local(lista_matriculas):
    json_str = json.dumps(lista_matriculas)
    components.html(
        f"""
        <script>
        localStorage.setItem('vuelos_guardados_nop', '{json_str}');
        </script>
        """,
        height=0
    )

# --- FUNCIÓN ROBUTA DE PARSEO DE PDF NOP ---
def parse_nop_pdf(uploaded_file):
    records = []
    
    # Intento 1: Extracción mediante pdfplumber (Especializado en Tablas)
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 5:
                            continue
                        
                        # Limpiar saltos de línea dentro de las celdas
                        clean_row = [str(cell).replace('\n', ' ').strip() if cell else '' for cell in row]
                        
                        # Detectar si la celda 0 tiene formato de hora (ej: 00:01)
                        if re.match(r'^\d{2}:\d{2}$', clean_row[0]):
                            records.append({
                                "Hora": clean_row[0],
                                "ARCID": clean_row[1] if len(clean_row) > 1 else "",
                                "Aeronave": clean_row[2] if len(clean_row) > 2 else "",
                                "Matricula": clean_row[3] if len(clean_row) > 3 else "",
                                "ADEP": clean_row[4] if len(clean_row) > 4 else "",
                                "ADES": clean_row[5] if len(clean_row) > 5 else "",
                                "Operador": clean_row[8] if len(clean_row) > 8 else (clean_row[7] if len(clean_row) > 7 else "")
                            })
    except Exception as e:
        st.warning(f"Aviso en pdfplumber: {e}. Probando método secundario...")

    # Intento 2 (Fallback): Regex directo por tokens sobre pypdf si el intento 1 devolvió vacío
    if not records:
        uploaded_file.seek(0)
        reader = pypdf.PdfReader(uploaded_file)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
            
        lines = full_text.split('\n')
        for line in lines:
            line_str = line.strip()
            # Patrón para identificar filas que inician con hora HH:MM y capturar matrículas
            match = re.search(r'(\d{2}:\d{2})\s+([A-Z0-9]+)\s+([A-Z0-9]+)\s+([A-Z0-9-]+)\s+([A-Z]{4})\s+([A-Z]{4})', line_str)
            if match:
                hora, arcid, aeronave, matricula, adep, ades = match.groups()
                records.append({
                    "Hora": hora,
                    "ARCID": arcid,
                    "Aeronave": aeronave,
                    "Matricula": matricula,
                    "ADEP": adep,
                    "ADES": ades,
                    "Operador": "N/D"
                })

    df = pd.DataFrame(records)
    if not df.empty:
        # Filtrar encabezados residuales y matrículas no válidas
        df = df[df["Matricula"].str.contains(r'[A-Z0-9]', na=False)]
        df = df.drop_duplicates(subset=["Hora", "ARCID", "Matricula"]).reset_index(drop=True)
    return df

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

# --- NAVEGACIÓN Y ESTADO DE SESIÓN ---
if "vuelos_objetivo" not in st.session_state:
    st.session_state["vuelos_objetivo"] = []

tab1, tab2 = st.tabs(["📋 Cargar PDF NOP y Seleccionar", "📡 Radar y Seguimiento Guardado"])

with tab1:
    st.header("Cargar Listado NOP Filtrado")
    uploaded_file = st.file_uploader("Sube el PDF de tráfico (ej. NOP filtrado.pdf)", type=["pdf"])
    
    if uploaded_file:
        with st.spinner("Procesando y extrayendo las tablas del PDF..."):
            df_vuelos = parse_nop_pdf(uploaded_file)
            
        if not df_vuelos.empty:
            st.success(f"✅ Se han extraído correctamente {len(df_vuelos)} vuelos del documento.")
            
            # Buscador y selector múltiple
            matriculas_unicas = sorted(df_vuelos["Matricula"].unique().tolist())
            
            seleccionadas = st.multiselect(
                "Selecciona las aeronaves que deseas guardar para seguimiento permanente:",
                options=matriculas_unicas,
                default=[m for m in st.session_state["vuelos_objetivo"] if m in matriculas_unicas]
            )
            
            if st.button("💾 Guardar Selección para Seguimiento"):
                st.session_state["vuelos_objetivo"] = list(set(st.session_state["vuelos_objetivo"] + seleccionadas))
                guardar_seleccion_local(st.session_state["vuelos_objetivo"])
                st.success(f"¡Guardadas {len(st.session_state['vuelos_objetivo'])} aeronaves en la memoria local!")
            
            # Mostrar tabla procesada
            st.subheader("Lista Completa Extraída")
            st.dataframe(df_vuelos[["Hora", "ARCID", "Aeronave", "Matricula", "ADEP", "ADES", "Operador"]], use_container_width=True)
        else:
            st.error("Error: No se pudieron extraer datos del PDF. Verifica que el archivo no esté protegido o vacío.")

with tab2:
    st.header("Seguimiento de Flota Guardada")
    
    # Permitir añadir matrículas ejecutivas/privadas manualmente sin re-subir el PDF
    col_input, col_add = st.columns([3, 1])
    with col_input:
        nueva_mat = st.text_input("Añadir matrículas privadas directamente (separadas por coma):", placeholder="ej: EC-NGX, N800KS, CS-PHV")
    with col_add:
        st.write(" ")
        st.write(" ")
        if st.button("Añadir"):
            if nueva_mat:
                m_list = [m.strip().upper() for m in nueva_mat.split(",") if m.strip()]
                st.session_state["vuelos_objetivo"] = list(set(st.session_state["vuelos_objetivo"] + m_list))
                guardar_seleccion_local(st.session_state["vuelos_objetivo"])
                st.rerun()

    if st.session_state["vuelos_objetivo"]:
        st.write(f"**Aeronaves en seguimiento ({len(st.session_state['vuelos_objetivo'])}):**")
        st.info(", ".join(sorted(st.session_state["vuelos_objetivo"])))
        
        target = st.selectbox("Selecciona la aeronave a rastrear:", sorted(st.session_state["vuelos_objetivo"]))
        
        if st.button("📡 Rastrear Posición Actual"):
            with st.spinner(f"Consultando red ADS-B en vivo para {target}..."):
                pos = consultar_telemetria_adsb(target)
                if pos and pos["lat"] and pos["lon"]:
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Callsign", pos["callsign"])
                    m2.metric("Altitud", f"{pos['altitud_ft']} ft" if pos['altitud_ft'] is not None else "N/A")
                    m3.metric("Velocidad", f"{pos['velocidad_kts']} kts" if pos['velocidad_kts'] is not None else "N/A")
                    m4.metric("Estado", "En Vuelo" if pos["en_vuelo"] else "En Tierra / Emitiendo")
                    
                    st.write(f"**Coordenadas:** Lat {pos['lat']}, Lon {pos['lon']} | **Hex Code ICAO:** `{pos['hex']}`")
                    
                    # Mapa centrado
                    df_map = pd.DataFrame([{"lat": pos["lat"], "lon": pos["lon"]}])
                    st.map(df_map, zoom=8)
                else:
                    st.warning(f"La aeronave {target} no está emitiendo señal ADS-B en directo o se encuentra en tierra sin cobertura activa.")
                    
        if st.button("🗑️ Limpiar Flota Guardada"):
            st.session_state["vuelos_objetivo"] = []
            guardar_seleccion_local([])
            st.rerun()
    else:
        st.info("No hay aeronaves en seguimiento. Sube el PDF en la primera pestaña o añade matrículas manualmente.")