// Aplica el tema y el tamaño de letra guardados antes de pintar la página, para que no parpadee.
// Va como archivo aparte porque la política de seguridad (CSP) no permite scripts en línea.
try {
  const p = JSON.parse(localStorage.getItem('hidrosar:preferencias') || '{}')
  if (p.tema === 'claro' || p.tema === 'oscuro') document.documentElement.dataset.tema = p.tema
  if (typeof p.letra === 'number' && p.letra >= 0.8 && p.letra <= 1.5) document.documentElement.style.setProperty('--escala', p.letra)
} catch {
  // sin almacenamiento del navegador: tema del sistema y letra normal
}
