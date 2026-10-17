# A very simple Flask Hello World app for you to get started with...

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import os
from sqlalchemy import func

app = Flask(__name__)
app.secret_key = 'any_random_string_here'

# Get the exact folder where THIS file lives
basedir = os.path.abspath(os.path.dirname(__file__))

# Build the path: /home/atomichabits/mysite/habits.db
db_path = os.path.join(basedir, 'habits.db')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Habit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    position = db.Column(db.Integer, default=0)
    unit = db.Column(db.String(50), nullable=False)
    goal = db.Column(db.Integer, nullable=False)
    # Highlight-add: Column to track if a project/habit has been permanently completed
    is_permanently_completed = db.Column(db.Boolean, default=False, nullable=False)
    logs = db.relationship('HabitLog', backref='parent_habit', lazy=True, cascade="all, delete-orphan")


class HabitLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    activity_name = db.Column(db.String(100), nullable=False) # e.g., "Running" or "Book Title"
    value = db.Column(db.Integer, nullable=False)            # e.g., 350 or 30
    date_created = db.Column(db.Date, default=date.today)
    time_created = db.Column(db.String(10), default=lambda: datetime.now().strftime("%H:%M"))
    habit_id = db.Column(db.Integer, db.ForeignKey('habit.id'), nullable=False)

class AtomicHabit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    habit_type = db.Column(db.String(20)) # 'standard' or 'stack'
    action = db.Column(db.String(200), nullable=False)
    trigger_or_time = db.Column(db.String(200), nullable=False)
    order_index = db.Column(db.Integer, default=0) # <--- New Column

@app.route('/', methods=['GET', 'POST'])
def index():
    # Highlight-change: Fetch all habits sorted by position (the template filters them into tabs)
    all_habits = Habit.query.order_by(Habit.position.asc()).all()
    today = date.today()

    # Create a list of IDs for habits that have at least one log today
    completed_today_ids = [
        log.habit_id for log in HabitLog.query.filter_by(date_created=today).all()
    ]

    return render_template('index.html',
                           all_habits=all_habits,
                           completed_today_ids=completed_today_ids)


@app.route('/atomic_habits')
def atomic_habits():
    # Fetch all three types, sorted by your new order_index
    stacks = AtomicHabit.query.filter_by(habit_type='stack').order_by(AtomicHabit.order_index.asc()).all()
    standards = AtomicHabit.query.filter_by(habit_type='standard').order_by(AtomicHabit.order_index.asc()).all()
    before_habits = AtomicHabit.query.filter_by(habit_type='before').order_by(AtomicHabit.order_index.asc()).all() # New category

    all_habits = Habit.query.all()
    return render_template('atomic_habits.html',
                           stacks=stacks,
                           standards=standards,
                           before_habits=before_habits,
                           all_habits=all_habits)

@app.route('/edit_atomic/<int:id>', methods=['POST'])
def edit_atomic(id):
    habit = AtomicHabit.query.get_or_404(id)
    habit.action = request.form.get('action')
    habit.trigger_or_time = request.form.get('trigger')
    habit.order_index = int(request.form.get('order', 0)) # Save the order
    db.session.commit()
    return redirect('/atomic_habits')

@app.route('/add_atomic', methods=['POST'])
def add_atomic():
    h_type = request.form.get('habit_type')
    action = request.form.get('action')
    trigger = request.form.get('trigger')

    if action and trigger:
        new_habit = AtomicHabit(habit_type=h_type, action=action, trigger_or_time=trigger)
        db.session.add(new_habit)
        db.session.commit()
    return redirect('/atomic_habits')

@app.route('/delete_atomic/<int:id>')
def delete_atomic(id):
    habit = AtomicHabit.query.get_or_404(id)
    db.session.delete(habit)
    db.session.commit()
    return redirect('/atomic_habits')

@app.route('/delete_habit/<int:habit_id>')
def delete_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    db.session.delete(habit)
    db.session.commit()
    return redirect('/')

# this is to edit the historical logs date in each habit tracker
@app.route('/edit_habit_log/<int:log_id>', methods=['GET', 'POST'])
def edit_habit_log(log_id):
    log = HabitLog.query.get_or_404(log_id)

    if request.method == 'POST':
        new_date_str = request.form.get('date')
        new_value = request.form.get('value')
        new_activity = request.form.get('activity_name')

        if new_date_str:
            # Convert the string from the HTML date input back into a Python date object
            log.date_created = datetime.strptime(new_date_str, '%Y-%m-%d').date()

        log.value = int(new_value)
        log.activity_name = new_activity

        log.time_created = request.form.get('time') # Add this line
        db.session.commit()
        return redirect(url_for('track_habit', habit_name=log.parent_habit.name))
    return render_template('edit_habit_log.html', log=log)


