import streamlit as st
import pandas as pd
import pypdf
import re
import requests
import json
import streamlit.components.v1 as components

# Configuración de página
st.set_page_config(page_title="Cruce Objetivos - Flight Tracking", layout="wide")

st.title("✈️ Cruce de Objetivos + Seguimiento en Tiempo Real")

# --- COMPONENTE PERSISTENCIA (localStorage) ---
# Permite guardar las matrículas seleccionadas en el navegador del usuario
def cargar_seleccion_local():
    return components.html(
        """
        <script>
        const saved = localStorage.getItem('vuelos_guardados');
        if (saved) {
            window.parent.postMessage({type: 'streamlit:setComponentValue', value: JSON.parse(saved)}, '*');
        }
        </script>
        """,
        height=0
    )

def guardar_seleccion_local(lista_matriculas):
    json_str = json.dumps(lista_matriculas)
    components.html(
        f"""
        <script>
        localStorage.setItem('vuelos_guardados', '{json_str}');
        </script>
        """,
        height=0
    )

# --- FUNCIÓN DE PARSEO DE PDF NOP ---
def parse_nop_pdf(uploaded_file):
    reader = pypdf.PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    
    lines = text.split('\n')
    data = []
    
    # Expresión regular para extraer columnas clave de las filas de tráfico
    pattern = re.compile(r'^(\d{2}:\d{2})\s+([A-Z0-9]+)\s+([A-Z0-9]+)\s+([A-Z0-9-]+)\s+([A-Z]{4})\s+([A-Z]{4})')
    
    for line in lines:
        match = pattern.match(line.strip())
        if match:
            hora, arcid, aeronave, matricula, adep, ades = match.groups()
            data.append({
                "Hora": hora,
                "ARCID": arcid,
                "Aeronave": aeronave,
                "Matricula": matricula,
                "ADEP": adep,
                "ADES": ades,
                "Linea_Completa": line
            })
            
    return pd.DataFrame(data)

# --- MÓDULO DE RASTREO ADS-B (Sin censura) ---
def consultar_telemetria_adsb(matricula):
    """
    Consulta la API abierta de adsb.lol por matrícula para evitar censura
    de aviación ejecutiva/privada.
    """
    url = f"https://api.adsb.lol/v2/reg/{matricula.strip().upper()}"
    headers = {"User-Agent": "CruceObjetivosTracker/1.0"}
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
        st.error(f"Error consultando la telemetría de {matricula}: {e}")
    return None

# --- ESTRUCTURA DE PESTAÑAS DE LA APLICACIÓN ---
tab1, tab2 = st.tabs(["📋 Cargar y Seleccionar Vuelos", "📡 Radar de Seguimiento Guardado"])

# Inicializar Estado
if "vuelos_objetivo" not in st.session_state:
    st.session_state["vuelos_objetivo"] = []

with tab1:
    st.header("Carga del archivo PDF NOP")
    uploaded_file = st.file_uploader("Sube el archivo NOP filtrado.pdf", type=["pdf"])
    
    if uploaded_file:
        df = parse_nop_pdf(uploaded_file)
        if not df.empty:
            st.success(f"Se procesaron {len(df)} vuelos correctamente.")
            
            # Selector múltiple con buscador integrado
            matriculas_disponibles = df["Matricula"].unique().tolist()
            seleccionadas = st.multiselect(
                "Selecciona las aeronaves/matrículas a las que deseas hacer seguimiento:",
                options=matriculas_disponibles,
                default=st.session_state["vuelos_objetivo"]
            )
            
            if st.button("💾 Guardar Selección en Navegador"):
                st.session_state["vuelos_objetivo"] = seleccionadas
                guardar_seleccion_local(seleccionadas)
                st.success(f"¡Guardadas {len(seleccionadas)} aeronaves para seguimiento permanente!")
            
            # Vista previa del DataFrame cargado
            st.dataframe(df[["Hora", "ARCID", "Aeronave", "Matricula", "ADEP", "ADES"]], use_container_width=True)
        else:
            st.error("No se pudieron extraer datos del PDF. Verifica el formato del archivo.")

with tab2:
    st.header("Seguimiento de Flota Seleccionada")
    
    # Campo manual o sincronizado para agregar matrículas directamente
    input_manual = st.text_input("Añadir matrícula privada directamente (separadas por coma):", "")
    if input_manual:
        m_list = [m.strip().upper() for m in input_manual.split(",") if m.strip()]
        st.session_state["vuelos_objetivo"] = list(set(st.session_state["vuelos_objetivo"] + m_list))
    
    if st.session_state["vuelos_objetivo"]:
        st.write(f"**Aeronaves en seguimiento permanente ({len(st.session_state['vuelos_objetivo'])}):**")
        st.write(", ".join(st.session_state["vuelos_objetivo"]))
        
        target_selected = st.selectbox("Selecciona una aeronave para consultar su radar:", st.session_state["vuelos_objetivo"])
        
        if st.button("📡 Rastrear Posición Actual"):
            with st.spinner(f"Consultando red ADS-B abierta para {target_selected}..."):
                pos = consultar_telemetria_adsb(target_selected)
                if pos and pos["lat"] and pos["lon"]:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Callsign", pos["callsign"])
                    c2.metric("Altitud", f"{pos['altitud_ft']} ft" if pos['altitud_ft'] else "N/A")
                    c3.metric("Velocidad", f"{pos['velocidad_kts']} kts" if pos['velocidad_kts'] else "N/A")
                    c4.metric("Estado", "En Vuelo" if pos["en_vuelo"] else "En Tierra / Detectado")
                    
                    # Dibujar mapa interactivo centrado
                    map_df = pd.DataFrame([{"lat": pos["lat"], "lon": pos["lon"]}])
                    st.map(map_df, zoom=8)
                else:
                    st.warning(f"La aeronave {target_selected} no está emitiendo señal en directo o está fuera de cobertura ADS-B.")
    else:
        st.info("No hay aeronaves guardadas. Carga un PDF en la pestaña anterior o añade matrículas manualmente.")