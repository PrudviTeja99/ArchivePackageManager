import sqlite3
import uuid

import os
from PyQt6.QtCore import QStandardPaths

def get_db_path():
    app_data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not os.path.exists(app_data_dir):
        os.makedirs(app_data_dir, exist_ok=True)
    return os.path.join(app_data_dir, "apps.db")

def get_connection():
    """Creates and returns a connection to the SQLite database."""
    return sqlite3.connect(get_db_path())

def init_db():
    """Initialize the database and create the installed_apps table if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS installed_apps (
            uuid TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            icon TEXT,
            exec_path TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def create_app(name, exec_path, icon=None):
    """Create a new installed app record."""
    app_uuid = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO installed_apps (uuid, name, icon, exec_path)
            VALUES (?, ?, ?, ?)
        ''', (app_uuid, name, icon, exec_path))
        conn.commit()
        return app_uuid
    except sqlite3.IntegrityError as e:
        print(f"Error creating app '{name}': {e}")
        return None
    finally:
        conn.close()

def fetch_all_installed_apps():
    """Fetch all installed apps."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row  # This allows us to access columns by name
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM installed_apps')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_app(identifier):
    """Fetch a single app by uuid or name."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM installed_apps WHERE uuid = ? OR name = ?', (identifier, identifier))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_app(identifier, name=None, icon=None, exec_path=None):
    """Update an existing app by uuid or name. Only provided fields will be updated."""
    conn = get_connection()
    cursor = conn.cursor()
    
    update_fields = []
    params = []
    
    if name is not None:
        update_fields.append("name = ?")
        params.append(name)
    if icon is not None:
        update_fields.append("icon = ?")
        params.append(icon)
    if exec_path is not None:
        update_fields.append("exec_path = ?")
        params.append(exec_path)
        
    if not update_fields:
        conn.close()
        return False  # Nothing to update
        
    query = f"UPDATE installed_apps SET {', '.join(update_fields)} WHERE uuid = ? OR name = ?"
    params.extend([identifier, identifier])
    
    try:
        cursor.execute(query, tuple(params))
        conn.commit()
        success = cursor.rowcount > 0
        return success
    except sqlite3.Error as e:
        print(f"Error updating app: {e}")
        return False
    finally:
        conn.close()

def delete_app(identifier):
    """Delete an app by uuid or name."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM installed_apps WHERE uuid = ? OR name = ?', (identifier, identifier))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

def delete_apps(identifiers):
    """Delete multiple apps by a list of uuids or names."""
    if not identifiers:
        return False
        
    conn = get_connection()
    cursor = conn.cursor()
    
    placeholders = ', '.join(['?'] * len(identifiers))
    query = f"DELETE FROM installed_apps WHERE uuid IN ({placeholders}) OR name IN ({placeholders})"
    params = tuple(identifiers) + tuple(identifiers)
    
    cursor.execute(query, params)
    conn.commit()
    deleted_count = cursor.rowcount
    conn.close()
    return deleted_count > 0

def delete_all_apps():
    """Delete all apps from the table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM installed_apps')
    conn.commit()
    conn.close()
    return True
