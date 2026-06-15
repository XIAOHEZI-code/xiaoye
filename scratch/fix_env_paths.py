import os
import re

old_path = "/home/xiaohezi/Desktop/prase _claudecode/xiaoye"
new_path = "/home/xiaohezi/Desktop/project/xiaoye"

bin_dir = os.path.join(new_path, "env_xiaoye", "bin")

def fix_file(filepath):
    try:
        with open(filepath, 'rb') as f:
            content = f.read()
        
        # Check if old path is in content
        if old_path.encode('utf-8') in content:
            print(f"Fixing: {filepath}")
            # We replace both bytes representation
            new_content = content.replace(old_path.encode('utf-8'), new_path.encode('utf-8'))
            with open(filepath, 'wb') as f:
                f.write(new_content)
    except Exception as e:
        print(f"Failed to fix {filepath}: {e}")

def main():
    print(f"Scanning bin directory: {bin_dir}")
    for root, dirs, files in os.walk(bin_dir):
        for file in files:
            filepath = os.path.join(root, file)
            # Skip symlinks
            if os.path.islink(filepath):
                continue
            fix_file(filepath)
            
    # Also check conda-meta files if any
    conda_meta = os.path.join(new_path, "env_xiaoye", "conda-meta")
    if os.path.exists(conda_meta):
        print(f"Scanning conda-meta: {conda_meta}")
        for root, dirs, files in os.walk(conda_meta):
            for file in files:
                if file.endswith('.json'):
                    filepath = os.path.join(root, file)
                    fix_file(filepath)
                    
    # Also check pkgconfig
    pkg_config = os.path.join(new_path, "env_xiaoye", "lib", "pkgconfig")
    if os.path.exists(pkg_config):
        print(f"Scanning pkgconfig: {pkg_config}")
        for root, dirs, files in os.walk(pkg_config):
            for file in files:
                filepath = os.path.join(root, file)
                fix_file(filepath)

if __name__ == "__main__":
    main()
