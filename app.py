import streamlit as st
import json
import requests
from ortools.sat.python import cp_model

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Πρόγραμμα Νοσηλευτών", page_icon="📅", layout="centered")

st.title("📅 Γεννήτρια Προγράμματος Νοσηλευτών")

# --- GLOBAL DATA ---

DEFAULT_NURSES = [f"Nurse {i+1}" for i in range(12)]

# Fetch from secrets if available, otherwise use defaults
nurse_names = st.secrets.get("NURSE_NAMES", DEFAULT_NURSES)

days_names = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή']
shift_names = ['Πρωί', 'Απόγευμα', 'Βράδυ']

# --- JSONBIN PERSISTENCE CONFIG ---
JSONBIN_BIN_ID = st.secrets.get("JSONBIN_BIN_ID", "")
JSONBIN_API_KEY = st.secrets.get("JSONBIN_API_KEY", "")

def load_saved_data():
    """Load JSON state from JSONBin or fallback to local file."""
    if JSONBIN_BIN_ID and JSONBIN_API_KEY:
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
        headers = {"X-Master-Key": JSONBIN_API_KEY}
        try:
            res = requests.get(url, headers=headers)
            if res.status_code == 200:
                return res.json().get("record", {})
        except Exception as e:
            st.warning(f"Σφάλμα σύνδεσης με το σύννεφο: {e}")
    
    # Local fallback
    try:
        with open('schedule_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"past_shifts": {}, "worked_last_weekend": {}, "last_sunday_shifts": {}}

def save_data(data):
    """Save JSON state to JSONBin or fallback to local file."""
    if JSONBIN_BIN_ID and JSONBIN_API_KEY:
        url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
        headers = {
            "Content-Type": "application/json",
            "X-Master-Key": JSONBIN_API_KEY
        }
        try:
            res = requests.put(url, headers=headers, json=data)
            if res.status_code == 200:
                st.success("Τα δεδομένα ενημερώθηκαν επιτυχώς στο σύννεφο!")
                return
        except Exception as e:
            st.error(f"Αποτυχία αποθήκευσης στο σύννεφο: {e}")

    # Local fallback
    with open('schedule_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    st.success("Τα δεδομένα αποθηκεύτηκαν τοπικά.")

# --- SCHEDULER FUNCTION ---
def generate_fair_schedule(leave_requests):
    num_nurses = len(nurse_names)
    num_weeks = 1  
    num_days = num_weeks * 7
    num_shifts = 3 
    
    all_nurses = range(num_nurses)
    all_days = range(num_days)
    all_shifts = range(num_shifts)
    
    nurse_dict = {name: i for i, name in enumerate(nurse_names)}
    
    shift_requirements = [4, 2, 2] 
    morning_only_nurses = [nurse_dict["Νταντάκας"], nurse_dict["Παρασκευοπούλου"]]
    noon_only_nurses = [nurse_dict["Τσουγκουτζίδου"]]
    no_weekend_nurses = [nurse_dict["Νταντάκας"], nurse_dict["Παρασκευοπούλου"]]

    past_shifts = {n: 0 for n in all_nurses} 
    worked_last_weekend = {n: 0 for n in all_nurses}
    last_sunday_shifts = {n: [0, 0, 0] for n in all_nurses}
    
    saved_data = load_saved_data()

    if "past_shifts" in saved_data:
        for n_id, score in saved_data["past_shifts"].items():
            past_shifts[int(n_id)] = score
            
    if "worked_last_weekend" in saved_data:
        for n_id, worked in saved_data["worked_last_weekend"].items():
            worked_last_weekend[int(n_id)] = worked
            
    if "last_sunday_shifts" in saved_data:
        for n_id, shifts_array in saved_data["last_sunday_shifts"].items():
            last_sunday_shifts[int(n_id)] = shifts_array

    leave_set = set(leave_requests)

    model = cp_model.CpModel()
    shifts = {}

    for n in all_nurses:
        for d in all_days:
            for s in all_shifts:
                shifts[(n, d, s)] = model.NewBoolVar(f'shift_n{n}_d{d}_s{s}')

    for d in all_days:
        is_weekend = (d % 7 == 5 or d % 7 == 6) 
        for s in all_shifts:
            req = shift_requirements[s]
            if is_weekend and s == 0:
                req = 2
            model.Add(sum(shifts[(n, d, s)] for n in all_nurses) == req)

    for n in all_nurses:
        for d in range(num_days):
            model.AddImplication(shifts[(n, d, 0)], shifts[(n, d, 1)].Not())
            model.AddImplication(shifts[(n, d, 1)], shifts[(n, d, 2)].Not())

        for d in range(num_days - 1):
            model.AddImplication(shifts[(n, d, 2)], shifts[(n, d + 1, 0)].Not())
            model.AddImplication(shifts[(n, d, 2)], shifts[(n, d + 1, 1)].Not())
            model.AddImplication(shifts[(n, d, 1)], shifts[(n, d + 1, 0)].Not())

    for n in all_nurses:
        for d in range(num_days - 1):
            model.Add(
                sum(shifts[(n, d + 1, s)] for s in all_shifts) == 0
            ).OnlyEnforceIf([shifts[(n, d, 0)], shifts[(n, d, 2)]])

    for n in all_nurses:
        prev_sun_morning = last_sunday_shifts[n][0]
        prev_sun_afternoon = last_sunday_shifts[n][1]
        prev_sun_night = last_sunday_shifts[n][2]
        
        if prev_sun_night == 1 or prev_sun_afternoon == 1:
            model.Add(shifts[(n, 0, 0)] == 0)
            
        if prev_sun_morning == 1 and prev_sun_night == 1:
            for s in all_shifts:
                model.Add(shifts[(n, 0, s)] == 0)

    for n in all_nurses:
        model.Add(sum(shifts[(n, d, 2)] for d in all_days) <= 2)

    for n in morning_only_nurses:
        for d in all_days:
            model.Add(shifts[(n, d, 1)] == 0)
            model.Add(shifts[(n, d, 2)] == 0)

    for n in noon_only_nurses:
        for d in all_days:
            model.Add(shifts[(n, d, 0)] == 0)
            model.Add(shifts[(n, d, 2)] == 0)

    for n in no_weekend_nurses:
        model.Add(sum(shifts[(n, 5, s)] for s in all_shifts) == 0) 
        model.Add(sum(shifts[(n, 6, s)] for s in all_shifts) == 0) 

    # Εφαρμογή δυναμικών αδειών
    for (n, d) in leave_requests:
        for s in all_shifts:
            model.Add(shifts[(n, d, s)] == 0)

    over_ideal_vars, under_ideal_vars = [], []

    for n in all_nurses:
        days_on_leave = sum(1 for d in all_days if (n, d) in leave_set)
        current_week_shifts = sum(shifts[(n, d, s)] for d in all_days for s in all_shifts)

        max_absolute = 6 if days_on_leave == 0 else max(0, 5 - days_on_leave)
        model.Add(current_week_shifts <= max_absolute)
        
        ideal_max = 5 if days_on_leave == 0 else max(0, 5 - days_on_leave)
        ideal_min = 4 if days_on_leave == 0 else max(0, 4 - days_on_leave)

        over_ideal = model.NewIntVar(0, 7, f'over_ideal_n{n}')
        under_ideal = model.NewIntVar(0, 7, f'under_ideal_n{n}')
        
        model.Add(over_ideal >= current_week_shifts - ideal_max)
        model.Add(under_ideal >= ideal_min - current_week_shifts)
        
        over_ideal_vars.append(over_ideal)
        under_ideal_vars.append(under_ideal)

    weekend_penalty_vars = []
    for n in all_nurses:
        if n in no_weekend_nurses:
            continue
            
        worked_this_weekend = model.NewBoolVar(f'worked_this_weekend_n{n}')
        sum_weekend_shifts = sum(shifts[(n, d, s)] for d in [5, 6] for s in all_shifts)
        
        model.Add(sum_weekend_shifts >= 1).OnlyEnforceIf(worked_this_weekend)
        model.Add(sum_weekend_shifts == 0).OnlyEnforceIf(worked_this_weekend.Not())
        
        weekend_violation = model.NewBoolVar(f'weekend_violation_n{n}')
        
        if worked_last_weekend[n] == 1:
            model.Add(weekend_violation == worked_this_weekend)
        else:
            model.Add(weekend_violation == 1 - worked_this_weekend)
            
        weekend_penalty_vars.append(weekend_violation)

    total_worked_vars = []
    for n in all_nurses:
        current_week_shifts = sum(shifts[(n, d, s)] for d in all_days for s in all_shifts)
        grand_total = model.NewIntVar(-100, 1000, f'grand_total_n{n}')
        model.Add(grand_total == current_week_shifts + past_shifts[n])
        total_worked_vars.append(grand_total)

    max_total = model.NewIntVar(-100, 1000, 'max_total')
    min_total = model.NewIntVar(-100, 1000, 'min_total')
    model.AddMaxEquality(max_total, total_worked_vars)
    model.AddMinEquality(min_total, total_worked_vars)

    
    # ΝΕΑ ΛΟΓΙΚΗ: ΕΝΘΑΡΡΥΝΣΗ ΣΥΝΕΧΟΜΕΝΩΝ ΡΕΠΟ (Πέναλτι μεμονωμένων ρεπό)
    works = {}
    for n in all_nurses:
        for d in all_days:
            works[(n, d)] = model.NewBoolVar(f'works_n{n}_d{d}')
            sum_shifts = sum(shifts[(n, d, s)] for s in all_shifts)
            # True αν δουλεύει έστω και μια βάρδια, False αν είναι ρεπό
            model.Add(sum_shifts >= 1).OnlyEnforceIf(works[(n, d)])
            model.Add(sum_shifts == 0).OnlyEnforceIf(works[(n, d)].Not())

    isolated_off_vars = []
    for n in all_nurses:
        # Έλεγχος για τη Δευτέρα (σε σχέση με την προηγούμενη Κυριακή)
        worked_last_sun = 1 if sum(last_sunday_shifts[n]) > 0 else 0
        iso_off_0 = model.NewBoolVar(f'iso_off_n{n}_d0')
        # Αν δούλεψε Κυριακή, έχει ρεπό Δευτέρα, και δουλεύει Τρίτη -> Πέναλτι
        model.Add(iso_off_0 >= worked_last_sun - works[(n, 0)] + works[(n, 1)] - 1)
        isolated_off_vars.append(iso_off_0)

        # Έλεγχος για τις υπόλοιπες ενδιάμεσες ημέρες (Τρίτη έως Σάββατο)
        for d in range(1, num_days - 1):
            iso_off = model.NewBoolVar(f'iso_off_n{n}_d{d}')
            # Ενεργοποιείται αν: Δουλεύει(d-1) ΚΑΙ Ρεπό(d) ΚΑΙ Δουλεύει(d+1)
            model.Add(iso_off >= works[(n, d-1)] - works[(n, d)] + works[(n, d+1)] - 1)
            isolated_off_vars.append(iso_off)

    model.Minimize(
        (max_total - min_total) + 
        1000 * sum(over_ideal_vars) + 
        1000 * sum(under_ideal_vars) +
        500 * sum(weekend_penalty_vars) +
        150 * sum(isolated_off_vars)  # Προσθήκη πέναλτι για τα σπαστά ρεπό
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        st.subheader("📋 Εβδομαδιαίο Πρόγραμμα")

        for d in all_days:
            with st.expander(f"📌 {days_names[d]}", expanded=True):
                for s in all_shifts:
                    working_nurses = [nurse_names[n] for n in all_nurses if solver.Value(shifts[(n, d, s)])]
                    st.write(f"**{shift_names[s]}:** {', '.join(working_nurses)}")

        st.subheader("📊 Απολογισμός Βαρδιών")
        report_data = []
        new_past_shifts = {}

        for n in all_nurses:
            current = sum(solver.Value(shifts[(n, d, s)]) for d in all_days for s in all_shifts)
            past = past_shifts[n]
            total = solver.Value(total_worked_vars[n])
            new_past_shifts[str(n)] = total
            
            leave_days = sum(1 for d in all_days if (n, d) in leave_set)
            report_data.append({
                "Νοσηλευτής/τρια": nurse_names[n],
                "Νέες Βάρδιες": current,
                "Ιστορικό": past,
                "Σύνολο": total,
                "Άδειες": f"{leave_days} μέρες" if leave_days > 0 else "-"
            })

        st.table(report_data)

        # UPDATE MEMORY & SAVE
        new_weekend_data = {}
        new_sunday_data = {}

        for n in all_nurses:
            if n in no_weekend_nurses:
                new_weekend_data[str(n)] = 0
            else:
                did_work_weekend = sum(solver.Value(shifts[(n, d, s)]) for d in [5, 6] for s in all_shifts) > 0
                new_weekend_data[str(n)] = 1 if did_work_weekend else 0

            s0 = 1 if solver.Value(shifts[(n, 6, 0)]) else 0
            s1 = 1 if solver.Value(shifts[(n, 6, 1)]) else 0
            s2 = 1 if solver.Value(shifts[(n, 6, 2)]) else 0
            new_sunday_data[str(n)] = [s0, s1, s2]

        saved_data["past_shifts"] = new_past_shifts
        saved_data["worked_last_weekend"] = new_weekend_data
        saved_data["last_sunday_shifts"] = new_sunday_data

        save_data(saved_data)

    else:
        st.error("Δεν βρέθηκε εφικτό πρόγραμμα! Δοκιμάστε να μειώσετε τον αριθμό των ταυτόχρονων αδειών, καθώς δεν επαρκεί το προσωπικό για την κάλυψη των βαρδιών.")


# --- UI: ΔΙΑΧΕΙΡΙΣΗ ΑΔΕΙΩΝ ---
st.subheader("🏖️ Διαχείριση Αδειών / Ρεπό")
st.write("Επιλέξτε ποιες ημέρες της εβδομάδας θα απουσιάζει ο κάθε νοσηλευτής/τρια.")

user_leave_requests = []

with st.expander("📝 Φόρμα Καταχώρησης Αδειών", expanded=False):
    # Φτιάχνουμε στήλες για πιο όμορφο UI (2 στήλες)
    col1, col2 = st.columns(2)
    
    for i, name in enumerate(nurse_names):
        # Εναλλαγή μεταξύ αριστερής και δεξιάς στήλης
        col = col1 if i % 2 == 0 else col2
        
        with col:
            selected_days = st.multiselect(
                f"{name}", 
                options=days_names,
                placeholder="Επιλέξτε ημέρες..."
            )
            # Μετατροπή των ονομάτων ημερών σε (nurse_index, day_index) για τον αλγόριθμο
            for day_name in selected_days:
                day_index = days_names.index(day_name)
                user_leave_requests.append((i, day_index))

# --- UI: ACTION BUTTON ---
st.write("---")
if st.button("🚀 Δημιουργία Νέου Προγράμματος", type="primary", use_container_width=True):
    with st.spinner("Υπολογισμός προγράμματος..."):
        generate_fair_schedule(user_leave_requests)
