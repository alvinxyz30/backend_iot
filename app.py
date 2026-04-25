from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector

app = Flask(__name__)
CORS(app) 

# --- CONFIG DB ---
db_config = {
    'host': '45.90.230.231', 
    'user': 'u1722332_b57760b191fad37b9a3b72213e43773c',
    'password': 'iotproject123!',
    'database': 'u1722332_IOT_Project'
}

def get_db_connection():
    try:
        return mysql.connector.connect(**db_config)
    except Exception as e:
        print(f"Error Koneksi: {e}")
        return None

# =====================================================================
# 🛠️ BAGIAN 1: API UNTUK KONSUMSI HARDWARE (NODEMCU)
# =====================================================================

# 1. API STATUS: Cek Perintah dari Web (Tabel: device_state)
@app.route('/api/device/status', methods=['GET'])
def get_device_status():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error'}), 500
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT mode, target_enroll_id, door_status FROM device_state WHERE id = 1')
    data = cursor.fetchone()
    conn.close()
    return jsonify(data)

# 2. API UPDATE: Reset Status biar alat gak looping
@app.route('/api/device/update', methods=['POST'])
def update_device_status():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error'}), 500
    
    new_door_status = request.json.get('door_status') 
    new_mode = request.json.get('mode') 
    
    cursor = conn.cursor()
    cursor.execute('UPDATE device_state SET door_status = %s, mode = %s WHERE id = 1', (new_door_status, new_mode))
    conn.commit()
    conn.close()
    return jsonify({'status': 'updated'})

# 3. API LOG ADD: Simpan riwayat absensi/akses
@app.route('/api/log/add', methods=['POST'])
def add_log():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error'}), 500
    data = request.json
    cursor = conn.cursor()
    query = "INSERT INTO access_logs (user_name, status, method) VALUES (%s, %s, %s)"
    cursor.execute(query, (data.get('user_name'), data.get('status'), data.get('method')))
    conn.commit()
    conn.close()
    return jsonify({'status': 'log_saved'})

# 4. API AUTH: Verifikasi Admin dari tombol fisik alat
@app.route('/api/auth/admin', methods=['POST'])
def verify_admin():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error'}), 500
    
    finger_id = request.json.get('fingerprint_id')
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT role FROM fingerprint_users WHERE fingerprint_id = %s", (finger_id,))
    user = cursor.fetchone()
    conn.close()

    if user and str(user['role']).lower() == 'admin':
        return jsonify({'status': 'authorized'})
    else:
        return jsonify({'status': 'unauthorized'})


# =====================================================================
# 🌐 BAGIAN 2: API UNTUK KONSUMSI WEB FRONTEND
# [ATTENTION FRONTEND AI / DEVELOPER]: Consume endpoints below!
# =====================================================================

# 5. API GET LOGS
# Deskripsi: Mengambil 20 data log terbaru untuk tabel riwayat.
# Method: GET
# URL: /api/logs
# Response: Array of objects [{ id, user_name, status, method, created_at }, ...]
@app.route('/api/logs', methods=['GET'])
def get_logs():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, user_name, status, method, created_at FROM access_logs ORDER BY created_at DESC LIMIT 20")
    logs = cursor.fetchall()
    conn.close()
    return jsonify(logs)

# 6. API WEB UNLOCK
# Deskripsi: Membuka pintu dari jarak jauh (Remote Unlock).
# Method: POST
# URL: /api/web/unlock
# Body: None required.
# Response: { "status": "command_sent" }
@app.route('/api/web/unlock', methods=['POST'])
def web_unlock():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error'}), 500
    
    cursor = conn.cursor()
    cursor.execute("UPDATE device_state SET door_status = 'OPEN_REQUEST' WHERE id = 1")
    conn.commit()
    conn.close()
    return jsonify({'status': 'command_sent'})

