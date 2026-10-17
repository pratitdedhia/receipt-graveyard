# seed_data.py - Realistic 1-Month Hackathon Dataset (October 2026) for Receipt Graveyard

import json
from datetime import datetime

def get_seed_dataset():
    """
    Returns 24 richly varied receipts across 5 employees for October 2026.
    Explicitly covers every single condition in the problem statement:
    - Layered rules & trip vs local office meals
    - City daily limit accumulation & partial capping
    - Non-reimbursable alcohol & itemized deductions
    - Missing client/attendee details
    - Exact file duplicate (cross-channel: Web vs Email)
    - Perceptual image duplicate
    - Cross-employee collusion duplicate
    - Split-transaction / smurfing to evade rules
    - Math discrepancies (subtotal + tax != total)
    - Currency conversions (USD, EUR, GBP, AED)
    - High-value approval thresholds (> ₹10,000)
    - Weekend out-of-policy claims
    - Stale / expired submissions (> 60 days old)
    - Claim inflation discrepancy (OCR total < claimed total)
    """
    return [
        # --- Week 1: Clean & Standard Submissions ---
        {
            "employee": "Aarav Mehta",
            "submitted_at": "2026-10-02 09:30",
            "expense_date": "2026-10-02",
            "merchant": "Theobroma Bakery",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 780,
            "currency": "INR",
            "amount_inr": 780,
            "client_name": "Acme Corp Tech Review",
            "attendees": 2,
            "description": "Client coffee and pastry meeting discussing Q4 renewal",
            "status": "Approved",
            "reimbursable": 780,
            "risk_score": 0,
            "flags": [],
            "suspicion_types": [],
            "explanation": "Within local meal cap; valid client name and attendee count provided.",
            "file_name": "sample_receipt_theobroma.png",
            "file_hash": "hash_theobroma_001",
            "perceptual_hash": "a1b2c3d4e5f60101",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified (Subtotal + Taxes + Tip = Total)",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 780
        },
        {
            "employee": "Nina Patel",
            "submitted_at": "2026-10-02 14:15",
            "expense_date": "2026-10-02",
            "merchant": "Delhi Metro Rail Corp",
            "category": "Travel",
            "city": "Delhi",
            "amount": 420,
            "currency": "INR",
            "amount_inr": 420,
            "client_name": "",
            "attendees": 0,
            "description": "Airport express metro token for supplier meeting",
            "status": "Approved",
            "reimbursable": 420,
            "risk_score": 0,
            "flags": [],
            "suspicion_types": [],
            "explanation": "Within travel category cap and Delhi daily limits.",
            "file_name": "sample_metro_delhi.png",
            "file_hash": "hash_metro_delhi_002",
            "perceptual_hash": "b2c3d4e5f6a10202",
            "source": "Mobile App",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 420
        },

        # --- Exact Duplicate Submitted via Email ---
        {
            "employee": "Aarav Mehta",
            "submitted_at": "2026-10-03 11:20",
            "expense_date": "2026-10-02",
            "merchant": "Theobroma Bakery",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 780,
            "currency": "INR",
            "amount_inr": 780,
            "client_name": "Acme Corp Tech Review",
            "attendees": 2,
            "description": "Forwarding coffee bill again just in case",
            "status": "Duplicate",
            "reimbursable": 0,
            "risk_score": 95,
            "flags": ["Exact duplicate receipt detected: matches your prior expense #1 (submitted via Web Upload)"],
            "suspicion_types": ["Exact File Duplicate"],
            "explanation": "Exact duplicate detected using receipt SHA-256 fingerprint. Reimbursable amount set to ₹0.00.",
            "file_name": "sample_receipt_theobroma_copy.png",
            "file_hash": "hash_theobroma_001",
            "perceptual_hash": "a1b2c3d4e5f60101",
            "source": "Email Forward",
            "is_trip": 0,
            "duplicate_of_id": 1,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 780
        },

        # --- Missing Client Details on High-Value Meal ---
        {
            "employee": "Kabir Rao",
            "submitted_at": "2026-10-04 18:40",
            "expense_date": "2026-10-04",
            "merchant": "Skyline Bistro",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 1460,
            "currency": "INR",
            "amount_inr": 1460,
            "client_name": "",
            "attendees": 0,
            "description": "Team dinner after product launch",
            "status": "Needs Info",
            "reimbursable": 1460,
            "risk_score": 30,
            "flags": [
                "Client name required for meals above ₹1,200",
                "Attendee count required for meals above ₹1,000"
            ],
            "suspicion_types": ["Missing Required Compliance Fields"],
            "explanation": "Claim exceeds ₹1,200 meal threshold. Returned to employee to provide client/project name and attendee count.",
            "file_name": "skyline_bistro_dinner.jpg",
            "file_hash": "hash_skyline_004",
            "perceptual_hash": "c3d4e5f6a1b20303",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Single Total Found",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1460
        },

        # --- Category Cap Exceeded (Accommodation) ---
        {
            "employee": "Isha Shah",
            "submitted_at": "2026-10-05 10:15",
            "expense_date": "2026-10-04",
            "merchant": "The Orchid Luxury Hotel",
            "category": "Accommodation",
            "city": "Mumbai",
            "amount": 9200,
            "currency": "INR",
            "amount_inr": 9200,
            "client_name": "Architecture Review",
            "attendees": 1,
            "description": "One night business stay in Mumbai",
            "status": "Needs Review",
            "reimbursable": 7500,
            "risk_score": 45,
            "flags": [
                "Category cap exceeded: Accommodation capped at ₹7,500 (excess: ₹1,700.00)",
                "Manager approval required: claim is ₹9,200 (reimbursable ₹7,500)"
            ],
            "suspicion_types": ["Category Cap Overrun"],
            "explanation": "Accommodation claim exceeds the ₹7,500 category limit. Reimbursable amount is capped at ₹7,500.00.",
            "file_name": "orchid_hotel_bill.pdf",
            "file_hash": "hash_orchid_005",
            "perceptual_hash": None,
            "source": "Email Forward",
            "is_trip": 1,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 9200
        },

        # --- Non-Reimbursable Category (Entertainment with ₹0 Cap) ---
        {
            "employee": "Kabir Rao",
            "submitted_at": "2026-10-06 23:10",
            "expense_date": "2026-10-06",
            "merchant": "Night Owl Lounge",
            "category": "Entertainment",
            "city": "Mumbai",
            "amount": 2600,
            "currency": "INR",
            "amount_inr": 2600,
            "client_name": "Acme Partners",
            "attendees": 4,
            "description": "Drinks and cocktails with potential clients",
            "status": "Rejected",
            "reimbursable": 0,
            "risk_score": 95,
            "flags": [
                "Entertainment is non-reimbursable under standard policy (cap is ₹0)",
                "Potential non-reimbursable item detected: 'cocktail'"
            ],
            "suspicion_types": ["Policy Disallowed Category"],
            "explanation": "Entertainment expenses have a ₹0 reimbursement cap under company policy. Entire claim rejected.",
            "file_name": "night_owl_receipt.jpg",
            "file_hash": "hash_nightowl_006",
            "perceptual_hash": "d4e5f6a1b2c30404",
            "source": "Mobile App",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 2600,
            "extracted_amount": 2600
        },

        # --- Itemized Bill with Alcohol Deduction (Partial Reimbursement) ---
        {
            "employee": "Isha Shah",
            "submitted_at": "2026-10-07 19:45",
            "expense_date": "2026-10-07",
            "merchant": "Toit Brewpub & Kitchen",
            "category": "Meals",
            "city": "Bengaluru",
            "amount": 2100,
            "currency": "INR",
            "amount_inr": 2100,
            "client_name": "Fintech Design Sprint",
            "attendees": 2,
            "description": "Dinner with lead client architect: Woodfired Pizza, Pasta, and 2 Craft Beers",
            "status": "Needs Review",
            "reimbursable": 1500,
            "risk_score": 45,
            "flags": [
                "Non-reimbursable line item deducted: 2x Craft Beers (-₹600.00)",
                "Food subtotal ₹1,500 approved within meal guidelines"
            ],
            "suspicion_types": ["Non-Reimbursable Item Extracted"],
            "explanation": "Itemized OCR detected ₹600.00 of alcoholic beverages. Deducted ₹600.00; approved food portion of ₹1,500.00.",
            "file_name": "toit_dinner_bill.png",
            "file_hash": "hash_toit_007",
            "perceptual_hash": "e5f6a1b2c3d40505",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified (Subtotal + Taxes + Tip = Total)",
            "non_reimbursable_deduction": 600,
            "extracted_amount": 2100
        },

        # --- Office Supplies Cap & Monthly Accumulation ---
        {
            "employee": "Isha Shah",
            "submitted_at": "2026-10-08 11:30",
            "expense_date": "2026-10-08",
            "merchant": "OfficeMart Tech",
            "category": "Office Supplies",
            "city": "Bengaluru",
            "amount": 3350,
            "currency": "INR",
            "amount_inr": 3350,
            "client_name": "",
            "attendees": 0,
            "description": "Ergonomic keyboard, mousepad, and USB-C adapters",
            "status": "Needs Review",
            "reimbursable": 3000,
            "risk_score": 35,
            "flags": ["Category cap exceeded: Office Supplies capped at ₹3,000 (excess: ₹350.00)"],
            "suspicion_types": ["Category Cap Overrun"],
            "explanation": "Claim exceeds the ₹3,000 single-expense office supplies limit. Reimbursable amount capped at ₹3,000.00.",
            "file_name": "officemart_receipt.pdf",
            "file_hash": "hash_officemart_008",
            "perceptual_hash": None,
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 3350
        },
        {
            "employee": "Isha Shah",
            "submitted_at": "2026-10-14 16:10",
            "expense_date": "2026-10-14",
            "merchant": "Chroma Electronics",
            "category": "Office Supplies",
            "city": "Bengaluru",
            "amount": 3200,
            "currency": "INR",
            "amount_inr": 3200,
            "client_name": "",
            "attendees": 0,
            "description": "HDMI switcher and multi-port hub for team presentation",
            "status": "Needs Review",
            "reimbursable": 2650,
            "risk_score": 40,
            "flags": [
                "Monthly employee budget exceeded: Prior office supplies ₹3,350 + this claim ₹3,200 exceeds ₹6,000 monthly limit",
                "Capped at remaining monthly budget allowance of ₹2,650.00"
            ],
            "suspicion_types": ["Monthly Budget Cap Breach"],
            "explanation": "Employee monthly office supplies budget of ₹6,000 is reached. Capped claim to remaining ₹2,650.00.",
            "file_name": "croma_electronics.jpg",
            "file_hash": "hash_croma_009",
            "perceptual_hash": "f6a1b2c3d4e50606",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 3200
        },

        # --- Business Trip: Aarav Mehta 3-Day Trip to Delhi (Oct 10 - Oct 12) ---
        {
            "employee": "Aarav Mehta",
            "submitted_at": "2026-10-10 08:00",
            "expense_date": "2026-10-10",
            "merchant": "IndiGo Airlines",
            "category": "Travel",
            "city": "Delhi",
            "amount": 8200,
            "currency": "INR",
            "amount_inr": 8200,
            "client_name": "Ministry of IT Pilot",
            "attendees": 1,
            "description": "Flight BOM -> DEL for client pilot deployment",
            "status": "Approved",
            "reimbursable": 8200,
            "risk_score": 0,
            "flags": [],
            "suspicion_types": [],
            "explanation": "Compliant intercity travel within ₹9,000 travel cap.",
            "file_name": "indigo_flight_ticket.pdf",
            "file_hash": "hash_flight_indigo_010",
            "perceptual_hash": None,
            "source": "Email Forward",
            "is_trip": 1,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 8200
        },
        {
            "employee": "Aarav Mehta",
            "submitted_at": "2026-10-10 13:30",
            "expense_date": "2026-10-10",
            "merchant": "Bukhara - ITC Maurya",
            "category": "Meals",
            "city": "Delhi",
            "amount": 2100,
            "currency": "INR",
            "amount_inr": 2100,
            "client_name": "Govt IT Committee",
            "attendees": 3,
            "description": "Lunch with client delegation during pilot rollout",
            "status": "Approved",
            "reimbursable": 2100,
            "risk_score": 0,
            "flags": [],
            "suspicion_types": [],
            "explanation": "Trip meal within Delhi travel per-diem. Client and 3 attendees noted (₹700/attendee < ₹1,800 limit).",
            "file_name": "bukhara_lunch_receipt.jpg",
            "file_hash": "hash_bukhara_011",
            "perceptual_hash": "a2b3c4d5e6f10707",
            "source": "Mobile App",
            "is_trip": 1,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 2100
        },
        # Same day, second expense in Delhi: Cabs ₹650 -> Total Delhi day spend = ₹2,750 vs ₹2,400 daily limit!
        {
            "employee": "Aarav Mehta",
            "submitted_at": "2026-10-10 20:15",
            "expense_date": "2026-10-10",
            "merchant": "BluSmart Electric Mobility",
            "category": "Travel",
            "city": "Delhi",
            "amount": 650,
            "currency": "INR",
            "amount_inr": 650,
            "client_name": "",
            "attendees": 0,
            "description": "Cabs across Delhi Secretariat and hotel",
            "status": "Needs Review",
            "reimbursable": 300,
            "risk_score": 30,
            "flags": [
                "City daily limit exceeded: Delhi daily cap is ₹2,400 (prior claims today: ₹2,100)",
                "Claim of ₹650 capped to remaining ₹300 daily per-diem allowance"
            ],
            "suspicion_types": ["Daily City Limit Overrun"],
            "explanation": "Total daily expenses in Delhi on 2026-10-10 reached ₹2,750.00. Capped this claim at the remaining ₹300.00 allowance.",
            "file_name": "blusmart_delhi_cab.pdf",
            "file_hash": "hash_blusmart_012",
            "perceptual_hash": None,
            "source": "Web Upload",
            "is_trip": 1,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 650
        },

        # --- Smurfing / Split Transaction to Evade Rules ---
        {
            "employee": "Kabir Rao",
            "submitted_at": "2026-10-11 19:40",
            "expense_date": "2026-10-11",
            "merchant": "Punjab Grill",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 1180,
            "currency": "INR",
            "amount_inr": 1180,
            "client_name": "",
            "attendees": 0,
            "description": "Starters and appetizers dinner",
            "status": "Needs Review",
            "reimbursable": 1180,
            "risk_score": 40,
            "flags": [
                "Split-transaction pattern: Multiple claims at Punjab Grill on 2026-10-11 total ₹2,330, appearing to avoid ₹1,200 client detail rule"
            ],
            "suspicion_types": ["Split Transaction / Smurfing"],
            "explanation": "Consecutive transactions at the same restaurant just below the ₹1,200 requirement threshold.",
            "file_name": "punjab_grill_bill_1.png",
            "file_hash": "hash_pgrill_013",
            "perceptual_hash": "b3c4d5e6f1a20808",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1180
        },
        {
            "employee": "Kabir Rao",
            "submitted_at": "2026-10-11 20:25",
            "expense_date": "2026-10-11",
            "merchant": "Punjab Grill",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 1150,
            "currency": "INR",
            "amount_inr": 1150,
            "client_name": "",
            "attendees": 0,
            "description": "Main course and dessert dinner",
            "status": "Needs Review",
            "reimbursable": 1150,
            "risk_score": 40,
            "flags": [
                "Split-transaction pattern: Multiple claims at Punjab Grill on 2026-10-11 total ₹2,330, appearing to avoid ₹1,200 client detail rule"
            ],
            "suspicion_types": ["Split Transaction / Smurfing"],
            "explanation": "Second bill from Punjab Grill 45 minutes after first bill. Combined total ₹2,330 requires client identification.",
            "file_name": "punjab_grill_bill_2.png",
            "file_hash": "hash_pgrill_014",
            "perceptual_hash": "c4d5e6f1a2b30909",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1150
        },

        # --- Receipt Math Error (Faded Thermal Receipt Discrepancy) ---
        {
            "employee": "Rohan Verma",
            "submitted_at": "2026-10-13 15:20",
            "expense_date": "2026-10-13",
            "merchant": "Mainland China Restaurant",
            "category": "Meals",
            "city": "Pune",
            "amount": 1450,
            "currency": "INR",
            "amount_inr": 1450,
            "client_name": "Pune Tech Partner",
            "attendees": 2,
            "description": "Client discussion lunch",
            "status": "Needs Review",
            "reimbursable": 1200,
            "risk_score": 55,
            "flags": [
                "Receipt math error: Discrepancy Detected (Expected ₹1,200.00 vs Stated ₹1,450.00)",
                "Subtotal ₹1,000 + CGST ₹50 + SGST ₹50 + Tip ₹100 totals ₹1,200; handwriting added extra ₹250"
            ],
            "suspicion_types": ["Receipt Math Mismatch", "Potential Tampering"],
            "explanation": "Calculated item total + taxes is ₹1,200.00, but stated grand total was ₹1,450.00. Reimbursable adjusted to verified math total of ₹1,200.00.",
            "file_name": "faded_thermal_math_error.jpg",
            "file_hash": "hash_faded_math_015",
            "perceptual_hash": "d5e6f1a2b3c41010",
            "source": "Mobile App",
            "is_trip": 0,
            "math_status": "Discrepancy Detected (Expected ₹1,200.00 vs Stated ₹1,450.00)",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1200
        },

        # --- Perceptual Image Duplicate (Re-photographed at Angle / Cropped) ---
        {
            "employee": "Rohan Verma",
            "submitted_at": "2026-10-15 11:00",
            "expense_date": "2026-10-13",
            "merchant": "Mainland China",
            "category": "Meals",
            "city": "Pune",
            "amount": 1450,
            "currency": "INR",
            "amount_inr": 1450,
            "client_name": "Pune Tech Partner",
            "attendees": 2,
            "description": "Re-uploading receipt from photo gallery",
            "status": "Duplicate",
            "reimbursable": 0,
            "risk_score": 90,
            "flags": [
                "Visual duplicate detected: receipt image matches expense #15 (visual diff: 2/64 bits)"
            ],
            "suspicion_types": ["Perceptual Duplicate"],
            "explanation": "Perceptual dHash algorithm detected visual duplicate of expense #15 (re-photographed/cropped). Reimbursable set to ₹0.00.",
            "file_name": "faded_thermal_rephoto_cropped.jpg",
            "file_hash": "hash_faded_cropped_016",
            "perceptual_hash": "d5e6f1a2b3c41012",
            "source": "Web Upload",
            "is_trip": 0,
            "duplicate_of_id": 15,
            "math_status": "Discrepancy Detected",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1200
        },

        # --- Cross-Employee Collusion Duplicate ---
        {
            "employee": "Nina Patel",
            "submitted_at": "2026-10-16 12:40",
            "expense_date": "2026-10-04",
            "merchant": "Skyline Bistro",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 1460,
            "currency": "INR",
            "amount_inr": 1460,
            "client_name": "Acme Partner Dinner",
            "attendees": 2,
            "description": "Dinner at Skyline Bistro in Mumbai",
            "status": "Duplicate",
            "reimbursable": 0,
            "risk_score": 95,
            "flags": [
                "COLLUSION ALERT: Receipt matches identical claim previously submitted by Kabir Rao (#4)",
                "Cross-employee double claim detected on same date and merchant"
            ],
            "suspicion_types": ["Cross-Employee Collusion", "Double Reimbursement"],
            "explanation": "Flagged for finance investigation: Two different employees submitted the exact same dinner bill.",
            "file_name": "skyline_bistro_dinner.jpg",
            "file_hash": "hash_skyline_004",
            "perceptual_hash": "c3d4e5f6a1b20303",
            "source": "Web Upload",
            "is_trip": 1,
            "duplicate_of_id": 4,
            "math_status": "Single Total Found",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1460
        },

        # --- International Currencies & Multi-Tier Approvals ---
        {
            "employee": "Nina Patel",
            "submitted_at": "2026-10-17 17:30",
            "expense_date": "2026-10-17",
            "merchant": "Hilton London Paddington",
            "category": "Accommodation",
            "city": "London",
            "amount": 140,
            "currency": "GBP",
            "amount_inr": 14700,
            "client_name": "UK Banking Forum",
            "attendees": 1,
            "description": "Hotel accommodation in London during UK Fintech summit (£140 @ 105.00)",
            "status": "Needs Review",
            "reimbursable": 12600,
            "risk_score": 50,
            "flags": [
                "London city daily accommodation cap applied: £120 / ₹12,600 (excess: ₹2,100.00)",
                "VP / Director approval required: claim total ₹14,700 crosses ₹10,000 threshold",
                "Foreign currency conversion: GBP 140.00 @ 105.00 INR/GBP"
            ],
            "suspicion_types": ["Executive Approval Required", "Foreign Currency Audit"],
            "explanation": "High-value international expense converted at demo rate. Capped at London daily per-diem of ₹12,600. Requires VP approval sign-off.",
            "file_name": "hilton_london_invoice.pdf",
            "file_hash": "hash_hilton_uk_018",
            "perceptual_hash": None,
            "source": "Email Forward",
            "is_trip": 1,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 140
        },
        {
            "employee": "Aarav Mehta",
            "submitted_at": "2026-10-19 14:00",
            "expense_date": "2026-10-19",
            "merchant": "Marriott Marquis Times Square",
            "category": "Accommodation",
            "city": "New York",
            "amount": 180,
            "currency": "USD",
            "amount_inr": 15030,
            "client_name": "Global Partner Summit",
            "attendees": 1,
            "description": "Conference hotel in New York ($180 @ 83.50)",
            "status": "Needs Review",
            "reimbursable": 12500,
            "risk_score": 50,
            "flags": [
                "New York daily cap applied: $150 / ₹12,500 (excess: ₹2,530.00)",
                "VP / Director approval required: claim total ₹15,030 crosses ₹10,000 threshold",
                "Foreign currency conversion: USD 180.00 @ 83.50 INR/USD"
            ],
            "suspicion_types": ["Executive Approval Required", "Foreign Currency Audit"],
            "explanation": "New York accommodation converted to ₹15,030.00. Capped at New York daily ceiling of ₹12,500.00. Requires executive sign-off.",
            "file_name": "marriott_nyc_invoice.pdf",
            "file_hash": "hash_marriott_nyc_019",
            "perceptual_hash": None,
            "source": "Web Upload",
            "is_trip": 1,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 180
        },

        # --- Weekend Expense Out of Policy ---
        {
            "employee": "Kabir Rao",
            "submitted_at": "2026-10-25 21:00",
            "expense_date": "2026-10-25",
            "merchant": "Bastian Bandra",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 2800,
            "currency": "INR",
            "amount_inr": 2800,
            "client_name": "",
            "attendees": 0,
            "description": "Sunday seafood dinner",
            "status": "Needs Info",
            "reimbursable": 1200,
            "risk_score": 60,
            "flags": [
                "Weekend expense on Sunday: Requires trip context or manager overtime verification",
                "Local meal cap exceeded: Home office meal capped at ₹1,200 (claimed ₹2,800)",
                "Client name required for meals above ₹1,200",
                "Attendee count required for meals above ₹1,000"
            ],
            "suspicion_types": ["Weekend Non-Travel Expense", "Missing Business Justification"],
            "explanation": "Sunday meal in home city without business trip or client justification. Reimbursable capped at ₹1,200 pending weekend overtime explanation.",
            "file_name": "bastian_sunday_dinner.jpg",
            "file_hash": "hash_bastian_020",
            "perceptual_hash": "e6f1a2b3c4d51111",
            "source": "Mobile App",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 2800
        },

        # --- Stale Submission (> 60 Days Old) ---
        {
            "employee": "Rohan Verma",
            "submitted_at": "2026-10-26 10:20",
            "expense_date": "2026-07-15",
            "merchant": "Pune Car Rentals",
            "category": "Travel",
            "city": "Pune",
            "amount": 2400,
            "currency": "INR",
            "amount_inr": 2400,
            "client_name": "",
            "attendees": 0,
            "description": "Forgot to submit July site inspection taxi",
            "status": "Needs Review",
            "reimbursable": 2400,
            "risk_score": 35,
            "flags": [
                "Stale claim: Expense is 103 days old (exceeds 60-day submission policy window)",
                "Requires manager policy exception approval for late reimbursement"
            ],
            "suspicion_types": ["Stale / Expired Submission"],
            "explanation": "Submitted 103 days after occurrence. Policy requires reimbursement within 60 days. Escalated for finance exception approval.",
            "file_name": "pune_car_july.png",
            "file_hash": "hash_pune_car_021",
            "perceptual_hash": "f1a2b3c4d5e61212",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 2400
        },

        # --- Claim Inflation Discrepancy (OCR found ₹1,250 but User Claimed ₹2,500) ---
        {
            "employee": "Rohan Verma",
            "submitted_at": "2026-10-27 16:30",
            "expense_date": "2026-10-27",
            "merchant": "Kalyan Bhel & Snacks",
            "category": "Meals",
            "city": "Pune",
            "amount": 2500,
            "currency": "INR",
            "amount_inr": 2500,
            "client_name": "Supplier Meeting",
            "attendees": 2,
            "description": "Snacks and catering for vendor team",
            "status": "Needs Review",
            "reimbursable": 1250,
            "risk_score": 70,
            "flags": [
                "Claim inflation discrepancy: Claimed ₹2,500.00 exceeds receipt OCR total of ₹1,250.00 by ₹1,250.00",
                "Potential alteration or padded claim flagged for manual audit"
            ],
            "suspicion_types": ["Claim Inflation", "Receipt Discrepancy"],
            "explanation": "OCR audit detected receipt total of ₹1,250.00 while user typed ₹2,500.00. Adjusted reimbursement to verified receipt value of ₹1,250.00.",
            "file_name": "kalyan_snacks_receipt.jpg",
            "file_hash": "hash_kalyan_022",
            "perceptual_hash": "a3b4c5d6e1f21313",
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Discrepancy Detected (Expected ₹1,250.00 vs Stated ₹2,500.00)",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1250
        },

        # --- Compliant High-Performance Trip Expense ---
        {
            "employee": "Nina Patel",
            "submitted_at": "2026-10-28 11:15",
            "expense_date": "2026-10-28",
            "merchant": "Starbucks Coffee",
            "category": "Meals",
            "city": "Delhi",
            "amount": 540,
            "currency": "INR",
            "amount_inr": 540,
            "client_name": "Briefing",
            "attendees": 1,
            "description": "Morning coffee before supplier review",
            "status": "Approved",
            "reimbursable": 540,
            "risk_score": 0,
            "flags": [],
            "suspicion_types": [],
            "explanation": "Fully compliant with meal and per-diem policy.",
            "file_name": "starbucks_delhi.png",
            "file_hash": "hash_starbucks_023",
            "perceptual_hash": "b4c5d6e1f2a31414",
            "source": "Mobile App",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 540
        },
        {
            "employee": "Aarav Mehta",
            "submitted_at": "2026-10-29 19:00",
            "expense_date": "2026-10-29",
            "merchant": "Oberoi Trident",
            "category": "Meals",
            "city": "Mumbai",
            "amount": 1750,
            "currency": "INR",
            "amount_inr": 1750,
            "client_name": "Fintech Enterprise Deal",
            "attendees": 2,
            "description": "Closing dinner with VP Technology",
            "status": "Approved",
            "reimbursable": 1750,
            "risk_score": 0,
            "flags": [],
            "suspicion_types": [],
            "explanation": "Valid client name provided; attendee spend ₹875/person within policy; approved.",
            "file_name": "oberoi_trident_dinner.pdf",
            "file_hash": "hash_oberoi_024",
            "perceptual_hash": None,
            "source": "Web Upload",
            "is_trip": 0,
            "math_status": "Verified",
            "non_reimbursable_deduction": 0,
            "extracted_amount": 1750
        }
    ]

