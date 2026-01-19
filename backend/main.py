from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import os
import glob
import time
import sqlite3
import requests
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any
import json

# Importar función optimizada
from log_fetchers import fetch_access_logs

app = FastAPI(title="F5 XC Log Viewer")

# Permitir peticiones desde cualquier origen (útil para frontend local)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directorio donde se guardarán los CSV generados
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Base de datos SQLite
DB_PATH = os.path.join(os.getcwd(), "tenants.db")

# ==========================================
# CONFIGURACIÓN ELASTICSEARCH
# ==========================================
ELASTICSEARCH_CONFIG = {
    "url": "http://192.168.0.200:9200",
    # Método de autenticación: "api_key" o "basic"
    # "auth_method": "api_key",
    # "api_key": "tu_api_key_aqui",
    # O usar credenciales básicas:
    # "auth_method": "basic",
    # "username": "elastic",
    # "password": "tu_password_aqui",
}

# Mapeo de tipos de log a índices de Elasticsearch
ELK_INDICES = {
    "access": "f5xc-access-logs",
    "audit": "f5xc-audit-logs",
    "security": "f5xc-security-events"
}

# ==========================================
# MODELOS PYDANTIC
# ==========================================
class TenantToken(BaseModel):
    tenant: str
    token: str

class TenantUpdate(BaseModel):
    token: str

class ElkConfig(BaseModel):
    url: str
    auth_method: Optional[str] = "api_key"  # "api_key" o "basic"
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

class ElkSendRequest(BaseModel):
    log_type: str
    tenant: str
    namespace: str
    loadbalancer: Optional[str] = None
    hours: int = 24

# ==========================================
# FUNCIONES DE BASE DE DATOS
# ==========================================
@contextmanager
def get_db():
    """Context manager para conexiones a la base de datos"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Inicializar la base de datos"""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Tabla para configuración de ELK
        conn.execute("""
            CREATE TABLE IF NOT EXISTS elk_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                url TEXT NOT NULL,
                auth_method TEXT DEFAULT 'api_key',
                api_key TEXT,
                username TEXT,
                password TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

# Inicializar DB al arrancar
@app.on_event("startup")
def startup_event():
    init_db()
    print(f"[INFO] Base de datos inicializada en: {DB_PATH}")
    print(f"[INFO] Elasticsearch configurado en: {ELASTICSEARCH_CONFIG['url']}")

# ==========================================
# FUNCIONES AUXILIARES ELASTICSEARCH
# ==========================================
def get_elk_auth():
    """
    Obtiene la configuración de autenticación para Elasticsearch.
    Retorna: (url, headers, auth)
    - headers: diccionario con Authorization header si usa API Key
    - auth: tupla (user, pass) si usa Basic Auth, None en caso contrario
    """
    # Primero intenta obtener de la base de datos
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT url, auth_method, api_key, username, password 
            FROM elk_config WHERE id = 1
        """)
        row = cursor.fetchone()
    
    if row and row['url']:
        config = {
            "url": row['url'],
            "auth_method": row['auth_method'] or 'api_key',
            "api_key": row['api_key'],
            "username": row['username'],
            "password": row['password']
        }
    else:
        # Usa configuración por defecto
        config = ELASTICSEARCH_CONFIG
    
    headers = {"Content-Type": "application/json"}
    auth = None
    
    # Configurar autenticación según el método
    auth_method = config.get('auth_method', 'api_key')
    
    if auth_method == 'api_key' and config.get('api_key'):
        headers["Authorization"] = f"ApiKey {config['api_key']}"
    elif auth_method == 'basic' and config.get('username') and config.get('password'):
        auth = (config['username'], config['password'])
    
    return config['url'], headers, auth

