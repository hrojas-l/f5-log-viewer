from datetime import datetime
import argparse
import json
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

def get_access_logs(token, tenant, namespace, loadbalancer, hours):
    """
    Versión con threading que paraleliza descarga de chunks de tiempo
    """
    current_time = datetime.now()
    end_time = int(round(datetime.timestamp(current_time)))
    
    # Dividir en chunks de 24 horas
    time_chunks = []
    remaining = hours
    chunk_end = end_time
    
    while remaining > 0:
        chunk_hours = min(24, remaining)
        chunk_start = chunk_end - (chunk_hours * 3600)
        time_chunks.append((chunk_start, chunk_end, chunk_hours))
        chunk_end = chunk_start
        remaining -= 24
    
    print(f"[INFO] Dividido en {len(time_chunks)} chunks de tiempo")
    
    # Si solo hay 1 chunk, usar versión serial (más simple)
    if len(time_chunks) == 1:
        return _fetch_chunk_serial(token, tenant, namespace, loadbalancer, time_chunks[0])
    
    # Para múltiples chunks, usar threading
    all_logs = []
    lock = threading.Lock()
    
    def fetch_and_collect(chunk_info, idx):
        chunk_start, chunk_end, chunk_hours = chunk_info
        print(f"[INFO] Chunk {idx+1}/{len(time_chunks)}: Descargando {chunk_hours}h...")
        
        chunk_logs = _fetch_time_chunk(token, tenant, namespace, loadbalancer, chunk_start, chunk_end)
        
        with lock:
            all_logs.extend(chunk_logs)
        
        print(f"[INFO] Chunk {idx+1}/{len(time_chunks)}: ✅ {len(chunk_logs)} logs descargados")
        return len(chunk_logs)
    
    # Ejecutar en paralelo (max 3 workers para no saturar la API)
    with ThreadPoolExecutor(max_workers=min(3, len(time_chunks))) as executor:
        futures = {
            executor.submit(fetch_and_collect, chunk, idx): idx 
            for idx, chunk in enumerate(time_chunks)
        }
        
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] Error en chunk: {e}")
    
    # Crear DataFrame
    columns = ['Time', 'Request ID', 'Response Code', 'Source IP address', 
               'Domain', 'Country', 'City', 'Response Details', 'Method', 'Request Path']
    
    if not all_logs:
        return pd.DataFrame(columns=columns)
    
    return pd.DataFrame(all_logs)

def _fetch_chunk_serial(token, tenant, namespace, loadbalancer, chunk_info):
    """Fetch serial para un solo chunk (sin threading overhead)"""
    chunk_start, chunk_end, _ = chunk_info
    logs_data = _fetch_time_chunk(token, tenant, namespace, loadbalancer, chunk_start, chunk_end)
    
    columns = ['Time', 'Request ID', 'Response Code', 'Source IP address', 
               'Domain', 'Country', 'City', 'Response Details', 'Method', 'Request Path']
    
    if not logs_data:
        return pd.DataFrame(columns=columns)
    
    return pd.DataFrame(logs_data)

def _fetch_time_chunk(token, tenant, namespace, loadbalancer, start_time, end_time):
    """
    Fetch logs para un chunk específico de tiempo
    """
    logs_data = []
    
    # Session propia para este thread
    session = requests.Session()
    session.headers.update({'Authorization': f"APIToken {token}"})
    
    try:
        base_url = f'https://{tenant}.console.ves.volterra.io/api/data/namespaces/{namespace}/access_logs'
        
        payload = {
            "aggs": {},
            "end_time": str(end_time),
            "limit": 0,
            "namespace": namespace,
            "query": f'{{vh_name="ves-io-http-loadbalancer-{loadbalancer}"}}',
            "sort": "DESCENDING",
            "start_time": str(start_time),
            "scroll": True
        }
        
        response = session.post(base_url, json=payload, timeout=30)
        access_logs = response.json()
        
        if 'logs' in access_logs:
            _process_logs_batch(access_logs['logs'], logs_data)
            
            scroll_url = f'https://{tenant}.console.ves.volterra.io/api/data/namespaces/{namespace}/access_logs/scroll'
            
            while access_logs.get("scroll_id", "") != "":
                scroll_payload = {
                    "namespace": namespace,
                    "scroll_id": access_logs["scroll_id"]
                }
                
                response = session.post(scroll_url, json=scroll_payload, timeout=30)
                access_logs = response.json()
                
                if 'logs' in access_logs:
                    _process_logs_batch(access_logs['logs'], logs_data)
    
    except Exception as e:
        print(f"[ERROR] Error fetching chunk: {e}")
    finally:
        session.close()
    
    return logs_data

def _process_logs_batch(logs, logs_data):
    """Procesar logs en batch"""
    parsed_logs = [json.loads(event) for event in logs]
    
    logs_data.extend([
        {
            'Time': log['time'],
            'Request ID': log['req_id'],
            'Response Code': log['rsp_code'],
            'Source IP address': log['src_ip'],
            'Domain': log['original_authority'],
            'Country': log['country'],
            'City': log['city'],
            'Response Details': log['rsp_code_details'],
            'Method': log['method'],
            'Request Path': log['req_path']
        }
        for log in parsed_logs
    ])

def main():
    current_time = datetime.now()
    
    parser = argparse.ArgumentParser(
        description="This *Python* script helps to export the Access logs from *F5 Distributed Cloud* via the XC API into a CSV file.",
        epilog='The script generates a CSV file named as: f5-xc-access_logs-<TENANT>_<NAMESPACE>-<date>.csv'
    )
    
    parser.add_argument('--token', type=str, required=True)
    parser.add_argument('--tenant', type=str, required=True)
    parser.add_argument('--namespace', type=str, required=True)
    parser.add_argument('--loadbalancer', type=str, required=True)
    parser.add_argument('--hours', type=int, required=True)
    
    args = parser.parse_args()
    
    print(f"[INFO] Fetching logs for {args.hours} hours...")
    import time
    start = time.time()
    
    security_logs = get_access_logs(
        args.token, args.tenant, args.namespace, 
        args.loadbalancer, args.hours
    )
    
    elapsed = time.time() - start
    rate = len(security_logs) / elapsed if elapsed > 0 else 0
    print(f"[INFO] ✅ Downloaded {len(security_logs)} logs in {elapsed:.2f} seconds ({rate:.0f} logs/sec)")
    
    filename = f"f5-xc-access_logs-{args.tenant}_{args.namespace}-{current_time.strftime('%m-%d-%Y')}.csv"
    security_logs.to_csv(filename, index=False, sep=',', encoding='utf-8')
    
    print(f"[INFO] Saved to: {filename}")

if __name__ == "__main__":
    main()
