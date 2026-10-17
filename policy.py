# policy.py - Comprehensive Expense Policy Definition for Receipt Graveyard

POLICY = {
    # Category reimbursement caps (in INR)
    # Note: Meals have different caps depending on trip context (Travel vs Local Office)
    "category_caps": {
        "Meals_Trip": 2200,          # On a registered business trip
        "Meals_Local": 1200,         # Local home office (requires client entertainment or overtime)
        "Travel": 9000,              # Flights, intercity trains, cabs per day/leg
        "Accommodation": 7500,       # Hotel per night cap
        "Office Supplies": 3000,     # Per expense cap
        "Entertainment": 0,          # Non-reimbursable by default unless authorized client event
        "Other": 1500                # Incidentals, baggage fees, etc.
    },
    
    # Per-employee monthly category budget caps (INR)
    "monthly_category_budgets": {
        "Meals": 25000,
        "Travel": 60000,
        "Accommodation": 45000,
        "Office Supplies": 6000,
        "Entertainment": 5000,
        "Other": 5000
    },

    # Daily city per-diem caps (cumulative daily limit for all meals & local transit on a trip)
    "city_daily_limits": {
        "Mumbai": 2500,
        "Delhi": 2400,
        "Bengaluru": 2300,
        "Pune": 2000,
        "Hyderabad": 2100,
        "Chennai": 2100,
        "Kolkata": 2000,
        "New York": 12500,           # Approx $150 USD
        "London": 12600,             # Approx £120 GBP
        "Paris": 10000,              # Approx €110 EUR
        "Dubai": 10200,              # Approx 450 AED
        "Singapore": 9500,           # Approx 150 SGD
        "Other": 1800
    },

    # Approval escalation thresholds (INR)
    "approval_thresholds": {
        "auto_eligible": 5000,       # Under ₹5,000 with 0 risk score can be fast-tracked
        "manager_approval": 10000,   # Claims ₹5,000 - ₹10,000 need Manager Approval
        "vp_approval": 25000         # Claims > ₹10,000 need VP / Finance Director sign-off
    },

    # Mandatory fields by category
    "required_fields": {
        "Meals": ["date", "merchant", "amount", "city"],
        "Travel": ["date", "merchant", "amount", "city"],
        "Accommodation": ["date", "merchant", "amount", "city"],
        "Office Supplies": ["date", "merchant", "amount"],
        "Entertainment": ["date", "merchant", "amount", "client_name"],
        "Other": ["date", "merchant", "amount"]
    },

    # Non-reimbursable item classifications & keywords
    "non_reimbursable_catalog": {
        "Alcohol": [
            "alcohol", "beer", "wine", "cocktail", "whiskey", "whisky", "vodka", "rum",
            "scotch", "liquor", "spirits", "gin", "tequila", "brandy", "bar tab", "draught", "brewery"
        ],
        "Tobacco": [
            "tobacco", "cigarette", "cigar", "nicotine", "vape", "hookah"
        ],
        "Personal & Leisure": [
            "mini bar", "minibar", "movie rental", "pay per view", "spa", "massage",
            "souvenir", "gift shop", "personal care", "laundry express", "room upgrade", "personal"
        ],
        "Traffic Fines": [
            "traffic ticket", "parking violation", "speeding fine", "toll penalty"
        ]
    },

    # Conditional meal rules
    "meal_rules": {
        "client_name_required_above": 1200,   # Single meal above this requires client/project name
        "attendees_required_above": 1000,      # Single meal above this requires attendee count >= 1
        "max_per_attendee": 1800              # Total meal / attendees cannot exceed ₹1,800 per person
    },

    # Anti-smurfing / split transaction thresholds
    "split_transaction_window_hours": 24,
    "split_threshold_proximity_pct": 0.15,     # Claims within 15% below threshold (e.g., ₹1,020 to ₹1,199)

    # Submission time window (days)
    "max_submission_age_days": 60,            # Claims older than 60 days require policy exception

    # Exchange rates to INR
    "currency_rates_to_inr": {
        "INR": 1.0,
        "USD": 83.5,
        "EUR": 90.5,
        "GBP": 105.0,
        "AED": 22.7,
        "JPY": 0.55,
        "CAD": 61.2,
        "AUD": 54.8,
        "SGD": 62.4
    },

    # Known company office cities (where employee is typically based unless on trip)
    "office_locations": ["Mumbai", "Bengaluru", "Delhi"]
}
