from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector

app = Flask(__name__)
CORS(app)

# Konfigurasi Database
db_config = {
    'host': '45.90.230.231',
    'user': 'u1722332_b57760b191fad37b9a3b72213e43773c',
    'password': 'iotproject123!',
    'database': 'u1722332_IOT_Project'
}

def get_db_connection():
    """ Fungsi helper untuk koneksi ke MySQL """
    try:
        return mysql.connector.connect(**db_config)
    except Exception as e:
        print(f"Database Connection Error: {e}")
        return None

# ---------------------------------------------------------
# ENDPOINTS UNTUK HARDWARE (NodeMCU / ESP8266)
# ---------------------------------------------------------

@app.route('/api/device/status', methods=['GET'])
def get_device_status():
    """ 
    NodeMCU akan memanggil endpoint ini secara berkala (polling) 
    untuk mengecek apakah ada perintah dari web (Unlock/Enroll/Delete).
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'DB connection failed'}), 500
        
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT mode, target_enroll_id, door_status FROM device_state WHERE id = 1')
    data = cursor.fetchone()
    
    conn.close()
    return jsonify(data)

@app.route('/api/device/update', methods=['POST'])
def update_device_status():
    """ 
    Digunakan oleh alat untuk update balik status pintu 
    atau mereset mode setelah aksi selesai dilakukan.
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error'}), 500
    
    new_door_status = request.json.get('door_status')
    new_mode = request.json.get('mode')
    
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE device_state SET door_status = %s, mode = %s WHERE id = 1', 
        (new_door_status, new_mode)
    )
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'updated'})

@app.route('/api/log/add', methods=['POST'])
def add_log():
    """ Mencatat riwayat akses (siapa, jam berapa, metodenya apa) ke database """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error'}), 500
        
    data = request.json
    cursor = conn.cursor()
    query = "INSERT INTO access_logs (user_name, status, method) VALUES (%s, %s, %s)"
    cursor.execute(query, (data.get('user_name'), data.get('status'), data.get('method')))
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'log_saved'})

@app.route('/api/auth/admin', methods=['POST'])
def verify_admin():
    """ Verifikasi apakah fingerprint ID yang ditempel memiliki akses level Admin """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error'}), 500
    
    finger_id = request.json.get('fingerprint_id')
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT role FROM fingerprint_users WHERE fingerprint_id = %s", (finger_id,))
    user = cursor.fetchone()
    conn.close()

    if user and str(user['role']).lower() == 'admin':
        return jsonify({'status': 'authorized'})
    
    return jsonify({'status': 'unauthorized'})


# ---------------------------------------------------------
# ENDPOINTS UNTUK FRONTEND WEB (Dashboard)
# ---------------------------------------------------------

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """ Ambil 20 riwayat akses terakhir untuk ditampilkan di tabel dashboard """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, user_name, status, method, created_at FROM access_logs ORDER BY created_at DESC LIMIT 20")
    logs = cursor.fetchall()
    
    conn.close()
    return jsonify(logs)

@app.route('/api/web/unlock', methods=['POST'])
def web_unlock():
    """ Request buka pintu dari tombol di dashboard web """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error'}), 500
    
    cursor = conn.cursor()
    # Mengirim sinyal OPEN_REQUEST yang nantinya akan dibaca oleh alat via polling
    cursor.execute("UPDATE device_state SET door_status = 'OPEN_REQUEST' WHERE id = 1")
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'command_sent'})

@app.route('/api/web/enroll', methods=['POST'])
def web_enroll():
    """ Proses registrasi user baru: cari ID kosong lalu set mode alat ke ENROLL """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    data = request.json
    new_name = data.get('name')
    new_role = data.get('role')
    
    if not new_name or not new_role:
        return jsonify({'status': 'error', 'message': 'Nama dan Role tidak boleh kosong'}), 400

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT fingerprint_id FROM fingerprint_users ORDER BY fingerprint_id ASC")
    used_ids = [u['fingerprint_id'] for u in cursor.fetchall()]
    
    # Cari slot ID yang kosong antara 1 - 127 (kapasitas sensor)
    assigned_id = next((i for i in range(1, 128) if i not in used_ids), None)
            
    if not assigned_id:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Kapasitas sensor penuh!'}), 400

    # Simpan data user ke DB dan trigger alat untuk mulai scanning sidik jari
    cursor.execute(
        "INSERT INTO fingerprint_users (fingerprint_id, name, role) VALUES (%s, %s, %s)", 
        (assigned_id, new_name, new_role)
    )
    cursor.execute(
        "UPDATE device_state SET mode = 'ENROLL', target_enroll_id = %s WHERE id = 1", 
        (assigned_id,)
    )
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'enroll_triggered', 'assigned_id': assigned_id})

@app.route('/api/user/name', methods=['POST'])
def get_user_name():
    """ Mendapatkan nama user berdasarkan ID sidik jari (biasanya dipanggil alat) """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'name': 'Unknown'}), 500

    finger_id = request.json.get('fingerprint_id')
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT name FROM fingerprint_users WHERE fingerprint_id = %s", (finger_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        return jsonify({'status': 'success', 'name': user['name']})
    
    return jsonify({'status': 'not_found', 'name': f'ID #{finger_id}'})

@app.route('/api/web/delete', methods=['POST'])
def web_delete():
    """ Hapus user dari database dan instruksikan alat untuk hapus data di sensor fisiknya """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    finger_id = request.json.get('fingerprint_id')
    if not finger_id:
        return jsonify({'status': 'error', 'message': 'fingerprint_id diperlukan'}), 400
        
    cursor = conn.cursor()
    
    # 1. Hapus record dari database
    cursor.execute("DELETE FROM fingerprint_users WHERE fingerprint_id = %s", (finger_id,))
    
    # 2. Set mode DELETE agar alat menghapus data di memori internal sensor
    cursor.execute("UPDATE device_state SET mode = 'DELETE', target_enroll_id = %s WHERE id = 1", (finger_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'delete_triggered', 'id': finger_id})

@app.route('/api/users', methods=['GET'])
def get_users():
    """ Menampilkan semua daftar user yang terdaftar di sistem """
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT fingerprint_id, name, role, created_at FROM fingerprint_users ORDER BY fingerprint_id ASC")
    users = cursor.fetchall()
    
    conn.close()
    return jsonify(users)

if __name__ == '__main__':
    # Jalankan server lokal di port 5000
    app.run(debug=True, host='0.0.0.0', port=5000)