# log_fetchers.py
from datetime import datetime
import json
import requests
import pandas as pd
import time

def fetch_access_logs(token: str, tenant: str, namespace: str, loadbalancer: str, hours: int) -> pd.DataFrame:
    """
    Fetch access logs directamente (sin subprocess)
    """
    print(f"[LOG_FETCHER] Iniciando descarga: {hours}h")
    logs_data = []
    
    current_time = int(datetime.now().timestamp())
    end_time = current_time
    start_time = end_time - (hours * 3600)
    
    # Session HTTP reutilizable
    session = requests.Session()
    session.headers.update({
        'Authorization': f"APIToken {token}",
        'Accept-Encoding': 'gzip, deflate',
    })
    
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
    
    try:
        # Primera petición
        t0 = time.time()
        response = session.post(base_url, json=payload, timeout=30)
        response.raise_for_status()
        access_logs = response.json()
        print(f"[LOG_FETCHER] Primera petición: {time.time()-t0:.2f}s")
        
        if 'logs' in access_logs:
            _process_logs_batch(access_logs['logs'], logs_data)
            print(f"[LOG_FETCHER] Primera página: {len(logs_data)} logs")
            
            # Scroll
            scroll_url = f'https://{tenant}.console.ves.volterra.io/api/data/namespaces/{namespace}/access_logs/scroll'
            scroll_count = 0
            
            while access_logs.get("scroll_id", "") != "":
                scroll_payload = {
                    "namespace": namespace,
                    "scroll_id": access_logs["scroll_id"]
                }
                
                response = session.post(scroll_url, json=scroll_payload, timeout=30)
                response.raise_for_status()
                access_logs = response.json()
                
                if 'logs' in access_logs:
                    _process_logs_batch(access_logs['logs'], logs_data)
                    scroll_count += 1
                    
                    if scroll_count % 10 == 0:
                        print(f"[LOG_FETCHER] Scroll #{scroll_count}: {len(logs_data)} logs")
            
            print(f"[LOG_FETCHER] Total scrolls: {scroll_count}")
    
    except Exception as e:
        print(f"[LOG_FETCHER ERROR] {str(e)}")
        raise
    finally:
        session.close()
    
    # Crear DataFrame
    columns = ['Time', 'Request ID', 'Response Code', 'Source IP address', 
               'Domain', 'Country', 'City', 'Response Details', 'Method', 'Request Path']
    
    if not logs_data:
        return pd.DataFrame(columns=columns)
    
    print(f"[LOG_FETCHER] ✅ Total logs: {len(logs_data)}")
    return pd.DataFrame(logs_data)

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