def seed_offices(con):
    con.execute("DELETE FROM offices")
    try: con.execute("DELETE FROM sqlite_sequence WHERE name='offices'")
    except Exception: pass

    offices = [
        (1, "Mumbai Corporate HQ", "Mumbai", "Maharashtra", "Level 14, Nariman Point, Mumbai 400021", 1, 1200.0),
        (2, "Bengaluru Technology Center", "Bengaluru", "Karnataka", "Outer Ring Road, Bellandur, Bengaluru 560103", 0, 1200.0),
        (3, "Delhi NCR Regional Hub", "Delhi", "Delhi NCR", "Connaught Place, Barakhamba Road, New Delhi 110001", 0, 1200.0),
        (4, "Pune Innovation Labs", "Pune", "Maharashtra", "Viman Nagar Business Bay, Pune 411014", 0, 1000.0),
        (5, "Hyderabad Tech Park", "Hyderabad", "Telangana", "HITEC City Phase 2, Hyderabad 500081", 0, 1000.0)
    ]
    for o in offices:
        con.execute("""
        INSERT INTO offices (id, name, city, state, address, is_headquarters, local_meal_cap)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, o)
    con.commit()

def seed_users(con):
    con.execute("DELETE FROM users")
    try: con.execute("DELETE FROM sqlite_sequence WHERE name='users'")
    except Exception: pass

    users = [
        # (id, email, password, name, role, office_id, department, phone, avatar_color)
        (1, "admin@company.com", "admin123", "Rajesh Sharma", "admin", 1, "Executive Management", "+91 98200 11223", "#0f766e"),
        (2, "accounts@company.com", "accounts123", "Priya Nair", "accounts", 1, "Finance & Accounts", "+91 98200 44556", "#15803d"),
        (3, "audit@company.com", "audit123", "Vikram Sen", "accounts", 3, "Internal Audit & Risk", "+91 98100 77889", "#0369a1"),
        (4, "aarav@company.com", "employee123", "Aarav Mehta", "employee", 1, "Sales & Client Partnerships", "+91 98210 55667", "#b45309"),
        (5, "isha@company.com", "employee123", "Isha Shah", "employee", 2, "Core Engineering", "+91 98450 11223", "#7c3aed"),
        (6, "kabir@company.com", "employee123", "Kabir Rao", "employee", 1, "Growth & Marketing", "+91 98201 33445", "#c2410c"),
        (7, "nina@company.com", "employee123", "Nina Patel", "employee", 3, "Global Operations", "+91 98110 99887", "#4338ca"),
        (8, "rohan@company.com", "employee123", "Rohan Verma", "employee", 4, "Field Technology Consulting", "+91 98900 66778", "#0891b2")
    ]
    for u in users:
        con.execute("""
        INSERT INTO users (id, email, password, name, role, office_id, department, phone, avatar_color)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, u)
    con.commit()