def send_to_elasticsearch_bulk(logs: List[Dict[Any, Any]], index_name: str, batch_size: int = 5000) -> Dict[str, Any]:
    """
    Envía logs a Elasticsearch usando Bulk API en lotes.
    
    Args:
        logs: Lista de diccionarios con los logs
        index_name: Nombre del índice destino
        batch_size: Número de documentos por lote (default: 5000)
    
    Returns:
        Dict con estadísticas del envío
    """
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    if not logs:
        return {
            "success": True,
            "documents_sent": 0,
            "errors": 0,
            "message": "No hay logs para enviar"
        }
    
    elk_url, headers, auth = get_elk_auth()
    bulk_url = f"{elk_url}/_bulk"
    
    # Headers para Bulk API
    bulk_headers = headers.copy()
    bulk_headers["Content-Type"] = "application/x-ndjson"
    
    total_sent = 0
    total_errors = 0
    total_took_ms = 0
    
    # Dividir en lotes
    total_batches = (len(logs) + batch_size - 1) // batch_size
    print(f"[ELK] Enviando {len(logs)} documentos en {total_batches} lotes de {batch_size}")
    
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(logs))
        batch = logs[start_idx:end_idx]
        
        # Construir payload para este lote
        bulk_lines = []
        for log in batch:
            # Agregar timestamp si no existe
            if '@timestamp' not in log:
                log['@timestamp'] = datetime.utcnow().isoformat() + 'Z'
            
            # Línea de acción (index)
            action = {"index": {"_index": index_name}}
            bulk_lines.append(json.dumps(action))
            
            # Línea del documento
            bulk_lines.append(json.dumps(log))
        
        # El payload debe terminar con newline
        bulk_payload = '\n'.join(bulk_lines) + '\n'
        
        try:
            response = requests.post(
                bulk_url,
                data=bulk_payload,
                headers=bulk_headers,
                auth=auth,
                timeout=120,
                verify=False
            )
            
            if response.status_code not in [200, 201]:
                print(f"[ELK] ❌ Lote {batch_num + 1}/{total_batches} falló: HTTP {response.status_code}")
                total_errors += len(batch)
                continue
            
            result = response.json()
            
            # Contar errores en este lote
            batch_errors = 0
            if result.get('errors', False):
                for item in result.get('items', []):
                    if 'error' in item.get('index', {}):
                        batch_errors += 1
            
            batch_sent = len(batch) - batch_errors
            total_sent += batch_sent
            total_errors += batch_errors
            total_took_ms += result.get('took', 0)
            
            print(f"[ELK] Lote {batch_num + 1}/{total_batches}: {batch_sent} enviados, {batch_errors} errores")
            
        except requests.exceptions.ConnectionError as e:
            print(f"[ELK] Lote {batch_num + 1}/{total_batches} error de conexión: {str(e)}")
            total_errors += len(batch)
        except Exception as e:
            print(f"[ELK] Lote {batch_num + 1}/{total_batches} error: {str(e)}")
            total_errors += len(batch)
    
    success = total_sent > 0
    message = f"Enviados {total_sent} documentos a {index_name}"
    if total_errors > 0:
        message += f" ({total_errors} errores)"
    
    print(f"[ELK] 📊 Total: {total_sent} enviados, {total_errors} errores, {total_took_ms}ms")
    
    return {
        "success": success,
        "documents_sent": total_sent,
        "errors": total_errors,
        "took_ms": total_took_ms,
        "message": message
    }

def dataframe_to_logs(df, log_type: str, tenant: str, namespace: str, loadbalancer: str = None) -> List[Dict]:
    """
    Convierte un DataFrame de pandas a lista de diccionarios para Elasticsearch
    Agrega campos de metadatos útiles
    """
    if df is None or len(df) == 0:
        return []
    
    logs = df.to_dict(orient='records')
    
    # Enriquecer cada log con metadatos
    for log in logs:
        log['_meta'] = {
            'tenant': tenant,
            'namespace': namespace,
            'loadbalancer': loadbalancer,
            'log_type': log_type,
            'ingested_at': datetime.utcnow().isoformat() + 'Z'
        }
        
        # Asegurar que hay un @timestamp
        # Buscar campos comunes de timestamp en los logs de F5
        timestamp_fields = ['timestamp', 'time', 'date', 'req_time', 'start_time']
        for field in timestamp_fields:
            if field in log and log[field]:
                try:
                    # Si es epoch, convertir
                    if isinstance(log[field], (int, float)):
                        log['@timestamp'] = datetime.utcfromtimestamp(log[field]).isoformat() + 'Z'
                    else:
                        log['@timestamp'] = log[field]
                    break
                except:
                    pass
        
        if '@timestamp' not in log:
            log['@timestamp'] = datetime.utcnow().isoformat() + 'Z'
    
    return logs

