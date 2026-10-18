# scripts/create_sample_receipts.py - Generates realistic synthetic receipt images for the demo
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import random

repo_root = Path(__file__).resolve().parent.parent
UPLOAD_DIR = repo_root / "uploads" if (repo_root / "uploads").exists() else Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

def generate_receipt_image(filename, merchant, date_str, items, total_str, subtotal_str=None, tax_str=None, tip_str=None, is_faded=False, note=""):
    width, height = 480, 680
    bg_color = (248, 246, 240) if not is_faded else (235, 230, 220)
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Use default bitmap font or basic drawing
    # Draw header
    draw.rectangle([10, 10, width-10, height-10], outline=(200, 195, 185), width=2)
    
    # Store title
    text_color = (30, 30, 30) if not is_faded else (130, 125, 115)
    faded_color = (100, 100, 100) if not is_faded else (160, 155, 145)

    y = 30
    draw.text((width//2 - len(merchant)*4, y), merchant.upper(), fill=text_color)
    y += 24
    draw.text((width//2 - 60, y), "TAX INVOICE / RECEIPT", fill=faded_color)
    y += 18
    draw.text((width//2 - 50, y), f"DATE: {date_str}", fill=faded_color)
    y += 25
    draw.line([(30, y), (width - 30, y)], fill=(180, 180, 180), width=1)
    y += 15

    # Items table header
    draw.text((35, y), "ITEM", fill=faded_color)
    draw.text((width - 95, y), "AMOUNT", fill=faded_color)
    y += 20
    draw.line([(30, y), (width - 30, y)], fill=(210, 210, 210), width=1)
    y += 15

    # Items
    for name, price in items:
        draw.text((35, y), name, fill=text_color)
        p_str = f"{price:.2f}"
        draw.text((width - 35 - len(p_str)*7, y), p_str, fill=text_color)
        y += 24

    y += 10
    draw.line([(30, y), (width - 30, y)], fill=(180, 180, 180), width=1)
    y += 15

    # Subtotals
    if subtotal_str:
        draw.text((width - 200, y), "SUBTOTAL:", fill=faded_color)
        draw.text((width - 35 - len(subtotal_str)*7, y), subtotal_str, fill=text_color)
        y += 20
    if tax_str:
        draw.text((width - 200, y), "GST / TAX:", fill=faded_color)
        draw.text((width - 35 - len(tax_str)*7, y), tax_str, fill=text_color)
        y += 20
    if tip_str:
        draw.text((width - 200, y), "SERVICE/TIP:", fill=faded_color)
        draw.text((width - 35 - len(tip_str)*7, y), tip_str, fill=text_color)
        y += 20

    y += 5
    draw.line([(30, y), (width - 30, y)], fill=(120, 120, 120), width=2)
    y += 15

    # Grand Total
    draw.text((35, y), "TOTAL AMOUNT DUE", fill=text_color)
    draw.text((width - 35 - len(total_str)*9, y), total_str, fill=text_color)
    y += 35

    if note:
        draw.text((35, y), note, fill=(150, 80, 80))
        y += 25

    draw.line([(30, y), (width - 30, y)], fill=(210, 210, 210), width=1)
    y += 20
    draw.text((width//2 - 60, y), "*** THANK YOU ***", fill=faded_color)
    y += 20
    draw.text((width//2 - 75, y), "GSTIN: 27AABCT9876C1Z5", fill=faded_color)

    # Simulated barcode
    y += 35
    for i in range(40):
        bar_w = random.choice([2, 4, 1])
        draw.rectangle([60 + i*9, y, 60 + i*9 + bar_w, y + 35], fill=text_color)

    if is_faded:
        img = img.filter(ImageFilter.GaussianBlur(radius=0.5))

    out_file = UPLOAD_DIR / filename
    img.save(out_file)
    return out_file

def build_all():
    # 1. Theobroma Bakery
    generate_receipt_image(
        "sample_receipt_theobroma.png",
        "Theobroma Bakery",
        "2026-10-02",
        [("2x Cappuccino Grande", 380.0), ("1x Walnut Brownie", 220.0), ("1x Butter Croissant", 180.0)],
        "780.00",
        subtotal_str="780.00"
    )
    # Duplicate copy
    generate_receipt_image(
        "sample_receipt_theobroma_copy.png",
        "Theobroma Bakery",
        "2026-10-02",
        [("2x Cappuccino Grande", 380.0), ("1x Walnut Brownie", 220.0), ("1x Butter Croissant", 180.0)],
        "780.00",
        subtotal_str="780.00"
    )

    # 2. Delhi Metro
    generate_receipt_image(
        "sample_metro_delhi.png",
        "Delhi Metro Rail Corp",
        "2026-10-02",
        [("1x Airport Express Token", 420.0)],
        "420.00"
    )

    # 3. Skyline Bistro Dinner
    generate_receipt_image(
        "skyline_bistro_dinner.jpg",
        "Skyline Bistro & Bar",
        "2026-10-04",
        [("1x Grilled Salmon", 650.0), ("1x Truffle Pasta", 520.0), ("1x Mineral Water", 110.0), ("1x Tiramisu", 180.0)],
        "1,460.00",
        subtotal_str="1,460.00"
    )

    # 4. Toit Brewpub (Itemized with Alcohol)
    generate_receipt_image(
        "toit_dinner_bill.png",
        "Toit Brewpub & Kitchen",
        "2026-10-07",
        [("1x Sourdough Pizza", 750.0), ("1x Peri Peri Chicken", 600.0), ("1x Garlic Bread", 150.0), ("2x Craft Beer Pint", 600.0)],
        "2,100.00",
        subtotal_str="2,100.00",
        note="* Non-reimbursable alcohol items: Craft Beer Pint (Rs. 600)"
    )

    # 5. Faded Thermal Receipt with Math Discrepancy
    generate_receipt_image(
        "faded_thermal_math_error.jpg",
        "Mainland China Restaurant",
        "2026-10-13",
        [("1x Dimsum Platter", 450.0), ("1x Hakka Noodles", 350.0), ("1x Kung Pao Paneer", 200.0)],
        "1,450.00",
        subtotal_str="1,000.00",
        tax_str="100.00",
        tip_str="100.00",
        is_faded=True,
        note="Math error: 1000 + 100 + 100 = 1,200 (Stated: 1,450)"
    )

    # 6. Re-photographed / Cropped version of Mainland China
    generate_receipt_image(
        "faded_thermal_rephoto_cropped.jpg",
        "Mainland China Restaurant",
        "2026-10-13",
        [("1x Dimsum Platter", 450.0), ("1x Hakka Noodles", 350.0), ("1x Kung Pao Paneer", 200.0)],
        "1,450.00",
        subtotal_str="1,000.00",
        tax_str="100.00",
        tip_str="100.00",
        is_faded=True
    )

    # 7. Punjab Grill Split Bills
    generate_receipt_image(
        "punjab_grill_bill_1.png",
        "Punjab Grill Restaurant",
        "2026-10-11",
        [("1x Dahi Ke Kebab", 480.0), ("1x Paneer Tikka", 550.0), ("1x Roti Basket", 150.0)],
        "1,180.00",
        subtotal_str="1,180.00"
    )
    generate_receipt_image(
        "punjab_grill_bill_2.png",
        "Punjab Grill Restaurant",
        "2026-10-11",
        [("1x Dal Makhani", 450.0), ("1x Butter Naan x2", 300.0), ("2x Gulab Jamun", 400.0)],
        "1,150.00",
        subtotal_str="1,150.00"
    )

    # 8. Kalyan Snacks (Claim Inflation)
    generate_receipt_image(
        "kalyan_snacks_receipt.jpg",
        "Kalyan Bhel & Snacks",
        "2026-10-27",
        [("5x Special Bhel Puri", 450.0), ("5x Sev Puri", 400.0), ("10x Cutting Chai", 250.0), ("Packaged Sweets", 150.0)],
        "1,250.00",
        subtotal_str="1,250.00",
        note="Actual receipt total is 1,250 (Claimed: 2,500)"
    )

    # 9. Bastian Bandra Sunday Dinner
    generate_receipt_image(
        "bastian_sunday_dinner.jpg",
        "Bastian Bandra",
        "2026-10-25",
        [("1x Lobster Roll", 1400.0), ("1x Avocado Salad", 750.0), ("1x Mocktail", 450.0), ("Service Charge", 200.0)],
        "2,800.00",
        subtotal_str="2,600.00",
        tip_str="200.00"
    )

    # 10. Starbucks Delhi
    generate_receipt_image(
        "starbucks_delhi.png",
        "Starbucks Coffee Delhi",
        "2026-10-28",
        [("1x Caramel Macchiato", 340.0), ("1x Blueberry Muffin", 200.0)],
        "540.00",
        subtotal_str="540.00"
    )

    # --- SYNTHETIC PAYMENT SCREENSHOTS (UPI & Card Slips) ---
    def generate_upi_screenshot(filename, app_name, payee, amount_str, date_str, utr_no, is_success=True):
        w, h = 420, 600
        # Dark modern fintech theme or clean card
        bg = (245, 247, 250)
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)

        # App banner
        banner_color = (25, 103, 210) if "Google" in app_name else ((95, 37, 159) if "PhonePe" in app_name else (0, 186, 242))
        draw.rectangle([0, 0, w, 70], fill=banner_color)
        draw.text((w//2 - len(app_name)*4, 25), app_name.upper(), fill=(255, 255, 255))

        # Checkmark circle
        y = 100
        draw.ellipse([w//2 - 30, y, w//2 + 30, y + 60], fill=(22, 163, 74))
        draw.text((w//2 - 8, y + 18), "✓", fill=(255, 255, 255))

        y += 75
        draw.text((w//2 - 60, y), "Payment Successful", fill=(20, 20, 20))
        y += 24
        draw.text((w//2 - 70, y), f"Paid to: {payee}", fill=(80, 80, 80))
        y += 30

        # Amount box
        draw.rectangle([30, y, w - 30, y + 80], fill=(255, 255, 255), outline=(210, 220, 230), width=1)
        draw.text((50, y + 15), "AMOUNT DEBITED", fill=(120, 130, 140))
        draw.text((50, y + 35), f"₹ {amount_str}", fill=(15, 23, 42))

        y += 105
        # Details
        draw.text((35, y), "TRANSACTION DETAILS", fill=(100, 110, 120))
        y += 22
        draw.line([(30, y), (w - 30, y)], fill=(210, 220, 230), width=1)
        y += 15

        details = [
            ("Date & Time", f"{date_str} 14:32 IST"),
            ("Payment Method", "UPI (Bank Account ending 4012)"),
            ("UPI Ref No (UTR)", utr_no),
            ("Status", "Completed"),
        ]
        for k, v in details:
            draw.text((35, y), k, fill=(110, 120, 130))
            draw.text((w - 35 - len(v)*7, y), v, fill=(20, 30, 40))
            y += 26

        y += 20
        draw.rectangle([50, y, w - 50, y + 40], fill=(230, 240, 255), outline=(180, 210, 250))
        draw.text((w//2 - 80, y + 12), "Official Transaction Receipt", fill=(30, 80, 160))

        out_path = UPLOAD_DIR / filename
        img.save(out_path)
        return out_path

    generate_upi_screenshot("payment_theobroma_gpay.png", "Google Pay", "Theobroma Bakery", "780.00", "02 Oct 2026", "428910283921")
    generate_upi_screenshot("payment_toit_paytm.png", "Paytm UPI", "Toit Brewpub", "2,100.00", "07 Oct 2026", "981273918231")
    generate_upi_screenshot("payment_skyline_phonepe.png", "PhonePe", "Skyline Bistro", "1,460.00", "04 Oct 2026", "293810293810")
    generate_upi_screenshot("payment_mainland_gpay.png", "Google Pay", "Mainland China", "1,200.00", "13 Oct 2026", "581920381920")

    print(f"All sample receipt images and payment screenshots successfully verified in {UPLOAD_DIR.resolve()}!")

if __name__ == "__main__":
    build_all()
