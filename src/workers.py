import os
import shutil
import tarfile
from pathlib import Path
from PyQt6 import QtCore

class ExtractionWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int)
    # success, extracted_path, default_exec, default_icon, default_desktop, message
    finished = QtCore.pyqtSignal(bool, str, str, str, str, str)
    
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        
    def run(self):
        try:
            file_path = Path(self.file_path)
            
            # Determine base filename without extension
            if file_path.name.endswith('.tar.gz'):
                base_name = file_path.name[:-7]
            elif file_path.name.lower().endswith('.appimage'):
                base_name = file_path.name[:-9]
            else:
                base_name = file_path.stem
                
            # Target directory
            app_data_dir = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.AppDataLocation)
            target_dir = Path(app_data_dir) / 'opt' / base_name
                
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Set directory permissions to 755
            os.chmod(target_dir, 0o755)
            
            self.progress.emit(10)
            
            default_exec = ""
            default_icon = ""
            default_desktop = ""
            
            if file_path.name.endswith('.tar.gz'):
                with tarfile.open(file_path, "r:gz") as tar:
                    members = tar.getmembers()
                    total = len(members)
                    
                    # Detect if there's a single top-level directory (common prefix)
                    common_prefix = None
                    for m in members:
                        parts = m.name.split('/')
                        if parts and parts[0] == '.':
                            parts = parts[1:]
                        if not parts:
                            continue
                            
                        root = parts[0]
                        if common_prefix is None:
                            common_prefix = root
                        elif common_prefix != root:
                            common_prefix = None
                            break
                            
                    best_exec_score = -1
                    best_icon_score = -1
                    best_desktop_score = -1
                    simple_base = base_name.split('-')[0].split('_')[0].lower()
                    
                    for i, member in enumerate(members):
                        # Strip the common top-level directory to prevent double-folders
                        if common_prefix:
                            parts = member.name.split('/')
                            if parts and parts[0] == '.':
                                parts = parts[1:]
                                
                            if parts and parts[0] == common_prefix:
                                if len(parts) == 1:
                                    continue # Skip the top-level directory entry itself
                                member.name = '/'.join(parts[1:])
                                
                        tar.extract(member, path=target_dir)
                        
                        # Auto-discover executable and icon during extraction
                        if member.isfile():
                            # Evaluate Executable
                            if (member.mode & 0o111):
                                score = 0
                                parts = member.name.split('/')
                                filename = parts[-1].lower()
                                
                                if 'bin' in [p.lower() for p in parts[:-1]]:
                                    score += 50
                                    
                                if simple_base and filename.startswith(simple_base):
                                    score += 30
                                elif simple_base and simple_base in filename:
                                    score += 10
                                    
                                if 'uninstall' in filename or 'update' in filename:
                                    score -= 50
                                    
                                if score > best_exec_score:
                                    best_exec_score = score
                                    default_exec = str(target_dir / member.name)
                                    
                            # Evaluate Icon
                            if member.name.lower().endswith(('.png', '.svg', '.jpg', '.jpeg', '.ico')):
                                score = 0
                                parts = member.name.split('/')
                                filename = parts[-1].lower()
                                
                                # Prioritize PNGs over SVGs since Qt's SVG renderer has limited support
                                if filename.endswith('.png'): score += 20
                                elif filename.endswith('.svg'): score += 10
                                
                                if simple_base and filename.startswith(simple_base):
                                    score += 30
                                elif simple_base and simple_base in filename:
                                    score += 10
                                    
                                if len(parts) == 1:
                                    score += 20
                                    
                                if score > best_icon_score:
                                    best_icon_score = score
                                    default_icon = str(target_dir / member.name)
                                    
                            # Evaluate Desktop
                            if member.name.lower().endswith('.desktop'):
                                score = 0
                                parts = member.name.split('/')
                                filename = parts[-1].lower()
                                
                                if simple_base and filename.startswith(simple_base):
                                    score += 30
                                elif simple_base and simple_base in filename:
                                    score += 10
                                    
                                if len(parts) == 1:
                                    score += 20
                                    
                                if score > best_desktop_score:
                                    best_desktop_score = score
                                    default_desktop = str(target_dir / member.name)
                                
                        progress_val = 10 + int(((i + 1) / total) * 90)
                        if i % max(1, total // 100) == 0:  # avoid emitting too often
                            self.progress.emit(progress_val)
                            
            elif file_path.name.lower().endswith('.appimage'):
                dest_path = target_dir / file_path.name
                shutil.copy2(file_path, dest_path)
                os.chmod(dest_path, 0o755)
                self.progress.emit(50)
                
                default_exec = str(dest_path)
                default_icon = ""
                
                import tempfile
                import subprocess
                
                with tempfile.TemporaryDirectory() as tmpdir:
                    try:
                        subprocess.run([str(dest_path), '--appimage-extract'], cwd=tmpdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                        
                    squashfs_root = Path(tmpdir) / 'squashfs-root'
                    best_icon_score = -1
                    best_desktop_score = -1
                    if squashfs_root.exists():
                        for root, _, files in os.walk(squashfs_root):
                            for file in files:
                                if file.lower().endswith(('.png', '.svg')):
                                    file_path_full = os.path.join(root, file)
                                    if os.path.islink(file_path_full):
                                        file_path_full = os.path.realpath(file_path_full)
                                        
                                    if not os.path.exists(file_path_full):
                                        continue
                                        
                                    score = 0
                                    if file.endswith('.png'): score += 20
                                    elif file.endswith('.svg'): score += 10
                                    
                                    if base_name.lower() in file.lower(): score += 30
                                    if root == str(squashfs_root): score += 20
                                    
                                    if score > best_icon_score:
                                        best_icon_score = score
                                        icons_dir = target_dir / 'icons'
                                        icons_dir.mkdir(parents=True, exist_ok=True)
                                        
                                        perm_icon_path = icons_dir / file
                                        shutil.copy2(file_path_full, perm_icon_path)
                                        default_icon = str(perm_icon_path)
                                        
                                if file.lower().endswith('.desktop'):
                                    file_path_full = os.path.join(root, file)
                                    if os.path.islink(file_path_full):
                                        file_path_full = os.path.realpath(file_path_full)
                                        
                                    if not os.path.exists(file_path_full):
                                        continue
                                        
                                    score = 0
                                    if base_name.lower() in file.lower(): score += 30
                                    if root == str(squashfs_root): score += 20
                                    
                                    if score > best_desktop_score:
                                        best_desktop_score = score
                                        desktops_dir = target_dir / 'desktop'
                                        desktops_dir.mkdir(parents=True, exist_ok=True)
                                        
                                        perm_desktop_path = desktops_dir / file
                                        shutil.copy2(file_path_full, perm_desktop_path)
                                        default_desktop = str(perm_desktop_path)
                                        
                self.progress.emit(100)
                
            else:
                self.finished.emit(False, "", "", "", "", "Error: Unsupported format")
                return
                
            self.finished.emit(True, str(target_dir), default_exec, default_icon, default_desktop, f"Successfully extracted to {target_dir}")
            
        except Exception as e:
            self.finished.emit(False, "", "", "", "", f"Error: {str(e)}")

class CleanupWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal()
    
    def __init__(self, extracted_path, original_exec_path):
        super().__init__()
        self.extracted_path = extracted_path
        self.original_exec_path = original_exec_path
        
    def run(self):
        try:
            app_data_dir = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.AppDataLocation)
            opt_dir = os.path.join(app_data_dir, 'opt')
            if self.extracted_path and opt_dir in self.extracted_path:
                if os.path.exists(self.extracted_path):
                    shutil.rmtree(self.extracted_path, ignore_errors=True)
        except Exception:
            pass
        finally:
            self.finished.emit()
