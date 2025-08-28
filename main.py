import sys
import os
import shutil
from datetime import datetime
import atexit # <-- PASO 1: Importar el módulo atexit
import subprocess # <-- PASO 1.1: Importar subprocess
import requests
import json
import zipfile
import hashlib

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QStackedWidget, QMessageBox, QMenuBar, QDialog, QLabel, QLineEdit, QPushButton, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, pyqtSignal, QUrl # <-- MODIFICA ESTA LÍNEA
from PyQt6.QtGui import QIcon, QAction, QDesktopServices # <-- AÑADE ESTA LÍNEA

import utils.path_manager as path_manager
from utils.path_manager import APP_BASE_DIR, LOG_DIR, OUTPUT_VIDEO_DIR, \
    OUTPUT_SCREENSHOT_DIR, LOG_FILE_PATH, get_resource_path, ADB_PATH, TEMP_DIR

from utils.log_manager import log_activity, init_log_file
from utils.path_manager import get_updater_url # Importar la nueva función


# Importar módulo de activación
import utils.activation_manager as activation_manager



from ui.welcome_screen import WelcomeScreen
from ui.data_entry_screen import DataEntryScreen
from ui.capture_screen import CaptureScreen
from ui.summary_screen import SummaryScreen

# Define la versión actual de la aplicación DENTRO de tu código
APP_VERSION = "2.0.0" 

# --- V INICIO DE MODIFICACIÓN ---
# Hoja de estilos unificada para todos los checkboxes de la aplicación.
CHECKBOX_STYLE = """

"""

def _force_cleanup_processes():
    """
    Esta función se ejecutará al salir de la aplicación para forzar la terminación
    de cualquier subproceso que pueda haber quedado colgado.
    """
    print("INFO: Ejecutando limpieza forzada de procesos al salir...")
    processes_to_kill = ["adb.exe", "scrcpy.exe", "ffmpeg.exe"]
    for process_name in processes_to_kill:
        try:
            # Comando de Windows para matar un proceso por su nombre de imagen (/F forzar, /IM nombre de imagen)
            command = ["taskkill", "/F", "/IM", process_name]
            # Se ejecuta sin mostrar ventana de consola y sin esperar a que termine
            subprocess.run(command, check=False, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"INFO: Intento de terminación forzada para '{process_name}' enviado.")
        except Exception as e:
            print(f"ERROR: Fallo al intentar terminar forzadamente '{process_name}': {e}")
# --- ^ FIN DE LA NUEVA LÓGICA DE LIMPIEZA FORZADA ^ ---

def convert_drive_url(url):
    """
    Convierte una URL de vista previa de Google Drive a una de descarga directa,
    añadiendo el token de confirmación para evitar la página de advertencia.
    """
    if "drive.google.com" in url and "/file/d/" in url:
        try:
            file_id = url.split('/d/')[1].split('/')[0]
            # --- CORRECCIÓN CLAVE: Añadir "&confirm=t" ---
            return f"https://drive.google.com/uc?export=download&confirm=t&id={file_id}"
        except IndexError:
            return url
    return url

def check_for_updates():
    updater_url = get_updater_url()
    if not updater_url:
        print("URL del actualizador no configurada en config.ini.")
        return
    
    direct_download_url = convert_drive_url(updater_url)
    print(f"URL de actualización convertida a: {direct_download_url}")

    try:
        response = requests.get(direct_download_url)
        response.raise_for_status()

        try:
            data = response.json()
        except json.JSONDecodeError:
            print("--- ERROR DE ACTUALIZACIÓN ---")
            print("La respuesta del servidor no es un JSON válido.")
            print("Contenido recibido:")
            print(response.text)
            print("-----------------------------")
            return

        latest_version = data.get("version")

        if latest_version and latest_version > APP_VERSION:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("Actualización Disponible")
            msg_box.setText(f"Hay una nueva versión de BUHO disponible ({latest_version}).")
            msg_box.setInformativeText("¿Deseas descargar e instalar ahora?")
            
            # --- INICIO DE LA CORRECCIÓN CLAVE ---
            # Usamos botones estándar para una respuesta fiable.
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.button(QMessageBox.StandardButton.Yes).setText("Actualizar Ahora")
            msg_box.button(QMessageBox.StandardButton.No).setText("Más Tarde")
            
            # Comparamos el resultado con el botón estándar, no con un número.
            if msg_box.exec() == QMessageBox.StandardButton.Yes:
                print("Usuario aceptó la actualización. Iniciando descarga...")
                run_updater(data.get("assets", []))
            else:
                print("Usuario pospuso la actualización.")
            # --- FIN DE LA CORRECCIÓN CLAVE ---

    except requests.exceptions.RequestException as e:
        print(f"Error de red al buscar actualizaciones: {e}")
    except Exception as e:
        print(f"Error inesperado al buscar actualizaciones: {e}")

