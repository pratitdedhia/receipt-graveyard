# trip_engine.py - Trip Auto-Detection, Travel vs Local Context, and Daily/Monthly Accumulation Engine

from datetime import datetime
from collections import defaultdict
from policy import POLICY

# Default home office city per employee
EMPLOYEE_HOME_OFFICES = {
    "Aarav Mehta": "Mumbai",
    "Isha Shah": "Bengaluru",
    "Kabir Rao": "Mumbai",
    "Nina Patel": "Delhi",
    "Rohan Verma": "Pune"
}

def get_employee_home_city(employee_name, con=None):
    if con:
        try:
            r = con.execute("""
            SELECT o.city FROM users u
            JOIN offices o ON u.office_id = o.id
            WHERE lower(u.name) = lower(?)
            """, (employee_name,)).fetchone()
            if r and r[0]:
                return r[0]
        except Exception:
            pass
    return EMPLOYEE_HOME_OFFICES.get(employee_name, "Mumbai")

def is_business_trip_context(employee, expense_date, city, con=None, manual_is_trip=False):
    """
    Determines if an expense took place during an active business trip.
    Rules:
    1. If manually tagged as a trip -> True
    2. If the expense city is different from the employee's mapped home office city -> True
    3. If there is an Accommodation or Travel booking by this employee in this city +/- 1 day -> True
    """
    if manual_is_trip:
        return True, "Manually designated as Business Trip"

    home_city = get_employee_home_city(employee, con)
    if city and city != home_city and city != "Other":
        return True, f"Out-of-town travel to {city} (Employee home base: {home_city})"

    if con and expense_date and employee:
        # Check if hotel or travel exists within +/- 1 day
        try:
            q = """
            SELECT id, category, city FROM expenses 
            WHERE employee = ? 
            AND category IN ('Travel', 'Accommodation')
            AND abs(julianday(expense_date) - julianday(?)) <= 1.5
            AND status != 'Duplicate'
            """
            matches = con.execute(q, (employee, expense_date)).fetchall()
            if matches:
                ref = matches[0]
                return True, f"Active trip confirmed by {ref['category']} booking (#{ref['id']} in {ref['city']})"
        except Exception:
            pass

    return False, f"Local office location ({home_city})"

def calculate_accumulations(con, employee, expense_date, city, category, amount_inr, exclude_id=None):
    """
    Calculates:
    - Same-employee same-day city spend before this expense
    - Remaining city daily allowance
    - Month-to-date category spend for this employee
    - Remaining monthly category budget
    """
    daily_spent_before = 0.0
    monthly_cat_spent_before = 0.0

    if con and employee and expense_date:
        # 1. Daily city spend
        q_daily = """
        SELECT SUM(amount_inr) as total_daily 
        FROM expenses 
        WHERE employee = ? 
        AND expense_date = ? 
        AND city = ? 
        AND status != 'Duplicate'
        """
        args_daily = [employee, expense_date, city]
        if exclude_id:
            q_daily += " AND id != ?"
            args_daily.append(exclude_id)
        
        row_daily = con.execute(q_daily, args_daily).fetchone()
        if row_daily and row_daily["total_daily"]:
            daily_spent_before = float(row_daily["total_daily"])

        # 2. Monthly category spend
        try:
            # Extract YYYY-MM
            month_str = expense_date[:7]
            q_month = """
            SELECT SUM(amount_inr) as total_monthly 
            FROM expenses 
            WHERE employee = ? 
            AND category = ? 
            AND expense_date LIKE ? 
            AND status != 'Duplicate'
            """
            args_month = [employee, category, f"{month_str}%"]
            if exclude_id:
                q_month += " AND id != ?"
                args_month.append(exclude_id)
            row_month = con.execute(q_month, args_month).fetchone()
            if row_month and row_month["total_monthly"]:
                monthly_cat_spent_before = float(row_month["total_monthly"])
        except Exception:
            pass

    city_limit = POLICY["city_daily_limits"].get(city, POLICY["city_daily_limits"]["Other"])
    remaining_daily = max(0.0, city_limit - daily_spent_before)

    monthly_budget = POLICY.get("monthly_category_budgets", {}).get(category, 50000)
    remaining_monthly = max(0.0, monthly_budget - monthly_cat_spent_before)

    return {
        "daily_spent_before": daily_spent_before,
        "daily_limit": city_limit,
        "remaining_daily": remaining_daily,
        "daily_spent_after": daily_spent_before + amount_inr,
        "monthly_spent_before": monthly_cat_spent_before,
        "monthly_budget": monthly_budget,
        "remaining_monthly": remaining_monthly,
        "monthly_spent_after": monthly_cat_spent_before + amount_inr
    }

def reconstruct_trips(expenses):
    """
    Analyzes a collection of expenses and reconstructs distinct business trips.
    Returns a list of trips with itinerary, spend, dates, and compliance.
    """
    # Group by employee
    by_emp = defaultdict(list)
    for e in expenses:
        if e["status"] != "Duplicate":
            by_emp[e["employee"]].append(e)

    trips = []
    trip_counter = 1

    for emp, claims in by_emp.items():
        home_city = get_employee_home_city(emp)
        # Filter for out-of-town claims or explicit trip claims
        out_of_town = []
        for c in claims:
            is_trip_val = bool(c["is_trip"]) if "is_trip" in c.keys() else False
            c_city = c["city"] or ""
            if (c_city and c_city != home_city and c_city != "Other") or is_trip_val:
                out_of_town.append(c)
        
        # Sort by date
        out_of_town.sort(key=lambda x: x["expense_date"] or "")

        # Cluster by city and date proximity (gap <= 3 days)
        current_cluster = []
        for c in out_of_town:
            if not current_cluster:
                current_cluster.append(c)
                continue

            last = current_cluster[-1]
            try:
                d1 = datetime.strptime(last["expense_date"], "%Y-%m-%d")
                d2 = datetime.strptime(c["expense_date"], "%Y-%m-%d")
                gap = abs((d2 - d1).days)
            except Exception:
                gap = 0

            if c["city"] == last["city"] and gap <= 3:
                current_cluster.append(c)
            else:
                if len(current_cluster) >= 1:
                    trips.append(build_trip_summary(emp, current_cluster, trip_counter))
                    trip_counter += 1
                current_cluster = [c]

        if current_cluster:
            trips.append(build_trip_summary(emp, current_cluster, trip_counter))
            trip_counter += 1

    return sorted(trips, key=lambda t: t["start_date"], reverse=True)

def build_trip_summary(employee, cluster, trip_num):
    dates = [c["expense_date"] for c in cluster if c["expense_date"]]
    start_date = min(dates) if dates else "Unknown"
    end_date = max(dates) if dates else "Unknown"
    city = cluster[0]["city"] or "Business Trip"
    total_claimed = sum(float(c["amount_inr"] or 0) for c in cluster)
    total_reimbursable = sum(float(c["reimbursable"] or 0) for c in cluster)
    has_issues = any(c["status"] in ("Needs Review", "Needs Info", "Rejected") for c in cluster)

    return {
        "id": f"TRIP-{trip_num:03d}",
        "employee": employee,
        "city": city,
        "start_date": start_date,
        "end_date": end_date,
        "claims_count": len(cluster),
        "total_claimed": total_claimed,
        "total_reimbursable": total_reimbursable,
        "status": "Flagged" if has_issues else "Compliant",
        "claim_ids": [c["id"] for c in cluster]
    }
