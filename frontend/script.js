const API_URL = 'http://192.168.0.219:8000';
let selectedHours = 24;
let lastTenant = '';

// Mapeo de tipos de log a índices de Elasticsearch
const ELK_INDICES = {
  'access': 'f5xc-access-logs',
  'audit': 'f5xc-audit-logs',
  'security': 'f5xc-security-events'
};

// ==========================================
// CREDENCIALES DE ACCESO (BÁSICO)
// Próximamente se reemplazará por Entra ID
// ==========================================
const VALID_CREDENTIALS = {
  'desarrollongeek@gmail.com': 'prueba'
};

// ==========================================
// FUNCIONES DE AUTENTICACIÓN
// ==========================================

/**
 * Verifica si el usuario está autenticado
 */
function checkAuth() {
  const session = sessionStorage.getItem('f5xc_session');
  if (session) {
    try {
      const sessionData = JSON.parse(session);
      if (sessionData.email && sessionData.authenticated) {
        return sessionData;
      }
    } catch (e) {
      console.error('Error parsing session:', e);
    }
  }
  return null;
}

/**
 * Muestra la pantalla correspondiente según el estado de autenticación
 */
function showAppropriateScreen() {
  const session = checkAuth();
  const loginScreen = document.getElementById('loginScreen');
  const mainApp = document.getElementById('mainApp');
  
  if (session) {
    // Usuario autenticado - mostrar app principal
    loginScreen.style.display = 'none';
    mainApp.style.display = 'block';
    
    // Mostrar email del usuario
    var userEmailDisplay = document.getElementById('userEmailDisplay');
    if (userEmailDisplay) {
      userEmailDisplay.textContent = session.email;
    }
    
    // Inicializar la aplicación
    initializeApp();
  } else {
    // No autenticado - mostrar login
    loginScreen.style.display = 'flex';
    mainApp.style.display = 'none';
  }
}

/**
 * Maneja el envío del formulario de login
 */
function handleLogin(event) {
  event.preventDefault();
  
  var email = document.getElementById('loginEmail').value.trim().toLowerCase();
  var password = document.getElementById('loginPassword').value;
  var loginError = document.getElementById('loginError');
  var loginErrorMsg = document.getElementById('loginErrorMsg');
  
  // Verificar credenciales
  if (VALID_CREDENTIALS[email] && VALID_CREDENTIALS[email] === password) {
    // Credenciales válidas - crear sesión
    var sessionData = {
      email: email,
      authenticated: true,
      loginTime: new Date().toISOString()
    };
    
    sessionStorage.setItem('f5xc_session', JSON.stringify(sessionData));
    
    // Ocultar error si estaba visible
    loginError.style.display = 'none';
    
    // Mostrar app principal
    showAppropriateScreen();
  } else {
    // Credenciales inválidas
    loginErrorMsg.textContent = 'Correo o contraseña incorrectos';
    loginError.style.display = 'block';
    
    // Limpiar campo de contraseña
    document.getElementById('loginPassword').value = '';
  }
  
  return false;
}

/**
 * Cierra la sesión del usuario
 */
function handleLogout() {
  sessionStorage.removeItem('f5xc_session');
  showAppropriateScreen();
  
  // Limpiar formulario de login
  document.getElementById('loginForm').reset();
  document.getElementById('loginError').style.display = 'none';
}

/**
 * Inicializa la aplicación después del login
 */
function initializeApp() {
  console.log('Inicializando aplicación...');
  
  // Verificar conexión ELK
  verificarConexionELK();
  
  // Actualizar índice ELK inicial
  actualizarIndiceELK();
  
  // Inicializar estado del formulario
  actualizarCamposSegunTipoLog();
}

// ==========================================
// FUNCIONES DE CONFIGURACIÓN ELK (AL INICIO)
// ==========================================

/**
 * Verifica la conexión a Elasticsearch y actualiza el indicador de estado
 */
