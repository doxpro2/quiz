from flask import Flask, render_template, request, redirect, url_for, session, flash, g
import sqlite3
import hashlib
def generate_quiz_version(questions):
    combined = ''.join([
        q['question'] + q['option1'] + q['option2'] + q['option3'] + q['option4'] + str(q['correct_option'])
        for q in questions
    ])
    return hashlib.sha256(combined.encode()).hexdigest()

app = Flask(__name__)
app.secret_key = 'secret'

DATABASE = 'quiz.db'



# -------------------- DB Setup --------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            option1 TEXT,
            option2 TEXT,
            option3 TEXT,
            option4 TEXT,
            correct_option INTEGER NOT NULL,
            quiz_version INTEGER DEFAULT 1
        )
    ''')

    # Create scores table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            quiz_version TEXT DEFAULT '',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Try adding quiz_version if it doesn't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE scores ADD COLUMN quiz_version TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        # This means the column already exists — ignore
        pass

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY,
    quiz_duration INTEGER DEFAULT 5
);
''')
# Insert default if none exists
    cursor.execute('INSERT OR IGNORE INTO settings (id, quiz_duration) VALUES (1, 5)')

    
    # Add quiz_version column to questions if not exists
    cursor.execute("PRAGMA table_info(questions)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'quiz_version' not in columns:
        cursor.execute("ALTER TABLE questions ADD COLUMN quiz_version INTEGER DEFAULT 1")

    # Add quiz_version column to scores if not exists
    cursor.execute("PRAGMA table_info(scores)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'quiz_version' not in columns:
        cursor.execute("ALTER TABLE scores ADD COLUMN quiz_version INTEGER DEFAULT 1")



    conn.commit()
    conn.close()

    

# -------------------- Routes --------------------


@app.route('/')
def index():
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        role = request.form['role']

        conn = get_db()
        try:
            conn.execute('INSERT INTO users (username, role) VALUES (?, ?)', (username, role))
            conn.commit()
            flash("Registration successful. Please login.")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Username already exists. Please choose another.")
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session and 'role' in session:
        return redirect(url_for(f"{session['role']}_dashboard"))

    role = request.args.get('role', '')

    if request.method == 'POST':
        username = request.form['username']
        role = request.form['role']

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND role = ?', (username, role)).fetchone()

        if user:
            session['username'] = username
            session['role'] = role
            return redirect(url_for(f"{role}_dashboard"))
        else:
            flash("Invalid login. Please register first.")
            return redirect(url_for('register'))

    return render_template('login.html', role=role)

@app.route('/delete_question/<int:question_id>', methods=['POST'])
def delete_question(question_id):
    if 'role' in session and session['role'] == 'teacher':
        conn = get_db()
        conn.execute('DELETE FROM questions WHERE id = ?', (question_id,))
        conn.commit()
    return redirect(url_for('teacher_dashboard'))

@app.route('/teacher', methods=['GET', 'POST'])
def teacher_dashboard():
    if 'role' not in session or session['role'] != 'teacher':
        return redirect(url_for('login'))

    conn = get_db()

    # Get the latest version
    current_version = conn.execute('SELECT MAX(quiz_version) FROM questions').fetchone()[0] or 1

    if request.method == 'POST':
        if 'delete_id' in request.form:
            qid = request.form['delete_id']
            conn.execute('DELETE FROM questions WHERE id = ?', (qid,))
            conn.commit()

        elif 'edit_id' in request.form:
            # Update question
            qid = request.form['edit_id']
            question = request.form['question']
            options = [request.form[f'option{i}'] for i in range(1, 5)]
            correct = int(request.form['correct_option'])
            conn.execute('''
                UPDATE questions 
                SET question = ?, option1 = ?, option2 = ?, option3 = ?, option4 = ?, correct_option = ?
                WHERE id = ?
            ''', (question, *options, correct, qid))
            conn.commit()
        else:
            # Add new question and increment quiz version
            new_version = (current_version or 1) + 1
            question = request.form['question']
            options = [request.form[f'option{i}'] for i in range(1, 5)]
            correct = int(request.form['correct_option'])
            conn.execute('''
                INSERT INTO questions (question, option1, option2, option3, option4, correct_option, quiz_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (question, *options, correct, new_version))
            conn.commit()

    questions = conn.execute('SELECT * FROM questions').fetchall()
    return render_template('teacher_dashboard.html', questions=questions)

@app.route('/teacher/results')
def view_results():
    if 'role' not in session or session['role'] != 'teacher':
        flash("Access denied.")
        return redirect(url_for('login'))

    conn = get_db()
    results = conn.execute('SELECT * FROM scores ORDER BY timestamp DESC').fetchall()
    return render_template('view_results.html', results=results)

@app.route('/update_settings', methods=['POST'])
def update_settings():
    if session.get('role') == 'teacher':
        duration = request.form.get('quiz_duration')
        conn = get_db()
        conn.execute("UPDATE settings SET quiz_duration = ? WHERE id = 1", (duration,))
        conn.commit()
    return redirect(url_for('teacher_dashboard'))



@app.route('/student', methods=['GET', 'POST'])
def student_dashboard():
    if 'username' not in session or session['role'] != 'student':
        return redirect(url_for('login'))

    conn = get_db()
    username = session['username']

    quiz_version = conn.execute('SELECT MAX(quiz_version) FROM questions').fetchone()[0] or 1
    questions = conn.execute('SELECT * FROM questions WHERE quiz_version = ?', (quiz_version,)).fetchall()
    duration_row = conn.execute("SELECT quiz_duration FROM settings WHERE id = 1").fetchone()
    duration = duration_row['quiz_duration'] if duration_row else 5

    already_attempted = conn.execute(
    'SELECT 1 FROM scores WHERE username = ?', 
    (username,)
).fetchone()


    if already_attempted:
        flash("You have already attempted the current quiz.")
        return render_template('student_dashboard.html', questions=[], attempted=True)

    if request.method == 'POST':
        submitted_answers = []
        for i, q in enumerate(questions, start=1):
            selected = request.form.get(f'selected_option_{i}')
            correct = str(q['correct_option'])

            submitted_answers.append({
                "question": q["question"],
                "options": [q["option1"], q["option2"], q["option3"], q["option4"]],
                "selected": selected,
                "correct": correct
            })

        score = sum(1 for a in submitted_answers if a['selected'] == a['correct'])

        conn.execute(
            "INSERT INTO scores (username, score, total, quiz_version) VALUES (?, ?, ?, ?)",
            (username, score, len(questions), quiz_version)
        )
        conn.commit()

        flash("Quiz submitted successfully.")
        return redirect(url_for('student_dashboard'))

    return render_template('student_dashboard.html', questions=questions, attempted=False, duration=duration)


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('login'))

# -------------------- Run App --------------------

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