def seed_database(con):
    """Populates the database with offices, users, and the rich October 2026 hackathon dataset."""
    seed_offices(con)
    seed_users(con)

    # User lookup by name
    user_map = {
        "Aarav Mehta": (4, 1),
        "Isha Shah": (5, 2),
        "Kabir Rao": (6, 1),
        "Nina Patel": (7, 3),
        "Rohan Verma": (8, 4)
    }

    # Payment screenshot mapping
    payment_map = {
        1: ("payment_theobroma_gpay.png", "Google Pay (UPI)", "428910283921", 1, "Verified: Google Pay payment of ₹780 matches bill total exactly. (UTR: 428910283921)"),
        4: ("payment_skyline_phonepe.png", "PhonePe (UPI)", "293810293810", 1, "Verified: PhonePe payment of ₹1,460 matches bill total. (Ref: 293810293810)"),
        7: ("payment_toit_paytm.png", "Paytm (UPI)", "981273918231", 1, "Verified: Paytm payment of ₹2,100 matches bill total (includes ₹600 alcohol)."),
        15: ("payment_mainland_gpay.png", "Google Pay (UPI)", "581920381920", 0, "DISCREPANCY: Payment screenshot shows ₹1,200 but user claimed ₹1,450 (diff: -₹250.00).")
    }

    dataset = get_seed_dataset()
    con.execute("DELETE FROM expenses")
    try: con.execute("DELETE FROM sqlite_sequence WHERE name='expenses'")
    except Exception: pass

    for idx, r in enumerate(dataset, 1):
        u_info = user_map.get(r["employee"], (4, 1))
        u_id, o_id = u_info

        pay_info = payment_map.get(idx, (None, "Corporate Card" if r["amount_inr"] > 5000 else "UPI", None, 1 if r["status"] == "Approved" else 0, "Bill verified; payment proof recorded." if r["status"] == "Approved" else "Payment proof pending verification."))
        pay_file, pay_method, txn_ref, pay_verified, pay_note = pay_info

        con.execute("""
        INSERT INTO expenses (
            user_id, office_id, employee, submitted_at, expense_date, merchant, category, city, amount, currency,
            amount_inr, client_name, attendees, attendee_names, project_code, description, status, reimbursable, risk_score,
            flags, suspicion_types, explanation, file_name, file_hash, perceptual_hash,
            payment_file, payment_method, transaction_ref, payment_verified, payment_match_note,
            source, is_trip, math_status, non_reimbursable_deduction, extracted_amount,
            audit_log
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            u_id, o_id, r["employee"], r["submitted_at"], r["expense_date"], r["merchant"], r["category"], r["city"],
            r["amount"], r["currency"], r["amount_inr"], r.get("client_name", ""), r.get("attendees", 0),
            "Aarav Mehta, Rohit Sen" if r.get("attendees", 0) > 1 else r["employee"],
            "PRJ-2026-Q4",
            r.get("description", ""), r["status"], r["reimbursable"], r["risk_score"],
            json.dumps(r.get("flags", [])), json.dumps(r.get("suspicion_types", [])),
            r["explanation"], r.get("file_name"), r.get("file_hash"), r.get("perceptual_hash"),
            pay_file, pay_method, txn_ref, pay_verified, pay_note,
            r.get("source", "Web Upload"), r.get("is_trip", 0), r.get("math_status", "Verified"),
            r.get("non_reimbursable_deduction", 0.0), r.get("extracted_amount", r["amount_inr"]),
            json.dumps([{"action": "Initial Audit", "status": r["status"], "timestamp": r["submitted_at"], "actor": "AI Policy Auditor"}])
        ))
    con.commit()