async function verificarConexionELK() {
  const statusEl = document.getElementById('elkStatus');
  if (!statusEl) return;
  
  statusEl.className = 'elk-status checking ms-2';
  statusEl.innerHTML = '<span class="status-dot yellow"></span> Verificando...';
  
  try {
    const response = await fetch(`${API_URL}/api/elk/test`);
    const data = await response.json();
    
    if (data.status === 'connected') {
      statusEl.className = 'elk-status connected ms-2';
      statusEl.innerHTML = '<span class="status-dot green"></span> Conectado (v' + (data.version || '?') + ')';
    } else {
      statusEl.className = 'elk-status disconnected ms-2';
      statusEl.innerHTML = '<span class="status-dot red"></span> Desconectado';
    }
  } catch (error) {
    statusEl.className = 'elk-status disconnected ms-2';
    statusEl.innerHTML = '<span class="status-dot red"></span> Error';
    console.error('Error verificando ELK:', error);
  }
}

/**
 * Muestra el panel de configuración de ELK
 */
function mostrarConfigELK() {
  console.log('mostrarConfigELK llamada');
  const configSection = document.getElementById('elkConfigSection');
  if (configSection) {
    configSection.style.display = 'block';
    
    // Cargar configuración actual
    fetch(API_URL + '/api/elk/config')
      .then(function(response) { return response.json(); })
      .then(function(data) {
        var elkUrlInput = document.getElementById('elkUrl');
        var elkAuthMethod = document.getElementById('elkAuthMethod');
        
        if (elkUrlInput) {
          elkUrlInput.value = data.url || 'http://192.168.0.200:9200';
        }
        if (elkAuthMethod) {
          elkAuthMethod.value = data.auth_method || 'api_key';
          toggleAuthFields();
        }
      })
      .catch(function(error) {
        console.error('Error cargando config ELK:', error);
      });
  } else {
    console.error('No se encontró elkConfigSection');
  }
}

/**
 * Alterna la visibilidad de los campos de autenticación
 */
function toggleAuthFields() {
  var authMethod = document.getElementById('elkAuthMethod').value;
  var apiKeyField = document.getElementById('apiKeyField');
  var basicAuthUser = document.getElementById('basicAuthUser');
  var basicAuthPass = document.getElementById('basicAuthPass');
  
  if (authMethod === 'api_key') {
    apiKeyField.style.display = 'block';
    basicAuthUser.style.display = 'none';
    basicAuthPass.style.display = 'none';
  } else {
    apiKeyField.style.display = 'none';
    basicAuthUser.style.display = 'block';
    basicAuthPass.style.display = 'block';
  }
}

/**
 * Oculta el panel de configuración de ELK
 */
function ocultarConfigELK() {
  const configSection = document.getElementById('elkConfigSection');
  if (configSection) {
    configSection.style.display = 'none';
  }
}

/**
 * Guarda la configuración de Elasticsearch
 */
