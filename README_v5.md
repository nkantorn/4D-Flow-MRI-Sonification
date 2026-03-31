# Sonificación 4D Flow MRI - v5 con links únicos y panel privado

Esta versión permite:

- acceso por **link único** usando `?token=...`
- **una sola respuesta por link**
- resultados visibles solo para el administrador
- respuestas **anónimas**
- panel privado para generar invitaciones y exportar resultados

## 1) Estructura del proyecto

```text
sonificacion_v5/
├── streamlit_app_v5.py
├── requirements_v5.txt
├── supabase_schema_v5.sql
└── FILES/
    ├── aaron_output.mp3
    ├── edmund_output.mp3
    ├── phantoma_output.mp3
    ├── carol_output.mp4
    ├── aaron_MRI.vtk   # o aaron_MRI.tvk
    ├── carol_MRI.vtk
    ├── edmund_MRI.vtk
    └── phantoma_MRI.vtk
```

## 2) Crear proyecto en Supabase

1. Crea un proyecto en Supabase.
2. Abre el SQL Editor.
3. Ejecuta completo el archivo `supabase_schema_v5.sql`.

## 3) Secrets de Streamlit

Crea `.streamlit/secrets.toml` con este contenido:

```toml
SUPABASE_URL = "https://TU-PROYECTO.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "TU_SERVICE_ROLE_KEY"
ADMIN_PASSWORD = "pon_aqui_una_password_larga"
TOKEN_HASH_SALT = "otra_cadena_larga_y_privada"
```

## 4) Instalar y ejecutar local

```bash
pip install -r requirements_v5.txt
streamlit run streamlit_app_v5.py
```

## 5) Uso

### Participante
Se entra con un link como:

```text
https://tu-app.streamlit.app/?token=TOKEN_UNICO
```

Si el token ya fue usado, la app bloquea una segunda respuesta.

### Administrador
Entra con:

```text
https://tu-app.streamlit.app/?admin=1
```

Ahí podrás:
- ver resultados
- generar links únicos
- exportar CSV
- ver el estado de las invitaciones

## 6) Despliegue

Puedes desplegar en Streamlit Community Cloud o en otra plataforma compatible con Streamlit.

Asegúrate de:
- subir la carpeta `FILES/`
- configurar los secrets en la plataforma
- usar una URL pública estable

## 7) Anonimato

Esta implementación:
- no guarda nombre
- no guarda email
- no guarda IP en la base de datos del proyecto
- no guarda una relación directa entre respuesta e invitación

Sí guarda:
- timestamp
- respuestas
- comentarios
- nota
- estado de uso del token

Con eso puedes impedir duplicados por invitación sin saber quién respondió qué.

## 8) Límite importante

Si una persona comparte su link con otra antes de responder, cualquiera de las dos podría usarlo primero.
La garantía es **una respuesta por token**, no verificación de identidad personal.