# 7. API WEB ENROLL
# Deskripsi: Mendaftarkan user baru (Auto-assign ID kosong).
# Method: POST
# URL: /api/web/enroll
# Body JSON Required: { "name": "Nama User", "role": "admin/staff" }
# Response Success: { "status": "enroll_triggered", "assigned_id": <int> }
@app.route('/api/web/enroll', methods=['POST'])
def web_enroll():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    data = request.json
    new_name = data.get('name')
    new_role = data.get('role')
    
    if not new_name or not new_role:
        return jsonify({'status': 'error', 'message': 'Name dan Role wajib diisi!'}), 400

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT fingerprint_id FROM fingerprint_users ORDER BY fingerprint_id ASC")
    used_ids = [user['fingerprint_id'] for user in cursor.fetchall()]
    
    assigned_id = None
    for i in range(1, 128):
        if i not in used_ids:
            assigned_id = i
            break
            
    if not assigned_id:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Sensor Penuh (127/127)!'}), 400

    # Insert ke DB dan ubah status alat jadi ENROLL
    cursor.execute("INSERT INTO fingerprint_users (fingerprint_id, name, role) VALUES (%s, %s, %s)", (assigned_id, new_name, new_role))
    cursor.execute("UPDATE device_state SET mode = 'ENROLL', target_enroll_id = %s WHERE id = 1", (assigned_id,))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'enroll_triggered', 'assigned_id': assigned_id})

# 8. API GET USER NAME (Baru ditambahkan)
# Deskripsi: Mengambil nama berdasarkan ID jari (dipanggil oleh NodeMCU sebelum buka pintu)
# Method: POST
# URL: /api/user/name
# Body JSON Required: { "fingerprint_id": <int> }
@app.route('/api/user/name', methods=['POST'])
def get_user_name():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error', 'name': 'Unknown'}), 500

    finger_id = request.json.get('fingerprint_id')
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name FROM fingerprint_users WHERE fingerprint_id = %s", (finger_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        return jsonify({'status': 'success', 'name': user['name']})
    else:
        return jsonify({'status': 'not_found', 'name': f'ID #{finger_id}'})

# 9. API WEB DELETE USER (Baru ditambahkan 🚀)
# Deskripsi: Menghapus user dari DB dan memerintahkan NodeMCU menghapus memori sensor fisiknya.
# Method: POST
# URL: /api/web/delete
# Body JSON Required: { "fingerprint_id": <int> }
@app.route('/api/web/delete', methods=['POST'])
def web_delete():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    finger_id = request.json.get('fingerprint_id')
    if not finger_id:
        return jsonify({'status': 'error', 'message': 'fingerprint_id wajib diisi!'}), 400
        
    cursor = conn.cursor()
    
    # 1. Hapus dari Database MySQL
    cursor.execute("DELETE FROM fingerprint_users WHERE fingerprint_id = %s", (finger_id,))
    
    # 2. Suruh alat fisik menghapus model jarinya
    cursor.execute("UPDATE device_state SET mode = 'DELETE', target_enroll_id = %s WHERE id = 1", (finger_id,))
    
    conn.commit()
    conn.close()
    
    print(f"LOG: Perintah hapus User ID #{finger_id} dikirim ke alat.")
    return jsonify({'status': 'delete_triggered', 'message': f'Menghapus ID #{finger_id} dari database & sensor.'})


# 10. API GET ALL USERS (Baru ditambahkan kembali 🚀)
# Deskripsi: Mengambil daftar semua user yang terdaftar di sensor & database.
# Method: GET
# URL: /api/users
# Response: Array of objects [{ fingerprint_id, name, role, created_at }, ...]
@app.route('/api/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    if not conn: return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    # Menarik semua data user dan diurutkan berdasarkan ID terkecil
    cursor.execute("SELECT fingerprint_id, name, role, created_at FROM fingerprint_users ORDER BY fingerprint_id ASC")
    users = cursor.fetchall()
    conn.close()
    
    return jsonify(users)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)