import sys
from PyQt6 import QtWidgets, uic, QtCore, QtGui
from workers import ExtractionWorker, CleanupWorker
from database import init_db, fetch_all_installed_apps, create_app, delete_apps, update_app, delete_app
import os
import subprocess


class LibraryItemWidget(QtWidgets.QWidget):
    """A custom list item widget showing hover-reveal actions and a three-dots menu."""
    open_requested = QtCore.pyqtSignal(str)          # exec_path
    edit_requested = QtCore.pyqtSignal(dict)         # full app dict
    delete_requested = QtCore.pyqtSignal(str, str, str)  # uuid, exec_path, name
    selection_changed = QtCore.pyqtSignal()          # emitted when checkbox toggled

    def __init__(self, app, item, parent=None):
        super().__init__(parent)
        self.app = app
        self.item = item
        self.setObjectName("listItemWidget")
        self.setMouseTracking(True)
        self._menu_open = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # --- Icon ---
        icon_label = QtWidgets.QLabel()
        icon_label.setFixedSize(48, 48)
        icon_path = app.get('icon', '')
        if icon_path and os.path.exists(icon_path):
            pixmap = QtGui.QPixmap(icon_path).scaled(
                48, 48,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation
            )
            icon_label.setPixmap(pixmap)
        layout.addWidget(icon_label)

        # --- App name ---
        name_label = QtWidgets.QLabel(app['name'])
        font = name_label.font()
        font.setPointSize(12)
        name_label.setFont(font)
        layout.addWidget(name_label)

        layout.addStretch()

        # --- Hover-reveal "Open" button ---
        self.open_btn = QtWidgets.QPushButton("Open")
        self.open_btn.setObjectName("openBtn")
        self.open_btn.setFixedHeight(32)
        self.open_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(app['exec_path']))
        layout.addWidget(self.open_btn)

        # --- Three-dots menu button ---
        self.menu_btn = QtWidgets.QPushButton("⋮")
        self.menu_btn.setObjectName("menuBtn")
        self.menu_btn.setFixedSize(32, 32)
        self.menu_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setVisible(False)
        self.menu_btn.clicked.connect(self._show_context_menu)
        layout.addWidget(self.menu_btn)

        # --- Checkbox ---
        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.toggled.connect(
            lambda checked, itm=item: itm.setData(QtCore.Qt.ItemDataRole.UserRole + 2, checked)
        )
        self.checkbox.toggled.connect(lambda _: self.selection_changed.emit())
        layout.addWidget(self.checkbox)

    def enterEvent(self, event):
        self.open_btn.setVisible(True)
        self.menu_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._menu_open:
            self.open_btn.setVisible(False)
            self.menu_btn.setVisible(False)
        super().leaveEvent(event)

    def _show_context_menu(self):
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("appContextMenu")
        edit_action = menu.addAction("Edit")
        menu.addSeparator()
        delete_action = menu.addAction("Uninstall")

        self._menu_open = True
        action = menu.exec(self.menu_btn.mapToGlobal(
            QtCore.QPoint(0, self.menu_btn.height())
        ))
        self._menu_open = False

        # After menu closes, check if mouse is still over this widget
        if not self.rect().contains(self.mapFromGlobal(QtGui.QCursor.pos())):
            self.open_btn.setVisible(False)
            self.menu_btn.setVisible(False)

        if action == edit_action:
            self.edit_requested.emit(self.app)
        elif action == delete_action:
            self.delete_requested.emit(
                self.app['uuid'], self.app['exec_path'], self.app['name']
            )



