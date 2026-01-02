const API_URL = 'http://192.168.0.219:8000';
let selectedHours = 24;
let lastTenant = '';

/**
 * Establece el rango de horas seleccionado
 */
function setHours(hours) {
  selectedHours = hours;
  document.getElementById('customHours').value = '';
  
  // Actualizar botones activos
  document.querySelectorAll('.btn-range').forEach(btn => btn.classList.remove('active'));
  event.target.classList.add('active');
}

/**
 * Limpia el formulario y resetea todos los campos
 */
function limpiarFormulario() {
  document.getElementById('logForm').reset();
  document.getElementById('resultado').innerHTML = '';
  selectedHours = 24;
  lastTenant = '';
  
  // Resetear dropdowns
  const namespaceSelect = document.getElementById('namespace');
  const lbSelect = document.getElementById('loadbalancer');
  
  namespaceSelect.innerHTML = '<option value="">Primero selecciona un tenant</option>';
  namespaceSelect.disabled = true;
  
  lbSelect.innerHTML = '<option value="">Primero selecciona un namespace</option>';
  lbSelect.disabled = true;
  
  // Resetear botón de diagnóstico
  const btnDiagnostico = document.getElementById('btnDiagnostico');
  if (btnDiagnostico) {
    btnDiagnostico.disabled = true;
  }
  
  document.querySelectorAll('.btn-range').forEach(btn => btn.classList.remove('active'));
  // Marcar 1 Día como activo por defecto
  document.querySelectorAll('.btn-range')[2].classList.add('active');
}

/**
 * Carga los namespaces disponibles para un tenant
 */
async function cargarNamespaces() {
  const tenant = document.getElementById('tenant').value.trim();
  const namespaceSelect = document.getElementById('namespace');
  const lbSelect = document.getElementById('loadbalancer');
  const loadingSpinner = document.getElementById('namespaceLoading');

  // Si el tenant no cambió o está vacío, no hacer nada
  if (!tenant || tenant === lastTenant) {
    return;
  }

  lastTenant = tenant;

  // Resetear namespace y load balancer
  namespaceSelect.innerHTML = '<option value="">Cargando...</option>';
  namespaceSelect.disabled = true;
  lbSelect.innerHTML = '<option value="">Primero selecciona un namespace</option>';
  lbSelect.disabled = true;
  loadingSpinner.style.display = 'inline-block';

  try {
    const response = await fetch(`${API_URL}/api/namespaces/${tenant}`);
    const data = await response.json();

    if (response.ok) {
      namespaceSelect.innerHTML = '<option value="">Selecciona un namespace</option>';
      
      if (data.namespaces && data.namespaces.length > 0) {
        data.namespaces.forEach(ns => {
          const option = document.createElement('option');
          option.value = ns;
          option.textContent = ns;
          namespaceSelect.appendChild(option);
        });
        namespaceSelect.disabled = false;
      } else {
        namespaceSelect.innerHTML = '<option value="">No hay namespaces disponibles</option>';
      }
    } else {
      const errorMsg = data.detail || 'Error al cargar namespaces';
      namespaceSelect.innerHTML = `<option value="">Error: ${errorMsg}</option>`;
      mostrarResultado(`Error al cargar namespaces: ${errorMsg}`, 'warning');
    }
  } catch (error) {
    namespaceSelect.innerHTML = '<option value="">Error de conexión</option>';
    mostrarResultado(`Error de conexión al cargar namespaces: ${error.message}`, 'danger');
  } finally {
    loadingSpinner.style.display = 'none';
  }
}

/**
 * Carga los load balancers disponibles para un namespace
 */
