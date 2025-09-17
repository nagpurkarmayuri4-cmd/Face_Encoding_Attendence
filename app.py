from flask import Flask, request, render_template, redirect, session, send_file, url_for
import face_recognition
import numpy as np
import os
import sqlite3
import cv2
from datetime import datetime
from werkzeug.utils import secure_filename
import pandas as pd
import base64
from io import BytesIO
from PIL import Image

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Create folders if they don't exist
os.makedirs("database", exist_ok=True)
os.makedirs("encodings", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)

# Setup SQLite database
def get_db_connection():
    conn = sqlite3.connect("database/students.db")
    conn.row_factory = sqlite3.Row
    return conn

# Initialize database tables
def init_db():
    conn = get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        roll TEXT UNIQUE,
        class TEXT,
        photo_path TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll TEXT,
        name TEXT,
        class TEXT,
        date TEXT,
        time TEXT,
        teacher TEXT,
        status TEXT DEFAULT 'Present'
    )
    """)
    conn.commit()
    conn.close()

init_db()

# Home → Redirect to login
@app.route('/')
def home():
    return redirect('/login')

# Teacher Login Page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        teacher_id = request.form['teacher_id']
        password = request.form['password']
        if teacher_id == 'admin' and password == 'admin123':
            session['teacher'] = teacher_id
            return redirect('/dashboard')
        return render_template('message.html', message="❌ Invalid credentials. Please try again.")
    return render_template('login.html')

# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'teacher' not in session:
        return redirect('/login')
    
    # Count total students
    conn = get_db_connection()
    student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    conn.close()
    
    return render_template('dashboard.html', student_count=student_count)

# Camera Page for Marking Attendance
@app.route('/mark-attendance', methods=['GET'])
def mark_attendance():
    if 'teacher' not in session:
        return redirect('/login')
    return render_template('upload.html')

# Upload Photo from Camera Capture - MARK ATTENDANCE (POST)
@app.route('/process-attendance', methods=['POST'])
def process_attendance():
    if 'teacher' not in session:
        return redirect('/login')

    image_data = request.form['imageData']
    if not image_data:
        return render_template('message.html', message="❌ No image captured")

    # Decode base64 image
    try:
        header, encoded = image_data.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        img = Image.open(BytesIO(img_bytes))
        path = "static/uploads/captured_photo.jpg"
        img.save(path)
    except:
        return render_template('message.html', message="❌ Error processing image")

    # Attendance logic
    image = face_recognition.load_image_file(path)
    face_locations = face_recognition.face_locations(image)
    face_encodings = face_recognition.face_encodings(image, face_locations)

    conn = get_db_connection()
    students = conn.execute("SELECT * FROM students").fetchall()
    marked = []
    today = datetime.now().strftime("%Y-%m-%d")
    
    # First, mark all students as absent for today
    conn.execute("UPDATE attendance SET status='Absent' WHERE date=?", (today,))
    conn.commit()

    for face_encoding in face_encodings:
        for student in students:
            try:
                db_encoding = np.load(f'encodings/{student["roll"]}.npy')
            except:
                continue
            result = face_recognition.compare_faces([db_encoding], face_encoding, tolerance=0.5)
            if result[0] and student["name"] not in marked:
                now = datetime.now()
                date = now.strftime("%Y-%m-%d")
                time = now.strftime("%H:%M:%S")
                
                # Check if attendance already exists for today
                existing = conn.execute("SELECT * FROM attendance WHERE roll=? AND date=?", 
                                      (student["roll"], date)).fetchone()
                
                if existing:
                    # Update existing record
                    conn.execute("UPDATE attendance SET time=?, status='Present' WHERE roll=? AND date=?",
                                (time, student["roll"], date))
                else:
                    # Insert new record
                    conn.execute("INSERT INTO attendance (roll, name, class, date, time, teacher, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (student["roll"], student["name"], student["class"], date, time, session['teacher'], 'Present'))
                
                conn.commit()
                marked.append(student["name"])
                break

    conn.close()
    if marked:
        return render_template('message.html', message=f"✅ Attendance marked for: {', '.join(marked)}")
    else:
        return render_template('message.html', message="❌ No recognized students found.")

# Student Registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'teacher' not in session:
        return redirect('/login')
        
    if request.method == 'POST':
        name = request.form['name']
        roll = request.form['roll']
        student_class = request.form['class']
        photo = request.files['photo']
        
        if not all([name, roll, student_class, photo]):
            return render_template('message.html', message="⚠ All fields are required!")
            
        filename = secure_filename(photo.filename)
        path = f"static/uploads/{filename}"
        photo.save(path)

        # Load image and encode
        image = face_recognition.load_image_file(path)
        encodings = face_recognition.face_encodings(image)

        if encodings:
            encoding = encodings[0]
            np.save(f'encodings/{roll}.npy', encoding)

            # Save student to database
            conn = get_db_connection()
            try:
                conn.execute("INSERT INTO students (name, roll, class, photo_path) VALUES (?, ?, ?, ?)",
                            (name, roll, student_class, path))
                conn.commit()
                conn.close()
                return render_template('message.html', message="✅ Student registered successfully!")
            except sqlite3.IntegrityError:
                conn.close()
                return render_template('message.html', message="⚠ Roll number already exists!")
        else:
            return render_template('message.html', message="⚠ No face detected. Please upload a clear face photo.")

    return render_template('register.html')

# View Students List
@app.route('/students')
def students_list():
    if 'teacher' not in session:
        return redirect('/login')
    
    conn = get_db_connection()
    students = conn.execute("SELECT * FROM students").fetchall()
    conn.close()
    
    return render_template('students_list.html', students=students)

# Edit Student - CORRECTED VERSION
@app.route('/edit-student/<int:student_id>', methods=['GET', 'POST'])
def edit_student(student_id):
    if 'teacher' not in session:
        return redirect('/login')
    
    conn = get_db_connection()
    
    if request.method == 'POST':
        name = request.form['name']
        roll = request.form['roll']
        student_class = request.form['class']
        
        # Get the original roll number to handle encoding file rename
        original_student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        original_roll = original_student['roll']
        
        # Check if a new photo was uploaded
        if 'photo' in request.files:
            photo = request.files['photo']
            if photo.filename != '':
                filename = secure_filename(photo.filename)
                path = f"static/uploads/{filename}"
                photo.save(path)
                
                # Update the database with new photo path
                conn.execute("UPDATE students SET name=?, roll=?, class=?, photo_path=? WHERE id=?",
                            (name, roll, student_class, path, student_id))
                
                # Generate new face encoding
                image = face_recognition.load_image_file(path)
                encodings = face_recognition.face_encodings(image)
                if encodings:
                    encoding = encodings[0]
                    # Save new encoding with new roll number
                    np.save(f'encodings/{roll}.npy', encoding)
                    # Remove old encoding file if roll number changed
                    if original_roll != roll and os.path.exists(f'encodings/{original_roll}.npy'):
                        os.remove(f'encodings/{original_roll}.npy')
                conn.commit()
                conn.close()
                return render_template('message.html', message="✅ Student information updated successfully!")
        
        # Update without changing the photo
        conn.execute("UPDATE students SET name=?, roll=?, class=? WHERE id=?",
                    (name, roll, student_class, student_id))
        
        # Handle encoding file if roll number changed
        if original_roll != roll:
            if os.path.exists(f'encodings/{original_roll}.npy'):
                os.rename(f'encodings/{original_roll}.npy', f'encodings/{roll}.npy')
        
        conn.commit()
        conn.close()
        return render_template('message.html', message="✅ Student information updated successfully!")
    
    # GET request - show the edit form
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    conn.close()
    
    if student:
        return render_template('edit_student.html', student=student)
    else:
        return render_template('message.html', message="❌ Student not found")

# Delete Student
@app.route('/delete-student/<int:student_id>')
def delete_student(student_id):
    if 'teacher' not in session:
        return redirect('/login')
    
    conn = get_db_connection()
    
    # Get student info before deleting
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    
    if student:
        # Delete the student
        conn.execute("DELETE FROM students WHERE id=?", (student_id,))
        
        # Delete the face encoding file if it exists
        try:
            os.remove(f'encodings/{student["roll"]}.npy')
        except:
            pass
        
        conn.commit()
        conn.close()
        return render_template('message.html', message="✅ Student deleted successfully!")
    else:
        conn.close()
        return render_template('message.html', message="❌ Student not found")

# View Attendance Records
@app.route('/view-attendance')
def view_attendance():
    if 'teacher' not in session:
        return redirect('/login')

    conn = get_db_connection()
    records = conn.execute("SELECT roll, name, class, date, time, teacher, status FROM attendance ORDER BY date DESC, time DESC").fetchall()
    conn.close()
    
    return render_template('view_attendance.html', records=records)

# Download Attendance as Excel
@app.route('/download-excel')
def download_excel():
    if 'teacher' not in session:
        return redirect('/login')
        
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT roll, name, class, date, time, teacher, status FROM attendance", conn)
    conn.close()
    
    path = "static/attendance.xlsx"
    df.to_excel(path, index=False)
    return send_file(path, as_attachment=True)

# Logout
@app.route('/logout')
def logout():
    session.pop('teacher', None)
    return redirect('/login')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)