def run_updater(assets):
    """Descarga y reemplaza los archivos de la aplicación."""
    temp_update_dir = os.path.join(TEMP_DIR, "update")
    os.makedirs(temp_update_dir, exist_ok=True)
    
    commands = ["@echo off", "echo Actualizando BUHO..."]
    
    try:
        # 1. Descargar todos los activos. Ahora usamos un simple requests.get
        # porque la URL que genera convert_drive_url ya es directa.
        for asset in assets:
            print(f"Descargando {asset['name']}...")
            # Convertimos la URL de este asset específico
            direct_asset_url = convert_drive_url(asset['url'])
            response = requests.get(direct_asset_url, stream=True)
            response.raise_for_status()

            download_path = os.path.join(temp_update_dir, asset['name'])
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # 2. Preparar los comandos para el script .bat
            app_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__))

            if download_path.endswith('.zip'):
                extract_path = os.path.join(temp_update_dir, asset['name'].replace('.zip', ''))
                with zipfile.ZipFile(download_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
                
                dest_folder = os.path.join(app_dir, asset['destination'])
                commands.append(f'timeout /t 1 /nobreak > NUL')
                commands.append(f'rd /s /q "{dest_folder}"')
                commands.append(f'move "{extract_path}" "{dest_folder}"')

            elif download_path.endswith('.exe'):
                old_exe = os.path.join(app_dir, "BUHO.exe")
                commands.append(f'timeout /t 2 /nobreak > NUL')
                commands.append(f'rename "{old_exe}" "BUHO_old.exe"')
                commands.append(f'move "{download_path}" "{old_exe}"')

    except Exception as e:
        QMessageBox.critical(None, "Error de Actualización", f"No se pudo procesar la descarga: {e}")
        return

    # 3. Comandos finales para relanzar y limpiar
    commands.append("echo Limpiando...")
    commands.append('timeout /t 1 /nobreak > NUL')
    commands.append(f'del /f /q "{os.path.join(app_dir, "BUHO_old.exe")}"') 
    commands.append("echo Actualizacion completa! Reiniciando BUHO...")
    commands.append(f'start "" "{os.path.join(app_dir, "BUHO.exe")}"')
    
    # 4. Escribir y ejecutar el script .bat
    updater_script_path = os.path.join(temp_update_dir, "updater.bat")
    with open(updater_script_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(commands))
        
    subprocess.Popen(updater_script_path, creationflags=subprocess.CREATE_NO_WINDOW)
    sys.exit()

# Diálogo para generar y mostrar clave de hardware
class GenerateKeyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generar Cadena de Activación")
        self.setFixedSize(500, 150)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        
        info_label = QLabel("Copie la siguiente cadena y envíela al proveedor para la activación:")
        layout.addWidget(info_label)

        # CAMBIO CRÍTICO AQUÍ: Llamar a la nueva función que devuelve la cadena de hardware en bruto
        generated_key_text = activation_manager.get_hardware_key_to_send().upper()
        #log_activity(f"DEBUG: Cadena de hardware para QLabel: '{generated_key_text}'", level="debug")

        self.key_label = QLabel(generated_key_text)
        self.key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.key_label.setStyleSheet("""
            font-family: monospace; 
            font-size: 14px; 
            font-weight: bold; 
            padding: 5px; 
            background-color: #f0f0f0; 
            color: black; 
            border: 1px solid #ccc;
        """)
        layout.addWidget(self.key_label)

        copy_button = QPushButton("Copiar al Portapapeles")
        copy_button.clicked.connect(self._copy_key)
        
        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(copy_button)
        btn_layout.addWidget(close_button)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)

    def _copy_key(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.key_label.text())
        QMessageBox.information(self, "Copiado", "Clave copiada al portapapeles.")
        #log_activity("Clave de hardware copiada al portapapeles.", level="info")

