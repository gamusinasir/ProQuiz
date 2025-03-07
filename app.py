from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
import qrcode
import os
import socket
import logging
from logging.handlers import RotatingFileHandler
import difflib  # new import
import random  # new import
from datetime import datetime, timedelta  # new import
from functools import wraps  # new import
from dotenv import load_dotenv
import hashlib

# Load environment variables
load_dotenv()

# Configure logging to capture only errors and issues
console_handler = logging.StreamHandler()
file_handler = RotatingFileHandler('app.log', maxBytes=100000, backupCount=3)

logging.basicConfig(
    level=logging.ERROR,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    handlers=[console_handler, file_handler]
)

logger = logging.getLogger(__name__)

# App Configuration
app = Flask(__name__)
app.secret_key = 'proquiz_secret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

current_question = {}

# Super Admin credentials (should be in environment variables in production)
SUPER_ADMIN_USERNAME = os.getenv('SUPER_ADMIN_USERNAME')
SUPER_ADMIN_PIN_HASH = os.getenv('SUPER_ADMIN_PIN_HASH')
SUPER_ADMIN_SALT = os.getenv('SUPER_ADMIN_SALT')

# Add this new middleware function
def require_super_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_super_admin'):
            return redirect(url_for('super_admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Database Models
class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    description = db.Column(db.String(200))
    admin_name = db.Column(db.String(50))
    status = db.Column(db.String(20), default="not_started")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    is_archived = db.Column(db.Boolean, default=False)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'))
    text = db.Column(db.String(300))
    type = db.Column(db.String(10))  # 'mcq' or 'fill'
    options = db.Column(db.String(500))  # Stored as "A,B,C,D"
    correct_answer = db.Column(db.String(100))

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'))
    score = db.Column(db.Integer, default=0)
    response_time = db.Column(db.Float, default=0)

class PlayerAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    answer = db.Column(db.String(500))
    is_correct = db.Column(db.Boolean, default=False)  # New field

# Add new model for tracking player progress
class PlayerProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'))
    current_question_index = db.Column(db.Integer, default=0)
    questions_order = db.Column(db.String(500))  # Store question IDs as comma-separated string
    completed = db.Column(db.Boolean, default=False)
    completion_time = db.Column(db.DateTime)

# Utility Functions
def generate_qr(quiz_id):
    try:
        # Get the local IP address
        local_ip = get_local_ip()
        
        # Create the full join URL with http:// prefix and correct port
        join_url = f"http://{local_ip}:5000/join/{quiz_id}"
        
        # Create QR with consistent format
        qr = qrcode.QRCode(
            version=1,
            box_size=10,
            border=5,
            error_correction=qrcode.constants.ERROR_CORRECT_L
        )
        qr.add_data(join_url)
        qr.make(fit=True)
        
        # Generate QR code image
        img = qr.make_image(fill='black', back_color='white')
        
        # Ensure directory exists
        os.makedirs('static/qrcodes', exist_ok=True)
        
        # Save the QR code
        img.save(f'static/qrcodes/quiz_{quiz_id}.png')
        
        # Generate new QR code whenever a quiz is re-offered
        os.utime(f'static/qrcodes/quiz_{quiz_id}.png')
        
        logger.info(f"QR code generated for quiz {quiz_id} with URL: {join_url}")
        
    except Exception as e:
        logger.error(f"Failed to generate QR code for quiz {quiz_id}: {str(e)}")
        
    return join_url  # Return the URL so it can be used to verify match

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to an external server (doesn't actually send any packets)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        logger.info(f"Local IP address retrieved: {ip}")
        return ip
    except Exception as e:
        logger.error(f"Failed to get local IP: {str(e)}")
        return '127.0.0.1'
    finally:
        s.close()

def get_rankings(quiz_id):
    try:
        quiz = db.session.get(Quiz, quiz_id)
        admin_name = quiz.admin_name
        players = Player.query.filter_by(quiz_id=quiz_id).all()
        rankings = []
        
        for p in players:
            # Skip the admin in current quiz rankings
            if p.username == admin_name:
                continue
                
            score = p.score
            # Handle string scores with time bonus
            if isinstance(score, str) and "+1⚡" in score:
                base_score = int(score.replace("+1⚡", ""))
                rankings.append({
                    "username": p.username,
                    "score": score,
                    "total": base_score + 1
                })
            else:
                rankings.append({
                    "username": p.username,
                    "score": score,
                    "total": int(score) if isinstance(score, int) else 0
                })
        
        rankings.sort(key=lambda x: x["total"], reverse=True)
        return rankings
    except Exception as e:
        logger.error(f"Failed to get rankings for quiz {quiz_id}: {str(e)}")
        return []

def get_overall_rankings():
    try:
        all_quizzes = Quiz.query.all()
        overall_stats = {}
        
        for quiz in all_quizzes:
            players = Player.query.filter_by(quiz_id=quiz.id).all()
            total_questions = Question.query.filter_by(quiz_id=quiz.id).count()
            
            # Initialize admin's score if not present
            if quiz.admin_name not in overall_stats:
                overall_stats[quiz.admin_name] = {
                    "quiz_score": 0,
                    "quizzes_participated": 0,
                    "time_bonuses": 0
                }
            
            # Add admin's perfect score for their quiz plus time bonus
            overall_stats[quiz.admin_name]["quiz_score"] += total_questions
            overall_stats[quiz.admin_name]["time_bonuses"] += 1  # Admin always gets time bonus for their quiz
            overall_stats[quiz.admin_name]["quizzes_participated"] += 1
            
            for player in players:
                # Skip adding admin's actual score for their own quiz
                if player.username == quiz.admin_name:
                    continue
                    
                if player.username not in overall_stats:
                    overall_stats[player.username] = {
                        "quiz_score": 0,
                        "quizzes_participated": 0,
                        "time_bonuses": 0
                    }
                
                overall_stats[player.username]["quizzes_participated"] += 1
                score = player.score
                
                if isinstance(score, str) and "+1⚡" in score:
                    base_score = int(score.replace("+1⚡", ""))
                    overall_stats[player.username]["quiz_score"] += base_score
                    overall_stats[player.username]["time_bonuses"] += 1
                else:
                    overall_stats[player.username]["quiz_score"] += int(score) if isinstance(score, int) else 0

        # Convert to sorted list with total points
        rankings = [
            {
                "username": username,
                "quiz_score": stats["quiz_score"],
                "quizzes": stats["quizzes_participated"],
                "bonuses": stats["time_bonuses"],
                "total_points": stats["quiz_score"] + stats["time_bonuses"]
            }
            for username, stats in overall_stats.items()
        ]
        
        return sorted(
            rankings, 
            key=lambda x: (x["total_points"], x["quizzes"], x["bonuses"]), 
            reverse=True
        )
    except Exception as e:
        logger.error(f"Failed to get overall rankings: {str(e)}") 
        return []
    
    
def get_player_answer(question_id):
    try:
        player_id = session.get('player_id')
        if (player_id):
            player_answer = PlayerAnswer.query.filter_by(player_id=player_id, question_id=question_id).first()
            return player_answer.answer if player_answer else None
        return None
    except Exception as e:
        logger.error(f"Failed to get player answer for question {question_id}: {str(e)}")
        return None

# Make the function available in the template context
app.jinja_env.globals.update(get_player_answer=get_player_answer)

# Route Handlers
@app.route('/')
def home():
    logger.info("Home page accessed")
    # Don't show archived quizzes on admin page
    quiz = Quiz.query.filter_by(is_archived=False).first()  # Get the first non-archived quiz
    if quiz:
        return redirect(url_for('admin', quiz_id=quiz.id, welcome_message="Welcome to ProQuiz Admin Page"))
    else:
        return render_template('admin.html', quiz=None, players=[], local_ip=get_local_ip(), overall_rankings=[], welcome_message="Welcome to ProQuiz Admin Page - No Quiz Created Yet")

@app.route('/upload', methods=['POST'])
def upload():
    try:
        file = request.files['excel']
        logger.info(f"Processing upload of file: {file.filename}")
        
        df = pd.read_excel(file)
        df = df.dropna(subset=['Question'])
        required_columns = ['Quiz Title', 'Description', 'Quiz Administrator', 'Question', 'Type', 'Correct Answer']
        
        if (not all(col in df.columns for col in required_columns)):
            logger.error("Missing required columns in uploaded file")
            return jsonify({"error": "Excel file is missing required columns!"}), 400

        first_row = df.iloc[0]
        quiz = Quiz(
            title=first_row['Quiz Title'],
            description=first_row['Description'],
            admin_name=first_row['Quiz Administrator']
        )
        db.session.add(quiz)
        db.session.commit()
        
        questions_imported = 0  # Counter for imported questions
        
        for _, row in df.iterrows():
            q_type = str(row['Type']).strip().lower()
            if (q_type not in ['mcq', 'fill']):
                continue
            
            options = None
            if (q_type == 'mcq'):
                options = [row.get('Option A'), row.get('Option B'), row.get('Option C'), row.get('Option D')]
                options = [str(opt) for opt in options if pd.notna(opt)]
            
            question = Question(
                quiz_id=quiz.id,
                text=row['Question'],
                type=q_type,
                options=','.join(options) if options else None,
                correct_answer=str(row['Correct Answer'])
            )
            db.session.add(question)
            questions_imported += 1
        
        db.session.commit()
        generate_qr(quiz_id=quiz.id)
        logger.info(f"Successfully created quiz {quiz.id} with {questions_imported} questions")
        
        return jsonify({
            "status": "success",
            "message": f"Quiz uploaded successfully! {questions_imported} questions imported.",
            "quiz_id": quiz.id,
            "questions_imported": questions_imported,
            "redirect_url": url_for('admin', quiz_id=quiz.id)
        }), 200
        
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        return jsonify({"error": "Upload failed!", "details": str(e)}), 500

@app.route('/join/<int:quiz_id>', methods=['GET', 'POST'])
def join(quiz_id):
    quiz = db.session.get(Quiz, quiz_id)
    
    # Check if quiz exists
    if not quiz:
        return render_template('join.html', error_message="Quiz not found")
    
    # Check if quiz has ended before allowing join
    if quiz.status == "ended":
        if request.method == 'POST':
            return jsonify({
                "status": "ended",
                "message": "This quiz has already ended. You cannot join it anymore."
            }), 403
        return render_template('join.html', quiz_id=quiz_id, error_message="This quiz has already ended.")
    
    if quiz.status == "not_started" or quiz.status == "started":
        if request.method == 'POST':
            try:
                username = request.form.get('username')
                if not username:
                    return jsonify({
                        "status": "error",
                        "message": "Username is required!"
                    }), 400
                    
                if Player.query.filter_by(username=username, quiz_id=quiz_id).first():
                    return jsonify({
                        "status": "error",
                        "message": "Username already taken!"
                    }), 400
                
                # Create new player
                player = Player(username=username, quiz_id=quiz_id)
                db.session.add(player)
                db.session.flush()  # Get player.id before committing
                
                # Initialize player progress
                questions = Question.query.filter_by(quiz_id=quiz_id).all()
                question_ids = [str(q.id) for q in questions]
                random.shuffle(question_ids)  # Randomize question order for each player
                
                progress = PlayerProgress(
                    player_id=player.id,
                    quiz_id=quiz_id,
                    questions_order=','.join(question_ids)
                )
                db.session.add(progress)
                db.session.commit()
                
                # Store player_id in session
                session['player_id'] = player.id
                
                # Redirect to the correct player page URL
                return jsonify({
                    "status": "success",
                    "redirect_url": f"/player/{quiz_id}/{player.id}"  # Changed to use direct URL
                })
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error during join: {str(e)}")
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500
        return render_template('join.html', quiz_id=quiz_id)

@app.route("/start_quiz/<int:quiz_id>")
def start_quiz(quiz_id):
    quiz = db.session.get(Quiz, quiz_id)
    quiz.status = "started"  # Mark quiz as started
    db.session.commit()
    current_question[quiz_id] = 0  # Reset question index
    return redirect(url_for("admin", quiz_id=quiz_id))

@app.route("/stop_quiz/<int:quiz_id>")
def stop_quiz(quiz_id):
    quiz = db.session.get(Quiz, quiz_id)
    quiz.status = "ended"
    db.session.commit()
    # Reset question counter if needed
    current_question[quiz_id] = 0
    return redirect(url_for("admin", quiz_id=quiz_id))

@app.route("/get_question/<int:quiz_id>")
def get_question(quiz_id):
    quiz = db.session.get(Quiz, quiz_id)
    
    if not quiz:
        return jsonify({"error": "Quiz not found"}), 404
    
    if quiz.status == "not_started":
        return jsonify({"status": "not_started"})
    
    if quiz.status == "ended":
        return jsonify({"status": "ended", "redirect_url": url_for('show_results', quiz_id=quiz_id)})
    
    player_id = session.get('player_id')
    if not player_id:
        return jsonify({"error": "Not logged in"}), 403
        
    player = db.session.get(Player, player_id)
    if not player or player.quiz_id != quiz_id:
        return jsonify({"error": "Invalid player"}), 403
        
    progress = PlayerProgress.query.filter_by(
        player_id=player_id,
        quiz_id=quiz_id
    ).first()
    
    if not progress:
        # Initialize progress if not exists
        questions = Question.query.filter_by(quiz_id=quiz_id).all()
        question_ids = [str(q.id) for q in questions]
        random.shuffle(question_ids)
        
        progress = PlayerProgress(
            player_id=player_id,
            quiz_id=quiz_id,
            questions_order=','.join(question_ids)
        )
        db.session.add(progress)
        db.session.commit()
    
    if progress.completed:
        return jsonify({
            "status": "finished",
            "redirect_url": url_for('show_results', quiz_id=quiz_id)
        })
    
    try:
        question_ids = progress.questions_order.split(',')
        if progress.current_question_index >= len(question_ids):
            progress.completed = True
            progress.completion_time = datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                "status": "finished",
                "redirect_url": url_for('show_results', quiz_id=quiz_id)
            })
        
        current_question_id = int(question_ids[progress.current_question_index])
        question = db.session.get(Question, current_question_id)
        
        if not question:
            return jsonify({"error": "Question not found"}), 404
        
        return jsonify({
            "status": "started",
            "question_id": question.id,
            "question": question.text,
            "type": question.type,
            "options": question.options.split(',') if question.options else None
        })
    except Exception as e:
        logger.error(f"Error serving question: {str(e)}")
        return jsonify({"error": "Failed to load question"}), 500

@app.route("/live_question/<int:quiz_id>")
def live_question(quiz_id):
    quiz = db.session.get(Quiz, quiz_id)
    if (quiz.status != "started"):
        return jsonify({"status": quiz.status})
    questions = Question.query.filter_by(quiz_id=quiz_id).all()
    current_idx = current_question.get(quiz_id, 0)
    # If no question has been served yet or index is out of range, return waiting status
    if (current_idx == 0 or current_idx > len(questions)):
        return jsonify({"status": "waiting"})
    # Show the question currently displayed to players (last served)
    question = questions[current_idx - 1]
    return jsonify({
        "status": "started",
        "question": question.text,
        "type": question.type,
        "options": question.options.split(',') if question.options else None
    })

@app.route('/quiz_status/<int:quiz_id>')
def quiz_status(quiz_id):
    try:
        quiz = db.session.get(Quiz, quiz_id)
        if not quiz:
            return jsonify({"error": "Quiz not found"}), 404
            
        # Also check if player is valid for this quiz
        player_id = session.get('player_id')
        if player_id:
            player = db.session.get(Player, player_id)
            if not player or player.quiz_id != quiz_id:
                return jsonify({"error": "Invalid player"}), 403
        
        return jsonify({"status": quiz.status})
    except Exception as e:
        logger.error(f"Error checking quiz status: {str(e)}")
        return jsonify({"error": "Failed to get quiz status"}), 500

def get_player_ranking_change(username, quiz_id):
    """Calculate player's ranking change after this quiz"""
    try:
        quiz = db.session.get(Quiz, quiz_id)
        previous_quizzes = Quiz.query.filter(Quiz.id < quiz_id).all()
        
        # Calculate previous stats (excluding current quiz)
        prev_stats = {
            "quiz_score": 0,
            "quizzes": 0,
            "bonuses": 0,
            "total_points": 0
        }
        
        for old_quiz in previous_quizzes:
            if (old_quiz.admin_name == username):
                # Add admin's perfect score for their quiz
                total_questions = Question.query.filter_by(quiz_id=old_quiz.id).count()
                prev_stats["quiz_score"] += total_questions
                prev_stats["bonuses"] += 1
                prev_stats["quizzes"] += 1
                continue
                
            player = Player.query.filter_by(quiz_id=old_quiz.id, username=username).first()
            if (player):
                prev_stats["quizzes"] += 1
                if (isinstance(player.score, str) and "+1⚡" in player.score):
                    base_score = int(player.score.replace("+1⚡", ""))
                    prev_stats["quiz_score"] += base_score
                    prev_stats["bonuses"] += 1
                else:
                    prev_stats["quiz_score"] += int(player.score) if isinstance(player.score, int) else 0
        
        prev_stats["total_points"] = prev_stats["quiz_score"] + prev_stats["bonuses"]
        
        # Get current quiz performance
        current_score = 0
        current_bonus = 0
        if (quiz.admin_name == username):
            current_score = Question.query.filter_by(quiz_id=quiz_id).count()
            current_bonus = 1
        else:
            player = Player.query.filter_by(quiz_id=quiz_id, username=username).first()
            if (player):
                if (isinstance(player.score, str) and "+1⚡" in player.score):
                    current_score = int(player.score.replace("+1⚡", ""))
                    current_bonus = 1
                else:
                    current_score = int(player.score) if isinstance(player.score, int) else 0
        
        return {
            "previous_total": prev_stats["total_points"],
            "points_gained": current_score + current_bonus,
            "new_total": prev_stats["total_points"] + current_score + current_bonus,
            "previous_quizzes": prev_stats["quizzes"],
            "previous_bonuses": prev_stats["bonuses"],
            "bonus_gained": current_bonus
        }
    except Exception as e:
        logger.error(f"Failed to calculate ranking change: {str(e)}")
        return None

@app.route("/results/<int:quiz_id>")
def show_results(quiz_id):
    quiz = db.session.get(Quiz, quiz_id)
    
    # Calculate rankings
    current_rankings = get_rankings(quiz_id)
    overall_rankings = get_overall_rankings()
    
    # Determine role and add extra data accordingly
    if ('player_id' in session):
        player = db.session.get(Player, session["player_id"])
        role = "player"
        player_score = player.score
        quiz_questions = Question.query.filter_by(quiz_id=quiz_id).all()
        # Get ranking change information
        ranking_change = get_player_ranking_change(player.username, quiz_id)
        admin_full_score = None
    else:
        role = "admin"
        player_score = None
        quiz_questions = Question.query.filter_by(quiz_id=quiz_id).all()
        # Compute the full total (admin) score as the current quiz's total questions
        admin_full_score = Question.query.filter_by(quiz_id=quiz_id).count()
        ranking_change = None
    
    return render_template(
        "results.html",
        quiz=quiz,
        current_rankings=current_rankings,
        overall_rankings=overall_rankings,
        role=role,
        player_score=player_score,
        quiz_questions=quiz_questions,
        admin_full_score=admin_full_score,
        ranking_change=ranking_change
    )

@app.route('/admin/<int:quiz_id>')
def admin(quiz_id):
    # Only show non-archived quizzes
    quiz = Quiz.query.filter_by(id=quiz_id, is_archived=False).first()
    if not quiz:
        return redirect(url_for('home'))
    players = Player.query.filter_by(quiz_id=quiz_id).all()
    local_ip = get_local_ip()
    overall_rankings = get_overall_rankings()
    return render_template('admin.html', quiz=quiz, players=players, local_ip=local_ip, overall_rankings=overall_rankings)

@app.route('/player/<int:quiz_id>')
def player(quiz_id):
    return render_template('player.html')

@app.route('/player/<int:quiz_id>/<int:player_id>')
def player_page(quiz_id, player_id):
    # Verify player session and existence
    if not session.get('player_id') or session['player_id'] != player_id:
        return redirect(url_for('join', quiz_id=quiz_id))
        
    player = db.session.get(Player, player_id)
    if not player or player.quiz_id != quiz_id:
        return redirect(url_for('join', quiz_id=quiz_id))
        
    quiz = db.session.get(Quiz, quiz_id)
    if not quiz:
        return "Quiz not found", 404
        
    # Initialize player progress if not exists
    progress = PlayerProgress.query.filter_by(
        player_id=player_id,
        quiz_id=quiz_id
    ).first()
    
    if not progress:
        questions = Question.query.filter_by(quiz_id=quiz_id).all()
        question_ids = [str(q.id) for q in questions]
        random.shuffle(question_ids)
        
        progress = PlayerProgress(
            player_id=player_id,
            quiz_id=quiz_id,
            questions_order=','.join(question_ids)
        )
        db.session.add(progress)
        db.session.commit()
    
    return render_template('player.html', 
                         quiz_id=quiz_id, 
                         player_id=player_id, 
                         quiz=quiz)

@app.route("/submit_answer/<int:quiz_id>", methods=["POST"])
def submit_answer(quiz_id):
    if not request.is_json:
        return jsonify({"error": "Invalid request format"}), 400

    data = request.get_json()
    question_id = data.get("question_id")
    answer = data.get("answer")
    
    if not question_id or not answer:
        return jsonify({"error": "Missing question_id or answer"}), 400

    player_id = session.get("player_id")
    if not player_id:
        return jsonify({"error": "Not logged in"}), 403

    try:
        player = db.session.get(Player, player_id)
        if not player or player.quiz_id != quiz_id:
            return jsonify({"error": "Invalid player"}), 403

        # Get player progress
        progress = PlayerProgress.query.filter_by(
            player_id=player_id,
            quiz_id=quiz_id
        ).first()

        if not progress:
            return jsonify({"error": "No progress found"}), 404

        # Get current question
        question = db.session.get(Question, question_id)
        if not question:
            return jsonify({"error": "Question not found"}), 404

        # Check if answer is correct
        is_correct = answer.lower().strip() == question.answer.lower().strip()
        
        # Update player score
        if is_correct:
            current_score = player.score if player.score else 0
            player.score = current_score + 1
            db.session.commit()

        # Move to next question
        progress.current_question_index += 1
        
        # Check if quiz is completed
        question_ids = progress.questions_order.split(',')
        if progress.current_question_index >= len(question_ids):
            progress.completed = True
            progress.completion_time = datetime.utcnow()
            
            # Check if this is the first player to finish
            first_finisher = not any(
                PlayerProgress.query.filter(
                    PlayerProgress.quiz_id == quiz_id,
                    PlayerProgress.id != progress.id,
                    PlayerProgress.completed == True
                ).all()
            )
            
            if first_finisher:
                if isinstance(player.score, str) and "+1⚡" in player.score:
                    base_score = int(player.score.replace("+1⚡", ""))
                    player.score = f"{base_score + 1}+1⚡"
                else:
                    player.score = f"{player.score}+1⚡"
            
            db.session.commit()
            
            return jsonify({
                "status": "finished",
                "redirect_url": url_for('show_results', quiz_id=quiz_id)
            })

        db.session.commit()

        return jsonify({
            "status": "success",
            "is_correct": is_correct,
            "next_question": progress.current_question_index + 1
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting answer: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/performance_data/<int:quiz_id>")
def performance_data(quiz_id):
    try:
        players = Player.query.filter_by(quiz_id=quiz_id).all()
        labels = [player.username for player in players]
        scores = [player.score for player in players]
        logger.info(f"Performance data generated for quiz {quiz_id}")
        return jsonify({"labels": labels, "scores": scores})
    except Exception as e:
        logger.error(f"Failed to get performance data for quiz {quiz_id}: {str(e)}")
        return jsonify({"error": "Failed to retrieve performance data"}), 500

# Error Handlers
#@app.errorhandler(404)
#def not_found_error(error):
    #logger.error(f"Page not found: {request.url}")
    #return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error(f"Server error: {str(error)}")
    return render_template('500.html'), 500

@app.route("/adjust_score/<int:quiz_id>/<int:player_id>", methods=["POST"])
def adjust_score(quiz_id, player_id):
    try:
        if (request.method == "POST"):
            data = request.get_json()
            points = int(data.get('points', 0))
            reason = data.get('reason', 'Manual adjustment by admin')
            
            player = db.session.get(Player, player_id)
            if (not player):
                return jsonify({"error": "Player not found"}), 404
                
            # Handle existing score with time bonus
            if (isinstance(player.score, str) and "+1⚡" in player.score):
                base_score = int(player.score.replace("+1⚡", ""))
                player.score = f"{base_score + points}+1⚡"
            else:
                current_score = int(player.score) if isinstance(player.score, int) else 0
                player.score = current_score + points
                
            db.session.commit()
            
            # Log the adjustment
            logger.info(f"Score adjusted for player {player.username} in quiz {quiz_id}: {points} points ({reason})")
            
            return jsonify({
                "status": "success",
                "new_score": player.score,
                "message": f"Score adjusted by {points} points"
            })
            
    except Exception as e:
        logger.error(f"Error adjusting score: {str(e)}")
        return jsonify({"error": "Failed to adjust score"}), 500

@app.route("/archive_quiz/<int:quiz_id>", methods=["POST"])
def archive_quiz(quiz_id):
    try:
        quiz = db.session.get(Quiz, quiz_id)
        if (not quiz):
            return jsonify({"error": "Quiz not found"}), 404
            
        quiz.is_archived = True
        quiz.ended_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Quiz archived successfully"
        })
    except Exception as e:
        logger.error(f"Failed to archive quiz {quiz_id}: {str(e)}")
        return jsonify({"error": "Failed to archive quiz"}), 500

@app.route("/archived_quizzes")
def archived_quizzes():
    quizzes = Quiz.query.filter_by(is_archived=True).order_by(Quiz.ended_at.desc()).all()
    stats = []
    
    for quiz in quizzes:
        players_count = Player.query.filter_by(quiz_id=quiz.id).count()
        questions_count = Question.query.filter_by(quiz_id=quiz.id).count()
        stats.append({
            "quiz": quiz,
            "players": players_count,
            "questions": questions_count,
            "date": quiz.ended_at.strftime("%Y-%m-%d %H:%M")
        })
    
    return render_template("archived_quizzes.html", stats=stats)

# Add these new routes
@app.route('/super-admin/login', methods=['GET', 'POST'])
def super_admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        pin = request.form.get('pin')
        
        if not username or not pin:
            return render_template('super_admin_login.html', error="Both username and PIN are required")
            
        # Hash the provided PIN with stored salt
        hashed_pin = hashlib.sha256((pin + SUPER_ADMIN_SALT).encode()).hexdigest()
        
        if username == SUPER_ADMIN_USERNAME and hashed_pin == SUPER_ADMIN_PIN_HASH:
            session['is_super_admin'] = True
            return redirect(url_for('super_admin_dashboard'))
            
        return render_template('super_admin_login.html', error="Invalid credentials")
            
    return render_template('super_admin_login.html')

@app.route('/super-admin/logout')
def super_admin_logout():
    session.pop('is_super_admin', None)
    return redirect(url_for('super_admin_login'))

@app.route('/super-admin/dashboard')
@require_super_admin
def super_admin_dashboard():
    # Get both active and archived quizzes
    all_quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
    quiz_data = {}
    
    for quiz in all_quizzes:
        admin = quiz.admin_name
        if (admin not in quiz_data):
            quiz_data[admin] = {
                "active": [],
                "archived": []
            }
        
        players_count = Player.query.filter_by(quiz_id=quiz.id).count()
        questions_count = Question.query.filter_by(quiz_id=quiz.id).count()
        total_answers = PlayerAnswer.query.join(Player).filter(Player.quiz_id == quiz.id).count()
        completed_players = PlayerProgress.query.filter_by(quiz_id=quiz.id, completed=True).count()
        
        quiz_info = {
            "quiz": quiz,
            "players": players_count,
            "questions": questions_count,
            "answers": total_answers,
            "completed": completed_players,
            "date": quiz.ended_at.strftime("%Y-%m-%d %H:%M") if quiz.ended_at else "Active",
            "status": quiz.status
        }
        
        if (quiz.is_archived):
            quiz_data[admin]["archived"].append(quiz_info)
        else:
            quiz_data[admin]["active"].append(quiz_info)
    
    return render_template('super_admin_dashboard.html', quiz_data=quiz_data)

@app.route("/super-admin/delete-quiz/<int:quiz_id>", methods=["POST"])
@require_super_admin
def delete_quiz(quiz_id):
    try:
        quiz = db.session.get(Quiz, quiz_id)
        if (not quiz):
            return jsonify({"error": "Quiz not found"}), 404
            
        # Delete all related records first
        PlayerAnswer.query.filter(
            PlayerAnswer.player_id.in_(
                db.session.query(Player.id).filter_by(quiz_id=quiz_id)
            )
        ).delete(synchronize_session=False)
        
        PlayerProgress.query.filter(
            PlayerProgress.player_id.in_(
                db.session.query(Player.id).filter_by(quiz_id=quiz_id)
            )
        ).delete(synchronize_session=False)
        
        Player.query.filter_by(quiz_id=quiz_id).delete()
        Question.query.filter_by(quiz_id=quiz_id).delete()
        
        # Store quiz info for response
        was_archived = quiz.is_archived
        
        db.session.delete(quiz)
        db.session.commit()
        
        # Delete QR code if exists
        qr_path = f'static/qrcodes/quiz_{quiz_id}.png'
        if (os.path.exists(qr_path)):
            os.remove(qr_path)
        
        return jsonify({
            "status": "success",
            "message": "Quiz and all related data deleted successfully",
            "was_archived": was_archived
        })
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete quiz {quiz_id}: {str(e)}")
        return jsonify({"error": "Failed to delete quiz"}), 500

@app.route("/super-admin/quiz/<int:quiz_id>/delete", methods=["POST"])  # Add this new route
@require_super_admin
def delete_quiz_new(quiz_id):
    return delete_quiz(quiz_id)  # Reuse the existing function

@app.route("/super-admin/re-offer-quiz/<int:quiz_id>", methods=["POST"])
@require_super_admin
def re_offer_quiz(quiz_id):
    try:
        quiz = db.session.get(Quiz, quiz_id)
        if (not quiz):
            return jsonify({"error": "Quiz not found"}), 404

        # Delete only player progress data for this quiz
        PlayerAnswer.query.filter(
            PlayerAnswer.player_id.in_(
                db.session.query(Player.id).filter_by(quiz_id=quiz_id)
            )
        ).delete(synchronize_session=False)
        
        PlayerProgress.query.filter(
            PlayerProgress.player_id.in_(
                db.session.query(Player.id).filter_by(quiz_id=quiz_id)
            )
        ).delete(synchronize_session=False)
        
        # Reset quiz status
        quiz.status = "not_started"
        quiz.is_archived = False
        quiz.ended_at = None
        
        db.session.commit()
        
        # Generate new QR code
        generate_qr(quiz_id)
        
        return jsonify({
            "status": "success",
            "message": "Quiz has been reset and is ready to be offered again"
        })
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to re-offer quiz {quiz_id}: {str(e)}")
        return jsonify({"error": "Failed to re-offer quiz"}), 500

@app.route("/super-admin/quiz/<int:quiz_id>/reoffer", methods=["POST"])  # Add this new route
@require_super_admin
def re_offer_quiz_new(quiz_id):
    return re_offer_quiz(quiz_id)  # Reuse the existing function

@app.route("/super-admin/reset-rankings", methods=["POST"])
@require_super_admin
def reset_all_rankings():
    try:
        # Reset all player scores and progress
        db.session.query(Player).update({Player.score: 0})
        db.session.query(PlayerProgress).update({
            PlayerProgress.completed: False,
            PlayerProgress.current_question_index: 0,
            PlayerProgress.completion_time: None
        })
        db.session.commit()
        return jsonify({"status": "success", "message": "All rankings have been reset"})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reset rankings: {str(e)}")
        return jsonify({"error": "Failed to reset rankings"}), 500

@app.route("/super-admin/reset-quiz/<int:quiz_id>", methods=["POST"])
@require_super_admin
def reset_quiz_session(quiz_id):
    try:
        quiz = db.session.get(Quiz, quiz_id)
        if (not quiz):
            return jsonify({"error": "Quiz not found"}), 404

        # Reset quiz status
        quiz.status = "not_started"
        quiz.ended_at = None
        
        # Reset all players' scores and progress for this quiz
        Player.query.filter_by(quiz_id=quiz_id).update({Player.score: 0})
        PlayerProgress.query.filter_by(quiz_id=quiz_id).update({
            PlayerProgress.completed: False,
            PlayerProgress.current_question_index: 0,
            PlayerProgress.completion_time: None
        })
        
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": "Quiz session has been reset"
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reset quiz session {quiz_id}: {str(e)}")
        return jsonify({"error": "Failed to reset quiz session"}), 500

@app.route("/super-admin/get-players/<int:quiz_id>")
@require_super_admin
def get_players(quiz_id):
    try:
        players = Player.query.filter_by(quiz_id=quiz_id).all()
        return jsonify([{
            'id': player.id,
            'username': player.username,
            'score': player.score
        } for player in players])
    except Exception as e:
        logger.error(f"Failed to get players for quiz {quiz_id}: {str(e)}")
        return jsonify({"error": "Failed to get players"}), 500

@app.route("/super-admin/edit-player/<int:player_id>", methods=["POST"])
@require_super_admin
def edit_player(player_id):
    try:
        data = request.get_json()
        new_username = data.get('username')
        
        if not new_username:
            return jsonify({"error": "Username cannot be empty"}), 400
            
        player = db.session.get(Player, player_id)
        if not player:
            return jsonify({"error": "Player not found"}), 404
            
        # Check if username is already taken in the same quiz
        existing_player = Player.query.filter_by(
            quiz_id=player.quiz_id,
            username=new_username
        ).first()
        
        if existing_player and existing_player.id != player_id:
            return jsonify({"error": "Username already taken"}), 400
            
        player.username = new_username
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Player name updated successfully",
            "quiz_id": player.quiz_id
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to edit player {player_id}: {str(e)}")
        return jsonify({"error": "Failed to update player name"}), 500

@app.route("/super-admin/delete-player/<int:player_id>", methods=["POST"])
@require_super_admin
def delete_player(player_id):
    try:
        player = db.session.get(Player, player_id)
        if not player:
            return jsonify({"error": "Player not found"}), 404
            
        # Delete related records
        PlayerAnswer.query.filter_by(player_id=player_id).delete()
        PlayerProgress.query.filter_by(player_id=player_id).delete()
        db.session.delete(player)
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Player deleted successfully"
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete player {player_id}: {str(e)}")
        return jsonify({"error": "Failed to delete player"}), 500

@app.route('/super-admin/players')
@require_super_admin
def super_admin_players():
    # Get all quizzes with their players
    quizzes = Quiz.query.all()
    quiz_data = []
    
    for quiz in quizzes:
        players = Player.query.filter_by(quiz_id=quiz.id).all()
        player_data = []
        total_questions = Question.query.filter_by(quiz_id=quiz.id).count()
        
        for player in players:
            progress = PlayerProgress.query.filter_by(
                player_id=player.id,
                quiz_id=quiz.id
            ).first()
            
            player_data.append({
                'id': player.id,
                'username': player.username,
                'score': player.score,
                'progress': progress
            })
        
        quiz_data.append({
            'id': quiz.id,
            'title': quiz.title,
            'admin_name': quiz.admin_name,
            'players': player_data,
            'total_questions': total_questions
        })
    
    return render_template('super_admin_players.html', quizzes=quiz_data)

@app.route('/super-admin/players/<int:player_id>/edit', methods=['POST'])
@require_super_admin
def super_admin_edit_player(player_id):
    try:
        data = request.get_json()
        new_username = data.get('username')
        
        if not new_username:
            return jsonify({'error': 'Username cannot be empty'}), 400
        
        player = Player.query.get_or_404(player_id)
        
        # Check if username is taken in the same quiz
        existing = Player.query.filter_by(
            quiz_id=player.quiz_id,
            username=new_username
        ).first()
        
        if existing and existing.id != player_id:
            return jsonify({'error': 'Username already taken in this quiz'}), 400
        
        player.username = new_username
        db.session.commit()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/super-admin/players/<int:player_id>/delete', methods=['POST'])
@require_super_admin
def super_admin_delete_player(player_id):
    try:
        player = Player.query.get_or_404(player_id)
        
        # Delete all related records
        PlayerAnswer.query.filter_by(player_id=player_id).delete()
        PlayerProgress.query.filter_by(player_id=player_id).delete()
        db.session.delete(player)
        db.session.commit()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return 'Server shutting down...'

# Application Startup
if (not os.path.exists('static/qrcodes')):
    os.makedirs('static/qrcodes')
    
if __name__ == '__main__':
    # Configure logging to output to the console
    logging.basicConfig(level=logging.ERROR, format='%(asctime)s %(levelname)s in %(module)s: %(message)s')
    
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {str(e)}")
    
    logger.info("Starting Flask app")
    app.run(host='0.0.0.0', debug=True)