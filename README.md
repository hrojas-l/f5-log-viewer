# F5 XC Log Viewer

Sistema de extracción y análisis de logs de F5 Distributed Cloud (XC) con backend en FastAPI, frontend web y gestión multi-tenant de credenciales API.

## Características

- **Gestión multi-tenant**: Administración de múltiples tenants de F5 XC con credenciales API independientes
- **Extracción masiva de logs**: Descarga bulk de logs de F5 Distributed Cloud API con control de rangos de tiempo
- **Almacenamiento estructurado**: Base de datos SQLite para gestión de tenants
- **Interface web intuitiva**: Frontend para configuración de tenants, ejecución de extracciones y visualización de logs
- **Filtrado y búsqueda**: Capacidades de filtrado por fecha, tenant, tipo de evento y campos personalizados
- **Exportación de datos**: Generación de reportes y exportación en formato CSV

## Arquitectura

- **Backend**: FastAPI + SQLAlchemy + SQLite. Punto de entrada en `main.py`
- **Frontend**: HTML/CSS/JavaScript
- **Base de datos**: SQLite para almacenamiento de configuración y logs
- **API Integration**: Cliente HTTP para consumo de F5 Distributed Cloud API

## Estructura del Proyecto

```
f5-xc-log-viewer/
├── backend/
│   ├── f5-xc-export-access-logs.py
│   ├── f5-xc-export-audit-logs.py
│   ├── f5-xc-export-security-event-logs.py
│   ├── log_fetchers.py
│   ├── main.py                     # Aplicación FastAPI
│   ├── requirements.txt            # Dependencias Python
│   └── .env.example                # Variables de entorno (ejemplo)
├── frontend/
│   ├── index.html                  # Página principal
│   └── script.js
├── data/
│   └── logs.db                     # Base de datos SQLite
└── README.md
```

## Requisitos

- Python 3.9+
- pip
- Credenciales de API de F5 Distributed Cloud (API Token por tenant)

## Configuración Rápida

### Backend (API)

1. **Crear y activar entorno virtual**:
   ```bash
   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   
   # Windows
   py -m venv venv
   venv\Scripts\activate
   ```

2. **Instalar dependencias**:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. **Configurar variables de entorno**:
   ```bash
   cp backend/.env.example backend/.env
   # Editar .env con tus configuraciones
   ```

4. **Ejecutar la aplicación**:
   ```bash
   cd backend
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Acceder a la documentación interactiva**:
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

### Frontend (Web)

1. **Configurar URL del backend**:
   ```javascript
   // Editar frontend/js/config.js
   const API_BASE_URL = 'http://localhost:8000';
   ```

2. **Servir archivos estáticos**:
   ```bash
   # Opción 1: Python SimpleHTTPServer
   cd frontend
   python -m http.server 8080
   
   # Opción 2: Usar el servidor FastAPI para servir estáticos
   # (configurado en main.py)
   ```

3. **Acceder a la aplicación**:
   - Abrir http://localhost:8080 (o el puerto configurado)

## Variables de Entorno

### Backend (`backend/.env`)

```env
# Base de datos
DATABASE_URL=sqlite:///./data/logs.db

# F5 XC API Configuration
F5_XC_API_BASE_URL=https://[tenant].console.ves.volterra.io/api

# Seguridad
SECRET_KEY=tu-clave-secreta-para-encriptacion
ENCRYPTION_ALGORITHM=fernet

# Configuración del servidor
HOST=0.0.0.0
PORT=8000
DEBUG=True

# Elasticsearch (futuro)
ELASTICSEARCH_HOST=localhost
ELASTICSEARCH_PORT=9200
ELASTICSEARCH_ENABLED=False
```

## Uso

### 1. Gestión de Tenants

**Agregar un nuevo tenant**:
```bash
POST /api/tenants
{
  "name": "Producción",
  "f5_tenant_name": "mi-tenant-f5",
  "api_token": "tu-api-token-aqui",
  "description": "Ambiente de producción"
}
```

**Listar tenants**:
```bash
GET /api/tenants
```

**Probar conectividad**:
```bash
GET /api/tenants/{tenant_id}/test-connection
```

### 2. Extracción de Logs

**Iniciar extracción masiva**:
```bash
POST /api/logs/extract
{
  "tenant_id": 1,
  "start_date": "2024-12-01T00:00:00Z",
  "end_date": "2024-12-31T23:59:59Z",
  "log_types": ["access", "security", "system"]
}
```

**Consultar estado de extracción**:
```bash
GET /api/logs/jobs/{job_id}
```

### 3. Consulta y Análisis

**Buscar logs**:
```bash
GET /api/logs/search?tenant_id=1&start_date=2024-12-01&keyword=error
```

**Filtros disponibles**:
- `tenant_id`: ID del tenant
- `start_date` / `end_date`: Rango de fechas
- `log_level`: INFO, WARNING, ERROR, CRITICAL
- `source`: Origen del log
- `keyword`: Búsqueda de texto libre

**Exportar resultados**:
```bash
GET /api/logs/export?format=csv&tenant_id=1&start_date=2024-12-01
```

## Integración con F5 Distributed Cloud API

El sistema consume los siguientes endpoints de F5 XC:

- **Authentication**: Token-based authentication con API credentials
- **Log Retrieval**: `/api/data/namespaces/{namespace}/logs`
- **Metadata**: `/api/config/namespaces/{namespace}/metadata`

### Ejemplo de credenciales F5 XC

```json
{
  "tenant": "mi-organizacion",
  "api_token": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "namespace": "default"
}
```

## Licencia

Proyecto interno de Ngeek - Todos los derechos reservados.
