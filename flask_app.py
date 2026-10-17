from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from datetime import datetime, date, timedelta
from collections import defaultdict
import os
import re

app = Flask(__name__)
app.secret_key = 'any_random_string_here'

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'habits.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
CATEGORIES = [('activity', 'Activities'), ('book', 'Books'), ('course', 'Courses')]
TAB_TO_CATEGORY = {'activities': 'activity', 'books': 'book', 'courses': 'course'}
CATEGORY_TO_TAB = {v: k for k, v in TAB_TO_CATEGORY.items()}
CATEGORY_LABEL = dict(CATEGORIES)

DEFAULT_COLORS = {'activity': '#3FB950', 'book': '#4C8DFF', 'course': '#F5A524'}
DELAY_COLOR = '#EF4444'          # wake-up / bedtime delay habits are red by default
SWATCHES = ['#3FB950', '#14B8A6', '#4C8DFF', '#8B5CF6', '#EC4899', '#F5A524', '#F97316', '#EF4444']

# Used once, to sort the habits you already have into the three tabs.
# You can change any of them later in Manage Library or the habit's settings.
COURSE_NAMES = {
    'c++', 'c', 'go', 'csharp', 'java', 'python', 'sql', 'rust', 'dart', 'swift', 'javascript',
    'lua', 'ruby', 'r', 'kotlin', 'terminal', 'aws', 'kubernetes', 'microeconomics',
    'dsa freecodecamp', 'java kata', 'python kata', 'claude 101', 'ai fluency',
    'mastering dsa in java',
}


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class Habit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    position = db.Column(db.Integer, default=0)
    unit = db.Column(db.String(50), nullable=False)
    goal = db.Column(db.Float, nullable=False)
    is_permanently_completed = db.Column(db.Boolean, default=False, nullable=False)

    # --- new in the redesign ---
    category = db.Column(db.String(12))                          # activity | book | course
    metric = db.Column(db.String(8), default='sum')              # sum | delay
    ref_time = db.Column(db.String(5), default='05:00')          # reference time for delay habits
    color = db.Column(db.String(9))                              # None -> category / delay default
    scale_mode = db.Column(db.String(10), default='gradient')    # gradient | levels
    target = db.Column(db.Float)                                 # value that reaches full colour (None = auto)
    levels = db.Column(db.String(120))                           # "5,15,30,60" (None = auto)

    logs = db.relationship('HabitLog', backref='parent_habit', lazy=True, cascade="all, delete-orphan")

    @property
    def is_delay(self):
        return self.metric == 'delay'

    @property
    def display_color(self):
        if self.color:
            return self.color
        return DELAY_COLOR if self.is_delay else DEFAULT_COLORS.get(self.category, DEFAULT_COLORS['activity'])


class HabitLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    activity_name = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Float, nullable=False)
    date_created = db.Column(db.Date, default=date.today)
    time_created = db.Column(db.String(10), default=lambda: datetime.now().strftime("%H:%M"))
    habit_id = db.Column(db.Integer, db.ForeignKey('habit.id'), nullable=False)


class AtomicHabit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    habit_type = db.Column(db.String(20))  # 'standard', 'stack' or 'before'
    action = db.Column(db.String(200), nullable=False)
    trigger_or_time = db.Column(db.String(200), nullable=False)
    order_index = db.Column(db.Integer, default=0)


# --------------------------------------------------------------------------
# Schema upgrade (runs on start-up, safe to run repeatedly)
# --------------------------------------------------------------------------
def guess_setup(name, unit):
    """Return (category, metric, ref_time) for a habit that has none yet."""
    n = (name or '').strip().lower()
    u = (unit or '').strip().lower()
    if '(delay)' in n:
        m = re.search(r'(\d{1,2})\s*(am|pm)', n)
        ref = '05:00'
        if m:
            hour = int(m.group(1)) % 12 + (12 if m.group(2) == 'pm' else 0)
            ref = f'{hour:02d}:00'
        return 'activity', 'delay', ref
    if n in COURSE_NAMES:
        return 'course', 'sum', '05:00'
    if u.startswith('page') or u == 'units':
        return ('activity' if n == 'linkedin' else 'book'), 'sum', '05:00'
    return 'activity', 'sum', '05:00'


