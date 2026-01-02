from datetime import datetime
import argparse
import json
import requests
import pandas as pd

def get_audit_logs(token, tenant, namespace, hours):
    """
    Obtiene audit logs de F5 XC de manera optimizada.
    Acumula datos en lista y crea DataFrame una sola vez al final.
    """
    logs_data = []
    
    currentTime = datetime.now()
    midTime = int(round(datetime.timestamp(currentTime)))
    startTime = midTime - (hours * 3600)
    
    # Preparar headers una sola vez
    headers = {'Authorization': f"APIToken {token}"}
    
    print(f"[DEBUG] Consultando audit logs para:")
    print(f"  - Tenant: {tenant}")
    print(f"  - Namespace: {namespace}")
    print(f"  - Período: {hours} horas (desde {datetime.fromtimestamp(startTime)})")
    
    iteration = 0
    
    while True:
        iteration += 1
        endTime = midTime
        midTime = endTime - (24 * 3600)
        if hours < 24:
            midTime = startTime
        
        BASE_URL = f'https://{tenant}.console.ves.volterra.io/api/data/namespaces/{namespace}/audit_logs'
        
        payload = {
            "aggs": {},
            "end_time": str(endTime),
            "limit": 0,
            "namespace": namespace,
            "sort": "DESCENDING",
            "start_time": str(midTime),
            "scroll": True
        }
        
        print(f"\n[DEBUG] Iteración {iteration}")
        print(f"  - Time range: {datetime.fromtimestamp(int(midTime))} -> {datetime.fromtimestamp(endTime)}")
        
        try:
            auth_response = requests.post(
                BASE_URL, 
                data=json.dumps(payload), 
                headers=headers,
                timeout=30
            )
            
            print(f"  - Status Code: {auth_response.status_code}")
            
            if auth_response.status_code != 200:
                print(f"  - ⚠️ Error Response: {auth_response.text[:200]}")
                hours = hours - 24
                if hours < 24:
                    break
                continue
            
            auditLogs = auth_response.json()
            
            if 'logs' in auditLogs and auditLogs['logs']:
                logs = auditLogs['logs']
                print(f"  - ✅ Logs encontrados: {len(logs)}")
                
                # Procesar logs iniciales
                for event in logs:
                    try:
                        event_dict = json.loads(event)
                        
                        # Extraer datos con valores por defecto
                        logs_data.append({
                            'Time': event_dict.get('time', ''),
                            'User': event_dict.get('user', ''),
                            'Namespace': event_dict.get('namespace', ''),
                            'Method': event_dict.get('method', ''),
                            'Request Path': event_dict.get('req_path', '').split('?')[0] if event_dict.get('req_path') else '',
                            'Message': next((event_dict[k] for k in event_dict if k.endswith('user_message')), '')
                        })
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"  - ⚠️ Error parseando log: {e}")
                        continue
                
                # Procesar scroll
                scroll_count = 0
                max_scrolls = 100  # Límite de seguridad
                
                while auditLogs.get("scroll_id", "") != "" and scroll_count < max_scrolls:
                    scroll_count += 1
                    BASE_URL_SCROLL = f'https://{tenant}.console.ves.volterra.io/api/data/namespaces/{namespace}/audit_logs/scroll'
                    scroll_payload = {
                        "namespace": namespace,
                        "scroll_id": auditLogs["scroll_id"]
                    }
                    
                    auth_response = requests.post(
                        BASE_URL_SCROLL, 
                        data=json.dumps(scroll_payload), 
                        headers=headers,
                        timeout=30
                    )
                    
                    if auth_response.status_code != 200:
                        print(f"  - ⚠️ Error en scroll: {auth_response.status_code}")
                        break
                    
                    auditLogs = auth_response.json()
                    
                    if 'logs' in auditLogs and auditLogs['logs']:
                        logs = auditLogs['logs']
                        print(f"  - 📄 Scroll {scroll_count}: +{len(logs)} logs")
                        
                        for event in logs:
                            try:
                                event_dict = json.loads(event)
                                
                                logs_data.append({
                                    'Time': event_dict.get('time', ''),
                                    'User': event_dict.get('user', ''),
                                    'Namespace': event_dict.get('namespace', ''),
                                    'Method': event_dict.get('method', ''),
                                    'Request Path': event_dict.get('req_path', '').split('?')[0] if event_dict.get('req_path') else '',
                                    'Message': next((event_dict[k] for k in event_dict if k.endswith('user_message')), '')
                                })
                            except (json.JSONDecodeError, KeyError):
                                continue
                    else:
                        break
            else:
                print(f"  - ℹ️ Sin logs para este período")
                
        except requests.exceptions.Timeout:
            print(f"  - ⚠️ Timeout en la petición")
        except Exception as e:
            print(f"  - ❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
        
        hours = hours - 24
        if hours < 24:
            break
    
    print(f"\n[RESUMEN] Total de audit logs recopilados: {len(logs_data)}")
    
    # Crear DataFrame una única vez al final
    if logs_data:
        df = pd.DataFrame(logs_data)
        return df
    else:
        print("⚠️ ADVERTENCIA: No se recopilaron audit logs. Retornando DataFrame vacío.")
        return pd.DataFrame(columns=[
            'Time', 'User', 'Namespace', 'Method', 'Request Path', 'Message'
        ])

def main():
    currentTime = datetime.now()
    parser = argparse.ArgumentParser(
        description="This *Python* script exports audit logs from *F5 Distributed Cloud* via the XC API into a CSV file.",
        epilog='The script generates a CSV file named: f5-xc-audit_logs-<TENANT>_<NAMESPACE>-<date>.csv'
    )
    
    parser.add_argument('--token', type=str, required=True)
    parser.add_argument('--tenant', type=str, required=True)
    parser.add_argument('--namespace', type=str, required=True)
    parser.add_argument('--hours', type=int, required=True)
    
    # NOTA: El parámetro --loadbalancer no se usa en audit logs, pero lo agregamos 
    # para mantener consistencia con la llamada desde el backend
    parser.add_argument('--loadbalancer', type=str, required=False, default='')
    
    args = parser.parse_args()
    
    auditLogsCSV = get_audit_logs(args.token, args.tenant, args.namespace, args.hours)
    
    filename = f"f5-xc-audit_logs-{args.tenant}_{args.namespace}-{currentTime.strftime('%m-%d-%Y')}.csv"
    auditLogsCSV.to_csv(filename, index=False, sep=',', encoding='utf-8')
    
    print(f"\n[SUCCESS] Archivo generado: {filename}")

if __name__ == "__main__":
    main()
