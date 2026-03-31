from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import pyvista as pv
import streamlit as st
from supabase import create_client


# =========================================================
# Configuración
# =========================================================
st.set_page_config(
    page_title="Evaluación de Sonificación 4D Flow MRI",
    page_icon="🎧",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent
FILES_DIR = BASE_DIR / "FILES"

# Cambia este valor si quieres rotar la "sal" del hash local del token
TOKEN_HASH_SALT = st.secrets.get("TOKEN_HASH_SALT", "change-this-salt")


# =========================================================
# Supabase
# =========================================================
@st.cache_resource
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def hash_token(token: str) -> str:
    return hashlib.sha256(f"{TOKEN_HASH_SALT}:{token}".encode("utf-8")).hexdigest()


# =========================================================
# Archivos
# =========================================================
def resolve_file(*candidates: str) -> Path:
    search_dirs = [FILES_DIR, BASE_DIR]
    for directory in search_dirs:
        for name in candidates:
            path = directory / name
            if path.exists():
                return path

    searched = [str(directory / name) for directory in search_dirs for name in candidates]
    raise FileNotFoundError(
        "No se encontró ninguno de estos archivos. Rutas buscadas:\n- " + "\n- ".join(searched)
    )


@st.cache_data(show_spinner=False)
def load_bytes(path_str: str) -> bytes:
    return Path(path_str).read_bytes()


# =========================================================
# Render 3D
# =========================================================
def _surface_to_triangles(mesh: pv.DataSet):
    surface = mesh.extract_surface().triangulate()

    try:
        if surface.n_cells > 20000:
            surface = surface.decimate(0.7).triangulate()
    except Exception:
        pass

    points = surface.points
    faces = surface.faces.reshape(-1, 4)
    i = faces[:, 1]
    j = faces[:, 2]
    k = faces[:, 3]
    x = points[:, 0]
    y = points[:, 1]
    z = points[:, 2]
    return x, y, z, i, j, k


@st.cache_data(show_spinner=False)
def build_plotly_figure(path_str: str):
    mesh = pv.read(path_str)
    x, y, z, i, j, k = _surface_to_triangles(mesh)

    fig = go.Figure(
        data=[
            go.Mesh3d(
                x=x,
                y=y,
                z=z,
                i=i,
                j=j,
                k=k,
                opacity=1.0,
                hoverinfo="skip",
            )
        ]
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectmode="data",
            dragmode="orbit",
        ),
        showlegend=False,
    )
    return fig


def show_vtk(path: Path, key: str, height: int = 420) -> None:
    try:
        fig = build_plotly_figure(str(path))
        st.plotly_chart(fig, use_container_width=True, key=key)
    except Exception as e:
        st.error("No fue posible renderizar el archivo 3D.")
        st.caption(f"Archivo que falló: {path.name}")
        st.exception(e)


# =========================================================
# Datos locales
# =========================================================
EXAMPLE_VTK = resolve_file("carol_MRI.vtk")
EXAMPLE_VIDEO = resolve_file("carol_output.mp4")

PATIENTS = {
    "aaron": {
        "audio": resolve_file("aaron_output.mp3"),
        "vtk": resolve_file("aaron_MRI.vtk", "aaron_MRI.tvk"),
    },
    "edmund": {
        "audio": resolve_file("edmund_output.mp3"),
        "vtk": resolve_file("edmund_MRI.vtk"),
    },
    "phantoma": {
        "audio": resolve_file("phantoma_output.mp3"),
        "vtk": resolve_file("phantoma_MRI.vtk"),
    },
}

REAL_AUDIO_FOR_LABEL = {
    "A": "aaron",
    "B": "edmund",
    "C": "phantoma",
}


@dataclass
class TrialMapping:
    audio_labels: dict[str, str]
    vtk_labels: dict[str, str]


# =========================================================
# Tokens / invitaciones
# =========================================================
def get_query_token() -> str:
    token_values = st.query_params.get_all("token")
    return token_values[0].strip() if token_values else ""


def is_admin_mode() -> bool:
    vals = st.query_params.get_all("admin")
    return len(vals) > 0 and vals[0] == "1"


