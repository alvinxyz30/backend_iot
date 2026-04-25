from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector

app = Flask(__name__)
CORS(app)

# Settingan database MySQL-nya
db_config = {
    'host': '45.90.230.231',
    'user': 'u1722332_b57760b191fad37b9a3b72213e43773c',
    'password': 'iotproject123!',
    'database': 'u1722332_IOT_Project'
}

# Fungsi buat buka koneksi ke database, biar ga repot ngetik ulang
def get_db_connection():
    try:
        return mysql.connector.connect(**db_config)
    except Exception as e:
        print(f"Duh, gagal konek db: {e}")
        return None

# ---------------------------------------------------------
# API BUAT ALAT (NodeMCU / ESP8266)
# ---------------------------------------------------------

# Alat bakal nge-cek kesini terus (polling) buat liat ada perintah buka pintu/enroll gak
@app.route('/api/device/status', methods=['GET'])
def get_device_status():
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Gagal konek database'}), 500
        
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT mode, target_enroll_id, door_status FROM device_state WHERE id = 1')
    data = cursor.fetchone()
    
    conn.close()
    return jsonify(data)

# Kalo alat udah beres ngelakuin sesuatu, dia lapor balik kesini buat update status
@app.route('/api/device/update', methods=['POST'])
def update_device_status():
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

# Buat simpan riwayat siapa aja yang akses pintu (Log)
@app.route('/api/log/add', methods=['POST'])
def add_log():
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

# Cek apakah ID jari yang ditempel itu Admin atau bukan
@app.route('/api/auth/admin', methods=['POST'])
def verify_admin():
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
# API BUAT DASHBOARD WEB
# ---------------------------------------------------------

# Ambil 20 data log terbaru buat dipajang di tabel dashboard web
@app.route('/api/logs', methods=['GET'])
def get_logs():
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, user_name, status, method, created_at FROM access_logs ORDER BY created_at DESC LIMIT 20")
    logs = cursor.fetchall()
    
    conn.close()
    return jsonify(logs)

# Trigger dari web buat buka pintu jarak jauh
@app.route('/api/web/unlock', methods=['POST'])
def web_unlock():
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error'}), 500
    
    cursor = conn.cursor()
    # Kasih perintah ke database biar nanti dibaca sama alat
    cursor.execute("UPDATE device_state SET door_status = 'OPEN_REQUEST' WHERE id = 1")
    
    conn.commit()
    conn.close()
    return jsonify({'status': 'command_sent'})

# Daftarin user baru: cari slot ID yang kosong di sensor terus suruh alat masuk mode Enroll
@app.route('/api/web/enroll', methods=['POST'])
def web_enroll():
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    data = request.json
    new_name = data.get('name')
    new_role = data.get('role')
    
    if not new_name or not new_role:
        return jsonify({'status': 'error', 'message': 'Nama ama Role-nya jangan lupa diisi'}), 400

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT fingerprint_id FROM fingerprint_users ORDER BY fingerprint_id ASC")
    used_ids = [u['fingerprint_id'] for u in cursor.fetchall()]
    
    # Cari ID kosong dari 1 sampe 127 buat ditaruh di memori sensor
    assigned_id = next((i for i in range(1, 128) if i not in used_ids), None)
            
    if not assigned_id:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Memori sensor udah penuh gan!'}), 400

    # Simpan ke db terus set mode alat jadi ENROLL
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

# Cari nama user berdasarkan ID jarinya (dipanggil alat sebelum buka pintu)
@app.route('/api/user/name', methods=['POST'])
def get_user_name():
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

# Hapus user dari database sekaligus suruh alat hapus memori sidik jarinya
@app.route('/api/web/delete', methods=['POST'])
def web_delete():
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    finger_id = request.json.get('fingerprint_id')
    if not finger_id:
        return jsonify({'status': 'error', 'message': 'ID jari yang mana yang mau dihapus?'}), 400
        
    cursor = conn.cursor()
    
    # Hapus datanya di db
    cursor.execute("DELETE FROM fingerprint_users WHERE fingerprint_id = %s", (finger_id,))
    
    # Suruh alat buat hapus template sidik jari yang ada di memori fisiknya
    cursor.execute("UPDATE device_state SET mode = 'DELETE', target_enroll_id = %s WHERE id = 1", (finger_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'delete_triggered', 'id': finger_id})

# Ambil semua daftar user buat ditampilin di web
@app.route('/api/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    if not conn:
        return jsonify({'status': 'error', 'message': 'Database error'}), 500
    
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT fingerprint_id, name, role, created_at FROM fingerprint_users ORDER BY fingerprint_id ASC")
    users = cursor.fetchall()
    
    conn.close()
    return jsonify(users)

if __name__ == '__main__':
    # Jalanin di port 5000
    app.run(debug=True, host='0.0.0.0', port=5000)