# Diálogo para ingresar clave de activación
class ActivateAppDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Activar BUHO")
        self.setFixedSize(400, 150)
        self.activation_successful = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        info_label = QLabel("Ingrese la clave de activación:")
        layout.addWidget(info_label)

        self.activation_input = QLineEdit()
        self.activation_input.setPlaceholderText("Clave de activación...")
        layout.addWidget(self.activation_input)

        activate_button = QPushButton("Activar")
        activate_button.clicked.connect(self._activate)
        
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(activate_button)
        btn_layout.addWidget(cancel_button)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _activate(self):
        key = self.activation_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Clave Vacía", "Por favor, ingrese una clave de activación.")
            log_activity("Intento de activación con clave vacía en diálogo.", level="warning")
            return

        activation_manager.store_activation_key(key)
        self.activation_successful = activation_manager.is_activated()

        if self.activation_successful:
            QMessageBox.information(self, "Activación Exitosa", "La aplicación ha sido activada correctamente.")
            log_activity("Aplicación activada con éxito.", level="info")
            self.accept()
        else:
            QMessageBox.critical(self, "Error de Activación", "La clave ingresada no es válida.")
            log_activity("Fallo en la activación. Clave no válida.", level="error")
            # No cerramos el diálogo para permitir reintentar

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BUHO - Grabador de Evidencia Digital Android")

        # --- INICIO DE LÍNEAS A AÑADIR ---
        # Cargar y establecer el ícono de la ventana
        icon_path = os.path.join(path_manager.LOGOS_DIR, 'buho_logo.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"ADVERTENCIA: No se encontró el ícono en la ruta: {icon_path}")
        # --- FIN DE LÍNEAS A AÑADIR ---

        # --- AJUSTE DE LA VENTANA ---
        screen = QApplication.primaryScreen() # Obtener la pantalla primaria
        screen_geometry = screen.availableGeometry() # Obtener la geometría DISPONIBLE de la pantalla

        # Calcular el nuevo ancho (la mitad del ancho de la pantalla)
        new_width = int(screen_geometry.width() * 0.5)
        # Establecer la nueva altura al 85% de la altura disponible de la pantalla
        new_height = int(screen_geometry.height() * 0.90) 

        # Establecer el tamaño y la posición de la ventana.
        # Se usan las coordenadas x e y de la geometría disponible para asegurar que la ventana se posicione
        # correctamente desde la esquina superior izquierda del área de trabajo.
        self.setGeometry(screen_geometry.x(), screen_geometry.y(), new_width, new_height)
        
        self.setMinimumSize(800, 600) # Tamaño mínimo de la ventana
        # Fondo oscuro para la aplicación
        self.setStyleSheet("background-color: #2e2e2e; color: white;")

         # --- V LÓGICA DE INICIO CORREGIDA ---
        # 1. Llamar a la limpieza PRIMERO, antes de cualquier otra operación de archivos.
        self._cleanup_previous_session_files()
        
        # 2. AHORA, asegurarse de que todos los directorios existan para la nueva sesión.
        path_manager.ensure_dirs()

        # 3. Finalmente, inicializar el sistema de logs en la estructura limpia.
        init_log_file()
        log_activity("Aplicación iniciada.", level="info")
        # --- ^ FIN DE LÓGICA CORREGIDA ^ ---
        
        # Bandera para el estado de activación
        self.is_app_activated = False 
        # La carga y verificación del estado de activación se harán en WelcomeScreen.showEvent()

        self.current_device_id = None
        self.current_case_data = {}

        # Layout principal que contendrá el menú y el QStackedWidget
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0) # Eliminar márgenes para que la barra de menú ocupe todo el ancho

        # Configurar la barra de menú
        self.menu_bar = QMenuBar(self)
        self.menu_bar.setStyleSheet("""
            QMenuBar {
                background-color: #3a3a3a;
                color: white;
                font-size: 14px;
            }
            QMenuBar::item {
                spacing: 3px;
                padding: 2px 10px;
                background: transparent;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background: #5a5a5a;
            }
            QMenuBar::item:pressed {
                background: #6a6a6a;
            }
            QMenu {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #555;
            }
            QMenu::item {
                padding: 4px 20px;
            }
            QMenu::item:selected {
                background-color: #5a5a5a;
            }
        """)
        main_layout.addWidget(self.menu_bar)
        self._create_menus()

        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        self.setLayout(main_layout)

        # Crear instancias de las pantallas
        # Pasar 'self' (MainWindow) a WelcomeScreen para que pueda llamar a los métodos de activación
        self.welcome_screen = WelcomeScreen(self, ADB_PATH) 
        self.data_entry_screen = DataEntryScreen()
        self.capture_screen = CaptureScreen(ADB_PATH, os.path.join(APP_BASE_DIR, "scrcpy", "scrcpy.exe"), os.path.join(APP_BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe"))
        self.summary_screen = SummaryScreen()

        # Añadir pantallas al stacked widget
        self.stacked_widget.addWidget(self.welcome_screen)
        self.stacked_widget.addWidget(self.data_entry_screen)
        self.stacked_widget.addWidget(self.capture_screen)
        self.stacked_widget.addWidget(self.summary_screen)

        # Conectar señales entre pantallas
        self.welcome_screen.next_screen_signal.connect(self.go_to_data_entry)
        self.data_entry_screen.next_screen_signal.connect(self.go_to_capture)
        self.data_entry_screen.back_screen_signal.connect(self.go_to_welcome) # Para "Cancelar" en DataEntryScreen
        # ACTUALIZAR LA CONEXIÓN DE LA SEÑAL para pasar la lista de archivos importados
        self.capture_screen.capture_complete_signal.connect(self.go_to_summary)
        self.capture_screen.back_screen_signal.connect(self.go_to_data_entry) # Para "Cancelar" en CaptureScreen
        self.summary_screen.procedure_finished_signal.connect(self.go_to_welcome_after_summary) # Nueva señal para volver a inicio tras finalización
        self.summary_screen.return_to_initial_screen_signal.connect(self.go_to_welcome) # Para "Cancelar" en SummaryScreen

        # Mostrar la pantalla de bienvenida al inicio
        # CORRECCIÓN: Usar setCurrentWidget directamente para establecer la pantalla inicial
        self.stacked_widget.setCurrentWidget(self.welcome_screen)

# <-- INICIO DE NUEVA FUNCIÓN DE LIMPIEZA -->
    def _cleanup_previous_session_files(self):
        """
        Limpia directorios de sesiones anteriores usando el comando nativo de Windows
        para máxima compatibilidad y para evitar errores de permisos.
        """
        log_activity("Iniciando limpieza de archivos de sesiones anteriores (Método Nativo)...", "info")
        
        evidence_dir = os.path.join(APP_BASE_DIR, "output", "evidence")
        dirs_to_clear = [OUTPUT_VIDEO_DIR, OUTPUT_SCREENSHOT_DIR, TEMP_DIR, evidence_dir]

        for directory in dirs_to_clear:
            if not os.path.exists(directory):
                continue
            
            try:
                # --- V INICIO DE LA MODIFICACIÓN: Usar RD (RMDIR) de Windows ---
                # cmd /c -> Ejecuta el comando y luego termina
                # rd /s /q -> Borra un directorio (/s recursivo, /q silencioso)
                command = ["cmd", "/c", "rd", "/s", "/q", directory]
                result = subprocess.run(command, check=False, capture_output=True)

                if result.returncode == 0:
                    log_activity(f"Directorio '{os.path.basename(directory)}' limpiado con éxito.", "info")
                else:
                    # Si incluso RD falla, el problema es definitivamente externo (ej. antivirus muy agresivo)
                    # Decodificamos el error que devuelve la consola de Windows
                    error_msg = result.stderr.decode('cp850', errors='ignore').strip()
                    log_activity(f"El comando RD falló al limpiar '{os.path.basename(directory)}'. Error: {error_msg}", "critical")
                # --- ^ FIN DE LA MODIFICACIÓN ^ ---
            except Exception as e:
                log_activity(f"Excepción inesperada al intentar limpiar '{directory}': {e}", "critical")

        # Limpieza selectiva del directorio de logs (esto sí suele funcionar bien)
        try:
            if os.path.exists(LOG_DIR):
                for filename in os.listdir(LOG_DIR):
                    if filename.startswith(('case_log_', 'session_log_')) and filename.endswith('.log'):
                        file_path = os.path.join(LOG_DIR, filename)
                        os.remove(file_path)
        except Exception as e:
            log_activity(f"No se pudo limpiar el directorio de logs: {e}", "error")
        
        log_activity("Limpieza finalizada.", "info")
    # <-- FIN DE NUEVA FUNCIÓN DE LIMPIEZA -->

    # Crear la barra de menú y las acciones
    def _create_menus(self):
        # Menu Archivo
        file_menu = self.menu_bar.addMenu("Archivo")
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Menu Ayuda para la activación
        help_menu = self.menu_bar.addMenu("Ayuda")

        self.generate_key_action = QAction("Generar Cadena de Activación", self)
        self.generate_key_action.triggered.connect(self._show_generate_key_dialog)
        help_menu.addAction(self.generate_key_action)

        self.activate_buho_action = QAction("Activar BUHO", self)
        self.activate_buho_action.triggered.connect(self._show_activate_app_dialog)
        help_menu.addAction(self.activate_buho_action)

        # --- INICIO DE LÍNEAS A AÑADIR ---
        help_menu.addSeparator() # Añade una línea separadora (opcional, pero recomendado)
        
        manual_action = QAction("Manual BUHO", self)
        manual_action.triggered.connect(self._open_manual)
        help_menu.addAction(manual_action)
        # --- FIN DE LÍNEAS A AÑADIR ---

         # --- INICIO DE LÍNEAS A AÑADIR ---
        usb_videos_action = QAction("Videos de ejemplo para activar Depuración USB en Android", self)
        usb_videos_action.triggered.connect(self._open_usb_debugging_videos)
        help_menu.addAction(usb_videos_action)
        # --- FIN DE LÍNEAS A AÑADIR ---

 # --- INICIO DE NUEVO MÉTODO ---
    def _open_manual(self):
        """Abre el manual de usuario en el navegador web."""
        url = QUrl("https://drive.google.com/file/d/1pNqkiTqsXBNmtl7_szlFWE37zCxyrf6A/view?usp=drive_link")
        QDesktopServices.openUrl(url)
        log_activity("Abriendo el manual de usuario desde el menú de ayuda.", level="info")
    # --- FIN DE NUEVO MÉTODO ---

  # --- INICIO DE NUEVO MÉTODO ---
    def _open_usb_debugging_videos(self):
        """Abre la playlist de YouTube con videos de ayuda para la depuración USB."""
        url = QUrl("https://www.youtube.com/playlist?list=PLDsprGh8TMPUE2am7uxEAi_7eod2rBJ71")
        QDesktopServices.openUrl(url)
        log_activity("Abriendo playlist de videos de ayuda para Depuración USB.", level="info")
    # --- FIN DE NUEVO MÉTODO ---

    # Método para verificar y actualizar el estado de activación
    def _check_activation_status(self):
        self.is_app_activated = activation_manager.is_activated()
        log_activity(f"Estado de activación de la aplicación: {'Activada' if self.is_app_activated else 'No Activada'}", level="info")
        # Asegurarse de que welcome_screen se actualice al cambiar el estado
        if hasattr(self, 'welcome_screen'):
            self.welcome_screen.update_activation_ui(self.is_app_activated)

    # Métodos para mostrar los diálogos de activación
    def _show_generate_key_dialog(self):
        dialog = GenerateKeyDialog(self)
        dialog.exec()

    def _show_activate_app_dialog(self):
        dialog = ActivateAppDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Si la activación fue exitosa, re-verificar y actualizar la UI
            self._check_activation_status()
            # Si el usuario ya está en welcome_screen, forzar una actualización completa
            if self.stacked_widget.currentWidget() == self.welcome_screen:
                self.welcome_screen.detect_devices() # Re-detectar dispositivos si se activó

    def _load_config(self):
        # Esta función es un placeholder si necesitaras cargar otras configuraciones
        # por ahora, solo se usa para asegurar que config.ini se maneje al inicio
        pass

    def go_to_data_entry(self, device_id):
        # Añadir un chequeo de activación antes de pasar a la siguiente pantalla
        if not self.is_app_activated:
            QMessageBox.warning(self, "Aplicación No Activada", "Debe activar la aplicación para continuar.")
            log_activity("Intento de avanzar a carga de datos sin activación.", level="warning")
            return
            
        self.current_device_id = device_id
        log_activity(f"Navegando a DataEntryScreen para dispositivo: {self.current_device_id}", level="info")
        self.data_entry_screen.clear_form() # Limpiar campos al navegar
        self.stacked_widget.setCurrentWidget(self.data_entry_screen)
        # Aquí puedes pasar el device_id a DataEntryScreen si lo necesita para su inicialización
        # self.data_entry_screen.set_device_id(device_id) 

    def go_to_capture(self, case_data):
        """
        Navega a la pantalla de captura.
        Recibe los datos del caso directamente de la señal de DataEntryScreen.
        """
        self.current_case_data = case_data
        
        # <-- MODIFICACIÓN: Iniciar un nuevo log para este caso específico -->
        # Esto asegura que cada procedimiento tenga su propio archivo de log único.
        init_log_file(case_id=self.current_case_data.get('Expediente', 'SIN_EXP'))
        log_activity("Iniciando nuevo log para el caso.", level="info")




        # El self.current_device_id ya fue establecido en go_to_data_entry,
        # por lo que ahora sí la validación debería pasar.
        if not self.current_device_id or not self.current_case_data:
            log_activity("No se puede iniciar la captura: Falta la ID del dispositivo o los datos del caso.", level="error")
            QMessageBox.warning(self, "Error de Datos", "Por favor, complete los datos del caso y seleccione un dispositivo.")
            return

        # --- CAMBIO IMPORTANTE: Eliminamos la llamada a update_case_info() ---
        
        # 1. Asignamos el ID del dispositivo
        self.capture_screen.set_current_device_id(self.current_device_id)
        
        # 2. Asignamos los datos del caso.
        # (Sin un método de actualización en CaptureScreen, estos datos solo se almacenarán internamente).
        self.capture_screen.set_case_data(self.current_case_data)
        
        # Navegamos a la pantalla. Se espera que capture_screen sepa qué hacer con los nuevos datos.
        self.stacked_widget.setCurrentWidget(self.capture_screen)
        log_activity(f"Navegando a CaptureScreen. Datos del caso: {self.current_case_data} | Dispositivo ID: {self.current_device_id}")

    def go_to_summary(self, device_info, recorded_videos, recorded_screenshots, imported_files): # AÑADIR imported_files
        log_activity("Navegando a SummaryScreen.", level="info", device_id=self.current_device_id)
        # PASAR la nueva lista imported_files a update_summary
        self.summary_screen.set_summary_data(self.current_case_data, device_info, recorded_videos, recorded_screenshots, imported_files)
        self.stacked_widget.setCurrentWidget(self.summary_screen)

    def go_to_welcome(self):
        log_activity("Navegando a WelcomeScreen.", level="info")
        # Al regresar a la pantalla de bienvenida, limpiamos la selección
        self.current_device_id = None
        self.current_case_data = {}
        self.welcome_screen.clear_selection()
        self.stacked_widget.setCurrentWidget(self.welcome_screen)

    # Nueva función para manejar el retorno a WelcomeScreen después de finalizar el procedimiento
    def go_to_welcome_after_summary(self):
        log_activity("Procedimiento finalizado. Regresando a WelcomeScreen y preparando para nuevo caso.", level="info")
        self.current_device_id = None
        self.current_case_data = {}
        self.welcome_screen.clear_selection() # Asegura que la WelcomeScreen se reinicie para una nueva búsqueda
        self.stacked_widget.setCurrentWidget(self.welcome_screen)
        # Forzar una nueva verificación de activación y detección de dispositivos
        # Al establecer setCurrentWidget, se activará el showEvent de welcome_screen
        # que manejará la actualización de UI y la detección.

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Salir', "¿Estás seguro de que quieres salir?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            log_activity("Aplicación cerrada por el usuario.", level="info", device_id=getattr(self, 'current_device_id', 'N/A'))
            # Mover el log final al historial antes de salir definitivamente
            #move_global_log_to_history()

            # Asegurarse de detener cualquier proceso activo al cerrar la aplicación
            if hasattr(self, 'capture_screen'):
                self.capture_screen.stop_all_processes()
                log_activity("Procesos activos detenidos antes de cerrar la aplicación.", level="info", device_id=getattr(self, 'current_device_id', 'N/A'))

            event.accept()
        else:
            event.ignore()

if __name__ == "__main__":
    # --- V INICIO DE LA MODIFICACIÓN ---
    # Cambiar el directorio de trabajo actual a la carpeta de inicio del usuario.
    # Esto libera cualquier bloqueo del sistema operativo sobre la carpeta de la aplicación,
    # permitiendo que la función de limpieza elimine las subcarpetas sin errores.
    os.chdir(os.path.expanduser('~'))
    # --- ^ FIN DE LA MODIFICACIÓN ^ ---

    # --- V PASO 2: Registrar la función de limpieza ---
    # Esto asegura que _force_cleanup_processes se llame SIEMPRE que el script termine.
    atexit.register(_force_cleanup_processes)
    # --- ^ FIN DEL PASO 2 ^ ---


    app = QApplication(sys.argv)
    check_for_updates() # Llamada a la función
    app.setStyle("Fusion")
    app.setStyleSheet(CHECKBOX_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())