def get_token_record(token: str) -> dict[str, Any] | None:
    sb = get_supabase()
    token_h = hash_token(token)
    response = (
        sb.table("invite_tokens")
        .select("id, token_hash, is_active, used_at, note")
        .eq("token_hash", token_h)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def consume_token_and_save_response(
    token: str,
    result_rows: list[dict[str, Any]],
    utilidad_opinion: str,
    aporte_opinion: str,
    comentarios: str,
    rating: int,
) -> tuple[bool, str]:
    sb = get_supabase()
    token_h = hash_token(token)

    payload = {
        "token_hash_input": token_h,
        "result_rows_input": result_rows,
        "utilidad_opinion_input": utilidad_opinion,
        "aporte_opinion_input": aporte_opinion,
        "comentarios_input": comentarios.strip(),
        "rating_input": int(rating),
    }

    try:
        resp = sb.rpc("submit_sonification_response", payload).execute()
        data = resp.data
        if isinstance(data, dict) and data.get("ok") is True:
            return True, "ok"
        if isinstance(data, dict) and data.get("ok") is False:
            return False, data.get("message", "No fue posible guardar la respuesta.")
        return False, "No fue posible guardar la respuesta."
    except Exception as e:
        return False, f"Error al guardar la respuesta: {e}"


def create_invitation_tokens(n: int, note: str = "") -> list[dict[str, str]]:
    sb = get_supabase()
    created: list[dict[str, str]] = []

    for _ in range(n):
        raw_token = secrets.token_urlsafe(24)
        token_h = hash_token(raw_token)
        sb.table("invite_tokens").insert(
            {
                "token_hash": token_h,
                "is_active": True,
                "note": note.strip(),
            }
        ).execute()
        created.append({"token": raw_token})

    return created


# =========================================================
# Randomización por token
# =========================================================
def deterministic_mapping_for_token(token: str) -> TrialMapping:
    seed_int = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)

    audio_patients = ["aaron", "edmund", "phantoma"]
    vtk_patients = ["aaron", "edmund", "phantoma"]

    # Para el usuario: A/B/C siempre se muestran como A/B/C,
    # pero el contenido se baraja de forma determinística por token.
    import random

    rng1 = random.Random(seed_int)
    rng2 = random.Random(seed_int ^ 0xABCDEF)

    rng1.shuffle(audio_patients)
    rng2.shuffle(vtk_patients)

    return TrialMapping(
        audio_labels={"A": audio_patients[0], "B": audio_patients[1], "C": audio_patients[2]},
        vtk_labels={"1": vtk_patients[0], "2": vtk_patients[1], "3": vtk_patients[2]},
    )


# =========================================================
# Lógica de evaluación
# =========================================================
def validate_unique_answers(answers: dict[str, str]) -> tuple[bool, str]:
    values = list(answers.values())
    if any(v in ("", None) for v in values):
        return False, "Debes asignar una opción para A, B y C."
    if len(set(values)) != 3:
        return False, "No se pueden repetir los pacientes 1, 2 y 3."
    return True, ""


def build_result_rows(mapping: TrialMapping, answers: dict[str, str]) -> list[dict]:
    rows = []
    for audio_label in ["A", "B", "C"]:
        real_audio_patient = mapping.audio_labels[audio_label]
        chosen_vtk_label = answers[audio_label]
        chosen_vtk_patient = mapping.vtk_labels[chosen_vtk_label]
        is_correct = real_audio_patient == chosen_vtk_patient

        status = "BIEN ASIGNADO" if is_correct else "MAL ASIGNADO"
        summary = f"AUDIO {real_audio_patient.upper()} = VTK {chosen_vtk_patient.upper()} ({status})"

        rows.append(
            {
                "audio_label": audio_label,
                "audio_real_patient": real_audio_patient,
                "selected_vtk_label": chosen_vtk_label,
                "selected_vtk_real_patient": chosen_vtk_patient,
                "is_correct": is_correct,
                "assignment_summary": summary,
            }
        )
    return rows


# =========================================================
# Admin
# =========================================================
def check_admin_password() -> bool:
    expected = st.secrets["ADMIN_PASSWORD"]
    entered = st.text_input("Contraseña de administrador", type="password")
    if not entered:
        return False
    if hmac.compare_digest(entered, expected):
        return True
    st.error("Contraseña incorrecta.")
    return False


