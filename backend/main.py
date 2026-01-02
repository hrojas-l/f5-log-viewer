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

# Modelos Pydantic
class TenantToken(BaseModel):
    tenant: str
    token: str

class TenantUpdate(BaseModel):
    token: str

# Funciones de base de datos
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
        conn.commit()

# Inicializar DB al arrancar
@app.on_event("startup")
def startup_event():
    init_db()
    print(f"[INFO] Base de datos inicializada en: {DB_PATH}")

# Endpoints de gestión de tokens
@app.post("/api/tenants")
def create_or_update_tenant(tenant_token: TenantToken):
    """
    Crear o actualizar un token para un tenant.
    """
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
    """
    Listar todos los tenants registrados (sin mostrar tokens completos).
    """
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
    """
    Obtener información de un tenant específico.
    """
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
    """
    Eliminar un tenant y su token.
    """
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
    """
    Obtener el token asociado a un tenant.
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT token FROM tenants WHERE tenant = ?", (tenant,))
        row = cursor.fetchone()
    
    if row is None:
        raise HTTPException(
            status_code=404, 
            detail=f"No se encontró token para el tenant '{tenant}'. Debe registrarlo primero en /api/tenants"
        )
    
    return row['token']

# ENDPOINTS PARA OBTENER NAMESPACES Y LOAD BALANCERS

@app.get("/api/namespaces/{tenant}")
def get_namespaces(tenant: str):
    """
    Obtener lista de namespaces para un tenant específico.
    """
    try:
        # Obtener token del tenant
        token = get_token_for_tenant(tenant)
        
        # Construir URL
        url = f"https://{tenant}.console.ves.volterra.io/api/web/namespaces"
        
        # Headers para la petición
        headers = {
            "Authorization": f"APIToken {token}",
            "Content-Type": "application/json"
        }
        
        # Hacer petición
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error al obtener namespaces: {response.text}"
            )
        
        data = response.json()
        
        # Extraer nombres de namespaces
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
    """
    Obtener lista de load balancers para un tenant y namespace específicos.
    """
    try:
        # Obtener token del tenant
        token = get_token_for_tenant(tenant)
        
        # Construir URL
        url = f"https://{tenant}.console.ves.volterra.io/api/config/namespaces/{namespace}/http_loadbalancers"
        
        # Headers para la petición
        headers = {
            "Authorization": f"APIToken {token}",
            "Content-Type": "application/json"
        }
        
        # Hacer petición
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Error al obtener load balancers: {response.text}"
            )
        
        data = response.json()
        
        # Extraer nombres de load balancers
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
    """
    Diagnostica por qué un load balancer no retorna logs.
    """
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
        start_time = current_time - 3600  # Última hora
        
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
        
        # Resumen
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

@app.get("/api/logs")
def get_logs(
    log_type: str = Query(..., description="Tipo de log: access | audit | security"),
    tenant: str = Query(..., description="Nombre del tenant"),
    namespace: str = Query(...),
    loadbalancer: str = Query(None),
    hours: int = Query(24)
):
    """
    Versión OPTIMIZADA: Sin subprocess para access logs, llamada directa a función
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
            # Llamar función directamente
            df = fetch_access_logs(token, tenant, namespace, loadbalancer, hours)
            
            fetch_time = time.time() - start_time
            print(f"[API] Logs descargados en {fetch_time:.2f}s ({len(df)} registros)")
            
            # Generar nombre de archivo
            current_date = datetime.now().strftime("%m-%d-%Y")
            filename = f"f5-xc-{log_type}_logs-{tenant}_{namespace}-{current_date}.csv"
            file_path = os.path.join(LOG_DIR, filename)
            
            # Guardar CSV
            df.to_csv(file_path, index=False, encoding='utf-8')
            
            total_time = time.time() - start_time
            print(f"[API] ✅ Proceso completo en {total_time:.2f}s")
            
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
            # Fallback a subprocess para audit (por ahora)
            print(f"[API] Usando subprocess para audit logs")
            return _get_logs_subprocess(log_type, token, tenant, namespace, loadbalancer, hours)
        
        elif log_type == "security":
            # Fallback a subprocess para security (por ahora)
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
    Mantiene la lógica original para tipos que aún no están optimizados
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
    
    # Buscar archivo generado
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