# ==========================================
# ENDPOINTS DE GESTIÓN DE TOKENS (SIN CAMBIOS)
# ==========================================
@app.post("/api/tenants")
def create_or_update_tenant(tenant_token: TenantToken):
    """Crear o actualizar un token para un tenant."""
    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO tenants (tenant, token, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant) DO UPDATE SET
                    token = excluded.token,
                    updated_at = CURRENT_TIMESTAMP
            """, (tenant_token.tenant, tenant_token.token))
            conn.commit()
        
        return {
            "message": f"Token guardado para tenant: {tenant_token.tenant}",
            "tenant": tenant_token.tenant
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tenants")
def list_tenants():
    """Listar todos los tenants registrados (sin mostrar tokens completos)."""
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT tenant, 
                       substr(token, 1, 10) || '...' as token_preview,
                       created_at,
                       updated_at
                FROM tenants
                ORDER BY tenant
            """)
            tenants = [dict(row) for row in cursor.fetchall()]
        
        return {"tenants": tenants}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tenants/{tenant}")
def get_tenant(tenant: str):
    """Obtener información de un tenant específico."""
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT tenant, 
                       substr(token, 1, 10) || '...' as token_preview,
                       created_at,
                       updated_at
                FROM tenants
                WHERE tenant = ?
            """, (tenant,))
            row = cursor.fetchone()
        
        if row is None:
            raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' no encontrado")
        
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/tenants/{tenant}")
def delete_tenant(tenant: str):
    """Eliminar un tenant y su token."""
    try:
        with get_db() as conn:
            cursor = conn.execute("DELETE FROM tenants WHERE tenant = ?", (tenant,))
            conn.commit()
            
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' no encontrado")
        
        return {"message": f"Tenant '{tenant}' eliminado correctamente"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def get_token_for_tenant(tenant: str) -> str:
    """Obtener el token asociado a un tenant."""
    with get_db() as conn:
        cursor = conn.execute("SELECT token FROM tenants WHERE tenant = ?", (tenant,))
        row = cursor.fetchone()
    
    if row is None:
        raise HTTPException(
            status_code=404, 
            detail=f"No se encontró token para el tenant '{tenant}'. Debe registrarlo primero en /api/tenants"
        )
    
    return row['token']

# ==========================================
# ENDPOINTS DE CONFIGURACIÓN ELASTICSEARCH
# ==========================================
@app.get("/api/elk/config")
def get_elk_config():
    """Obtener configuración actual de Elasticsearch"""
    elk_url, headers, auth = get_elk_auth()
    
    # Determinar método de autenticación actual
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT auth_method, 
                   CASE WHEN api_key IS NOT NULL THEN substr(api_key, 1, 10) || '...' ELSE NULL END as api_key_preview
            FROM elk_config WHERE id = 1
        """)
        row = cursor.fetchone()
    
    auth_method = row['auth_method'] if row else 'api_key'
    has_api_key = row['api_key_preview'] is not None if row else False
    
    return {
        "url": elk_url,
        "auth_method": auth_method,
        "has_api_key": has_api_key,
        "has_credentials": auth is not None,
        "indices": ELK_INDICES
    }