async function cargarLoadBalancers() {
  const tenant = document.getElementById('tenant').value.trim();
  const namespace = document.getElementById('namespace').value;
  const lbSelect = document.getElementById('loadbalancer');
  const loadingSpinner = document.getElementById('lbLoading');
  const logType = document.getElementById('logType').value;

  if (!tenant || !namespace) {
    return;
  }

  // Si es audit log, no cargar load balancers
  if (logType === 'audit') {
    lbSelect.innerHTML = '<option value="">No requerido para Audit Logs</option>';
    lbSelect.disabled = true;
    return;
  }

  lbSelect.innerHTML = '<option value="">Cargando...</option>';
  lbSelect.disabled = true;
  loadingSpinner.style.display = 'inline-block';

  try {
    const response = await fetch(`${API_URL}/api/loadbalancers/${tenant}/${namespace}`);
    const data = await response.json();

    if (response.ok) {
      lbSelect.innerHTML = '<option value="">Selecciona un load balancer</option>';
      
      if (data.loadbalancers && data.loadbalancers.length > 0) {
        data.loadbalancers.forEach(lb => {
          const option = document.createElement('option');
          option.value = lb;
          option.textContent = lb;
          lbSelect.appendChild(option);
        });
        lbSelect.disabled = false;
        
        // Habilitar botón de diagnóstico
        const btnDiagnostico = document.getElementById('btnDiagnostico');
        if (btnDiagnostico && lbSelect.value) {
          btnDiagnostico.disabled = false;
        }
      } else {
        lbSelect.innerHTML = '<option value="">No hay load balancers disponibles</option>';
      }
    } else {
      const errorMsg = data.detail || 'Error al cargar load balancers';
      lbSelect.innerHTML = `<option value="">Error: ${errorMsg}</option>`;
      mostrarResultado(`Error al cargar load balancers: ${errorMsg}`, 'warning');
    }
  } catch (error) {
    lbSelect.innerHTML = '<option value="">Error de conexión</option>';
    mostrarResultado(`Error de conexión al cargar load balancers: ${error.message}`, 'danger');
  } finally {
    loadingSpinner.style.display = 'none';
  }
}

/**
 * Actualiza los campos del formulario según el tipo de log seleccionado
 */
function actualizarCamposSegunTipoLog() {
  const logType = document.getElementById('logType').value;
  const lbSelect = document.getElementById('loadbalancer');
  const lbContainer = lbSelect.closest('.col-md-4');
  const lbLabel = lbContainer.querySelector('label');
  const btnDiagnostico = document.getElementById('btnDiagnostico');
  
  if (logType === 'audit') {
    // Audit logs NO necesita load balancer
    lbSelect.disabled = true;
    lbSelect.required = false;
    lbSelect.value = '';
    lbSelect.innerHTML = '<option value="">No requerido para Audit Logs</option>';
    lbLabel.innerHTML = 'Load Balancer <small class="text-muted">(No requerido para Audit Logs)</small>';
    
    // Ocultar botón de diagnóstico
    if (btnDiagnostico) {
      btnDiagnostico.style.display = 'none';
    }
  } else {
    // Access y Security logs SÍ necesitan load balancer
    const namespace = document.getElementById('namespace').value;
    lbSelect.required = true;
    lbLabel.innerHTML = 'Load Balancer <span id="lbLoading" style="display:none;" class="loading-spinner"></span>';
    
    // Mostrar botón de diagnóstico
    if (btnDiagnostico) {
      btnDiagnostico.style.display = 'inline-block';
    }
    
    if (namespace) {
      lbSelect.disabled = false;
      if (!lbSelect.value || lbSelect.value === '') {
        cargarLoadBalancers();
      }
    } else {
      lbSelect.disabled = true;
      lbSelect.innerHTML = '<option value="">Primero selecciona un namespace</option>';
    }
  }
}

/**
 * Diagnostica por qué un load balancer no retorna logs
 */
