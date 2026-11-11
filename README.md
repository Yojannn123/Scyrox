#  Scyrox V8 Battery Monitor & Widget

Un widget elegante, minimalista y ultra ligero para monitorear en tiempo real la batería de tu mouse **Scyrox V8** (y V6) directamente en Windows, sin necesidad de abrir el navegador ni la web oficial.

---

##  Características Principales

1. **Superposición sobre Juegos (Gaming Overlay):**
   - **Siempre visible encima de juegos:** Configurado con atributos Win32 (`WS_EX_TOPMOST` y reaserción periódica) para flotar encima de tus juegos en pantalla completa sin bordes / ventana.
   - **No interrumpe tus partidas:** Cuenta con `WS_EX_NOACTIVATE`, lo que significa que el widget nunca le roba el foco a tu juego ni te minimizará una partida.
   - **Modo Clics Transparentes (Click-through):** Puedes activar esta opción desde el menú clic derecho para que tus disparos o clics del ratón atraviesen el widget como si fuera invisible al cursor, ideal para tenerlo en una esquina sin que interfiera con tu puntería.

2. **Monitoreo en Vivo de Carga por Cable:**
   - **Detección instantánea de cable:** En cuanto conectas tu mouse por cable USB Type-C, el widget y la bandeja detectan el cambio en menos de 1.5 segundos.
   - **Porcentaje en tiempo real:** Muestra claramente:
     - `⚡ Cargando: X%` junto con el voltaje de la celda.
   - **Aviso de desconexión al 100%:** Cuando la batería se llena al 100%, el widget cambia a verde brillante (`🟢 100% Completo • Quitar cable`) y Windows te envía una notificación sonora para avisarte que ya puedes desconectarlo y jugar sin cable.

2. **Integración con la Bandeja del Sistema (Taskbar Tray):**
   - Icono dinámico junto al reloj de Windows que dibuja el número exacto del porcentaje de batería restante con colores intuitivos:
     - 🟢 **Verde (>= 40%):** Batería óptima.
     - 🟡 **Amarillo (20% - 39%):** Batería media.
     - 🔴 **Rojo (< 20%):** Batería baja.
     - ⚡ **Cian:** Cargando con animación / rayo.
     - 💤 **Gris:** Modo reposo / ahorro de energía.
   - Si no quieres tener el widget en pantalla, puedes ocultarlo y dejar solo el icono de la bandeja del sistema.

3. **Alertas Inteligentes (Para saber cuándo cargarlo):**
   - Te envía una notificación nativa de Windows cuando la batería llega al 20% o menos para que nunca te quedes sin mouse a mitad de una partida o trabajo.
   - Te avisa cuando la batería se cargó al 100% para que puedas desconectar el cable.

4. **Inicio Automático con Windows:**
   - Se ejecuta automáticamente en segundo plano al encender tu PC (`HKCU\Run`).
   - Sin ventanas negras de consola ni distracciones.

5. **Detección de Reposo (Sleep Mode):**
   - Los ratones inalámbricos entran en modo suspensión tras unos minutos de inactividad para ahorrar batería. El monitor lo detecta automáticamente, guarda en caché el último porcentaje registrado y lo mantiene visible en modo reposo (`💤`) sin parpadeos ni errores.

---

##  Controles Rápidos

- **Clic Izquierdo y Arrastrar:** Mueve el widget por la pantalla.
- **Doble Clic:** Alterna entre Modo Detallado y Modo Compacto.
- **Clic Derecho en el Widget:** Abre el menú contextual rápido (Ocultar, Bloquear, Iniciar con Windows, Salir).
- **Clic en el Icono del Reloj (Bandeja):** Muestra u oculta el widget flotante al instante.

---

##  Inicio y Configuración

Puedes iniciar el programa haciendo doble clic en:
- `Iniciar_Scyrox_Widget.bat` o
- `dist\ScyroxWidget\ScyroxWidget.exe`

Los ajustes se guardan automáticamente en `data/config.json`.

