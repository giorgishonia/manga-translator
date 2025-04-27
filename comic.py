import os, sys
import re

# --- Manually add potential NVIDIA paths --- START
def adjust_nvidia_paths():
    print("--- NVIDIA Path Adjustment --- START")
    TARGET_CUDA_VERSION = "12.1"
    target_cuda_base = f"C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v{TARGET_CUDA_VERSION}"
    target_cuda_paths = {
        "bin": os.path.join(target_cuda_base, "bin"),
        "libnvvp": os.path.join(target_cuda_base, "libnvvp")
    }
    nvidia_smi_path = r"C:\Program Files\NVIDIA Corporation\NVSMI"

    current_path = os.environ.get('PATH', '')
    current_path_list = current_path.split(os.pathsep)
    print(f"Original PATH (first 300 chars): {current_path[:300]}...")

    paths_to_prepend = []
    found_target_paths_exist = False
    for name, path in target_cuda_paths.items():
        if os.path.isdir(path):
            found_target_paths_exist = True
            print(f"Target CUDA {TARGET_CUDA_VERSION} path found: {path}")
            if path not in current_path_list:
                print(f"  -> Adding {name} path to PATH.")
                paths_to_prepend.append(path)
            else:
                print(f"  -> {name} path already in PATH.")
        else:
            print(f"Target CUDA {TARGET_CUDA_VERSION} path NOT found: {path}")
            
    if os.path.isdir(nvidia_smi_path) and nvidia_smi_path not in current_path_list:
         print(f"NVSMI path found and not in PATH, adding: {nvidia_smi_path}")
         paths_to_prepend.append(nvidia_smi_path)

    if not found_target_paths_exist:
        print(f"WARNING: Core CUDA {TARGET_CUDA_VERSION} directories ({target_cuda_base}\bin, etc.) not found!")
        print("         Please ensure CUDA Toolkit {TARGET_CUDA_VERSION} is installed correctly.")

    # Check for other CUDA versions in PATH
    other_cuda_versions = set()
    cuda_path_pattern = re.compile(r"nvidia gpu computing toolkit\\cuda\\v(\d+\.\d+)", re.IGNORECASE)
    for p in current_path_list:
        match = cuda_path_pattern.search(p)
        if match:
            version = match.group(1)
            if version != TARGET_CUDA_VERSION:
                other_cuda_versions.add(version)
                
    if other_cuda_versions:
        print(f"WARNING: Found paths for other CUDA versions ({', '.join(other_cuda_versions)}) in PATH.")
        print("         This might conflict with PyTorch compiled for {TARGET_CUDA_VERSION}.")
        print("         Consider adjusting your system PATH or installing PyTorch for the detected version if available.")

    if paths_to_prepend:
        new_path_str = os.pathsep.join(paths_to_prepend) + os.pathsep + current_path
        os.environ['PATH'] = new_path_str
        print(f"Updated PATH (first 300 chars): {os.environ['PATH'][:300]}...")
    else:
        print("No new paths were prepended to PATH.")
    print("--- NVIDIA Path Adjustment --- END")

adjust_nvidia_paths() # Run the adjustment
# --- Manually add potential NVIDIA paths --- END

# --- Early CUDA Check --- START
try:
    import torch
    print(f"PyTorch Location: {torch.__file__}") # Print where torch is imported from
    print(f"Attempting torch.cuda.is_available()...")
    cuda_available = torch.cuda.is_available()
    print(f"torch.cuda.is_available() returned: {cuda_available}")
    if cuda_available:
        print("Early CUDA Check: CUDA IS AVAILABLE. Initializing...")
        torch.cuda.init()
        device_count = torch.cuda.device_count()
        print(f"Early CUDA Check: Device Count: {device_count}")
        if device_count > 0:
            print(f"Early CUDA Check: Device Name (GPU 0): {torch.cuda.get_device_name(0)}")
    else:
        # Add more diagnostics if CUDA not available
        print("Early CUDA Check: CUDA NOT AVAILABLE according to torch.cuda.is_available()")
        cuda_version_compiled = getattr(torch.version, 'cuda', 'N/A')
        print(f"  PyTorch was compiled with CUDA version: {cuda_version_compiled}")
        try:
            import ctypes
            # Define TARGET_CUDA_VERSION within this scope or pass it
            _TARGET_CUDA_VERSION_DIAG = "12.1" # Quick fix: redefine locally for diagnostics
            cudart_paths = (
                f"C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v{_TARGET_CUDA_VERSION_DIAG}\\bin\\cudart64_*.dll", # Check target version
                "C:\\Windows\\System32\\cudart64_*.dll", # Check system path
                r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v*\bin\cudart64_*.dll" # Check any version
            )
            found_cudart = False
            for pattern in cudart_paths:
                import glob
                libs = glob.glob(pattern)
                if libs:
                    print(f"  Found CUDA Runtime library matching {pattern}: {libs[0]}")
                    try:
                        ctypes.CDLL(libs[0])
                        print(f"    -> Successfully loaded {libs[0]} via ctypes.")
                        found_cudart = True
                        break # Stop after finding one
                    except Exception as load_err:
                        print(f"    -> Failed to load {libs[0]} via ctypes: {load_err}")
            if not found_cudart:
                 print("  Could not find or load a suitable CUDA Runtime library (cudart64_*.dll). Check CUDA Toolkit installation and PATH.")
        except Exception as diag_err:
            print(f"  Error during diagnostic check for cudart: {diag_err}")