async function diagnosticarLB() {
  const tenant = document.getElementById('tenant').value.trim();
  const namespace = document.getElementById('namespace').value;
  const loadbalancer = document.getElementById('loadbalancer').value;

  if (!tenant || !namespace || !loadbalancer) {
    mostrarResultado('Completa todos los campos antes de diagnosticar', 'warning');
    return;
  }

  mostrarResultado('<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Cargando...</span></div><p class="mt-2">Diagnosticando load balancer...</p>', 'info');

  try {
    const response = await fetch(`${API_URL}/api/diagnose/${tenant}/${namespace}/${loadbalancer}`);
    const data = await response.json();

    if (response.ok) {
      let html = `
        <div class="alert alert-info">
          <h5>🔍 Diagnóstico: ${loadbalancer}</h5>
          <p><strong>Estado:</strong> ${data.status === 'working' ? '✅ Funcional' : '⚠️ Sin logs'}</p>
          <p><strong>Recomendación:</strong> ${data.recommendation}</p>
          <hr>
          <h6>Pruebas Realizadas:</h6>
          <ul class="text-start">
      `;

      data.tests.forEach(test => {
        const icon = test.status === 'pass' ? '✅' : (test.logs_found > 0 ? '✅' : '❌');
        html += `<li>${icon} <strong>${test.name}:</strong> `;
        
        if (test.logs_found !== undefined) {
          html += `${test.logs_found} logs encontrados`;
        } else {
          html += test.status;
        }
        
        html += `</li>`;
      });

      html += `
          </ul>
        </div>
      `;

      mostrarResultado(html, 'info');
    } else {
      mostrarResultado(`Error en diagnóstico: ${data.detail}`, 'danger');
    }
  } catch (error) {
    mostrarResultado(`Error de conexión: ${error.message}`, 'danger');
  }
}

/**
 * Consulta los logs según los parámetros del formulario
 */
async function consultarLogs() {
  const tenant = document.getElementById('tenant').value.trim();
  const namespace = document.getElementById('namespace').value;
  const loadbalancer = document.getElementById('loadbalancer').value;
  const logType = document.getElementById('logType').value;
  const customHours = document.getElementById('customHours').value;
  const hours = customHours || selectedHours;

  // Validar campos según el tipo de log
  if (!tenant || !namespace) {
    mostrarResultado('Por favor completa tenant y namespace', 'warning');
    return;
  }
  
  if (logType !== 'audit' && !loadbalancer) {
    mostrarResultado('Por favor selecciona un load balancer', 'warning');
    return;
  }

  mostrarResultado('<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Cargando...</span></div><p class="mt-2">Consultando logs, por favor espera...</p>', 'info');

  try {
    const params = new URLSearchParams({
      log_type: logType,
      tenant: tenant,
      namespace: namespace,
      hours: hours
    });
    
    // Solo agregar loadbalancer si no es audit log
    if (logType !== 'audit') {
      params.append('loadbalancer', loadbalancer);
    }

    const response = await fetch(`${API_URL}/api/logs?${params}`);
    const data = await response.json();

    if (response.ok) {
      const downloadUrl = `${API_URL}/api/download?file=${data.file}`;
      mostrarResultado(`
        <div class="alert alert-success">
          <h5>¡Logs generados exitosamente!</h5>
          <p><strong>Tipo:</strong> ${data.log_type}</p>
          <p><strong>Archivo:</strong> ${data.file}</p>
          <p><strong>Registros:</strong> ${data.records || 'N/A'}</p>
          <p><strong>Tiempo:</strong> ${data.total_time_seconds || 'N/A'}s</p>
          <a href="${downloadUrl}" class="btn btn-primary mt-2" download>📥 Descargar CSV</a>
        </div>
      `, 'success');
    } else {
      const errorMsg = data.detail?.error || data.detail || 'Error desconocido';
      const errorDetails = data.detail?.stderr || data.detail?.stdout || '';
      
      mostrarResultado(`
        <div class="alert alert-danger">
          <strong>Error:</strong> ${errorMsg}
          ${errorDetails ? `<hr><pre class="text-start small">${errorDetails}</pre>` : ''}
        </div>
      `, 'danger');
    }
  } catch (error) {
    mostrarResultado(`<strong>Error de conexión:</strong> ${error.message}`, 'danger');
  }
}

/**
 * NUEVA FUNCIÓN: Envía logs directamente a Elasticsearch
 */
