import os
import re
from pathlib import Path

def main():
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    translations_py = script_dir / "app" / "translations" / "ct_translations.py"
    
    if not translations_py.exists():
        print(f"Error: {translations_py} does not exist!")
        return 1
    
    # Read the current file
    with open(translations_py, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Add the Georgian file to the resource name section
    name_pattern = r'qt_resource_name = b"(.*?)"'
    name_match = re.search(name_pattern, content, re.DOTALL)
    
    if not name_match:
        print("Error: Could not find qt_resource_name section in the file!")
        return 1
    
    current_names = name_match.group(1)
    
    # Check if Georgian is already included
    if b"ct_ka.qm" in current_names.encode('utf-8'):
        print("Georgian translation is already included in the resource file.")
        return 0
    
    # Add Georgian translation to the list
    # This is a complex operation because we need to add a new entry to the resource list
    # Typically this would be done using Qt's resource compiler (rcc)
    
    print("Creating a backup of the original file...")
    backup_file = translations_py.with_suffix('.py.bak')
    with open(backup_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Manual steps required:")
    print("1. Use Qt's resource compiler (rcc) to add the Georgian translation file.")
    print("2. The compiled Georgian translation file should be named 'ct_ka.qm'.")
    print("3. Add an entry for 'ct_ka.qm' in app/translations/ct_translations.py:")
    print("   - In qt_resource_name, add a new entry for '\\x00\\x08\\x00\\x00\\x00\\x00\\x00c\\x00t\\x00_\\x00k\\x00a\\x00.\\x00q\\x00m'")
    print("   - Update qt_resource_struct to include the new file")
    print("4. Restart the application for the changes to take effect.")
    
    print("\nAlternatively, you can recompile all translation resources using Qt Creator or the Qt resource compiler (rcc).")
    
    return 0

if __name__ == "__main__":
    main() 