@app.route('/create_habit', methods=['POST'])
def create_habit():
    name = request.form.get('name')
    unit = request.form.get('unit')
    goal = request.form.get('goal')
    if name and unit and goal:
        # Check if habit already exists to avoid errors
        existing = Habit.query.filter_by(name=name).first()
        if not existing:
            new_habit = Habit(name=name, unit=unit, goal=int(goal))
            db.session.add(new_habit)
            db.session.commit()
    return redirect('/')

@app.route('/edit_habit/<int:habit_id>', methods=['GET', 'POST'])
def edit_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    all_habits = Habit.query.all() # For the nav bar

    if request.method == 'POST':
        new_name = request.form.get('name')
        new_goal = request.form.get('goal')
        new_unit = request.form.get('unit')

        if new_name:
            habit.name = new_name.strip()
            habit.goal = int(new_goal)
            habit.unit = new_unit
            db.session.commit()
            flash(f'Tracker updated to "{new_name}"!', 'success')
            return redirect('/')

    return render_template('edit_habit.html', habit=habit, all_habits=all_habits)

@app.route('/habit/<string:habit_name>', methods=['GET', 'POST'])
def track_habit(habit_name):
    habit = Habit.query.filter_by(name=habit_name).first()
    if not habit:
        # If someone clicks an old link with an old name, just send them home
        return redirect('/')
    today = date.today()

    if request.method == 'POST':
        activity = request.form.get('activity')
        val = request.form.get('value')

        if activity and val:
            new_log = HabitLog(activity_name=activity, value=int(val), habit_id=habit.id)
            db.session.add(new_log)
            db.session.commit()

            # CHANGE THIS LINE: Use a direct f-string instead of url_for
            return redirect(f'/habit/{habit_name}')

    # Fetch logs for today
    today_logs = HabitLog.query.filter_by(habit_id=habit.id, date_created=today).all()
    total_today = sum(log.value for log in today_logs)

    # Group logs by date for Chart
    all_logs = HabitLog.query.filter_by(habit_id=habit.id).order_by(HabitLog.date_created.asc()).all()
    chart_dict = {}
    for log in all_logs:
        d_str = log.date_created.strftime('%m-%d')
        chart_dict[d_str] = chart_dict.get(d_str, 0) + log.value

    return render_template('habit_tracker.html',
                           habit=habit,
                           total=total_today,
                           today_logs=today_logs,
                           all_logs=all_logs,
                           labels=list(chart_dict.keys()),
                           values=list(chart_dict.values()))

# Highlight-add: New Endpoint to trigger complete state archiving
@app.route('/complete_habit_permanently/<int:habit_id>', methods=['POST'])
def complete_habit_permanently(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    habit.is_permanently_completed = True
    db.session.commit()
    return redirect('/')

@app.route('/delete_habit_log/<int:log_id>')
def delete_habit_log(log_id):
    log = HabitLog.query.get_or_404(log_id)
    habit_name = log.parent_habit.name
    db.session.delete(log)
    db.session.commit()
    return redirect(f'/habit/{habit_name}')

@app.route('/manage_library')
def manage_library():
    all_habits = Habit.query.all()
    # We still pass all_habits for the nav bar at the top
    return render_template('manage_library.html', all_habits=all_habits)

@app.route('/update_habit_order', methods=['POST'])
def update_habit_order():
    data = request.get_json()
    new_order = data.get('order')  # This will be a list of IDs like ['5', '2', '8']

    for index, habit_id in enumerate(new_order):
        habit = Habit.query.get(habit_id)
        if habit:
            habit.position = index  # Update position based on the list index

    db.session.commit()
    return jsonify({"status": "success"}), 200


@app.route('/api/habits/today')
def habits_today():
    today = date.today()

    results = db.session.query(
        Habit.name,
        Habit.unit,
        Habit.goal,
        func.sum(HabitLog.value).label('total')
    ).join(HabitLog, HabitLog.habit_id == Habit.id
    ).filter(HabitLog.date_created == today
    ).group_by(Habit.id).all()

    grouped = {}
    for name, unit, goal, total in results:
        grouped.setdefault(unit, []).append({
            "name": name,
            "value": total,
            "goal": goal
        })

    return jsonify(grouped)

@app.route('/summary', methods=['GET'])
def summary():
    selected_date_str = request.args.get('date')

    selected_date = None
    habit_entries = []

    if selected_date_str:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()

        all_habits = Habit.query.order_by(Habit.position.asc()).all()

        for habit in all_habits:
            logs = HabitLog.query.filter_by(
                habit_id=habit.id,
                date_created=selected_date
            ).order_by(HabitLog.time_created.asc()).all()

            if logs:
                habit_entries.append({
                    "habit": habit,
                    "logs": logs,
                    "total": sum(log.value for log in logs)
                })

    return render_template('summary.html',
                           selected_date=selected_date,
                           habit_entries=habit_entries)