async function enviarAElastic() {
  const tenant = document.getElementById('tenant').value.trim();
  const namespace = document.getElementById('namespace').value;
  const loadbalancer = document.getElementById('loadbalancer').value;
  const logType = document.getElementById('logType').value;
  const customHours = document.getElementById('customHours').value;
  const hours = customHours || selectedHours;

  // Validar campos según el tipo de log
  if (!tenant || !namespace) {
    mostrarResultado('Por favor completa tenant y namespace', 'warning');
    return;
  }
  
  if (logType !== 'audit' && !loadbalancer) {
    mostrarResultado('Por favor selecciona un load balancer', 'warning');
    return;
  }

  // Validación adicional: por ahora solo soportamos access logs
  if (logType !== 'access') {
    mostrarResultado('⚠️ Solo Access Logs están soportados para Elasticsearch por ahora', 'warning');
    return;
  }

  mostrarResultado('<div class="spinner-border text-success" role="status"><span class="visually-hidden">Cargando...</span></div><p class="mt-2">Enviando logs a Elasticsearch, por favor espera...</p>', 'info');

  try {
    const params = new URLSearchParams({
      log_type: logType,
      tenant: tenant,
      namespace: namespace,
      hours: hours
    });
    
    // Solo agregar loadbalancer si no es audit log
    if (logType !== 'audit') {
      params.append('loadbalancer', loadbalancer);
    }

    const response = await fetch(`${API_URL}/api/logs/to-elastic?${params}`, {
      method: 'POST'
    });
    const data = await response.json();

    if (response.ok) {
      const successRate = ((data.elastic.success / data.records) * 100).toFixed(1);
      mostrarResultado(`
        <div class="alert alert-success">
          <h5>✅ Logs enviados a Elasticsearch</h5>
          <p><strong>Registros totales:</strong> ${data.records}</p>
          <p><strong>Indexados exitosamente:</strong> ${data.elastic.success} (${successRate}%)</p>
          ${data.elastic.failed > 0 ? `<p class="text-warning"><strong>Fallidos:</strong> ${data.elastic.failed}</p>` : ''}
          <p><strong>Tiempo de descarga:</strong> ${data.fetch_time_seconds}s</p>
          <p><strong>Tiempo total:</strong> ${data.total_time_seconds}s</p>
          <hr>
          <p class="mb-0"><strong>Índice:</strong> <code>f5-xc-logs</code></p>
          <small class="text-muted">Ahora puedes visualizar los datos en Kibana</small>
        </div>
      `, 'success');
    } else {
      const errorMsg = data.detail?.error || data.detail || 'Error desconocido';
      const errorDetails = data.detail?.traceback || '';
      
      mostrarResultado(`
        <div class="alert alert-danger">
          <h5>❌ Error al enviar a Elasticsearch</h5>
          <p><strong>Error:</strong> ${errorMsg}</p>
          ${errorDetails ? `<hr><details><summary>Ver detalles técnicos</summary><pre class="text-start small">${errorDetails}</pre></details>` : ''}
        </div>
      `, 'danger');
    }
  } catch (error) {
    mostrarResultado(`
      <div class="alert alert-danger">
        <h5>❌ Error de conexión</h5>
        <p>${error.message}</p>
        <small>Verifica que el servidor FastAPI esté ejecutándose y que Elasticsearch esté disponible.</small>
      </div>
    `, 'danger');
  }
}

/**
 * Muestra un mensaje de resultado al usuario
 */
function mostrarResultado(mensaje, tipo) {
  const resultado = document.getElementById('resultado');
  resultado.innerHTML = `<div class="alert alert-${tipo}">${mensaje}</div>`;
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
  // Listener para cambio de tipo de log
  const logTypeSelect = document.getElementById('logType');
  if (logTypeSelect) {
    logTypeSelect.addEventListener('change', actualizarCamposSegunTipoLog);
  }
  
  // Listener para habilitar botón de diagnóstico cuando se seleccione un LB
  const lbSelect = document.getElementById('loadbalancer');
  if (lbSelect) {
    lbSelect.addEventListener('change', function() {
      const btnDiagnostico = document.getElementById('btnDiagnostico');
      if (btnDiagnostico) {
        btnDiagnostico.disabled = !this.value;
      }
    });
  }
  
  // Inicializar estado del formulario
  actualizarCamposSegunTipoLog();
});