def ensure_schema():
    db.create_all()
    existing = {row[1] for row in db.session.execute(text("PRAGMA table_info(habit)"))}
    additions = {
        'category': "VARCHAR(12)",
        'metric': "VARCHAR(8) DEFAULT 'sum'",
        'ref_time': "VARCHAR(5) DEFAULT '05:00'",
        'color': "VARCHAR(9)",
        'scale_mode': "VARCHAR(10) DEFAULT 'gradient'",
        'target': "FLOAT",
        'levels': "VARCHAR(120)",
    }
    for col, ddl in additions.items():
        if col not in existing:
            db.session.execute(text(f"ALTER TABLE habit ADD COLUMN {col} {ddl}"))
    db.session.commit()

    for h in Habit.query.filter(Habit.category.is_(None)).all():
        h.category, h.metric, h.ref_time = guess_setup(h.name, h.unit)
    db.session.commit()


with app.app_context():
    ensure_schema()


# --------------------------------------------------------------------------
# Formatting helpers (the JS in static/js/heatmap.js mirrors these)
# --------------------------------------------------------------------------
def _num(v):
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else f'{v:g}'


def _dur(minutes):
    m = int(round(minutes))
    if m < 60:
        return f'{m} min'
    return f'{m // 60} h' if m % 60 == 0 else f'{m // 60} h {m % 60:02d} m'


def fmt_value(v, unit='', metric='sum'):
    if v is None:
        return '—'
    unit = (unit or '').strip()
    if metric == 'delay':
        v = int(round(v))
        if v == 0:
            return 'On time'
        return f'{_dur(abs(v))} {"late" if v > 0 else "early"}'
    lu = unit.lower()
    if lu.startswith('min'):
        return _dur(v)
    if lu in ('h', 'hr', 'hrs') or lu.startswith('hour'):
        return f'{_num(v)} h'
    if lu in ('pages', 'page') and float(v) == 1:
        return '1 page'
    return f'{_num(v)} {unit}'.strip()


app.jinja_env.filters['fmt'] = fmt_value
app.jinja_env.filters['num'] = _num


def parse_amount(raw, unit):
    """'25', '1.5', '1,5' or '1:30' (h:mm) -> float in the habit's unit."""
    raw = (raw or '').strip().replace(',', '.')
    if not raw:
        raise ValueError('empty')
    if ':' in raw:
        h, m = raw.split(':', 1)
        hours = int(h or 0) + int(m or 0) / 60
        return hours if (unit or '').lower().startswith(('h',)) else hours * 60
    return float(raw)


def delay_minutes(ref_time, hhmm):
    rh, rm = [int(x) for x in (ref_time or '05:00').split(':')]
    th, tm = [int(x) for x in hhmm.split(':')[:2]]
    d = (th * 60 + tm) - (rh * 60 + rm)
    if d < -720:      # e.g. bedtime 21:00 logged as 00:30
        d += 1440
    return d


# --------------------------------------------------------------------------
# Heat-map data
# --------------------------------------------------------------------------
def daily_values(habits, since=None):
    """{habit_id: {'YYYY-MM-DD': value}}. Sum habits add up; delay habits keep the first log of the day."""
    ids = {h.id for h in habits}
    delay_ids = {h.id for h in habits if h.is_delay}
    q = db.session.query(HabitLog.habit_id, HabitLog.date_created, HabitLog.value)
    if since:
        q = q.filter(HabitLog.date_created >= since)
    q = q.order_by(HabitLog.date_created, HabitLog.time_created, HabitLog.id)
    out = defaultdict(dict)
    for hid, d, v in q:
        if hid not in ids:
            continue
        k = d.isoformat()
        if hid in delay_ids:
            out[hid].setdefault(k, v)
        else:
            out[hid][k] = out[hid].get(k, 0) + v
    return out


def _nice(x):
    if x <= 0:
        return 1
    if x < 10:
        return round(x * 2) / 2 or 0.5
    if x < 100:
        return int(round(x / 5.0) * 5)
    return int(round(x / 10.0) * 10)


def parse_levels(raw):
    if not raw:
        return []
    vals = []
    for part in re.split(r'[,\s;]+', raw.strip()):
        try:
            f = float(part)
        except ValueError:
            continue
        if f > 0:
            vals.append(f)
    vals = sorted(set(vals))[:8]
    return vals