@app.post("/api/elk/config")
def update_elk_config(config: ElkConfig):
    """Actualizar configuración de Elasticsearch"""
    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO elk_config (id, url, auth_method, api_key, username, password, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    url = excluded.url,
                    auth_method = excluded.auth_method,
                    api_key = excluded.api_key,
                    username = excluded.username,
                    password = excluded.password,
                    updated_at = CURRENT_TIMESTAMP
            """, (config.url, config.auth_method, config.api_key, config.username, config.password))
            conn.commit()
        
        return {
            "message": "Configuración de Elasticsearch actualizada",
            "url": config.url,
            "auth_method": config.auth_method
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/elk/test")
def test_elk_connection():
    """Probar conexión a Elasticsearch"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        elk_url, headers, auth = get_elk_auth()
        response = requests.get(elk_url, headers=headers, auth=auth, timeout=10, verify=False)
        
        if response.status_code == 200:
            info = response.json()
            return {
                "status": "connected",
                "cluster_name": info.get('cluster_name'),
                "version": info.get('version', {}).get('number'),
                "url": elk_url
            }
        elif response.status_code == 401:
            return {
                "status": "error",
                "status_code": 401,
                "message": "Error de autenticación. Verifica tu API Key o credenciales."
            }
        else:
            return {
                "status": "error",
                "status_code": response.status_code,
                "message": response.text[:200]
            }
    except requests.exceptions.ConnectionError as e:
        return {
            "status": "error",
            "message": f"No se puede conectar a {ELASTICSEARCH_CONFIG['url']}: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

# ==========================================
# ENDPOINTS PARA NAMESPACES Y LOAD BALANCERS
# ==========================================
@app.get("/api/namespaces/{tenant}")
def get_namespaces(tenant: str):
    """Obtener lista de namespaces para un tenant específico."""
    try:
        token = get_token_for_tenant(tenant)
        url = f"https://{tenant}.console.ves.volterra.io/api/web/namespaces"
        headers = {
            "Authorization": f"APIToken {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error al obtener namespaces: {response.text}"
            )
        
        data = response.json()
        namespaces = []
        if "items" in data:
            namespaces = [item.get("name", "") for item in data["items"] if "name" in item]
        
        return {
            "tenant": tenant,
            "namespaces": sorted(namespaces)
        }
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error de conexión al obtener namespaces: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/loadbalancers/{tenant}/{namespace}")
def get_loadbalancers(tenant: str, namespace: str):
    """Obtener lista de load balancers para un tenant y namespace específicos."""
    try:
        token = get_token_for_tenant(tenant)
        url = f"https://{tenant}.console.ves.volterra.io/api/config/namespaces/{namespace}/http_loadbalancers"
        headers = {
            "Authorization": f"APIToken {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error al obtener load balancers: {response.text}"
            )
        
        data = response.json()
        loadbalancers = []
        if "items" in data:
            loadbalancers = [
                item.get("name", "") 
                for item in data["items"] 
                if "name" in item
            ]
        
        return {
            "tenant": tenant,
            "namespace": namespace,
            "loadbalancers": sorted(loadbalancers)
        }
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error de conexión al obtener load balancers: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/diagnose/{tenant}/{namespace}/{loadbalancer}")
def diagnose_loadbalancer(tenant: str, namespace: str, loadbalancer: str):
    """Diagnostica por qué un load balancer no retorna logs."""
    try:
        token = get_token_for_tenant(tenant)
        headers = {
            "Authorization": f"APIToken {token}",
            "Content-Type": "application/json"
        }
        
        results = {
            "loadbalancer": loadbalancer,
            "namespace": namespace,
            "tenant": tenant,
            "tests": []
        }
        
        # Test 1: Verificar que el LB existe
        url = f"https://{tenant}.console.ves.volterra.io/api/config/namespaces/{namespace}/http_loadbalancers/{loadbalancer}"
        response = requests.get(url, headers=headers, timeout=10)
        
        results["tests"].append({
            "name": "Load Balancer Exists",
            "status": "pass" if response.status_code == 200 else "fail",
            "status_code": response.status_code,
            "details": response.json() if response.status_code == 200 else response.text[:200]
        })
        
        # Test 2: Probar diferentes queries de logs
        current_time = int(time.time())
        start_time = current_time - 3600
        
        query_variants = [
            f'{{vh_name="ves-io-http-loadbalancer-{loadbalancer}"}}',
            f'{{vh_name="{loadbalancer}"}}',
            f'{{vh_name="ves-io-https-loadbalancer-{loadbalancer}"}}',
            ""
        ]
        
        for query in query_variants:
            url = f"https://{tenant}.console.ves.volterra.io/api/data/namespaces/{namespace}/access_logs"
            payload = {
                "namespace": namespace,
                "query": query,
                "start_time": str(start_time),
                "end_time": str(current_time),
                "scroll": False,
                "limit": 10
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            
            log_count = 0
            if response.status_code == 200:
                data = response.json()
                log_count = len(data.get('logs', []))
            
            results["tests"].append({
                "name": f"Query Test: {query if query else '(no filter)'}",
                "status": "pass" if log_count > 0 else "no_data",
                "status_code": response.status_code,
                "logs_found": log_count,
                "query": query
            })
        
        successful_queries = [t for t in results["tests"][1:] if t.get("logs_found", 0) > 0]
        
        if successful_queries:
            results["recommendation"] = f"Usa la query: {successful_queries[0]['query']}"
            results["status"] = "working"
        else:
            results["recommendation"] = "El load balancer no tiene logs en la última hora. Verifica: 1) Tiene tráfico real, 2) Logging está habilitado, 3) Permisos del token"
            results["status"] = "no_logs"
        
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# ENDPOINT PRINCIPAL: ENVIAR LOGS A ELK
# ==========================================
@app.post("/api/logs/elk")
def send_logs_to_elk(
    log_type: str = Query(..., description="Tipo de log: access | audit | security"),
    tenant: str = Query(..., description="Nombre del tenant"),
    namespace: str = Query(...),
    loadbalancer: str = Query(None),
    hours: int = Query(24)
):
    """
    Obtiene logs de F5 XC y los envía directamente a Elasticsearch via Bulk API.
    
    Returns:
        Estadísticas del envío a ELK
    """
    try:
        start_time = time.time()
        
        # Obtener token
        token = get_token_for_tenant(tenant)
        
        # Validar parámetros
        if log_type in ["access", "security"] and not loadbalancer:
            raise HTTPException(
                status_code=400,
                detail=f"El tipo de log '{log_type}' requiere especificar un load balancer"
            )
        
        if log_type not in ELK_INDICES:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de log inválido. Valores permitidos: {list(ELK_INDICES.keys())}"
            )
        
        print(f"[ELK] Iniciando: tenant={tenant}, type={log_type}, hours={hours}")
        
        # Obtener logs según el tipo
        if log_type == "access":
            df = fetch_access_logs(token, tenant, namespace, loadbalancer, hours)
            logs = dataframe_to_logs(df, log_type, tenant, namespace, loadbalancer)
        
        elif log_type == "audit":
            # Para audit logs, usar subprocess y convertir CSV a lista de dicts
            csv_result = _get_logs_subprocess_raw(log_type, token, tenant, namespace, None, hours)
            logs = csv_result if csv_result else []
            # Agregar metadatos
            for log in logs:
                log['_meta'] = {
                    'tenant': tenant,
                    'namespace': namespace,
                    'log_type': log_type,
                    'ingested_at': datetime.utcnow().isoformat() + 'Z'
                }
        
        elif log_type == "security":
            # Para security logs, usar subprocess y convertir CSV a lista de dicts
            csv_result = _get_logs_subprocess_raw(log_type, token, tenant, namespace, loadbalancer, hours)
            logs = csv_result if csv_result else []
            # Agregar metadatos
            for log in logs:
                log['_meta'] = {
                    'tenant': tenant,
                    'namespace': namespace,
                    'loadbalancer': loadbalancer,
                    'log_type': log_type,
                    'ingested_at': datetime.utcnow().isoformat() + 'Z'
                }
        
        fetch_time = time.time() - start_time
        print(f"[ELK] Logs obtenidos en {fetch_time:.2f}s ({len(logs)} registros)")
        
        if not logs:
            return {
                "success": True,
                "message": "No se encontraron logs para el período especificado",
                "documents_sent": 0,
                "tenant": tenant,
                "log_type": log_type,
                "index": ELK_INDICES[log_type]
            }
        
        # Enviar a Elasticsearch
        index_name = ELK_INDICES[log_type]
        elk_result = send_to_elasticsearch_bulk(logs, index_name)
        
        total_time = time.time() - start_time
        print(f"[ELK] Proceso completo en {total_time:.2f}s")
        
        return {
            "success": elk_result["success"],
            "message": elk_result["message"],
            "documents_sent": elk_result["documents_sent"],
            "errors": elk_result["errors"],
            "tenant": tenant,
            "namespace": namespace,
            "loadbalancer": loadbalancer,
            "log_type": log_type,
            "index": index_name,
            "fetch_time_seconds": round(fetch_time, 2),
            "total_time_seconds": round(total_time, 2),
            "took_ms": elk_result.get("took_ms", 0)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        )

def _get_logs_subprocess_raw(log_type: str, token: str, tenant: str, namespace: str, loadbalancer: str, hours: int) -> List[Dict]:
    """
    Obtiene logs usando subprocess y retorna como lista de diccionarios.
    Para audit y security logs que aún usan scripts externos.
    """
    import csv
    import io
    
    scripts = {
        "access": "f5-xc-export-access-logs.py",
        "audit": "f5-xc-export-audit-logs.py",
        "security": "f5-xc-export-security-event-logs.py"
    }
    
    script = os.path.join(os.getcwd(), scripts[log_type])
    
    if not os.path.exists(script):
        print(f"[WARNING] Script no encontrado: {script}")
        return []
    
    files_before = set(glob.glob(f"{LOG_DIR}/*.csv"))
    files_before_cwd = set(glob.glob(f"{os.getcwd()}/*.csv"))
    
    cmd = [
        "python3",
        script,
        "--token", token,
        "--tenant", tenant,
        "--namespace", namespace,
        "--hours", str(hours)
    ]
    
    if log_type in ["access", "security"] and loadbalancer:
        cmd.extend(["--loadbalancer", loadbalancer])
    
    print(f"[DEBUG] Ejecutando: {' '.join(cmd[:6])}...")
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    if result.returncode != 0:
        print(f"[ERROR] Script falló: {result.stderr}")
        return []
    
    time.sleep(1)
    
    # Buscar archivo generado
    files_after = set(glob.glob(f"{LOG_DIR}/*.csv"))
    files_after_cwd = set(glob.glob(f"{os.getcwd()}/*.csv"))
    new_files = (files_after - files_before) | (files_after_cwd - files_before_cwd)
    
    if new_files:
        latest_file = max(new_files, key=os.path.getctime)
        
        # Leer CSV y convertir a lista de dicts
        logs = []
        with open(latest_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                logs.append(dict(row))
        
        # Eliminar archivo temporal
        os.remove(latest_file)
        
        return logs
    
    return []

# ==========================================
# ENDPOINT ORIGINAL: DESCARGAR CSV (MANTENIDO)
# ==========================================
@app.get("/api/logs")
def get_logs(
    log_type: str = Query(..., description="Tipo de log: access | audit | security"),
    tenant: str = Query(..., description="Nombre del tenant"),
    namespace: str = Query(...),
    loadbalancer: str = Query(None),
    hours: int = Query(24)
):
    """
    Genera archivo CSV para descarga.
    """
    try:
        start_time = time.time()
        
        # Obtener token
        token = get_token_for_tenant(tenant)
        
        # Validar parámetros
        if log_type in ["access", "security"] and not loadbalancer:
            raise HTTPException(
                status_code=400,
                detail=f"El tipo de log '{log_type}' requiere especificar un load balancer"
            )
        
        print(f"[API] Iniciando descarga: tenant={tenant}, type={log_type}, hours={hours}")
        
        # NUEVA LÓGICA: Llamada directa (sin subprocess) para access logs
        if log_type == "access":
            df = fetch_access_logs(token, tenant, namespace, loadbalancer, hours)
            
            fetch_time = time.time() - start_time
            print(f"[API] Logs descargados en {fetch_time:.2f}s ({len(df)} registros)")
            
            current_date = datetime.now().strftime("%m-%d-%Y")
            filename = f"f5-xc-{log_type}_logs-{tenant}_{namespace}-{current_date}.csv"
            file_path = os.path.join(LOG_DIR, filename)
            
            df.to_csv(file_path, index=False, encoding='utf-8')
            
            total_time = time.time() - start_time
            print(f"[API] Proceso completo en {total_time:.2f}s")
            
            return {
                "message": f"Archivo generado correctamente: {filename}",
                "file": filename,
                "tenant": tenant,
                "log_type": log_type,
                "records": len(df),
                "fetch_time_seconds": round(fetch_time, 2),
                "total_time_seconds": round(total_time, 2)
            }
        
        elif log_type == "audit":
            print(f"[API] Usando subprocess para audit logs")
            return _get_logs_subprocess(log_type, token, tenant, namespace, loadbalancer, hours)
        
        elif log_type == "security":
            print(f"[API] Usando subprocess para security logs")
            return _get_logs_subprocess(log_type, token, tenant, namespace, loadbalancer, hours)
        
        else:
            raise HTTPException(status_code=400, detail="Tipo de log no válido")
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        )

def _get_logs_subprocess(log_type: str, token: str, tenant: str, namespace: str, loadbalancer: str, hours: int):
    """
    Función helper para llamadas con subprocess (audit y security logs)
    Mantiene la lógica original para tipos que aún no están optimizados.
    Genera archivo CSV.
    """
    scripts = {
        "access": "f5-xc-export-access-logs.py",
        "audit": "f5-xc-export-audit-logs.py",
        "security": "f5-xc-export-security-event-logs.py"
    }
    
    script = os.path.join(os.getcwd(), scripts[log_type])
    
    if not os.path.exists(script):
        raise HTTPException(status_code=500, detail=f"Script no encontrado: {script}")
    
    files_before = set(glob.glob(f"{LOG_DIR}/*.csv"))
    files_before_cwd = set(glob.glob(f"{os.getcwd()}/*.csv"))
    
    cmd = [
        "python3",
        script,
        "--token", token,
        "--tenant", tenant,
        "--namespace", namespace,
        "--hours", str(hours)
    ]
    
    if log_type in ["access", "security"]:
        cmd.extend(["--loadbalancer", loadbalancer])
    
    print(f"[DEBUG] Ejecutando: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Error ejecutando script",
                "stderr": result.stderr,
                "stdout": result.stdout
            }
        )
    
    time.sleep(1)
    
    files_after = set(glob.glob(f"{LOG_DIR}/*.csv"))
    files_after_cwd = set(glob.glob(f"{os.getcwd()}/*.csv"))
    new_files = (files_after - files_before) | (files_after_cwd - files_before_cwd)
    
    if new_files:
        latest_file = max(new_files, key=os.path.getctime)
        filename = os.path.basename(latest_file)
        
        if os.path.dirname(latest_file) == os.getcwd():
            import shutil
            dest_file = os.path.join(LOG_DIR, filename)
            shutil.move(latest_file, dest_file)
        
        return {
            "message": f"Archivo generado correctamente: {filename}",
            "file": filename,
            "tenant": tenant,
            "log_type": log_type
        }
    
    raise HTTPException(
        status_code=500,
        detail="No se encontró el archivo generado"
    )

@app.get("/api/download")
def download_log(file: str):
    """
    Permite descargar el archivo CSV generado.
    Solo acepta nombres de archivo (sin rutas) por seguridad.
    """
    filename = os.path.basename(file)
    file_path = os.path.join(LOG_DIR, filename)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(
            file_path, 
            filename=filename,
            media_type='text/csv'
        )
    else:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Archivo no encontrado: {filename}",
                "archivos_disponibles": os.listdir(LOG_DIR)
            }
        )

# ==========================================
# ENDPOINT DE SALUD
# ==========================================
@app.get("/api/health")
def health_check():
    """Verificar estado del servicio"""
    elk_url, headers, auth = get_elk_auth()
    
    # Test ELK connection
    elk_status = "unknown"
    try:
        response = requests.get(elk_url, headers=headers, auth=auth, timeout=5, verify=False)
        elk_status = "connected" if response.status_code == 200 else f"error_{response.status_code}"
    except:
        elk_status = "disconnected"
    
    return {
        "status": "running",
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "elasticsearch": {
            "url": elk_url,
            "status": elk_status
        },
        "indices": ELK_INDICES
    }
