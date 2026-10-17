import json
from datetime import datetime
from flask_app import app, db, Habit, HabitLog, AtomicHabit

with app.app_context():
    # 1. Clear existing (Optional - only if you want a fresh start)
    db.drop_all()
    db.create_all()

    with open("habit_data.json", "r") as f:
        data = json.load(f)

    # 2. Map old IDs to new IDs to keep logs connected
    id_map = {}

    for h in data["habits"]:
        new_h = Habit(name=h["name"], unit=h["unit"], goal=h["goal"])
        db.session.add(new_h)
        db.session.flush() # Gets the new ID before committing
        id_map[h["id"]] = new_h.id

    for l in data["logs"]:
        new_log = HabitLog(
            activity_name=l["activity_name"],
            value=l["value"],
            date_created=datetime.strptime(l["date"], '%Y-%m-%d').date(),
            habit_id=id_map[l["habit_id"]]
        )
        db.session.add(new_log)

    for a in data["atomic"]:
        new_a = AtomicHabit(habit_type=a["type"], action=a["action"], trigger_or_time=a["trigger"])
        db.session.add(new_a)

    db.session.commit()
    print("Import Successful! Your data is now in SQLite.")