except ImportError:
    print("Early CUDA Check: PyTorch module not found.")
except Exception as e:
    print(f"Early CUDA Check: Error during PyTorch CUDA check/initialization: {e}")
# --- Early CUDA Check --- END

from PySide6.QtGui import QIcon
from PySide6.QtCore import QSettings, QTranslator, QLocale
from PySide6.QtWidgets import QApplication  

from controller import ComicTranslate
from app.translations import ct_translations
from app import icon_resource

def main():
    if sys.platform == "win32":
        # Necessary Workaround to set Taskbar Icon on Windows
        import ctypes
        myappid = u'ComicLabs.ComicTranslate' # arbitrary string
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    # Create QApplication directly instead of using the context manager
    app = QApplication(sys.argv)
    
    # Set the application icon
    icon = QIcon(":/icons/window_icon.png")  
    app.setWindowIcon(icon)

    settings = QSettings("ComicLabs", "ComicTranslate")
    selected_language = settings.value('language', get_system_language())
    if selected_language != 'English':
        load_translation(app, selected_language)  

    ct = ComicTranslate()

    # Check for file arguments
    if len(sys.argv) > 1:
        project_file = sys.argv[1]
        if os.path.exists(project_file) and project_file.endswith(".ctpr"):
            ct.thread_load_project(project_file)

    ct.show()
    
    # Start the event loop
    sys.exit(app.exec())


def get_system_language():
    locale = QLocale.system().name()  # Returns something like "en_US" or "zh_CN"
    
    # Special handling for Chinese
    if locale.startswith('zh_'):
        if locale in ['zh_CN', 'zh_SG']:
            return '简体中文'
        elif locale in ['zh_TW', 'zh_HK']:
            return '繁體中文'
    
    # For other languages, we can still use the first part of the locale
    lang_code = locale.split('_')[0]
    
    # Map the system language code to your application's language names
    lang_map = {
        'en': 'English',
        'ko': '한국어',
        'fr': 'Français',
        'ja': '日本語',
        'ru': 'русский',
        'de': 'Deutsch',
        'nl': 'Nederlands',
        'es': 'Español',
        'it': 'Italiano',
        'tr': 'Türkçe',
        'ka': 'ქართული'
    }
    
    return lang_map.get(lang_code, 'English')  # Default to English if not found

def load_translation(app, language: str):
    translator = QTranslator(app)
    lang_code = {
        'English': 'en',
        '한국어': 'ko',
        'Français': 'fr',
        '日本語': 'ja',
        '简体中文': 'zh_CN',
        '繁體中文': 'zh_TW',
        'русский': 'ru',
        'Deutsch': 'de',
        'Nederlands': 'nl',
        'Español': 'es',
        'Italiano': 'it',
        'Türkçe': 'tr',
        'ქართული': 'ka'
    }.get(language, 'en')

    # Load the translation file
    # if translator.load(f"ct_{lang_code}", "app/translations/compiled"):
    #     app.installTranslator(translator)
    # else:
    #     print(f"Failed to load translation for {language}")

    if translator.load(f":/translations/ct_{lang_code}.qm"):
        app.installTranslator(translator)
    else:
        print(f"Failed to load translation for {language}")

if __name__ == "__main__":
    main()

