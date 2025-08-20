import requests
import threading
import time
import random
import json
import base64
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
import logging
import re

# Suppress unnecessary Flask logging to keep the console clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
# A secret key is required for session management. Change this to a random string.
app.secret_key = 'your_very_secret_and_random_key_12345'

# The required password to access the application.
# IMPORTANT: Change this password for security!
APP_PASSWORD = "z8!qW-bK$v-x#7sE-j9@Lp-f3^aY-c5&uI-p2*oT-m6(rZ-h1)gN-v4}eX-k0{dC-w7[eS-t8]fB-n9;qA-r2:pD-g5<uF-s3>vG-a1,yH-b4.zJ-c6?iKujshdbcjuhudywegaibvx"

# =============================================================================
# CORE ATTENDANCE LOGIC (Unchanged)
# =============================================================================

def login_and_get_cookie(username, password, output_log):
    url = "https://student.bennetterp.camu.in/login/validate"
    headers = {
        "Content-Type": "application/json", "Origin": "https://student.bennetterp.camu.in",
        "Referer": "https://student.bennetterp.camu.in/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    payload = {"dtype": "M", "Email": username, "pwd": password}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=18)
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
    # This function is now only used for the "Upload Image" option
    api_url = "https://api.qrserver.com/v1/read-qr-code/"
    files = {'file': ('qr_code.png', image_data, 'image/png')}
    try:
        response = requests.post(api_url, files=files, timeout=15)
        response.raise_for_status()
        result = response.json()
        if result and result[0]['symbol'][0]['data']:
            return result[0]['symbol'][0]['data']
        else:
            error_message = result[0]['symbol'][0].get('error', 'No QR code data found in API response.')
            raise ValueError(f"QR code decoding failed: {error_message}")
    except requests.exceptions.RequestException as e:
        raise ValueError(f"API request to qrserver.com failed: {e}")
    except (IndexError, KeyError, TypeError):
        raise ValueError("Could not parse the QR code from the API response.")

def mark_attendance(username, attendance_id, stu_id, cookie_str, output_log):
    url = "https://student.bennetterp.camu.in/api/Attendance/record-online-attendance"
    headers = {
        "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
        "Cookie": cookie_str, "Origin": "https://student.bennetterp.camu.in",
        "Referer": "https://student.bennetterp.camu.in/v2/timetable",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
    payload = {"attendanceId": attendance_id, "StuID": stu_id, "offQrCdEnbld": True}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        output_log.append(f"📊 [{username}] Status: {r.status_code} | Response: {r.text.strip()}")
    except requests.exceptions.RequestException as e:
        output_log.append(f"❌ [{username}] Attendance request failed: {e}")

def process_student(student_info, attendance_id, output_log):
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
                # =================================================================
# Find this part in your parse_logs_for_table function and replace it
# =================================================================

                elif "Status:" in log:
                    try:
                        parts = log.split('|')
                        http_status = re.search(r'Status: (\d+)', parts[0]).group(1)
                        response_text = parts[1].replace("Response:", "").strip()
                        response_json = json.loads(response_text)
                        
                        # Safely access the nested 'code'
                        status_code = ""
                        if 'output' in response_json and 'data' in response_json['output']:
                            status_code = response_json['output']['data'].get('code', '')

                        # Check for success
                        if http_status == '200' and 'suc' in status_code.lower():
                            result_entry["status"] = "Success"
                            result_entry["response"] = "Attendance marked."
                        else:
                            result_entry["status"] = "Failed"
                            # Make the error message readable, e.g., "Attendance Not Valid"
                            if status_code:
                                result_entry["response"] = status_code.replace('_', ' ').title()
                            else:
                                result_entry["response"] = "Unknown server response."

                    except (IndexError, AttributeError, json.JSONDecodeError, KeyError):
                        result_entry["status"] = "Error"
                        result_entry["response"] = "Could not parse server response."
                    break # Stop searching logs for this email
        results.append(result_entry)
    return results

def run_attendance_for_all(attendance_id, students):
    output_log = []
    if not students or not isinstance(students, list):
        return {"logs": ["❌ FATAL ERROR: No student data provided."], "table_data": []}
    output_log.append(f"🚀 Starting attendance process for {len(students)} student(s)...\n")
    threads = []
    for student in students:
        thread = threading.Thread(target=process_student, args=(student, attendance_id, output_log))
        threads.append(thread)
        thread.start()
        time.sleep(random.uniform(0.4, 0.7))
    for thread in threads:
        thread.join()
    table_data = parse_logs_for_table(output_log, students)
    return {"logs": output_log, "table_data": table_data}

# =============================================================================
# TEMPLATES (HTML/JS Updated for Responsiveness and Readability)
# =============================================================================

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Attendance Automator</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Poppins', sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; background-color: #1e1e2e; margin: 0; padding: 1rem; }
        h1 { color: #f1f1f1; }
        .login-container { background: #2a2a40; padding: 2.5rem; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,.4); text-align: center; max-width: 400px; width: 100%; border: 1px solid #444; }
        .error { color: #ff8a8a; background: #4d2a2a; border: 1px solid #f5c6cb4d; padding: 10px; border-radius: 8px; margin-bottom: 1rem; }
        input[type=password] { width: 100%; padding: 12px; border: 1px solid #555; border-radius: 8px; font-size: 16px; margin-bottom: 1rem; background-color: #1e1e2e; color: #f1f1f1; box-sizing: border-box; }
        .button { background-image: linear-gradient(45deg, #4a90e2 0%, #50e3c2 100%); color: #fff; border: none; padding: 12px 24px; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all .3s; }
        .button:hover { transform: translateY(-2px); }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Enter Password</h1>
        {% if error %}
            <p class="error">{{ error }}</p>
        {% endif %}
        <form method="post">
            <input type="password" name="password" placeholder="Password" required autofocus>
            <button type="submit" class="button">Login</button>
        </form>
    </div>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Attendance Automator</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>

    <style>
        /* CSS Variables for easy theme management */
        :root {
            --primary-color: #4a90e2;
            --secondary-color: #50e3c2;
            --bg-color: #1e1e2e;
            --card-bg: #2a2a40;
            --text-color: #f1f1f1;
            --shadow: 0 10px 30px rgba(0, 0, 0, .4);
            --success-color: #28a745;
            --error-color: #dc3545;
        }

        /* Basic Body Styling */
        body {
            font-family: 'Poppins', sans-serif;
            display: flex;
            align-items: flex-start;
            justify-content: center;
            min-height: 100vh;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 1rem;
            box-sizing: border-box;
        }

        /* Main container for the application */
        .container {
            background: var(--card-bg);
            padding: 2rem;
            border-radius: 20px;
            box-shadow: var(--shadow);
            text-align: center;
            max-width: 900px;
            width: 100%;
            transition: all .3s ease;
            position: relative;
            border: 1px solid #444;
            box-sizing: border-box;
        }
        .logout-btn {
            position: absolute;
            top: 15px;
            right: 20px;
            background: none;
            border: 1px solid #555;
            color: #aaa;
            padding: 5px 10px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 12px;
        }
        .logout-btn:hover { background: #333; }

        /* Typography */
        h1, h2, h3 { color: var(--text-color); margin-bottom: .5rem; }
        p.subtitle { color: #aaa; margin-top: 0; margin-bottom: 2rem; }

        /* Button Styles */
        .button {
            background-image: linear-gradient(45deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            color: #fff;
            border: none;
            padding: 12px 24px;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all .3s;
            margin: .5rem;
            box-shadow: 0 4px 15px rgba(0,0,0,.2);
            display: inline-block;
            text-align: center;
        }
        .button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0,0,0,.25);
        }
        .button-secondary {
            background-image: none;
            background-color: #444;
            color: #f1f1f1;
        }
        .button-secondary:hover { background-color: #555; }

        /* Utility Classes */
        .hidden { display: none; }

        /* Layout Styles */
        .flex-container {
            display: flex;
            justify-content: space-between;
            gap: 2rem;
            margin-top: 2rem;
            flex-wrap: wrap;
        }
        .panel {
            flex: 1;
            min-width: 280px;
            text-align: left;
        }
        #student-manager-panel, #process-panel {
            border: 1px solid #444;
            padding: 1.5rem;
            border-radius: 12px;
        }

        /* Form and Input Styles */
        .input-group { margin-bottom: 1rem; }
        .input-group label { display: block; margin-bottom: 5px; font-weight: 600; font-size: 14px; }
        input[type=text], input[type=password] {
            width: 100%;
            padding: 12px;
            border: 1px solid #555;
            border-radius: 8px;
            font-size: 16px;
            background-color: #1e1e2e;
            color: #f1f1f1;
            box-sizing: border-box;
        }
        #decoded-id {
            background: #1e1e2e;
            padding: 10px;
            border-radius: 8px;
            font-weight: 600;
            color: var(--primary-color);
            word-wrap: break-word;
            margin: 1rem 0;
            border: 1px solid #444;
        }

        /* MODIFICATION START: Improved styles for scrollable areas */
        .results-table-container, #results-log {
            max-height: 30vh; /* Use viewport height for better responsiveness on mobile */
            overflow-y: auto; /* Ensure vertical scrolling is enabled */
            -webkit-overflow-scrolling: touch; /* Adds momentum-based scrolling on iOS */
            border: 1px solid #444;
            border-radius: 8px;
        }
        .results-table-container {
             margin-bottom: 1rem;
        }
        #results-log {
            background: #1a1a1a;
            color: #f1f1f1;
            padding: 1rem;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-family: 'Courier New', Courier, monospace;
            font-size: 14px;
        }
        /* MODIFICATION END */

        .loader {
            border: 4px solid #444;
            border-top: 4px solid var(--primary-color);
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* Table Styles */
        #student-list-table, #results-table {
            border-collapse: collapse;
            width: 100%;
            margin-top: 1.5rem;
            font-size: 14px;
        }
        /* MODIFICATION: Remove margin-top from #results-table to fit wrapper */
        #results-table {
            margin-top: 0;
        }
        #student-list-table th, #student-list-table td, #results-table th, #results-table td {
            border: 1px solid #444;
            padding: 10px;
            text-align: left;
        }
        #student-list-table th, #results-table th {
            background-color: #333757;
            font-weight: 600;
        }
        .status {
            font-weight: 700;
            padding: 5px 8px;
            border-radius: 5px;
            color: #fff;
            display: inline-block;
        }
        .status-success { background-color: var(--success-color); }
        .status-failed { background-color: var(--error-color); }

        /* QR Scanner Specific Styles */
        .options-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
            margin-bottom: 1rem;
        }
        #camera-view #reader {
            border: 2px solid #555;
            border-radius: 8px;
            overflow: hidden;
        }
        #zoom-controls { margin-top: 10px; }
        .zoom-label { font-size: 14px; margin-right: 10px; }

        /* Responsive Design for smaller screens */
        @media (max-width: 768px) {
            body { padding-top: 1rem; }
            .container { padding: 1.5rem; }
            .flex-container { flex-direction: column; }
            h1 { font-size: 1.8rem; }
            
            #student-list-table thead, #results-table thead { display: none; }
            #student-list-table, #student-list-table tbody, #student-list-table tr, #student-list-table td,
            #results-table, #results-table tbody, #results-table tr, #results-table td {
                display: block;
                width: 100%;
                box-sizing: border-box;
            }
            #student-list-table tr, #results-table tr {
                margin-bottom: 15px;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 5px;
            }
            #student-list-table td, #results-table td {
                text-align: right;
                padding-left: 50%;
                position: relative;
                border: none;
                border-bottom: 1px solid #333;
                min-height: 24px;
            }
            #student-list-table td:before, #results-table td:before {
                content: attr(data-label);
                position: absolute;
                left: 10px;
                width: 45%;
                padding-right: 10px;
                white-space: nowrap;
                text-align: left;
                font-weight: 700;
            }
            #student-list-table td:last-child, #results-table td:last-child { border-bottom: 0; }
            #student-list-table td[data-label="Email"], #results-table td[data-label="Response"] {
                white-space: normal;
                word-wrap: break-word;
                overflow-wrap: break-word;
                text-align: left;
                padding-left: 10px;
                padding-top: 30px;
            }
            #student-list-table td[data-label="Email"]:before, #results-table td[data-label="Response"]:before {
                top: 10px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <a href="/logout" class="logout-btn">Logout</a>
        <h1>Attendance Automator</h1>
        <p class="subtitle">Manage your student list, then scan a QR code to mark attendance for everyone.</p>

        <div class="flex-container">
            
            <div class="panel" id="student-manager-panel">
                <h2>Student List</h2>
                <p style="font-size:12px;color:#777">Your list is saved in your browser. Max 15 students.</p>
                
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

                <hr style="margin:1.5rem 0; border-color: #444;">

                <table id="student-list-table">
                    <thead>
                        <tr>
                            <th>Email</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        </tbody>
                </table>

                <div style="margin-top:1rem">
                    <label for="json-upload" class="button button-secondary">Upload credentials.json</label>
                    <input type="file" id="json-upload" accept=".json" class="hidden">
                </div>
            </div>

            <div class="panel" id="process-panel">
                
                <div id="initial-view">
                    <h2>Step 1: Get Attendance ID</h2>
                    <div class="options-grid">
                        <button class="button" id="start-camera-btn">Scan with Camera (Live)</button>
                        <label for="qr-upload" class="button">Upload QR Image</label>
                        <input type="file" id="qr-upload" accept="image/*" class="hidden">
                    </div>
                    <hr style="margin:1.5rem 0; border-color: #444;">
                    <div class="input-group" style="margin-top:1rem">
                        <input type="text" id="qr-text-input" placeholder="Or paste QR text here...">
                        <button class="button" id="submit-text-btn">Use Text</button>
                    </div>
                </div>

                <div id="camera-view" class="hidden">
                    <div id="reader" width="100%"></div>
                    <div id="zoom-controls" class="hidden">
                        <span class="zoom-label">Zoom:</span>
                        <input type="range" id="zoom-slider" min="1" max="5" step="0.1" value="1">
                    </div>
                    <button class="button button-secondary" id="cancel-scan-btn" style="margin-top:1rem;">Cancel</button>
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
                        <div class="results-table-container">
                            <table id="results-table">
                                <thead>
                                    <tr>
                                        <th>Email</th>
                                        <th>Status</th>
                                        <th>Response</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    </tbody>
                            </table>
                        </div>
                        <h3>Raw Log</h3>
                        <div id="results-log"></div>
                        <button class="button" onclick="location.reload()">Run Again</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <audio id="beep-sound" src="data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YU9vT19PANkPCz4/rgr5Cg8+v60K+g4QPj/9CvoODz/APww/QD8P/w8+P/8K+g4QPj+tCvoODz6/rQr5Cg8+P60K+QoPPg=="></audio>

    <script>
        // DOM Element References
        const addStudentForm = document.getElementById('add-student-form');
        const studentListBody = document.querySelector('#student-list-table tbody');
        const jsonUpload = document.getElementById('json-upload');
        const initialView = document.getElementById('initial-view');
        const cameraView = document.getElementById('camera-view');
        const confirmView = document.getElementById('confirm-view');
        const resultsView = document.getElementById('results-view');
        const startCameraBtn = document.getElementById('start-camera-btn');
        const qrUploadInput = document.getElementById('qr-upload');
        const submitTextBtn = document.getElementById('submit-text-btn');
        const markAttendanceBtn = document.getElementById('mark-attendance-btn');
        const qrTextInput = document.getElementById('qr-text-input');
        const decodedIdDiv = document.getElementById('decoded-id');
        const resultsLogDiv = document.getElementById('results-log');
        const resultsLoader = document.getElementById('results-loader');
        const resultsContent = document.getElementById('results-content');
        const resultsTableBody = document.querySelector('#results-table tbody');
        const cancelScanBtn = document.getElementById('cancel-scan-btn');
        const zoomControls = document.getElementById('zoom-controls');
        const zoomSlider = document.getElementById('zoom-slider');
        const beepSound = document.getElementById('beep-sound');

        // Application State
        let students = [];
        let decodedAttendanceId = null;
        let html5QrCode = null;

        // --- Student Management Functions ---

        function saveStudents() {
            localStorage.setItem('studentList', JSON.stringify(students));
        }

        function renderStudentList() {
            studentListBody.innerHTML = '';
            students.forEach((student, index) => {
                const row = `<tr>
                    <td data-label="Email">${student.email}</td>
                    <td data-label="Action"><button onclick="deleteStudent(${index})" style="background:var(--error-color); color:white; border:none; padding: 5px 10px; border-radius:5px; cursor:pointer;">Delete</button></td>
                </tr>`;
                studentListBody.innerHTML += row;
            });
        }

        function addStudent(email, password, stu_id) {
            if (students.length >= 15) {
                alert("You can only add up to 15 students.");
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

        jsonUpload.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (event) => {
                try {
                    const data = JSON.parse(event.target.result);
                    if (!data.students || !Array.isArray(data.students)) {
                        throw new Error("Invalid JSON format. Expected a 'students' array.");
                    }
                    students = data.students.slice(0, 15); // Enforce max limit
                    saveStudents();
                    renderStudentList();
                    alert(`${students.length} students loaded successfully!`);
                } catch (error) {
                    alert(`Error reading file: ${error.message}`);
                }
            };
            reader.readAsText(file);
        });

        document.addEventListener('DOMContentLoaded', () => {
            const storedStudents = localStorage.getItem('studentList');
            if (storedStudents) {
                students = JSON.parse(storedStudents);
                renderStudentList();
            }
        });

        // --- UI and Workflow Functions ---

        startCameraBtn.addEventListener('click', startLiveScanner);
        qrUploadInput.addEventListener('change', handleFileUpload);
        submitTextBtn.addEventListener('click', usePastedText);
        markAttendanceBtn.addEventListener('click', runAttendanceProcess);
        cancelScanBtn.addEventListener('click', () => {
            if (html5QrCode && html5QrCode.isScanning) {
                html5QrCode.stop().then(ignore => showView(initialView)).catch(err => console.error("Failed to stop scanner", err));
            }
        });

        function showView(viewToShow) {
            [initialView, cameraView, confirmView, resultsView].forEach(view => view.classList.add('hidden'));
            viewToShow.classList.remove('hidden');
        }

        // --- QR Code Handling ---

        const onScanSuccess = (decodedText, decodedResult) => {
            beepSound.play();
            if (html5QrCode && html5QrCode.isScanning) {
                html5QrCode.stop().then(() => {
                    decodedAttendanceId = decodedText;
                    showConfirmationScreen();
                }).catch(err => {
                    console.error("Failed to stop scanner but proceeding anyway.", err);
                    decodedAttendanceId = decodedText;
                    showConfirmationScreen();
                });
            }
        };
        
        const onScanFailure = (error) => {
            // console.warn(`QR error = ${error}`);
        };

        function startLiveScanner() {
            showView(cameraView);
            html5QrCode = new Html5Qrcode("reader");
            const config = { fps: 10, qrbox: { width: 250, height: 250 } };
            html5QrCode.start({ facingMode: "environment" }, config, onScanSuccess, onScanFailure)
                .then(() => {
                    setupZoom(); // Attempt to set up zoom controls after camera starts
                })
                .catch(err => {
                    alert("Could not start camera. Please grant permission and try again.");
                    showView(initialView);
                });
        }
        
        function setupZoom() {
            try {
                setTimeout(() => {
                    const videoElement = document.querySelector("#reader video");
                    if (!videoElement || !videoElement.srcObject) {
                        return;
                    }
                    const [track] = videoElement.srcObject.getVideoTracks();
                    if (!track) {
                        return;
                    }
                    const capabilities = track.getCapabilities();
                    if (capabilities.zoom) {
                        zoomSlider.min = capabilities.zoom.min;
                        zoomSlider.max = capabilities.zoom.max;
                        zoomSlider.step = capabilities.zoom.step || 0.1;
                        zoomSlider.value = track.getSettings().zoom || capabilities.zoom.min;
                        
                        zoomControls.classList.remove('hidden');

                        zoomSlider.addEventListener('input', (event) => {
                            const zoomValue = parseFloat(event.target.value);
                            track.applyConstraints({ advanced: [{ zoom: zoomValue }] })
                                .catch(e => console.error("Error applying zoom:", e));
                        });
                    }
                }, 500);
            } catch (e) {
                console.error("Zoom setup failed:", e);
            }
        }

        function handleFileUpload(event) {
            const file = event.target.files[0];
            if (file) {
                if (!file.type.startsWith('image/')) {
                    alert("Please upload a valid image file.");
                    return;
                }
                const reader = new FileReader();
                reader.onload = (e) => {
                    const imageDataUrl = e.target.result;
                    showView(resultsView);
                    resultsContent.classList.add('hidden');
                    resultsLoader.classList.remove('hidden');
                    resultsLogDiv.textContent = "Decoding uploaded QR code via API...";
                    decodeImageOnServer(imageDataUrl);
                };
                reader.onerror = () => {
                    alert("Error reading file.");
                };
                reader.readAsDataURL(file);
            }
        }

        async function decodeImageOnServer(imageDataUrl) {
            try {
                const response = await fetch('/decode-qr', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: imageDataUrl })
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `Server responded with status ${response.status}`);
                }
                const result = await response.json();
                if (result.error) throw new Error(result.error);
                
                decodedAttendanceId = result.attendance_id;
                showConfirmationScreen();
            } catch (error) {
                showView(initialView);
                alert(`Error decoding QR: ${error.message}`);
            }
        }

        function usePastedText() {
            const qrText = qrTextInput.value.trim();
            if (qrText) {
                decodedAttendanceId = qrText;
                showConfirmationScreen();
            } else {
                alert("Please paste the QR code text.");
            }
        }

        // --- Final Attendance Process ---

        function showConfirmationScreen() {
            if (students.length === 0) {
                alert("Please add at least one student before marking attendance.");
                location.reload();
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

# =============================================================================
# FLASK WEB SERVER ROUTES (Unchanged)
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            error = 'Invalid password. Please try again.'
    return render_template_string(LOGIN_TEMPLATE, error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template_string(HTML_TEMPLATE)

@app.route('/decode-qr', methods=['POST'])
def decode_qr_endpoint():
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authorized. Please log in again.'}), 401
    try:
        data = request.json
        image_data = base64.b64decode(data['image'].split(',')[1])
        attendance_id = decode_qr_from_data(image_data)
        return jsonify({'attendance_id': attendance_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/mark-attendance', methods=['POST'])
def mark_attendance_endpoint():
    if not session.get('logged_in'):
        return jsonify({'error': 'Not authorized. Please log in again.'}), 401
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