def admin_dashboard() -> None:
    st.title("Panel privado de resultados")

    if not check_admin_password():
        st.stop()

    sb = get_supabase()

    tab1, tab2, tab3 = st.tabs(["Resultados", "Invitaciones", "Exportar"])

    with tab1:
        responses = (
            sb.table("responses")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        ).data or []

        if not responses:
            st.info("Todavía no hay respuestas.")
        else:
            df = pd.DataFrame(responses)
            st.metric("Total de respuestas", len(df))

            if "rating" in df.columns and len(df) > 0:
                st.metric("Promedio nota 1-10", round(float(df["rating"].mean()), 2))

            if "correct_count" in df.columns and len(df) > 0:
                st.metric("Promedio aciertos", round(float(df["correct_count"].mean()), 2))

            st.dataframe(df, use_container_width=True)

    with tab2:
        st.subheader("Crear links únicos")
        with st.form("create_tokens_form"):
            n = st.number_input("Cantidad de links", min_value=1, max_value=500, value=10, step=1)
            note = st.text_input("Nota interna opcional", placeholder="Ej: ronda 1, cardiólogos, pilotos")
            base_url = st.text_input("URL base pública de la app", placeholder="https://tu-app.streamlit.app/")
            generate = st.form_submit_button("Generar links")

        if generate:
            created = create_invitation_tokens(int(n), note=note)
            if base_url.strip():
                normalized = base_url.strip().rstrip("/")
                links = [f"{normalized}/?token={row['token']}" for row in created]
                out_df = pd.DataFrame({"link_unico": links})
            else:
                out_df = pd.DataFrame(created)

            st.success(f"Se generaron {len(out_df)} links.")
            st.dataframe(out_df, use_container_width=True)
            st.download_button(
                "Descargar CSV de links",
                data=out_df.to_csv(index=False).encode("utf-8"),
                file_name="links_unicos_sonificacion.csv",
                mime="text/csv",
            )

        tokens = (
            sb.table("invite_tokens")
            .select("id, is_active, used_at, note, created_at")
            .order("created_at", desc=True)
            .execute()
        ).data or []
        if tokens:
            st.markdown("#### Estado de invitaciones")
            st.dataframe(pd.DataFrame(tokens), use_container_width=True)

    with tab3:
        responses = (
            sb.table("responses")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        ).data or []
        df = pd.DataFrame(responses)
        st.download_button(
            "Descargar respuestas CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="resultados_sonificacion.csv",
            mime="text/csv",
        )