def heat_cfg(h, values):
    """Everything the browser needs to colour one habit's cells."""
    effective = [max(v, 0) for v in values.values()]
    positive = sorted(v for v in effective if v > 0)
    auto_target = None
    if positive:
        auto_target = positive[min(len(positive) - 1, int(len(positive) * 0.9))]
    auto_target = _nice(auto_target or h.goal or 1)
    target = h.target if h.target and h.target > 0 else auto_target
    custom_levels = parse_levels(h.levels)
    levels = custom_levels or sorted({_nice(target * f) for f in (0.25, 0.5, 0.75, 1.0)})
    return {
        'color': h.display_color,
        'mode': h.scale_mode or 'gradient',
        'target': target,
        'autoTarget': auto_target,
        'levels': levels,
        'autoLevels': not custom_levels,
        'unit': (h.unit or '').strip(),
        'metric': h.metric or 'sum',
    }


def streaks(date_strs):
    days = sorted({date.fromisoformat(s) for s in date_strs})
    if not days:
        return 0, 0
    best = run = 1
    for a, b in zip(days, days[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        best = max(best, run)
    today = date.today()
    cur = 0
    d = today if today in set(days) else today - timedelta(days=1)
    s = set(days)
    while d in s:
        cur += 1
        d -= timedelta(days=1)
    return cur, best


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def add_log(habit, form):
    """Create a log from a form/JSON dict. Returns (log, error)."""
    note = (form.get('activity') or '').strip() or habit.name.strip()
    when = form.get('date')
    try:
        log_date = datetime.strptime(when, '%Y-%m-%d').date() if when else date.today()
    except ValueError:
        log_date = date.today()

    try:
        if habit.is_delay:
            if form.get('time'):
                value = delay_minutes(habit.ref_time, form['time'])
            else:
                value = parse_amount(form.get('value'), habit.unit)
        else:
            value = parse_amount(form.get('value'), habit.unit)
    except (ValueError, TypeError):
        return None, 'Enter a number (or h:mm) for the amount.'

    if habit.is_delay:
        # one wake-up / bedtime per day: logging again corrects the existing entry
        existing = (HabitLog.query.filter_by(habit_id=habit.id, date_created=log_date)
                    .order_by(HabitLog.time_created, HabitLog.id).first())
        if existing:
            existing.value = value
            existing.time_created = (form.get('time') or datetime.now().strftime('%H:%M'))
            if form.get('activity'):
                existing.activity_name = note[:100]
            db.session.commit()
            return existing, None

    log = HabitLog(activity_name=note[:100], value=value, habit_id=habit.id, date_created=log_date)
    db.session.add(log)
    db.session.commit()
    return log, None


def today_state(habit):
    vals = daily_values([habit], since=date.today()).get(habit.id, {})
    v = vals.get(date.today().isoformat())
    if habit.is_delay:
        pct = 100 if v is not None else 0
    else:
        pct = min(100, round((v or 0) / habit.goal * 100)) if habit.goal else (100 if v else 0)
    return {
        'value': v,
        'text': fmt_value(v, habit.unit, habit.metric) if v is not None else 'Not logged',
        'goal_text': fmt_value(habit.goal, habit.unit) if not habit.is_delay else '',
        'pct': pct,
        'done': (v is not None) if habit.is_delay else bool(v and v >= habit.goal),
    }


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.route('/', methods=['GET'])
def index():
    tab = request.args.get('tab', 'activities')
    if tab not in TAB_TO_CATEGORY:
        tab = 'activities'
    category = TAB_TO_CATEGORY[tab]

    habits = (Habit.query.filter_by(category=category)
              .order_by(Habit.position.asc(), Habit.id.asc()).all())
    active = [h for h in habits if not h.is_permanently_completed]
    finished = [h for h in habits if h.is_permanently_completed]

    today = date.today()
    daily_all = daily_values(habits)
    recent_cut = (today - timedelta(days=7 * 24)).isoformat()

    cards, heat = [], {}
    for h in active:
        vals = daily_all.get(h.id, {})
        v = vals.get(today.isoformat())
        if h.is_delay:
            pct = 100 if v is not None else 0
            done = v is not None
        else:
            pct = min(100, round((v or 0) / h.goal * 100)) if h.goal else (100 if v else 0)
            done = bool(v and v >= h.goal)
        cur, best = streaks(vals.keys())
        cards.append({
            'h': h, 'color': h.display_color, 'pct': pct, 'done': done,
            'today_text': fmt_value(v, h.unit, h.metric) if v is not None else 'Not logged',
            'goal_text': '' if h.is_delay else fmt_value(h.goal, h.unit),
            'streak': cur,
        })
        heat[h.id] = {
            'cfg': heat_cfg(h, vals),
            'data': {k: x for k, x in vals.items() if k >= recent_cut},
        }

    # tab-wide "how many habits did I touch" heat-map
    per_day = defaultdict(int)
    for h in habits:
        for k, v in daily_all.get(h.id, {}).items():
            if h.is_delay or v > 0:
                per_day[k] += 1
    cur, best = streaks(per_day.keys())
    counts = sorted(per_day.values())
    hero_target = counts[min(len(counts) - 1, int(len(counts) * 0.9))] if counts else 1
    hero = {
        'data': dict(per_day),
        'first': min(per_day) if per_day else today.isoformat(),
        'cfg': {'color': DEFAULT_COLORS[category], 'mode': 'gradient', 'target': max(hero_target, 1),
                'levels': [], 'unit': 'habits', 'metric': 'sum'},
    }
    logged_today = sum(1 for c in cards if c['today_text'] != 'Not logged')

    return render_template('index.html', tab=tab, category=category, cards=cards, finished=finished,
                           finished_totals={h.id: sum(daily_all.get(h.id, {}).values()) for h in finished},
                           heat=heat, hero=hero, streak=cur, best=best, logged_today=logged_today,
                           total_active=len(cards), today=today.isoformat(),
                           categories=CATEGORIES, tab_label=CATEGORY_LABEL[category])


@app.route('/create_habit', methods=['POST'])
def create_habit():
    name = (request.form.get('name') or '').strip()
    unit = (request.form.get('unit') or 'min').strip()
    category = request.form.get('category', 'activity')
    if category not in CATEGORY_LABEL:
        category = 'activity'
    try:
        goal = float(request.form.get('goal') or 0)
    except ValueError:
        goal = 0
    if name and Habit.query.filter_by(name=name).first():
        flash(f'"{name}" already exists.', 'error')
    elif name:
        is_delay = request.form.get('metric') == 'delay'
        h = Habit(name=name, unit=unit, goal=goal, category=category,
                  metric='delay' if is_delay else 'sum',
                  ref_time=request.form.get('ref_time') or '05:00')
        db.session.add(h)
        db.session.commit()
        flash(f'Created "{name}".', 'ok')
    return redirect(url_for('index', tab=CATEGORY_TO_TAB[category]))


@app.route('/api/log/<int:habit_id>', methods=['POST'])
def api_log(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    payload = request.get_json(silent=True) or request.form
    log, err = add_log(habit, payload)
    if err:
        return jsonify({'error': err}), 400
    st = today_state(habit)
    day_vals = daily_values([habit], since=log.date_created).get(habit.id, {})
    return jsonify({'today': st, 'date': log.date_created.isoformat(),
                    'day_value': day_vals.get(log.date_created.isoformat())})


# --------------------------------------------------------------------------
# Habit page
# --------------------------------------------------------------------------
@app.route('/habit/<string:habit_name>')
def track_habit_by_name(habit_name):
    habit = Habit.query.filter_by(name=habit_name).first()
    return redirect(url_for('track_habit', habit_id=habit.id) if habit else '/')


@app.route('/h/<int:habit_id>', methods=['GET', 'POST'])
def track_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)

    if request.method == 'POST':
        _, err = add_log(habit, request.form)
        if err:
            flash(err, 'error')
        return redirect(url_for('track_habit', habit_id=habit.id))

    today = date.today()
    all_logs = (HabitLog.query.filter_by(habit_id=habit.id)
                .order_by(HabitLog.date_created.desc(), HabitLog.time_created.desc(), HabitLog.id.desc()).all())
    today_logs = [l for l in all_logs if l.date_created == today]
    vals = daily_values([habit]).get(habit.id, {})
    cur, best = streaks(vals.keys())

    total = sum(max(v, 0) for v in vals.values()) if habit.is_delay else sum(vals.values())
    active_days = len(vals)
    avg = (total / active_days) if active_days else 0
    st = today_state(habit)

    # last 60 days for the bar chart
    labels, series = [], []
    for i in range(59, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime('%d %b'))
        series.append(vals.get(d.isoformat()))

    years = sorted({int(k[:4]) for k in vals} | {today.year}, reverse=True)

    return render_template('habit_tracker.html', habit=habit, tab=CATEGORY_TO_TAB.get(habit.category, 'activities'),
                           today_logs=today_logs, all_logs=all_logs, state=st,
                           streak=cur, best=best, total=total, active_days=active_days, avg=avg,
                           heat={'cfg': heat_cfg(habit, vals), 'data': vals},
                           chart={'labels': labels, 'values': series}, years=years,
                           first=min(vals) if vals else today.isoformat(), today=today.isoformat())


@app.route('/edit_habit/<int:habit_id>', methods=['GET', 'POST'])
def edit_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)

    if request.method == 'POST':
        f = request.form
        new_name = (f.get('name') or '').strip()
        clash = Habit.query.filter(Habit.name == new_name, Habit.id != habit.id).first()
        if not new_name or clash:
            flash('That name is empty or already used by another habit.', 'error')
        else:
            habit.name = new_name
            habit.unit = (f.get('unit') or habit.unit).strip()
            try:
                habit.goal = float(f.get('goal') or 0)
            except ValueError:
                pass
            if f.get('category') in CATEGORY_LABEL:
                habit.category = f['category']
            habit.metric = 'delay' if f.get('metric') == 'delay' else 'sum'
            if f.get('ref_time'):
                habit.ref_time = f['ref_time']

            color = (f.get('color') or '').strip()
            habit.color = color if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else None
            habit.scale_mode = 'levels' if f.get('scale_mode') == 'levels' else 'gradient'
            try:
                t = float(f.get('target') or 0)
                habit.target = t if t > 0 else None
            except ValueError:
                habit.target = None
            lv = parse_levels(f.get('levels'))
            habit.levels = ','.join(_num(x) for x in lv) or None
            db.session.commit()
            flash(f'Saved "{habit.name}".', 'ok')
            return redirect(url_for('track_habit', habit_id=habit.id))

    vals = daily_values([habit]).get(habit.id, {})
    return render_template('edit_habit.html', habit=habit, categories=CATEGORIES, swatches=SWATCHES,
                           tab=CATEGORY_TO_TAB.get(habit.category, 'activities'),
                           heat={'cfg': heat_cfg(habit, vals), 'data': vals},
                           defaults={'activity': DEFAULT_COLORS['activity'], 'book': DEFAULT_COLORS['book'],
                                     'course': DEFAULT_COLORS['course'], 'delay': DELAY_COLOR},
                           first=min(vals) if vals else date.today().isoformat(),
                           today=date.today().isoformat())


@app.route('/set_category/<int:habit_id>', methods=['POST'])
def set_category(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    cat = (request.get_json(silent=True) or {}).get('category')
    if cat not in CATEGORY_LABEL:
        return jsonify({'error': 'bad category'}), 400
    habit.category = cat
    db.session.commit()
    return jsonify({'status': 'success'})


@app.route('/complete_habit_permanently/<int:habit_id>', methods=['POST'])
def complete_habit_permanently(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    habit.is_permanently_completed = True
    db.session.commit()
    return redirect(url_for('index', tab=CATEGORY_TO_TAB.get(habit.category, 'activities')))


@app.route('/reopen_habit/<int:habit_id>', methods=['POST'])
def reopen_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    habit.is_permanently_completed = False
    db.session.commit()
    return redirect(url_for('index', tab=CATEGORY_TO_TAB.get(habit.category, 'activities')))


@app.route('/delete_habit/<int:habit_id>')
def delete_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    db.session.delete(habit)
    db.session.commit()
    return redirect(url_for('manage_library'))


@app.route('/edit_habit_log/<int:log_id>', methods=['GET', 'POST'])
def edit_habit_log(log_id):
    log = HabitLog.query.get_or_404(log_id)
    habit = log.parent_habit
    if request.method == 'POST':
        if request.form.get('date'):
            log.date_created = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        try:
            log.value = parse_amount(request.form.get('value'), habit.unit)
        except ValueError:
            flash('Enter a number for the amount.', 'error')
            return redirect(url_for('edit_habit_log', log_id=log.id))
        log.activity_name = request.form.get('activity_name') or habit.name
        log.time_created = request.form.get('time') or log.time_created
        db.session.commit()
        return redirect(url_for('track_habit', habit_id=habit.id))
    return render_template('edit_habit_log.html', log=log, habit=habit,
                           tab=CATEGORY_TO_TAB.get(habit.category, 'activities'))


@app.route('/delete_habit_log/<int:log_id>')
def delete_habit_log(log_id):
    log = HabitLog.query.get_or_404(log_id)
    hid = log.habit_id
    db.session.delete(log)
    db.session.commit()
    return redirect(url_for('track_habit', habit_id=hid))


# --------------------------------------------------------------------------
# Library, ordering, summary, today API
# --------------------------------------------------------------------------
@app.route('/manage_library')
def manage_library():
    habits = Habit.query.order_by(Habit.position.asc(), Habit.id.asc()).all()
    order = {c: i for i, (c, _) in enumerate(CATEGORIES)}
    habits.sort(key=lambda h: order.get(h.category, 9))
    return render_template('manage_library.html', habits=habits, categories=CATEGORIES, tab=None)


@app.route('/update_habit_order', methods=['POST'])
def update_habit_order():
    data = request.get_json()
    for index, habit_id in enumerate(data.get('order', [])):
        habit = db.session.get(Habit, int(habit_id))
        if habit:
            habit.position = index
    db.session.commit()
    return jsonify({"status": "success"}), 200


@app.route('/api/habits/today')
def habits_today():
    today = date.today()
    category = request.args.get('category')
    q = (db.session.query(Habit.name, Habit.unit, Habit.goal, Habit.id, func.sum(HabitLog.value))
         .join(HabitLog, HabitLog.habit_id == Habit.id)
         .filter(HabitLog.date_created == today, Habit.metric != 'delay'))
    if category:
        q = q.filter(Habit.category == category)
    grouped = {}
    for name, unit, goal, hid, total in q.group_by(Habit.id).all():
        h = db.session.get(Habit, hid)
        if total and total > 0:
            grouped.setdefault((unit or '').strip(), []).append(
                {"name": name.strip(), "value": total, "goal": goal, "color": h.display_color,
                 "label": fmt_value(total, unit)})
    return jsonify(grouped)


@app.route('/summary', methods=['GET'])
def summary():
    raw = request.args.get('date')
    try:
        selected = datetime.strptime(raw, '%Y-%m-%d').date() if raw else date.today()
    except ValueError:
        selected = date.today()

    entries = []
    for habit in Habit.query.order_by(Habit.category, Habit.position.asc()).all():
        logs = (HabitLog.query.filter_by(habit_id=habit.id, date_created=selected)
                .order_by(HabitLog.time_created.asc()).all())
        if logs:
            vals = daily_values([habit], since=selected).get(habit.id, {})
            entries.append({"habit": habit, "logs": logs, "total": vals.get(selected.isoformat(), 0)})
    return render_template('summary.html', selected_date=selected, habit_entries=entries, tab=None,
                           prev_day=(selected - timedelta(days=1)).isoformat(),
                           next_day=(selected + timedelta(days=1)).isoformat(),
                           is_today=selected == date.today())


# --------------------------------------------------------------------------
# Atomic Habits (unchanged behaviour)
# --------------------------------------------------------------------------
@app.route('/atomic_habits')
def atomic_habits():
    q = lambda t: AtomicHabit.query.filter_by(habit_type=t).order_by(AtomicHabit.order_index.asc()).all()
    return render_template('atomic_habits.html', stacks=q('stack'), standards=q('standard'),
                           before_habits=q('before'), tab=None)


@app.route('/edit_atomic/<int:id>', methods=['POST'])
def edit_atomic(id):
    habit = AtomicHabit.query.get_or_404(id)
    habit.action = request.form.get('action')
    habit.trigger_or_time = request.form.get('trigger')
    habit.order_index = int(request.form.get('order', 0))
    db.session.commit()
    return redirect('/atomic_habits')


@app.route('/add_atomic', methods=['POST'])
def add_atomic():
    action, trigger = request.form.get('action'), request.form.get('trigger')
    if action and trigger:
        db.session.add(AtomicHabit(habit_type=request.form.get('habit_type'), action=action, trigger_or_time=trigger))
        db.session.commit()
    return redirect('/atomic_habits')


@app.route('/delete_atomic/<int:id>')
def delete_atomic(id):
    db.session.delete(AtomicHabit.query.get_or_404(id))
    db.session.commit()
    return redirect('/atomic_habits')