class ArchievePackageManager(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        # Load the UI file
        uic.loadUi('ArchievePackageManager.ui', self)
        
        # Initialize the database table if it doesn't exist
        init_db()
        
        # Populate the library list
        self.populate_library()
        
        # Determine which page to show based on installed apps
        if self.packageList.count() == 0:
            self.mainStackedWidget.setCurrentIndex(0)
        else:
            self.mainStackedWidget.setCurrentIndex(1)
            
        # Disable default list item highlighting
        self.packageList.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.packageList.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        
        # Apply modern theme
        self.apply_modern_theme()
        
        # Connect the "Add App" button
        self.addPackage.clicked.connect(self.select_package)
        if hasattr(self, 'initAdd_2'):
            self.initAdd_2.clicked.connect(self.select_package)
            
        if hasattr(self, 'deleteBtn'):
            self.deleteBtn.clicked.connect(self.delete_selected_apps)
            self.deleteBtn.setEnabled(False)  # nothing selected on startup
        
        # Connect setup window buttons
        self.execBrowseBtn.clicked.connect(self.browse_exec)
        self.iconBrowseBtn.clicked.connect(self.browse_icon)
        self.doneBtn.clicked.connect(self.save_app_details)
        self.cancelBtn.clicked.connect(self.cancel_setup)
        
        # Connect default icon toggle
        if hasattr(self, 'defaultIconCheckbox'):
            self.defaultIconCheckbox.toggled.connect(self.toggle_default_icon)
        
        self.current_extracted_path = ""
        self.current_icon_path = ""
        self.found_icon_path = ""
        self.original_exec_path = ""
        self.original_archive_path = ""
        self.found_desktop_path = ""
        self.editing_app_uuid = ""
        self.editing_app_old_name = ""
        self.previous_index = 0
        
    def apply_modern_theme(self):
        modern_stylesheet = """
            QDialog {
                background-color: #121212;
                color: #ffffff;
            }
            QLabel {
                color: #e0e0e0;
            }
            QPushButton {
                background-color: #2979ff;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #448aff;
            }
            QPushButton:pressed {
                background-color: #2264d1;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
            QPushButton#deleteBtn {
                background-color: #d32f2f;
            }
            QPushButton#deleteBtn:hover {
                background-color: #f44336;
            }
            QPushButton#deleteBtn:pressed {
                background-color: #b71c1c;
            }
            QPushButton#deleteBtn:disabled {
                background-color: #333333;
                color: #666666;
            }
            QListWidget {
                background-color: #1e1e1e;
                border: 1px solid #333333;
                border-radius: 8px;
                outline: 0;
            }
            QListWidget::item {
                background-color: #1e1e1e;
                border-bottom: 1px solid #333333;
                padding: 4px;
            }
            QListWidget::item:hover {
                background-color: #2c2c2c;
            }
            QWidget#listItemWidget {
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background-color: #1e1e1e;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #777777;
            }
            QLineEdit {
                background-color: #1e1e1e;
                border: 1px solid #333333;
                color: #ffffff;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus {
                border: 1px solid #2979ff;
            }
            QCheckBox {
                color: #e0e0e0;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #555555;
                background-color: #1e1e1e;
            }
            QCheckBox::indicator:checked {
                background-color: #2979ff;
                border: 2px solid #2979ff;
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIi8+PC9zdmc+);
            }
            QPushButton#openBtn {
                background-color: #2979ff;
                color: white;
                border-radius: 6px;
                padding: 4px 14px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton#openBtn:hover {
                background-color: #448aff;
            }
            QPushButton#menuBtn {
                background-color: transparent;
                color: #aaaaaa;
                border: 1px solid #444444;
                border-radius: 6px;
                font-size: 16px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton#menuBtn:hover {
                background-color: #333333;
                color: #ffffff;
            }
            QMenu#appContextMenu {
                background-color: #2c2c2c;
                color: #e0e0e0;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu#appContextMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu#appContextMenu::item:selected {
                background-color: #2979ff;
                color: white;
            }
            QMenu#appContextMenu::separator {
                height: 1px;
                background-color: #444444;
                margin: 4px 8px;
            }
        """
        self.setStyleSheet(modern_stylesheet)
        
    def select_package(self):
        self.previous_index = self.mainStackedWidget.currentIndex()
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Package",
            "",
            "Supported Packages (*.tar.gz *.AppImage *.appimage);;Tar gzip files (*.tar.gz);;AppImage files (*.AppImage *.appimage);;All Files (*)"
        )
        if file_name:
            print(f"Selected file: {file_name}")
            self.start_extraction(file_name)

    def start_extraction(self, file_name):
        self.original_archive_path = file_name
        self.progress_dialog = QtWidgets.QProgressDialog("Processing Package...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowTitle("Please Wait")
        self.progress_dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        
        self.worker = ExtractionWorker(file_name)
        
        self.worker.progress.connect(self.progress_dialog.setValue)
        self.worker.finished.connect(self.on_extraction_finished)
        self.progress_dialog.canceled.connect(self.worker.terminate)
        
        self.worker.start()
        
    def on_extraction_finished(self, success, path, default_exec, default_icon, default_desktop, message):
        self.progress_dialog.setValue(100)
        
        if success:
            self.current_extracted_path = path
            self.original_exec_path = default_exec
            self.found_desktop_path = default_desktop
            
            app_name = os.path.basename(path)
            if app_name.lower().endswith('.appimage'):
                app_name = app_name[:-9]
                
            self.appNameInput.setText(app_name)
            self.execFileInput.setText(default_exec)
            
            self.current_icon_path = default_icon
            self.found_icon_path = default_icon
            
            if hasattr(self, 'defaultIconCheckbox'):
                self.defaultIconCheckbox.setChecked(False)
            
            if default_icon and os.path.exists(default_icon):
                pixmap = QtGui.QPixmap(default_icon)
                self.iconLabel.setPixmap(pixmap)
            else:
                self.iconLabel.clear()
                self.iconLabel.setText("No Icon")
            
            self.mainStackedWidget.setCurrentIndex(2)
        else:
            QtWidgets.QMessageBox.critical(self, "Error", message)

    def toggle_default_icon(self, checked):
        if checked:
            # Determine which default icon to show
            base_dir = os.path.dirname(os.path.abspath(__file__))
            if self.original_archive_path and self.original_archive_path.lower().endswith('.appimage'):
                icon_path = os.path.join(base_dir, "assets", "icons", "appimage_icon.png")
            elif self.original_archive_path and self.original_archive_path.lower().endswith('.tar.gz'):
                icon_path = os.path.join(base_dir, "assets", "icons", "targz_icon.png")
            else:
                icon_path = os.path.join(base_dir, "assets", "icons", "app_icon.png")
                
            if not os.path.exists(icon_path):
                icon_path = os.path.join(base_dir, "assets", "icons", "app_icon.png")
                
            self.current_icon_path = icon_path
            if os.path.exists(icon_path):
                pixmap = QtGui.QPixmap(icon_path)
                self.iconLabel.setPixmap(pixmap)
            else:
                self.iconLabel.clear()
                self.iconLabel.setText("No Icon")
        else:
            self.current_icon_path = self.found_icon_path
            if self.found_icon_path and os.path.exists(self.found_icon_path):
                pixmap = QtGui.QPixmap(self.found_icon_path)
                self.iconLabel.setPixmap(pixmap)
            else:
                self.iconLabel.clear()
                self.iconLabel.setText("No Icon")

    def browse_exec(self):
        start_dir = self.current_extracted_path if self.current_extracted_path else os.path.expanduser('~')
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Executable", start_dir, "All Files (*)")
        if file_name:
            self.execFileInput.setText(file_name)

    def browse_icon(self):
        start_dir = self.current_extracted_path if self.current_extracted_path else os.path.expanduser('~')
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Icon", start_dir, "Images (*.png *.svg *.jpg *.jpeg *.ico)")
        if file_name:
            self.current_icon_path = file_name
            pixmap = QtGui.QPixmap(file_name)
            self.iconLabel.setPixmap(pixmap)

    def save_app_details(self):
        name = self.appNameInput.text().strip()
        exec_path = self.execFileInput.text().strip()
        icon_path = self.current_icon_path
        
        if not name or not exec_path:
            QtWidgets.QMessageBox.warning(self, "Input Error", "App name and executable path are required.")
            return
        
        if self.editing_app_uuid:
            # --- Edit mode: update existing app ---
            # Delete old desktop entry (name may have changed)
            self.delete_desktop_entry(self.editing_app_old_name)
            
            success = update_app(self.editing_app_uuid, name=name, exec_path=exec_path, icon=icon_path)
            if success:
                self.create_desktop_entry(name, exec_path, icon_path, getattr(self, 'found_desktop_path', ''))
                QtWidgets.QMessageBox.information(self, "Success", "App updated successfully.")
            else:
                QtWidgets.QMessageBox.critical(self, "Error", "Failed to update app.")
            
            # Clear editing state
            self.editing_app_uuid = ""
            self.editing_app_old_name = ""
            self.populate_library()
            self.mainStackedWidget.setCurrentIndex(1)
        else:
            # --- Create mode ---
            uuid = create_app(name=name, exec_path=exec_path, icon=icon_path)
            if uuid:
                self.create_desktop_entry(name, exec_path, icon_path, getattr(self, 'found_desktop_path', ''))
                QtWidgets.QMessageBox.information(self, "Success", "App added successfully.")
                self.populate_library()
                self.mainStackedWidget.setCurrentIndex(1)
            else:
                QtWidgets.QMessageBox.critical(self, "Error", "Failed to save app. Name might already exist.")

    def cancel_setup(self):
        # Delegate cleanup to a background worker so it doesn't freeze the GUI
        if self.current_extracted_path:
            self.cleanup_worker = CleanupWorker(self.current_extracted_path, self.original_exec_path, self.found_icon_path)
            self.cleanup_worker.start()
            
            # Clear state so it doesn't try to delete again
            self.current_extracted_path = ""
            self.original_exec_path = ""
            self.found_icon_path = ""
            self.found_desktop_path = ""
                            
        # Cancel the setup and return to the previous screen immediately
        self.editing_app_uuid = ""
        self.editing_app_old_name = ""
        self.mainStackedWidget.setCurrentIndex(self.previous_index)

    def populate_library(self):
        self.packageList.clear()
        
        apps = fetch_all_installed_apps()
        for app in apps:
            item = QtWidgets.QListWidgetItem()
            # Store the UUID, exec_path, checked state, and name inside the item
            item.setData(QtCore.Qt.ItemDataRole.UserRole, app['uuid'])
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, app['exec_path'])
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 2, False) # Checked state
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 3, app['name']) # Name for desktop entry deletion
            
            # Create a custom widget to hold the icon, text, and right-aligned checkbox
            widget = LibraryItemWidget(app, item)
            widget.open_requested.connect(self.launch_app)
            widget.edit_requested.connect(self.edit_app)
            widget.delete_requested.connect(self.delete_single_app)
            widget.selection_changed.connect(self.update_action_buttons)
            
            # Force the item height to accommodate the icon
            item.setSizeHint(QtCore.QSize(0, 70))
            
            self.packageList.addItem(item)
            self.packageList.setItemWidget(item, widget)

        self.update_action_buttons()

    def update_action_buttons(self):
        """Enable/disable Install Package and Uninstall Selected based on checkbox selection."""
        any_checked = any(
            self.packageList.item(i).data(QtCore.Qt.ItemDataRole.UserRole + 2)
            for i in range(self.packageList.count())
        )
        if hasattr(self, 'initAdd_2'):
            self.initAdd_2.setEnabled(not any_checked)
        if hasattr(self, 'deleteBtn'):
            self.deleteBtn.setEnabled(any_checked)

    def launch_app(self, exec_path):
        """Launch the application asynchronously without blocking the manager."""
        try:
            subprocess.Popen([exec_path], start_new_session=True)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Launch Error", f"Could not launch application:\n{e}")

    def edit_app(self, app):
        """Pre-fill the setup window with existing app data for editing."""
        self.editing_app_uuid = app['uuid']
        self.editing_app_old_name = app['name']
        self.previous_index = self.mainStackedWidget.currentIndex()

        # Temporarily clear extraction path so cancel_setup won't run cleanup
        self.current_extracted_path = ""
        self.original_exec_path = app['exec_path']
        self.found_icon_path = app.get('icon', '')
        self.current_icon_path = app.get('icon', '')

        self.appNameInput.setText(app['name'])
        self.execFileInput.setText(app['exec_path'])

        icon_path = app.get('icon', '')
        if icon_path and os.path.exists(icon_path):
            pixmap = QtGui.QPixmap(icon_path)
            self.iconLabel.setPixmap(pixmap)
        else:
            self.iconLabel.clear()
            self.iconLabel.setText("No Icon")

        if hasattr(self, 'defaultIconCheckbox'):
            self.defaultIconCheckbox.setChecked(False)

        self.mainStackedWidget.setCurrentIndex(2)

    def delete_single_app(self, uuid, exec_path, name):
        """Delete a single app by UUID after confirmation."""
        import shutil
        from pathlib import Path

        reply = QtWidgets.QMessageBox.question(
            self, 'Confirm Uninstall',
            f"Are you sure you want to completely uninstall '{name}'?\nThis will permanently delete the app files from your disk.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        app_data_dir = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.AppDataLocation)
        opt_dir = os.path.join(app_data_dir, 'opt')

        if exec_path and opt_dir in exec_path:
            try:
                parts = Path(exec_path).parts
                opt_index = parts.index('opt')
                base_folder = Path(*parts[:opt_index + 2])
                if base_folder.exists() and base_folder.is_dir():
                    shutil.rmtree(base_folder, ignore_errors=True)
            except ValueError:
                pass

        self.delete_desktop_entry(name)
        delete_app(uuid)

        self.populate_library()
        if self.packageList.count() == 0:
            self.mainStackedWidget.setCurrentIndex(0)

    def delete_selected_apps(self):
        import shutil
        from pathlib import Path
        
        uuids_to_delete = []
        paths_to_delete = []
        names_to_delete = []
        
        for index in range(self.packageList.count()):
            item = self.packageList.item(index)
            # Read our custom checked state
            if item.data(QtCore.Qt.ItemDataRole.UserRole + 2):
                uuids_to_delete.append(item.data(QtCore.Qt.ItemDataRole.UserRole))
                paths_to_delete.append(item.data(QtCore.Qt.ItemDataRole.UserRole + 1))
                names_to_delete.append(item.data(QtCore.Qt.ItemDataRole.UserRole + 3))
                
        if not uuids_to_delete:
            QtWidgets.QMessageBox.warning(self, "Selection Empty", "Please select at least one app to delete.")
            return
            
        reply = QtWidgets.QMessageBox.question(
            self, 'Confirm Deletion', 
            f"Are you sure you want to completely remove {len(uuids_to_delete)} app(s)?\nThis will permanently delete the app files from your disk.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No, 
            QtWidgets.QMessageBox.StandardButton.No
        )
                                               
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # Delete files from disk
            app_data_dir = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.AppDataLocation)
            opt_dir = os.path.join(app_data_dir, 'opt')
            
            for exec_path in paths_to_delete:
                if not exec_path: continue
                
                # Both .tar.gz and .AppImage are stored in AppDataLocation/opt/[app_name], so we delete the base folder entirely
                if opt_dir in exec_path:
                    try:
                        parts = Path(exec_path).parts
                        opt_index = parts.index('opt')
                        base_folder = Path(*parts[:opt_index+2])
                        if base_folder.exists() and base_folder.is_dir():
                            shutil.rmtree(base_folder, ignore_errors=True)
                    except ValueError:
                        pass
            
            # Delete desktop files
            for app_name in names_to_delete:
                if app_name:
                    self.delete_desktop_entry(app_name)
                    
            # Delete from database
            delete_apps(uuids_to_delete)
            
            # Refresh library view
            self.populate_library()
            
            # If library is now empty, return to the start screen
            if self.packageList.count() == 0:
                self.mainStackedWidget.setCurrentIndex(0)

    def create_desktop_entry(self, name, exec_path, icon_path, source_desktop_path=None):
        from pathlib import Path
        import os
        from PyQt6 import QtCore
        import re
        
        desktop_dir_str = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.ApplicationsLocation)
        if desktop_dir_str:
            desktop_dir = Path(desktop_dir_str)
        else:
            desktop_dir = Path.home() / '.local' / 'share' / 'applications'
            
        desktop_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a safe, normalized filename for the .desktop file
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_').lower()
        desktop_file = desktop_dir / f"apm_{safe_name}.desktop"
        
        desktop_content = ""
        if source_desktop_path and os.path.exists(source_desktop_path):
            try:
                with open(source_desktop_path, 'r') as f:
                    lines = f.readlines()
                    
                in_desktop_entry = False
                for i, line in enumerate(lines):
                    if line.strip() == '[Desktop Entry]':
                        in_desktop_entry = True
                        continue
                    elif line.startswith('['):
                        in_desktop_entry = False
                        
                    if in_desktop_entry:
                        if line.startswith('Name='):
                            lines[i] = f'Name={name}\n'
                        elif line.startswith('Icon='):
                            lines[i] = f'Icon={icon_path if icon_path else ""}\n'
                        elif line.startswith('Exec='):
                            lines[i] = re.sub(r'^Exec=(?:"[^"]*"|[^ \n]+)(.*)$', f'Exec="{exec_path}"\\1', line)
                            
                    # Also replace Exec in Actions to keep them functional
                    if not in_desktop_entry and line.startswith('Exec='):
                        lines[i] = re.sub(r'^Exec=(?:"[^"]*"|[^ \n]+)(.*)$', f'Exec="{exec_path}"\\1', line)
                        
                desktop_content = "".join(lines)
            except Exception as e:
                print(f"Error reading source desktop file: {e}")
                desktop_content = ""
                
        if not desktop_content:
            desktop_content = f"""[Desktop Entry]
Type=Application
Name={name}
Exec="{exec_path}"
Icon={icon_path if icon_path else ''}
Terminal=false
Categories=Utility;Application;
"""
        try:
            with open(desktop_file, 'w') as f:
                f.write(desktop_content)
            # Make the .desktop file executable
            os.chmod(desktop_file, 0o755)
        except Exception as e:
            print(f"Error creating desktop entry: {e}")

    def delete_desktop_entry(self, name):
        from pathlib import Path
        import os
        from PyQt6 import QtCore
        
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_').lower()
        desktop_dir_str = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.ApplicationsLocation)
        if desktop_dir_str:
            desktop_dir = Path(desktop_dir_str)
        else:
            desktop_dir = Path.home() / '.local' / 'share' / 'applications'
            
        desktop_file = desktop_dir / f"apm_{safe_name}.desktop"
        
        try:
            if desktop_file.exists():
                os.remove(desktop_file)
        except OSError:
            pass

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ArchivePackageManager")
    window = ArchievePackageManager()
    window.show()
    sys.exit(app.exec())