# =========================================================
# Participante
# =========================================================
def participant_page() -> None:
    token = get_query_token()

    if not token:
        st.title("Link inválido")
        st.error("Este enlace no contiene un token válido.")
        st.stop()

    token_record = get_token_record(token)

    if token_record is None:
        st.title("Link inválido")
        st.error("Este link no existe o fue generado incorrectamente.")
        st.stop()

    if not token_record.get("is_active", False):
        st.title("Link deshabilitado")
        st.warning("Este link ya no está activo.")
        st.stop()

    if token_record.get("used_at") is not None:
        st.title("Encuesta ya respondida")
        st.info("Este link ya fue utilizado y no permite una segunda respuesta.")
        st.stop()

    mapping = deterministic_mapping_for_token(token)

    top_left, top_right = st.columns([4, 1])
    with top_left:
        st.title("Evaluación de tecnología de sonificación para 4D Flow MRI")
    with top_right:
        st.caption("Acceso único")

    st.markdown(
        """
Esta aplicación permite evaluar una tecnología de **sonificación** aplicada a datos de
**4D Flow MRI**. Primero se presenta un ejemplo de referencia. Luego se muestran
**3 audios** y **3 geometrías 3D** para que relaciones cada audio con la geometría correspondiente.

**Importante:** esto se evalúa solo como un **aporte complementario** al examen de resonancia magnética,
**sin pretender reemplazarlo**.
"""
    )

    st.divider()

    st.header("Ejemplo inicial")
    st.markdown(
        """
A continuación se muestra un caso de ejemplo **TEST**:

- A la izquierda: visualización 3D interactiva.
- A la derecha: video con la geometría y el sonido generado.
"""
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("TEST")
        show_vtk(EXAMPLE_VTK, key="example_vtk")
        st.caption("Puedes rotar, mover y hacer zoom sobre la geometría 3D.")
    with col2:
        st.subheader("Video de referencia")
        st.video(load_bytes(str(EXAMPLE_VIDEO)))

    st.divider()

    st.header("Asociación entre audio y geometría")
    st.markdown(
        """
Escucha los audios **A, B y C**. Luego observa las geometrías **1, 2 y 3**.
Después asigna qué geometría corresponde a cada audio.
"""
    )

    audio_cols = st.columns(3)
    for idx, audio_label in enumerate(["A", "B", "C"]):
        patient = mapping.audio_labels[audio_label]
        with audio_cols[idx]:
            st.subheader(f"Audio {audio_label}")
            st.audio(load_bytes(str(PATIENTS[patient]["audio"])), format="audio/mp3")

    st.markdown("### Geometrías 3D")
    vtk_cols = st.columns(3)
    for idx, vtk_label in enumerate(["1", "2", "3"]):
        patient = mapping.vtk_labels[vtk_label]
        with vtk_cols[idx]:
            st.subheader(f"Paciente {vtk_label}")
            show_vtk(PATIENTS[patient]["vtk"], key=f"vtk_{vtk_label}")

    st.divider()
    st.header("Formulario de evaluación")

    current_A = st.session_state.get("ans_A", "")
    current_B = st.session_state.get("ans_B", "")
    current_C = st.session_state.get("ans_C", "")
    all_opts = ["1", "2", "3"]

    def available_options(current_value: str, other_values: list[str]) -> list[str]:
        taken = {v for v in other_values if v}
        opts = [o for o in all_opts if (o == current_value or o not in taken)]
        return [""] + opts

    with st.form("evaluation_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)

        with c1:
            opts_A = available_options(current_A, [current_B, current_C])
            st.selectbox(
                "Audio A corresponde a",
                options=opts_A,
                index=0 if current_A == "" else opts_A.index(current_A),
                key="ans_A",
            )

        with c2:
            opts_B = available_options(current_B, [current_A, current_C])
            st.selectbox(
                "Audio B corresponde a",
                options=opts_B,
                index=0 if current_B == "" else opts_B.index(current_B),
                key="ans_B",
            )

        with c3:
            opts_C = available_options(current_C, [current_A, current_B])
            st.selectbox(
                "Audio C corresponde a",
                options=opts_C,
                index=0 if current_C == "" else opts_C.index(current_C),
                key="ans_C",
            )

        utilidad_opinion = st.radio(
            "¿Te parece útil esta tecnología como apoyo complementario al examen?",
            options=[
                "Sí, me parece útil",
                "No estoy seguro/a",
                "No, no me parece útil",
            ],
            horizontal=True,
        )

        aporte_opinion = st.radio(
            "¿Consideras que puede ser un aporte adicional a la resonancia magnética, sin reemplazarla?",
            options=[
                "Sí, puede ser un aporte adicional",
                "Tal vez, con más validación",
                "No lo considero un aporte",
            ],
            horizontal=True,
        )

        comentarios = st.text_area(
            "Comentarios adicionales",
            placeholder="Escribe aquí tus observaciones, sugerencias o interpretación general.",
            height=140,
        )

        rating = st.slider("Evalúa el proyecto de 1 a 10", min_value=1, max_value=10, value=7)

        submitted = st.form_submit_button("Enviar evaluación")

    if submitted:
        answers = {
            "A": st.session_state.get("ans_A", ""),
            "B": st.session_state.get("ans_B", ""),
            "C": st.session_state.get("ans_C", ""),
        }
        valid, msg = validate_unique_answers(answers)

        if not valid:
            st.error(msg)
            st.stop()

        result_rows = build_result_rows(mapping, answers)
        ok, message = consume_token_and_save_response(
            token=token,
            result_rows=result_rows,
            utilidad_opinion=utilidad_opinion,
            aporte_opinion=aporte_opinion,
            comentarios=comentarios,
            rating=rating,
        )

        if not ok:
            st.error(message)
            st.stop()

        st.success("Gracias por completar la evaluación.")
        st.markdown(
            """
<script>
setTimeout(function () {
    document.body.innerHTML =
        "<div style='font-family: Arial, sans-serif; text-align:center; padding-top:80px;'>"
        + "<h1>Gracias por completar la evaluación.</h1>"
        + "<p>Tu respuesta fue registrada correctamente.</p>"
        + "<p>Esta invitación ya no permite una segunda respuesta.</p>"
        + "</div>";
}, 1200);
</script>
""",
            unsafe_allow_html=True,
        )
        st.stop()


# =========================================================
# Router
# =========================================================
def main():
    if is_admin_mode():
        admin_dashboard()
    else:
        participant_page()


if __name__ == "__main__":
    main()
