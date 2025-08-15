import cv2
import numpy as np
from pyzbar.pyzbar import decode
import requests
import threading
import time
import random
import json
import base64
from flask import Flask, render_template_string, request, jsonify
import logging
import re

# Suppress unnecessary Flask logging to keep the console clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# =============================================================================
# CORE ATTENDANCE LOGIC (This section is unchanged)
# =============================================================================

def login_and_get_cookie(username, password, output_log):
    # This function remains the same
    url = "https://student.bennetterp.camu.in/login/validate"
    headers = {
        "Content-Type": "application/json", "Origin": "https://student.bennetterp.camu.in",
        "Referer": "https://student.bennetterp.camu.in/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    payload = {"dtype": "M", "Email": username, "pwd": password}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        if 'Set-Cookie' in r.headers:
            session_cookie = r.headers['Set-Cookie'].split(';')[0]
            output_log.append(f"✅ [{username}] Login successful.")
            return session_cookie
        else:
            output_log.append(f"❌ [{username}] Login failed. Check credentials.")
            return None
    except requests.exceptions.RequestException as e:
        output_log.append(f"❌ [{username}] Login request failed: {e}")
        return None

def decode_qr_from_data(image_data):
    # This function remains the same
    nparr = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image data.")
    codes = decode(img)
    if not codes:
        raise ValueError("No QR code found in the image!")
    return codes[0].data.decode("utf-8")

def mark_attendance(username, attendance_id, stu_id, cookie_str, output_log):
    # This function remains the same
    url = "https://student.bennetterp.camu.in/api/Attendance/record-online-attendance"
    headers = {
        "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
        "Cookie": cookie_str, "Origin": "https://student.bennetterp.camu.in",
        "Referer": "https://student.bennetterp.camu.in/v2/timetable",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    payload = {"attendanceId": attendance_id, "StuID": stu_id, "offQrCdEnbld": True}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        output_log.append(f"📊 [{username}] Status: {r.status_code} | Response: {r.text.strip()}")
    except requests.exceptions.RequestException as e:
        output_log.append(f"❌ [{username}] Attendance request failed: {e}")

def process_student(student_info, attendance_id, output_log):
    # This function remains the same
    email = student_info.get("email")
    password = student_info.get("password")
    stu_id = student_info.get("stu_id")
    if not all([email, password, stu_id]):
        output_log.append(f"⚠️ Skipping invalid student entry.")
        return
        
    output_log.append(f"[*] Starting process for: {email}")
    session_cookie = login_and_get_cookie(email, password, output_log)
    if session_cookie:
        mark_attendance(email, attendance_id, stu_id, session_cookie, output_log)

def parse_logs_for_table(logs, students):
    # This function remains the same
    results = []
    student_emails = [s.get("email") for s in students]

    for email in student_emails:
        if not email: continue
        
        result_entry = {"email": email, "status": "Pending", "response": "No response recorded."}
        
        for log in reversed(logs):
            if f"[{email}]" in log:
                if "Login failed" in log or "request failed" in log:
                    result_entry["status"] = "Login Failed"
                    result_entry["response"] = log.split(f"[{email}]")[1].strip()
                    break
                elif "Status:" in log:
                    try:
                        parts = log.split('|')
                        status_part = parts[0]
                        response_part = parts[1]
                        
                        http_status = re.search(r'Status: (\d+)', status_part).group(1)
                        response_json = json.loads(response_part.replace("Response:", "").strip())
                        
                        if http_status == '200' and response_json.get('status') == 'success':
                            result_entry["status"] = "Success"
                        else:
                            result_entry["status"] = "Failed"
                        
                        result_entry["response"] = response_json.get('message', 'No message.')
                    except (IndexError, AttributeError, json.JSONDecodeError):
                        result_entry["status"] = "Error"
                        result_entry["response"] = "Could not parse server response."
                    break
        results.append(result_entry)
    return results


def run_attendance_for_all(attendance_id, students):
    # This function remains the same
    output_log = []
    
    if not students or not isinstance(students, list):
        return {"logs": ["❌ FATAL ERROR: No student data provided."], "table_data": []}

    output_log.append(f"🚀 Starting attendance process for {len(students)} student(s)...\n")
    
    threads = []
    for student in students:
        thread = threading.Thread(target=process_student, args=(student, attendance_id, output_log))
        threads.append(thread)
        thread.start()
        time.sleep(random.uniform(0.5, 0.9))
        
    for thread in threads:
        thread.join()
        
    table_data = parse_logs_for_table(output_log, students)
    
    return {"logs": output_log, "table_data": table_data}

# =============================================================================
# FLASK WEB SERVER ROUTES
# =============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Attendance Automator</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root { --primary-color: #4a90e2; --secondary-color: #50e3c2; --bg-color: #f4f7f6; --card-bg: #ffffff; --text-color: #333; --shadow: 0 10px 30px rgba(0,0,0,0.1); --success-color: #28a745; --error-color: #dc3545; }
        body { font-family: 'Poppins', sans-serif; display: flex; align-items: flex-start; justify-content: center; min-height: 100vh; background-image: linear-gradient(to top, #cfd9df 0%, #e2ebf0 100%); margin: 1rem; padding-top: 2rem; }
        .container { background: var(--card-bg); padding: 2.5rem; border-radius: 20px; box-shadow: var(--shadow); text-align: center; max-width: 900px; width: 100%; transition: all 0.3s ease; }
        h1, h2, h3 { color: var(--text-color); margin-bottom: 0.5rem; }
        p.subtitle { color: #888; margin-top: 0; margin-bottom: 2rem; }
        .button { background-image: linear-gradient(45deg, var(--primary-color) 0%, var(--secondary-color) 100%); color: white; border: none; padding: 12px 24px; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.3s; margin: 0.5rem; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
        .button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.25); }
        .button-secondary { background-image: none; background-color: #eee; color: #555; }
        .button:disabled { background-image: none; background-color: #cccccc; cursor: not-allowed; transform: none; box-shadow: none; }
        .hidden { display: none; }
        .flex-container { display: flex; justify-content: space-between; gap: 2rem; margin-top: 2rem; flex-wrap: wrap; }
        .panel { flex: 1; min-width: 300px; text-align: left;}
        #student-manager-panel, #process-panel { border: 1px solid #eee; padding: 1.5rem; border-radius: 12px; }
        .input-group { margin-bottom: 1rem; }
        .input-group label { display: block; margin-bottom: 5px; font-weight: 600; font-size: 14px; }
        input[type="text"], input[type="password"] { width: calc(100% - 24px); padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; }
        #decoded-id { background: #eef; padding: 10px; border-radius: 8px; font-weight: 600; color: var(--primary-color); word-wrap: break-word; margin: 1rem 0; }
        #results-log { margin-top: 1rem; text-align: left; background: #2d2d2d; color: #f1f1f1; border-radius: 8px; padding: 1rem; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-wrap: break-word; font-family: 'Courier New', Courier, monospace; font-size: 14px; }
        .loader { border: 4px solid #f3f3f3; border-top: 4px solid var(--primary-color); border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        #student-list-table, #results-table { border-collapse: collapse; width: 100%; margin-top: 1.5rem; font-size: 14px; }
        #student-list-table th, #student-list-table td, #results-table th, #results-table td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        #student-list-table th, #results-table th { background-color: #f2f2f2; font-weight: 600; }
        .status { font-weight: bold; padding: 5px 8px; border-radius: 5px; color: white; display: inline-block; }
        .status-success { background-color: var(--success-color); }
        .status-failed { background-color: var(--error-color); }

        /* --- NEW: MOBILE RESPONSIVE STYLES --- */
        @media (max-width: 768px) {
            body { padding-top: 1rem; }
            .container { padding: 1.5rem; }
            .flex-container { flex-direction: column; }
            h1 { font-size: 1.8rem; }
            
            /* Responsive Table Styling */
            #student-list-table thead, #results-table thead { display: none; }
            #student-list-table, #student-list-table tbody, #student-list-table tr, #student-list-table td,
            #results-table, #results-table tbody, #results-table tr, #results-table td {
                display: block;
                width: 100%;
                box-sizing: border-box;
            }
            #student-list-table tr, #results-table tr {
                margin-bottom: 15px;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 5px;
            }
            #student-list-table td, #results-table td {
                text-align: right;
                padding-left: 50%;
                position: relative;
                border: none;
                border-bottom: 1px solid #eee;
            }
            #student-list-table td:before, #results-table td:before {
                content: attr(data-label);
                position: absolute;
                left: 10px;
                width: 45%;
                padding-right: 10px;
                white-space: nowrap;
                text-align: left;
                font-weight: bold;
            }
            #student-list-table td:last-child, #results-table td:last-child { border-bottom: 0; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Attendance Automator</h1>
        <p class="subtitle">Manage your student list, then scan a QR code to mark attendance for everyone.</p>

        <div class="flex-container">
            <div class="panel" id="student-manager-panel">
                <h2>Student List</h2>
                <p style="font-size: 12px; color: #777;">Your list is saved in your browser. Max 10 students.</p>
                <form id="add-student-form">
                    <div class="input-group">
                        <label for="email">Email</label>
                        <input type="text" id="email" required>
                    </div>
                    <div class="input-group">
                        <label for="password">Password</label>
                        <input type="password" id="password" required>
                    </div>
                    <div class="input-group">
                        <label for="stu_id">Student ID</label>
                        <input type="text" id="stu_id" required>
                    </div>
                    <button type="submit" class="button">Add Student</button>
                </form>
                <hr style="margin: 1.5rem 0;">
                <table id="student-list-table">
                    <thead><tr><th>Email</th><th>Action</th></tr></thead>
                    <tbody></tbody>
                </table>
                <div style="margin-top: 1rem;">
                    <label for="json-upload" class="button button-secondary">Upload credentials.json</label>
                    <input type="file" id="json-upload" accept=".json" class="hidden">
                </div>
            </div>

            <div class="panel" id="process-panel">
                <div id="initial-view">
                    <h2>Step 1: Get Attendance ID</h2>
                    <button class="button" id="start-camera-btn">Use Camera</button>
                    <div class="input-group" style="margin-top: 1rem;">
                        <input type="text" id="qr-text-input" placeholder="Or paste QR text here...">
                        <button class="button" id="submit-text-btn">Use Text</button>
                    </div>
                </div>
                <div id="camera-view" class="hidden">
                    <video id="video" autoplay playsinline style="width:100%; border-radius:8px;"></video>
                    <button class="button" id="capture-btn">Capture QR</button>
                </div>
                <div id="confirm-view" class="hidden">
                    <h2>Step 2: Confirm & Run</h2>
                    <p><strong>Attendance ID:</strong></p>
                    <div id="decoded-id"></div>
                    <button class="button" id="mark-attendance-btn">Confirm & Mark Attendance</button>
                </div>
                <div id="results-view" class="hidden">
                    <h2>Process Complete</h2>
                    <div id="results-loader" class="loader"></div>
                    <div id="results-content" class="hidden">
                        <h3>Results Summary</h3>
                        <table id="results-table">
                            <thead><tr><th>Email</th><th>Status</th><th>Response</th></tr></thead>
                            <tbody></tbody>
                        </table>
                        <h3>Raw Log</h3>
                        <div id="results-log"></div>
                        <button class="button" onclick="location.reload()">Run Again</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // DOM Elements
        const addStudentForm = document.getElementById('add-student-form');
        const studentListBody = document.querySelector('#student-list-table tbody');
        const jsonUpload = document.getElementById('json-upload');
        const initialView = document.getElementById('initial-view');
        const cameraView = document.getElementById('camera-view');
        const confirmView = document.getElementById('confirm-view');
        const resultsView = document.getElementById('results-view');
        const startCameraBtn = document.getElementById('start-camera-btn');
        const captureBtn = document.getElementById('capture-btn');
        const submitTextBtn = document.getElementById('submit-text-btn');
        const markAttendanceBtn = document.getElementById('mark-attendance-btn');
        const video = document.getElementById('video');
        const qrTextInput = document.getElementById('qr-text-input');
        const decodedIdDiv = document.getElementById('decoded-id');
        const resultsLogDiv = document.getElementById('results-log');
        const resultsLoader = document.getElementById('results-loader');
        const resultsContent = document.getElementById('results-content');
        const resultsTableBody = document.querySelector('#results-table tbody');

        let students = [];
        let decodedAttendanceId = null;

        // --- Student Management Logic ---
        function saveStudents() {
            localStorage.setItem('studentList', JSON.stringify(students));
        }

        function renderStudentList() {
            studentListBody.innerHTML = '';
            students.forEach((student, index) => {
                // *** MODIFIED: Added data-label attributes for mobile view ***
                const row = `<tr>
                    <td data-label="Email">${student.email}</td>
                    <td data-label="Action"><button onclick="deleteStudent(${index})" style="background:var(--error-color); color:white; border:none; padding: 5px 10px; border-radius:5px; cursor:pointer;">Delete</button></td>
                </tr>`;
                studentListBody.innerHTML += row;
            });
        }

        function addStudent(email, password, stu_id) {
            if (students.length >= 10) {
                alert("You can only add up to 10 students.");
                return;
            }
            if (students.some(s => s.email === email)) {
                alert("This email is already in the list.");
                return;
            }
            students.push({ email, password, stu_id });
            saveStudents();
            renderStudentList();
        }

        function deleteStudent(index) {
            students.splice(index, 1);
            saveStudents();
            renderStudentList();
        }

        addStudentForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            const stu_id = document.getElementById('stu_id').value;
            addStudent(email, password, stu_id);
            addStudentForm.reset();
        });

        jsonUpload.addEventListener('change', (event) => {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                try {
                    const data = JSON.parse(e.target.result);
                    if (!data.students || !Array.isArray(data.students)) {
                        throw new Error("Invalid JSON format. Expected an object with a 'students' array.");
                    }
                    students = data.students.slice(0, 10); // Limit to 10
                    saveStudents();
                    renderStudentList();
                    alert(`${students.length} students loaded successfully from file!`);
                } catch (err) {
                    alert(`Error reading file: ${err.message}`);
                }
            };
            reader.readAsText(file);
        });

        document.addEventListener('DOMContentLoaded', () => {
            const savedStudents = localStorage.getItem('studentList');
            if (savedStudents) {
                students = JSON.parse(savedStudents);
                renderStudentList();
            }
        });
        
        // --- Attendance Process Logic ---
        startCameraBtn.addEventListener('click', startCamera);
        captureBtn.addEventListener('click', captureImage);
        submitTextBtn.addEventListener('click', usePastedText);
        markAttendanceBtn.addEventListener('click', runAttendanceProcess);
        
        function showView(viewToShow) {
            [initialView, cameraView, confirmView, resultsView].forEach(view => view.classList.add('hidden'));
            viewToShow.classList.remove('hidden');
        }

        async function startCamera() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
                video.srcObject = stream;
                video.onloadedmetadata = () => showView(cameraView);
            } catch (err) {
                alert("Could not access camera. Please grant permission.");
            }
        }

        function captureImage() {
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
            video.srcObject.getTracks().forEach(track => track.stop());
            
            showView(resultsView);
            resultsContent.classList.add('hidden');
            resultsLoader.classList.remove('hidden');
            
            const imageData = canvas.toDataURL('image/png');
            decodeImageOnServer(imageData);
        }

        async function decodeImageOnServer(imageData) {
            try {
                const response = await fetch('/decode-qr', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: imageData })
                });
                const result = await response.json();
                if (result.error) throw new Error(result.error);
                
                decodedAttendanceId = result.attendance_id;
                showConfirmationScreen();
            } catch (error) {
                resultsLogDiv.textContent = `Error decoding QR: ${error.message}`;
            }
        }

        function usePastedText() {
            const text = qrTextInput.value.trim();
            if (!text) {
                alert('Please paste the QR code text.');
                return;
            }
            decodedAttendanceId = text;
            showConfirmationScreen();
        }

        function showConfirmationScreen() {
            if (students.length === 0) {
                alert("Please add at least one student to your list before marking attendance.");
                return;
            }
            showView(confirmView);
            decodedIdDiv.textContent = decodedAttendanceId;
        }

        async function runAttendanceProcess() {
            showView(resultsView);
            resultsLoader.classList.remove('hidden');
            resultsContent.classList.add('hidden');

            try {
                const response = await fetch('/mark-attendance', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        attendance_id: decodedAttendanceId,
                        students: students
                    })
                });
                const result = await response.json();
                
                resultsLoader.classList.add('hidden');
                resultsContent.classList.remove('hidden');

                resultsTableBody.innerHTML = '';
                result.table_data.forEach(item => {
                    const statusClass = item.status === 'Success' ? 'status-success' : 'status-failed';
                    // *** MODIFIED: Added data-label attributes for mobile view ***
                    const row = `<tr>
                        <td data-label="Email">${item.email}</td>
                        <td data-label="Status"><span class="status ${statusClass}">${item.status}</span></td>
                        <td data-label="Response">${item.response}</td>
                    </tr>`;
                    resultsTableBody.innerHTML += row;
                });
                
                resultsLogDiv.textContent = result.logs.join('\\n');

            } catch (error) {
                resultsLoader.classList.add('hidden');
                resultsContent.classList.remove('hidden');
                resultsLogDiv.textContent = `An error occurred: ${error.message}`;
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/decode-qr', methods=['POST'])
def decode_qr_endpoint():
    try:
        data = request.json
        image_data = base64.b64decode(data['image'].split(',')[1])
        attendance_id = decode_qr_from_data(image_data)
        return jsonify({'attendance_id': attendance_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/mark-attendance', methods=['POST'])
def mark_attendance_endpoint():
    try:
        data = request.json
        attendance_id = data.get('attendance_id')
        students = data.get('students') 

        if not attendance_id or not students:
            return jsonify({'error': 'Attendance ID and student list are required.'}), 400
        
        result_data = run_attendance_for_all(attendance_id, students)
        
        return jsonify(result_data)
    except Exception as e:
        return jsonify({'logs': [f"A critical server error occurred: {str(e)}"], 'table_data': []}), 500

if __name__ == '__main__':
    print("=====================================================")
    print("🚀 Attendance Automator Web Server is RUNNING")
    print("   Open your web browser and go to:")
    print("   http://127.0.0.1:5000")
    print("=====================================================")
    app.run(host='0.0.0.0', port=5000, debug=False)