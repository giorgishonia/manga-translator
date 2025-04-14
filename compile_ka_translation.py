import os
import subprocess
import sys
from pathlib import Path

def main():
    # Get the directory of the script
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    
    # Set paths
    translations_dir = script_dir / "app" / "translations"
    ka_ts_file = translations_dir / "ct_ka.ts"
    ka_qm_file = translations_dir / "ct_ka.qm"
    
    print(f"Georgian translation file: {ka_ts_file}")
    
    if not ka_ts_file.exists():
        print(f"Error: {ka_ts_file} does not exist!")
        return 1
    
    try:
        # Try to use lrelease from PySide6
        try:
            from PySide6.QtCore import QLibraryInfo
            lrelease_path = QLibraryInfo.path(QLibraryInfo.LibraryExecutables) + "/lrelease"
            if not os.path.exists(lrelease_path) and sys.platform == "win32":
                lrelease_path += ".exe"
            if not os.path.exists(lrelease_path):
                lrelease_path = "lrelease"  # Try using system lrelease
        except ImportError:
            lrelease_path = "lrelease"  # Fall back to system lrelease
        
        print(f"Using lrelease at: {lrelease_path}")
        
        # Compile the translation file
        cmd = [lrelease_path, str(ka_ts_file), "-qm", str(ka_qm_file)]
        print(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Error compiling translation: {result.stderr}")
            return 1
        
        print(f"Successfully compiled {ka_ts_file} to {ka_qm_file}")
        print(result.stdout)
        
        # Now we need to update ct_translations.py to include the Georgian file
        # This is a complex operation and would ideally be done with proper Qt tools
        # For now, let's just provide instructions for the user
        
        print("\nManual step required:")
        print("1. You need to add the Georgian translation file to the Qt resource system.")
        print("2. Add 'ct_ka.qm' to the files list in app/translations/ct_translations.py.")
        print("3. Recompile the resource file using Qt's resource compiler.")
        print("4. Restart the application for the changes to take effect.")
        
        return 0
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 