async function guardarConfigELK() {
  var authMethod = document.getElementById('elkAuthMethod').value;
  
  var config = {
    url: document.getElementById('elkUrl').value,
    auth_method: authMethod,
    api_key: null,
    username: null,
    password: null
  };
  
  if (authMethod === 'api_key') {
    config.api_key = document.getElementById('elkApiKey').value || null;
  } else {
    config.username = document.getElementById('elkUsername').value || null;
    config.password = document.getElementById('elkPassword').value || null;
  }
  
  try {
    const response = await fetch(API_URL + '/api/elk/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    
    const data = await response.json();
    
    if (response.ok) {
      mostrarResultado('✅ Configuración de Elasticsearch guardada correctamente (' + authMethod + ')', 'success');
      verificarConexionELK();
      ocultarConfigELK();
    } else {
      mostrarResultado('❌ Error guardando configuración: ' + data.detail, 'danger');
    }
  } catch (error) {
    mostrarResultado('❌ Error de conexión: ' + error.message, 'danger');
  }
}

/**
 * Prueba la conexión a Elasticsearch
 */
async function testConexionELK() {
  mostrarResultado('<div class="spinner-border spinner-border-sm"></div> Probando conexión a Elasticsearch...', 'info');
  
  await verificarConexionELK();
  
  setTimeout(function() {
    const statusEl = document.getElementById('elkStatus');
    if (statusEl && statusEl.classList.contains('connected')) {
      mostrarResultado('✅ Conexión exitosa a Elasticsearch', 'success');
    } else {
      mostrarResultado('❌ No se pudo conectar a Elasticsearch. Verifica la URL y credenciales.', 'danger');
    }
  }, 1500);
}

/**
 * Actualiza el campo de índice ELK según el tipo de log
 */
function actualizarIndiceELK() {
  const logTypeSelect = document.getElementById('logType');
  const elkIndexInput = document.getElementById('elkIndex');
  if (logTypeSelect && elkIndexInput) {
    const logType = logTypeSelect.value;
    elkIndexInput.value = ELK_INDICES[logType] || 'f5xc-access-logs';
  }
}

// ==========================================
// FUNCIONES DE FORMULARIO
// ==========================================

/**
 * Establece el rango de horas seleccionado
 */
function setHours(hours) {
  selectedHours = hours;
  document.getElementById('customHours').value = '';
  
  // Actualizar botones activos
  document.querySelectorAll('.btn-range').forEach(function(btn) {
    btn.classList.remove('active');
  });
  if (event && event.target) {
    event.target.classList.add('active');
  }
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
  
  document.querySelectorAll('.btn-range').forEach(function(btn) {
    btn.classList.remove('active');
  });
  // Marcar 1 Día como activo por defecto
  const btnRanges = document.querySelectorAll('.btn-range');
  if (btnRanges[2]) {
    btnRanges[2].classList.add('active');
  }
  
  // Actualizar índice ELK
  actualizarIndiceELK();
}

/**
 * Muestra un mensaje de resultado al usuario
 */
function mostrarResultado(mensaje, tipo) {
  const resultado = document.getElementById('resultado');
  if (resultado) {
    resultado.innerHTML = '<div class="alert alert-' + tipo + '">' + mensaje + '</div>';
  }
}

// ==========================================
// CARGA DINÁMICA DE DATOS
// ==========================================

/**
 * Carga los namespaces disponibles para un tenant
 */
async function cargarNamespaces() {
  const tenantSelect = document.getElementById('tenant');
  const tenant = tenantSelect ? tenantSelect.value.trim() : '';
  const namespaceSelect = document.getElementById('namespace');
  const lbSelect = document.getElementById('loadbalancer');
  const loadingSpinner = document.getElementById('namespaceLoading');

  if (!tenant || tenant === lastTenant) {
    return;
  }

  lastTenant = tenant;

  namespaceSelect.innerHTML = '<option value="">Cargando...</option>';
  namespaceSelect.disabled = true;
  lbSelect.innerHTML = '<option value="">Primero selecciona un namespace</option>';
  lbSelect.disabled = true;
  if (loadingSpinner) loadingSpinner.style.display = 'inline-block';

  try {
    const response = await fetch(API_URL + '/api/namespaces/' + tenant);
    const data = await response.json();

    if (response.ok) {
      namespaceSelect.innerHTML = '<option value="">Selecciona un namespace</option>';
      
      if (data.namespaces && data.namespaces.length > 0) {
        data.namespaces.forEach(function(ns) {
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
      namespaceSelect.innerHTML = '<option value="">Error: ' + errorMsg + '</option>';
      mostrarResultado('Error al cargar namespaces: ' + errorMsg, 'warning');
    }
  } catch (error) {
    namespaceSelect.innerHTML = '<option value="">Error de conexión</option>';
    mostrarResultado('Error de conexión al cargar namespaces: ' + error.message, 'danger');
  } finally {
    if (loadingSpinner) loadingSpinner.style.display = 'none';
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

  if (logType === 'audit') {
    lbSelect.innerHTML = '<option value="">No requerido para Audit Logs</option>';
    lbSelect.disabled = true;
    return;
  }

  lbSelect.innerHTML = '<option value="">Cargando...</option>';
  lbSelect.disabled = true;
  if (loadingSpinner) loadingSpinner.style.display = 'inline-block';

  try {
    const response = await fetch(API_URL + '/api/loadbalancers/' + tenant + '/' + namespace);
    const data = await response.json();

    if (response.ok) {
      lbSelect.innerHTML = '<option value="">Selecciona un load balancer</option>';
      
      if (data.loadbalancers && data.loadbalancers.length > 0) {
        data.loadbalancers.forEach(function(lb) {
          const option = document.createElement('option');
          option.value = lb;
          option.textContent = lb;
          lbSelect.appendChild(option);
        });
        lbSelect.disabled = false;
      } else {
        lbSelect.innerHTML = '<option value="">No hay load balancers disponibles</option>';
      }
    } else {
      const errorMsg = data.detail || 'Error al cargar load balancers';
      lbSelect.innerHTML = '<option value="">Error: ' + errorMsg + '</option>';
      mostrarResultado('Error al cargar load balancers: ' + errorMsg, 'warning');
    }
  } catch (error) {
    lbSelect.innerHTML = '<option value="">Error de conexión</option>';
    mostrarResultado('Error de conexión al cargar load balancers: ' + error.message, 'danger');
  } finally {
    if (loadingSpinner) loadingSpinner.style.display = 'none';
  }
}

/**
 * Actualiza los campos del formulario según el tipo de log seleccionado
 */
function actualizarCamposSegunTipoLog() {
  const logType = document.getElementById('logType').value;
  const lbSelect = document.getElementById('loadbalancer');
  const lbContainer = lbSelect.closest('.col-md-4');
  const lbLabel = lbContainer ? lbContainer.querySelector('label') : null;
  const btnDiagnostico = document.getElementById('btnDiagnostico');
  
  actualizarIndiceELK();
  
  if (logType === 'audit') {
    lbSelect.disabled = true;
    lbSelect.required = false;
    lbSelect.value = '';
    lbSelect.innerHTML = '<option value="">No requerido para Audit Logs</option>';
    if (lbLabel) {
      lbLabel.innerHTML = 'Load Balancer <small class="text-muted">(No requerido para Audit Logs)</small>';
    }
    if (btnDiagnostico) {
      btnDiagnostico.style.display = 'none';
    }
  } else {
    const namespace = document.getElementById('namespace').value;
    lbSelect.required = true;
    if (lbLabel) {
      lbLabel.innerHTML = 'Load Balancer <span id="lbLoading" style="display:none;" class="loading-spinner"></span>';
    }
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

// ==========================================
// FUNCIONES DE DIAGNÓSTICO Y CONSULTA
// ==========================================

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
    const response = await fetch(API_URL + '/api/diagnose/' + tenant + '/' + namespace + '/' + loadbalancer);
    const data = await response.json();

    if (response.ok) {
      let html = '<div class="alert alert-info">';
      html += '<h5>🔍 Diagnóstico: ' + loadbalancer + '</h5>';
      html += '<p><strong>Estado:</strong> ' + (data.status === 'working' ? '✅ Funcional' : '⚠️ Sin logs') + '</p>';
      html += '<p><strong>Recomendación:</strong> ' + data.recommendation + '</p>';
      html += '<hr><h6>Pruebas Realizadas:</h6><ul class="text-start">';

      if (data.tests && data.tests.length > 0) {
        data.tests.forEach(function(test) {
          const icon = test.status === 'pass' ? '✅' : (test.logs_found > 0 ? '✅' : '❌');
          html += '<li>' + icon + ' <strong>' + test.name + ':</strong> ';
          if (test.logs_found !== undefined) {
            html += test.logs_found + ' logs encontrados';
          } else {
            html += test.status;
          }
          html += '</li>';
        });
      }

      html += '</ul></div>';
      mostrarResultado(html, 'info');
    } else {
      mostrarResultado('Error en diagnóstico: ' + data.detail, 'danger');
    }
  } catch (error) {
    mostrarResultado('Error de conexión: ' + error.message, 'danger');
  }
}

/**
 * Consulta los logs según los parámetros del formulario (genera CSV)
 */
async function consultarLogs() {
  const tenant = document.getElementById('tenant').value.trim();
  const namespace = document.getElementById('namespace').value;
  const loadbalancer = document.getElementById('loadbalancer').value;
  const logType = document.getElementById('logType').value;
  const customHours = document.getElementById('customHours').value;
  const hours = customHours || selectedHours;

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
    let url = API_URL + '/api/logs?log_type=' + logType + '&tenant=' + tenant + '&namespace=' + namespace + '&hours=' + hours;
    
    if (logType !== 'audit') {
      url += '&loadbalancer=' + loadbalancer;
    }

    const response = await fetch(url);
    const data = await response.json();

    if (response.ok) {
      const downloadUrl = API_URL + '/api/download?file=' + data.file;
      let html = '<div class="alert alert-success">';
      html += '<h5>✅ Logs generados exitosamente</h5>';
      html += '<p><strong>Tipo:</strong> ' + data.log_type + '</p>';
      html += '<p><strong>Archivo:</strong> ' + data.file + '</p>';
      html += '<p><strong>Registros:</strong> ' + (data.records ? data.records.toLocaleString() : 'N/A') + '</p>';
      html += '<p><strong>Tiempo:</strong> ' + (data.total_time_seconds || 'N/A') + 's</p>';
      html += '<a href="' + downloadUrl + '" class="btn btn-primary mt-2" download><i class="bi bi-download"></i> Descargar CSV</a>';
      html += '</div>';
      mostrarResultado(html, 'success');
    } else {
      const errorMsg = data.detail?.error || data.detail || 'Error desconocido';
      const errorDetails = data.detail?.stderr || data.detail?.stdout || '';
      let html = '<div class="alert alert-danger"><strong>Error:</strong> ' + errorMsg;
      if (errorDetails) {
        html += '<hr><pre class="text-start small">' + errorDetails + '</pre>';
      }
      html += '</div>';
      mostrarResultado(html, 'danger');
    }
  } catch (error) {
    mostrarResultado('<strong>Error de conexión:</strong> ' + error.message, 'danger');
  }
}

/**
 * Envía logs directamente a Elasticsearch
 */
async function enviarAElastic() {
  const tenant = document.getElementById('tenant').value.trim();
  const namespace = document.getElementById('namespace').value;
  const loadbalancer = document.getElementById('loadbalancer').value;
  const logType = document.getElementById('logType').value;
  const customHours = document.getElementById('customHours').value;
  const hours = customHours || selectedHours;
  const indexName = ELK_INDICES[logType];

  if (!tenant || !namespace) {
    mostrarResultado('Por favor completa tenant y namespace', 'warning');
    return;
  }
  
  if (logType !== 'audit' && !loadbalancer) {
    mostrarResultado('Por favor selecciona un load balancer', 'warning');
    return;
  }

  mostrarResultado(
    '<div class="text-center">' +
    '<div class="spinner-border text-success" role="status"><span class="visually-hidden">Cargando...</span></div>' +
    '<p class="mt-2">Enviando logs a Elasticsearch...</p>' +
    '<small class="text-muted">Índice destino: <code>' + indexName + '</code></small>' +
    '</div>',
    'info'
  );

  try {
    let url = API_URL + '/api/logs/elk?log_type=' + logType + '&tenant=' + tenant + '&namespace=' + namespace + '&hours=' + hours;
    
    if (logType !== 'audit') {
      url += '&loadbalancer=' + loadbalancer;
    }

    const response = await fetch(url, { method: 'POST' });
    const data = await response.json();

    if (response.ok && data.success) {
      let html = '<div class="alert alert-success">';
      html += '<h5>✅ Logs enviados a Elasticsearch</h5>';
      html += '<div class="row text-center mt-3">';
      html += '<div class="col-3"><div class="h4 mb-0 text-primary">' + (data.documents_sent ? data.documents_sent.toLocaleString() : 0) + '</div><small class="text-muted">Documentos</small></div>';
      html += '<div class="col-3"><div class="h4 mb-0 ' + (data.errors > 0 ? 'text-danger' : 'text-success') + '">' + (data.errors || 0) + '</div><small class="text-muted">Errores</small></div>';
      html += '<div class="col-3"><div class="h4 mb-0">' + (data.fetch_time_seconds || 0) + 's</div><small class="text-muted">Fetch</small></div>';
      html += '<div class="col-3"><div class="h4 mb-0">' + (data.total_time_seconds || 0) + 's</div><small class="text-muted">Total</small></div>';
      html += '</div><hr>';
      html += '<p class="mb-1"><strong>Índice:</strong> <code>' + data.index + '</code></p>';
      html += '<p class="mb-1"><strong>Tenant:</strong> ' + data.tenant + '</p>';
      html += '<p class="mb-1"><strong>Namespace:</strong> ' + data.namespace + '</p>';
      if (data.loadbalancer) {
        html += '<p class="mb-1"><strong>Load Balancer:</strong> ' + data.loadbalancer + '</p>';
      }
      if (data.took_ms) {
        html += '<p class="mb-0"><small class="text-muted">Elasticsearch took: ' + data.took_ms + 'ms</small></p>';
      }
      html += '</div>';
      mostrarResultado(html, 'success');
    } else {
      const errorMsg = data.message || (data.detail ? (data.detail.error || data.detail) : 'Error desconocido');
      let html = '<div class="alert alert-danger">';
      html += '<h5>❌ Error al enviar a Elasticsearch</h5>';
      html += '<p><strong>Error:</strong> ' + errorMsg + '</p>';
      if (data.detail && data.detail.traceback) {
        html += '<hr><details><summary>Ver detalles técnicos</summary>';
        html += '<pre class="text-start small mt-2">' + data.detail.traceback + '</pre></details>';
      }
      html += '</div>';
      mostrarResultado(html, 'danger');
    }
  } catch (error) {
    mostrarResultado(
      '<div class="alert alert-danger">' +
      '<h5>❌ Error de conexión</h5>' +
      '<p>' + error.message + '</p>' +
      '<small class="text-muted">Verifica que el servidor FastAPI esté ejecutándose y que Elasticsearch esté disponible.</small>' +
      '</div>',
      'danger'
    );
  }
}

// ==========================================
// EVENT LISTENERS
// ==========================================
document.addEventListener('DOMContentLoaded', function() {
  console.log('Script cargado correctamente');
  
  // Verificar autenticación y mostrar pantalla apropiada
  showAppropriateScreen();
  
  // Listener para cambio de tipo de log
  var logTypeSelect = document.getElementById('logType');
  if (logTypeSelect) {
    logTypeSelect.addEventListener('change', actualizarCamposSegunTipoLog);
  }
  
  // Listener para habilitar botón de diagnóstico cuando se seleccione un LB
  var lbSelect = document.getElementById('loadbalancer');
  if (lbSelect) {
    lbSelect.addEventListener('change', function() {
      var btnDiagnostico = document.getElementById('btnDiagnostico');
      if (btnDiagnostico) {
        btnDiagnostico.disabled = !this.value;
      }
    });
  }
});
