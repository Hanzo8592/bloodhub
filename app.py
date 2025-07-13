import streamlit as st
import random
import base64
import csv
import io
from datetime import datetime, timedelta
import pandas as pd
from utils import load_data, save_data, load_locations
import time

# ================== CONSTANTS ==================
KERALA_GOVT_HOSPITALS = [
    # Medical Colleges
    "Government Medical College, Thiruvananthapuram",
    "Government Medical College, Kottayam",
    "Government T D Medical College, Alappuzha",
    "Government Medical College, Thrissur",
    "Government Medical College, Kozhikode",
    "Government Medical College, Kannur",  # new addition :contentReference[oaicite:0]{index=0}

    # Major General / District Hospitals
    "General Hospital, Thiruvananthapuram",
    "Sree Avittom Thirunal Hospital (SAT Hospital), Thiruvananthapuram",
    "General Hospital, Kollam",
    "AA Rahim Memorial District Hospital, Kollam",
    "General Hospital, Pathanamthitta",
    "General Hospital, Adoor",
    "General Hospital, Alappuzha",
    "General Hospital, Kottayam",
    "General Hospital, Changanassery",
    "General Hospital, Kanjirappally",
    "Ernakulam General Hospital",
    "General Hospital, Muvattupuzha",
    "Thrissur General Hospital",
    "General Hospital, Irinjalakuda",
    "General Hospital, Malappuram (Manjeri)",
    "General Hospital, Kozhikode",
    "General Hospital, Kalpetta",
    "General Hospital, Thalassery",
    "General Hospital, Kasaragod",
    "District Hospital, Palakkad",
    "District Hospital, Malappuram",
    "District Hospital, Idukki"  # new addition :contentReference[oaicite:1]{index=1}
]

KERALA_BLOOD_BANKS = [
    "Indian Red Cross Society Blood Bank, Thiruvananthapuram",
    "Government Medical College Blood Bank, Thiruvananthapuram",
    "Government General Hospital Blood Bank, Thiruvananthapuram",   # GH Thiruvananthapuram :contentReference[oaicite:2]{index=2}
    "Regional Cancer Centre Blood Bank, Thiruvananthapuram",       # RCC Ulloor :contentReference[oaicite:3]{index=3}
    "General Hospital Blood Bank, Kollam",
    "Government Medical College Blood Bank, Paripally (Kollam)",   # MCH Paripally :contentReference[oaicite:4]{index=4}
    "TD Medical College Blood Bank, Alappuzha",                    # TD MC Vandanam :contentReference[oaicite:5]{index=5}
    "Government Medical College Blood Bank, Kottayam",
    "Regional Blood Transfusion Centre, Ernakulam",
    "General Hospital Blood Bank, Ernakulam",                      # GH Ernakulam :contentReference[oaicite:6]{index=6}
    "District Hospital Blood Bank, Pathanamthitta",
    "District Hospital Blood Bank, Malappuram (Manjeri)",
    "District Hospital Blood Bank, Sultanpet (Palakkad)",
    "District Hospital Blood Bank, Neyyattinkara (Thiruvananthapuram)",
    "District Hospital Blood Bank, Mananthavady (Wayanad)",
    "District Hospital Blood Bank, Kannur",
    "General Hospital Blood Bank, Thalassery"
]

BLOOD_TYPES = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
URGENCY_LEVELS = {
    "Normal": {"timeout": 120, "search_radius": "Taluk", "notification": "🔵"},
    "Urgent": {"timeout": 45, "search_radius": "District", "notification": "🟠"},
    "Critical": {"timeout": 15, "search_radius": "FullState", "notification": "🔴"}
}

# Load Kerala locations from updated JSON
KERALA_LOCATIONS = load_locations()

# ================== HELPER FUNCTIONS ==================
def has_profile(phone):
    """Check if user has completed their profile"""
    return st.session_state.users.get(phone, {}).get("profile", False)

def is_approved(phone):
    """Check if user is approved by admin"""
    user = st.session_state.users.get(phone, {})
    if user.get("role") in ["Hospital", "Blood Bank"]:
        return user.get("approved", False)
    return True  # Always approved for other roles

def donor_in_cooldown(phone):
    """Check if donor is in cooldown period"""
    if st.session_state.red_alert:
        return False  # Bypass cooldown during red alert
    
    donor = st.session_state.users.get(phone, {})
    if donor.get("cooldown_override", False):
        return False
    
    last_donation = donor.get("last_donation_date")
    if not last_donation:
        return False
    
    if isinstance(last_donation, str):
        last_donation = datetime.fromisoformat(last_donation)
    
    return (datetime.now() - last_donation).days < 90

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

def get_location_name(district, taluk, village):
    """Get formatted location name"""
    return f"{village}, {taluk}, {district}" if village else f"{taluk}, {district}"

def get_request_timeout(urgency):
    """Get timeout duration for a request"""
    return URGENCY_LEVELS[urgency]["timeout"]

def format_timedelta(delta):
    """Format timedelta to readable string"""
    if delta.total_seconds() < 0:
        return "Expired"
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m"

def display_image(image_data):
    """Display image from base64 string"""
    if image_data:
        st.image(f"data:image;base64,{image_data}", 
                caption="Certificate/Test Report", 
                width=300)

def clean_expired_inventory():
    """Remove expired blood units from inventory"""
    now = datetime.now().date()
    cleaned_inventory = []
    
    for item in st.session_state.inventory:
        if "expiry" in item:
            expiry_date = datetime.fromisoformat(item["expiry"]).date()
            if expiry_date >= now:
                cleaned_inventory.append(item)
    
    if len(cleaned_inventory) != len(st.session_state.inventory):
        st.session_state.inventory = cleaned_inventory
        save_data("inventory.json", st.session_state.inventory)
        return True
    return False

def get_donor_badge(points):
    """Determine donor badge based on points"""
    if points >= 100:
        return "🥇 Gold", "#FFD700", "Donated 10+ units"
    elif points >= 50:
        return "🥈 Silver", "#C0C0C0", "Donated 5+ units"
    elif points >= 10:
        return "🥉 Bronze", "#CD7F32", "Donated at least once"
    return "🌟 New Donor", "#1E90FF", "Just getting started"

def notify_admins(message):
    """Store notification for admins"""
    for phone, user in st.session_state.users.items():
        if user.get("role") == "Admin":
            if "notifications" not in user:
                user["notifications"] = []
            user["notifications"].append({
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "read": False
            })
    save_data("users.json", st.session_state.users)

def check_inventory_alerts():
    """Check inventory levels and notify admins if low"""
    inventory_df = pd.DataFrame(st.session_state.inventory)
    if inventory_df.empty:
        return
    
    # Group by blood type and sum units
    inventory_by_type = inventory_df.groupby("blood_type")["units"].sum().reset_index()
    
    for _, row in inventory_by_type.iterrows():
        if row["units"] < 5:  # Threshold for low inventory
            notify_admins(f"⚠️ Low inventory for {row['blood_type']} - only {row['units']} units left")

def generate_inventory_forecast():
    """Generate fake inventory forecast data"""
    forecast = []
    today = datetime.today()
    
    for i in range(30):  # 30-day forecast
        date = today + timedelta(days=i)
        # Generate random but decreasing inventory
        forecast.append({
            "date": date.strftime("%Y-%m-%d"),
            "A+": max(0, 100 - i*3 + random.randint(-5, 5)),
            "A-": max(0, 40 - i + random.randint(-2, 2)),
            "B+": max(0, 90 - i*2 + random.randint(-4, 4)),
            "B-": max(0, 35 - i + random.randint(-2, 2)),
            "O+": max(0, 120 - i*4 + random.randint(-6, 6)),
            "O-": max(0, 45 - i + random.randint(-3, 3)),
            "AB+": max(0, 30 - i + random.randint(-2, 2)),
            "AB-": max(0, 15 - i//2 + random.randint(-1, 1))
        })
    
    return pd.DataFrame(forecast)

def send_whatsapp_notification(phone, message):
    """Simulate sending WhatsApp notification (Twilio integration would go here)"""
    # In a real implementation, this would use the Twilio API
    st.info(f"WhatsApp notification sent to {phone}: {message}")
    return True

def generate_unique_id(prefix):
    """Generate unique ID for inventory items"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))
    return f"{prefix}-{timestamp}-{random_str}"

# ================== CORE FUNCTIONS ==================
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        "users": load_data("users.json", {}),
        "requests": load_data("requests.json", []),
        "inventory": load_data("inventory.json", []),
        "red_alert": load_data("red_alert.json", False),
        "request_counter": load_data("request_counter.json", 0),
        "stage": "enter_phone",
        "logged_in": False,
        "phone": "",
        "otp": "",
        "role": "",
        "last_inventory_check": datetime.now().isoformat(),
        "focus_request": None
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def find_matching_donors(request):
    """Hierarchical donor matching: Village → Taluk → District → State"""
    matched_donors = []
    req_district = request["district"]
    req_taluk = request["taluk"]
    req_village = request.get("village", "")
    search_scope = URGENCY_LEVELS[request["urgency"]]["search_radius"]
    
    for phone, user in st.session_state.users.items():
        if user.get("role") != "Donor" or user.get("blood_group") != request["blood_type"]:
            continue
            
        if donor_in_cooldown(phone):
            continue
            
        # Skip if not in the same district unless search_scope is FullState
        if search_scope != "FullState" and user.get("district") != req_district:
            continue
            
        # Check Village level
        if search_scope == "Taluk" and req_village and user.get("village") == req_village:
            distance = "0-5km"
            priority = 1
        # Check Taluk level
        elif search_scope == "Taluk" and user.get("taluk") == req_taluk:
            distance = "5-10km"
            priority = 2
        # District level
        elif search_scope == "District" and user.get("district") == req_district:
            distance = "10-20km"
            priority = 3
        # Full state
        else:
            distance = "20+ km"
            priority = 4
            
        matched_donors.append({
            "phone": phone,
            "name": user.get("name", ""),
            "location": get_location_name(user.get("district", ""), user.get("taluk", ""), user.get("village", "")),
            "distance": distance,
            "priority": priority
        })
    
    # Sort by priority (closest first)
    matched_donors.sort(key=lambda x: x["priority"])
    return matched_donors

def create_blood_request(requester_phone, blood_type, units, urgency):
    """Create a new blood request with atomic locking"""
    # Check for duplicate requests
    now = datetime.now()
    for req in st.session_state.requests:
        if (req["requester"] == requester_phone and 
            req["blood_type"] == blood_type and 
            req["status"] == "Pending" and 
            (now - datetime.fromisoformat(req["created_at"])).total_seconds() < 3600):  # 1 hour cooldown
            st.error("You already have a pending request for this blood type. Please wait before creating a new one.")
            return None
    
    requester = st.session_state.users.get(requester_phone, {})
    new_request = {
        "id": st.session_state.request_counter + 1,
        "requester": requester_phone,
        "blood_type": blood_type,
        "units": units,
        "urgency": urgency,
        "status": "Pending",
        "district": requester.get("district", ""),
        "taluk": requester.get("taluk", ""),
        "village": requester.get("village", ""),
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(minutes=URGENCY_LEVELS[urgency]["timeout"])).isoformat(),
        "matched_donors": [],
        "pledged_donors": [],  # Donors who have pledged to donate
        "inventory_ids": [],    # Stores inventory IDs for fulfilled units
        "test_results": {}      # Stores test results keyed by inventory ID
    }
    
    st.session_state.requests.append(new_request)
    st.session_state.request_counter += 1
    
    # Find matching donors
    new_request["matched_donors"] = find_matching_donors(new_request)
    
    save_data("requests.json", st.session_state.requests)
    save_data("request_counter.json", st.session_state.request_counter)
    
    # Notify donors if critical
    if urgency == "Critical":
        notify_donors(new_request["id"])
    
    # Notify nearby blood banks if hospital creates request
    if st.session_state.users.get(requester_phone, {}).get("role") == "Hospital":
        notify_nearby_blood_banks(new_request["id"])
    
    return new_request["id"]

def notify_donors(request_id):
    """Notify matched donors about a critical request"""
    request = next((r for r in st.session_state.requests if r["id"] == request_id), None)
    if not request:
        return
    
    for donor in request["matched_donors"]:
        donor_phone = donor["phone"]
        donor_user = st.session_state.users.get(donor_phone, {})
        if "notifications" not in donor_user:
            donor_user["notifications"] = []
        
        notification = {
            "type": "critical_request",
            "request_id": request_id,
            "blood_type": request["blood_type"],
            "units": request["units"],
            "location": get_location_name(request["district"], request["taluk"], request.get("village", "")),
            "timestamp": datetime.now().isoformat(),
            "read": False
        }
        
        donor_user["notifications"].append(notification)
        
        # Send WhatsApp notification
        message = (f"URGENT: Blood request for {request['blood_type']} at {notification['location']}. "
                  f"{request['units']} units needed. Please check the Kerala Blood Hub app to pledge.")
        send_whatsapp_notification(donor_phone, message)
    
    save_data("users.json", st.session_state.users)

def notify_nearby_blood_banks(request_id):
    """Notify nearby blood banks about a hospital request"""
    request = next((r for r in st.session_state.requests if r["id"] == request_id), None)
    if not request:
        return
    
    for phone, user in st.session_state.users.items():
        if (user.get("role") == "Blood Bank" and 
            user.get("district") == request["district"] and 
            user.get("approved", False)):
            
            if "notifications" not in user:
                user["notifications"] = []
                
            user["notifications"].append({
                "type": "hospital_request",
                "request_id": request_id,
                "blood_type": request["blood_type"],
                "units": request["units"],
                "location": get_location_name(request["district"], request["taluk"], request.get("village", "")),
                "timestamp": datetime.now().isoformat(),
                "read": False
            })
    
    save_data("users.json", st.session_state.users)

def add_to_inventory(request_id, donor_phone, units=1, test_report=None):
    """Add donated blood to inventory with tracking"""
    request = next((r for r in st.session_state.requests if r["id"] == request_id), None)
    if not request:
        return False
    
    donor = st.session_state.users.get(donor_phone, {})
    
    # Generate unique inventory IDs for each unit
    inventory_ids = []
    for i in range(units):
        inventory_id = generate_unique_id("INV")
        st.session_state.inventory.append({
            "id": inventory_id,
            "blood_type": donor.get("blood_group", ""),
            "units": 1,  # Each donation is 1 unit
            "expiry": (datetime.now() + timedelta(days=42)).isoformat(),  # 6-week expiry
            "added_by": st.session_state.phone,  # Blood bank/hospital that processed it
            "added_at": datetime.now().isoformat(),
            "donor_phone": donor_phone,
            "request_id": request_id,
            "test_report": test_report  # Base64 of test result if provided
        })
        inventory_ids.append(inventory_id)
        request["inventory_ids"].append(inventory_id)
    
    # Store test result if provided
    if test_report:
        request["test_results"][inventory_id] = test_report
    
    # Update request status
    if len(request["inventory_ids"]) >= request["units"]:
        request["status"] = "Fulfilled"
    
    # Update donor points
    donor["points"] = donor.get("points", 0) + (10 * units)
    donor["last_donation_date"] = datetime.now().isoformat()
    
    save_data("inventory.json", st.session_state.inventory)
    save_data("requests.json", st.session_state.requests)
    save_data("users.json", st.session_state.users)
    
    return True

# ================== UI COMPONENTS ==================
def show_header():
    st.title("🩸 Kerala Centralized Blood Hub")
    st.markdown("""
    <style>
        .header-style { color: #e63946; font-size: 28px; }
        .subheader-style { color: #1d3557; font-size: 20px; }
        .info-box { 
            background-color: #f8f9fa; 
            border-radius: 10px; 
            padding: 15px; 
            margin-bottom: 20px;
            border-left: 4px solid #e63946;
        }
        .section-title { 
            color: #1d3557; 
            border-bottom: 2px solid #a8dadc; 
            padding-bottom: 5px;
            margin-top: 20px;
        }
        .feature-card {
            background-color: #ffffff;
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 15px;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Top features banner
    st.markdown("""
    <div class="info-box" style="background-color: #1e3a8a; padding: 16px; border-radius: 8px;">
    <h4 class="subheader-style" style="color: white;">Key Features:</h4>
    <div class="feature-card" style="background-color: white; color: #111; padding: 12px; margin-bottom: 10px; border-radius: 10px;">
        <b>Real-time Matching</b> - Instantly connect donors with patients
    </div>
    <div class="feature-card" style="background-color: white; color: #111; padding: 12px; margin-bottom: 10px; border-radius: 10px;">
        <b>Statewide Network</b> - Connect with blood banks across Kerala
    </div>
    <div class="feature-card" style="background-color: white; color: #111; padding: 12px; border-radius: 10px;">
        <b>Life-saving Alerts</b> - Critical requests get prioritized notifications
    </div>
    </div>


    """, unsafe_allow_html=True)
    
    if st.session_state.red_alert:
        st.markdown("""
        <div style='background:#ff4b4b;padding:10px;border-radius:8px;color:white;text-align:center'>
        <h3>🚨 RED ALERT ACTIVATED 🚨</h3>
        <p>Emergency blood shortage - All donor cooldowns suspended</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style='background:#a8dadc;padding:10px;border-radius:8px;color:#1d3557;text-align:center'>
        <h4>❤️ Donate Blood - Save Lives ❤️</h4>
        <p>Kerala's unified platform connecting donors, hospitals and blood banks</p>
        </div>
        """, unsafe_allow_html=True)

def phone_login():
    st.markdown('<h2 class="header-style">📱 Login / Register</h2>', unsafe_allow_html=True)
    
    phone = st.text_input("Mobile Number (10 digits)", max_chars=10, key="phone_input")
    
    existing_role = st.session_state.users.get(phone, {}).get("role")
    role = st.selectbox(
        "Your Role",
        ["Hospital", "Blood Bank", "Donor", "Organization", "Admin"],
        disabled=existing_role is not None
    )
    
    if st.button("Continue", type="primary"):
        if len(phone) == 10 and phone.isdigit():
            if phone in st.session_state.users:
                user_data = st.session_state.users[phone]
                
                # If user has completed profile, log them in directly
                if has_profile(phone):
                    st.session_state.update({
                        "logged_in": True,
                        "phone": phone,
                        "role": user_data["role"]
                    })
                    st.success("Welcome back! Redirecting to dashboard...")
                    st.rerun()
                else:
                    st.session_state.update({
                        "phone": phone,
                        "role": user_data["role"],
                        "stage": "complete_profile"
                    })
                    st.success("Please complete your profile")
                    st.rerun()
            else:
                otp = generate_otp()
                st.session_state.update({
                    "phone": phone,
                    "role": role,
                    "otp": otp,
                    "stage": "enter_otp"
                })
                st.session_state.users[phone] = {"role": role}
                save_data("users.json", st.session_state.users)
                st.success(f"OTP sent to {phone}: {st.session_state.otp}")
        else:
            st.error("Please enter a valid 10-digit mobile number")

def otp_verification():
    st.markdown('<h2 class="header-style">🔐 Verify OTP</h2>', unsafe_allow_html=True)
    st.write(f"Verifying for: {st.session_state.phone}")
    user_otp = st.text_input("Enter 6-digit OTP", max_chars=6, key="otp_input")
    
    if st.button("Verify", type="primary"):
        if user_otp == st.session_state.otp:
            if not has_profile(st.session_state.phone):
                st.session_state.stage = "complete_profile"
                st.success("OTP verified! Complete your profile")
            else:
                st.session_state.logged_in = True
                st.success("Login successful!")
            st.rerun()
        else:
            st.error("Incorrect OTP")
    
    if st.button("← Back"):
        st.session_state.stage = "enter_phone"
        st.session_state.phone = ""  # Clear phone to prevent bypass
        st.rerun()

def complete_profile():
    st.markdown(f'<h2 class="header-style">📝 Complete {st.session_state.role} Profile</h2>', unsafe_allow_html=True)
    phone = st.session_state.phone
    user_data = st.session_state.users[phone]
    
    if st.session_state.role == "Admin":
        # Admin profile - no location needed
        user_data["name"] = st.text_input("Full Name")
        user_data["email"] = st.text_input("Official Email")
        user_data["employee_id"] = st.text_input("Employee ID")
        
    else:
        # Location selection for non-admins
        district = st.selectbox("District", list(KERALA_LOCATIONS.keys()))
        district_data = KERALA_LOCATIONS.get(district, {})
        taluks = district_data.get("taluks", [])
        taluk = st.selectbox("Taluk", taluks)
        
        # Get villages for selected taluk
        villages_dict = district_data.get("villages", {})
        villages = villages_dict.get(taluk, [])
        village = st.selectbox("Village", [""] + villages)
        
        user_data.update({
            "district": district, 
            "taluk": taluk,
            "village": village if village else None
        })
        
        # Role-specific fields
        if st.session_state.role in ["Hospital", "Blood Bank"]:
            if st.session_state.role == "Hospital":
                user_data["name"] = st.selectbox(
                    "Hospital Name",
                    KERALA_GOVT_HOSPITALS
                )
            else:
                user_data["name"] = st.selectbox(
                    "Blood Bank Name",
                    KERALA_BLOOD_BANKS
                )
            
            # Certificate upload
            st.subheader("🔒 Authentication Certificate")
            certificate = st.file_uploader(
                "Upload Certificate of Authenticity (Image)",
                type=["jpg", "jpeg", "png"],
                key="certificate_upload"
            )
            
            if certificate is not None:
                # Store as base64 string
                user_data["certificate"] = base64.b64encode(certificate.getvalue()).decode("utf-8")
                st.success("Certificate uploaded successfully!")
            
            # Initially not approved
            user_data["approved"] = False
            
            # Current inventory (for hospitals and blood banks)
            st.subheader("📦 Current Blood Inventory")
            st.info("Please add your current blood inventory")
            
            cols = st.columns(4)
            inventory = {}
            for i, blood_type in enumerate(BLOOD_TYPES):
                inventory[blood_type] = cols[i % 4].number_input(
                    f"{blood_type} Units", 
                    min_value=0, 
                    max_value=100, 
                    value=0,
                    key=f"inventory_{blood_type}"
                )
            
            user_data["inventory"] = inventory
            
        elif st.session_state.role == "Donor":
            user_data["name"] = st.text_input("Full Name")
            user_data["blood_group"] = st.selectbox("Blood Group", BLOOD_TYPES)
            user_data["height"] = st.number_input("Height (cm)", 140, 220, 170)
            user_data["weight"] = st.number_input("Weight (kg)", 40, 120, 65)
            
            # Chronic disease information
            chronic_disease = st.radio("Do you have any chronic diseases?", ["No", "Yes"])
            if chronic_disease == "Yes":
                user_data["chronic_disease"] = st.text_input("Please specify chronic diseases")
            else:
                user_data["chronic_disease"] = None
                
            # Donor declaration
            st.subheader("ℹ️ Health Declaration")
            declaration = st.checkbox("I confirm that:", key="declaration")
            st.caption("- I am in good health and free from any infectious diseases")
            st.caption("- I have not engaged in any high-risk activities in the past 6 months")
            st.caption("- I understand the donation process and risks involved")
            
            if not declaration:
                st.error("You must accept the health declaration to register as a donor")
                
            user_data["last_donation_date"] = st.date_input("Last Donation Date (if any)", None)
            user_data["points"] = 0  # Initialize donor points
            
        elif st.session_state.role == "Organization":
            user_data["name"] = st.text_input("Organization Name")
            user_data["organization_type"] = st.selectbox(
                "Organization Type", 
                ["NGO", "NSS", "NCC", "Red Cross", "Educational Institution", "Other"]
            )
    
    if st.button("Save Profile", type="primary"):
        if st.session_state.role == "Donor" and not st.session_state.get("declaration", False):
            st.error("You must accept the health declaration to register as a donor")
        else:
            user_data["profile"] = True
            save_data("users.json", st.session_state.users)
            
            if st.session_state.role in ["Hospital", "Blood Bank"]:
                st.success("✅ Profile submitted for admin approval. You'll be notified when approved.")
            else:
                st.session_state.logged_in = True
            st.rerun()

def show_dashboard():
    user = st.session_state.users.get(st.session_state.phone, {})
    if not user:
        st.error("User data not found")
        st.session_state.logged_in = False
        return
        
    st.markdown(f'<h2 class="header-style">Welcome, {user.get("name", "User")} ({st.session_state.role})</h2>', unsafe_allow_html=True)
    
    # Check approval status for hospitals and blood banks
    if st.session_state.role in ["Hospital", "Blood Bank"] and not user.get("approved", False):
        st.warning("⚠️ Your account is pending admin approval. You cannot create requests until approved.")
        return
    
    # Check for notifications
    if user.get("notifications"):
        unread = sum(1 for n in user["notifications"] if not n.get("read", False))
        if unread > 0:
            with st.expander(f"🔔 Notifications ({unread} unread)", expanded=True):
                for i, note in enumerate(user["notifications"]):
                    if note.get("read", False):
                        continue
                        
                    cols = st.columns([1, 20])
                    if note.get("type") == "critical_request":
                        cols[0].warning("🔥")
                        cols[1].write(f"**Critical Blood Request!**")
                        cols[1].write(f"Type: {note['blood_type']} | Units: {note['units']}")
                        cols[1].write(f"Location: {note['location']}")
                        if cols[1].button("View Request", key=f"view_req_{note['request_id']}"):
                            note["read"] = True
                            save_data("users.json", st.session_state.users)
                            # Focus on request in donor dashboard
                            st.session_state.focus_request = note["request_id"]
                            st.rerun()
                    elif note.get("type") == "hospital_request":
                        cols[0].info("🏥")
                        cols[1].write(f"**Hospital Blood Request**")
                        cols[1].write(f"Type: {note['blood_type']} | Units: {note['units']}")
                        cols[1].write(f"Location: {note['location']}")
                        if cols[1].button("View Request", key=f"view_hosp_req_{note['request_id']}"):
                            note["read"] = True
                            save_data("users.json", st.session_state.users)
                            st.session_state.focus_request = note["request_id"]
                            st.rerun()
                    else:
                        cols[0].info("ℹ️")
                        cols[1].write(note.get("message", "Notification"))
                    
                    st.divider()
                    
                if st.button("Mark all as read"):
                    for note in user["notifications"]:
                        note["read"] = True
                    save_data("users.json", st.session_state.users)
                    st.rerun()
    
    if st.session_state.role == "Hospital":
        show_hospital_dashboard()
    elif st.session_state.role == "Blood Bank":
        show_blood_bank_dashboard()
    elif st.session_state.role == "Donor":
        show_donor_dashboard()
    elif st.session_state.role == "Organization":
        show_organization_dashboard()
    elif st.session_state.role == "Admin":
        show_admin_dashboard()
    
    # Single logout button at the end
    st.divider()
    if st.button("Logout", key="logout", use_container_width=True, type="primary"):
        for key in ["logged_in", "phone", "role", "otp", "focus_request"]:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state.stage = "enter_phone"
        st.rerun()

def show_hospital_dashboard():
    st.markdown('<h3 class="section-title">🏥 Hospital Dashboard</h3>', unsafe_allow_html=True)
    user = st.session_state.users.get(st.session_state.phone, {})
    
    with st.form("blood_request_form"):
        st.write("### 🆕 Create New Blood Request")
        blood_type = st.selectbox("Blood Type", BLOOD_TYPES)
        units = st.number_input("Units Needed", 1, 10, 1)
        urgency = st.selectbox("Urgency Level", list(URGENCY_LEVELS.keys()))
        
        submitted = st.form_submit_button("Submit Request", type="primary")
        
        if submitted:
            request_id = create_blood_request(st.session_state.phone, blood_type, units, urgency)
            if request_id:
                st.success(f"✅ Request #{request_id} created successfully! Matching donors...")
                st.balloons()
    
    st.divider()
    st.write("### 📋 Your Active Requests")
    hospital_requests = [r for r in st.session_state.requests if r.get("requester") == st.session_state.phone]
    
    if not hospital_requests:
        st.info("No active requests")
    else:
        for req in sorted(hospital_requests, key=lambda x: x["created_at"], reverse=True):
            created_time = datetime.fromisoformat(req["created_at"])
            expires_time = datetime.fromisoformat(req["expires_at"])
            time_left = expires_time - datetime.now()
            
            with st.expander(f"Request #{req['id']}: {req['units']} units {req['blood_type']} "
                            f"{URGENCY_LEVELS[req['urgency']]['notification']} {req['urgency']} - {req['status']}"):
                cols = st.columns(2)
                cols[0].metric("Created", created_time.strftime("%d %b %Y, %H:%M"))
                cols[1].metric("Expires In", format_timedelta(time_left) if time_left.total_seconds() > 0 else "Expired")
                
                st.write(f"**Location:** {get_location_name(req['district'], req['taluk'], req.get('village', ''))}")
                
                if req["status"] == "Pending":
                    st.warning("Awaiting donor response")
                    if st.button(f"Cancel Request", key=f"cancel_{req['id']}"):
                        req["status"] = "Cancelled"
                        save_data("requests.json", st.session_state.requests)
                        st.rerun()
                elif req["status"] == "Partially Fulfilled":
                    st.warning("Partially fulfilled - still need donors")
                elif req["status"] == "Accepted":
                    if req.get("pledged_donors"):
                        donor_phone = req["pledged_donors"][0]["phone"]
                        donor_user = st.session_state.users.get(donor_phone, {})
                        st.success(f"✅ Accepted by {donor_user.get('name', 'Unknown')} ({donor_phone})")
                    
                    # Blood test section
                    st.write("### 🧪 Blood Test & Inventory")
                    test_report = st.file_uploader("Upload Blood Test Report (PNG)", 
                                                  type=["png"], 
                                                  key=f"test_report_{req['id']}")
                    
                    units_to_add = st.number_input("Units to Add", 1, req["units"], 1)
                    
                    if st.button(f"Add to Inventory", key=f"fulfill_{req['id']}"):
                        # Convert test report to base64 if provided
                        test_report_base64 = None
                        if test_report:
                            test_report_base64 = base64.b64encode(test_report.getvalue()).decode("utf-8")
                        
                        # Add to inventory
                        if add_to_inventory(req["id"], donor_phone, units_to_add, test_report_base64):
                            st.success("Blood added to inventory successfully!")
                            st.balloons()
                            st.rerun()
                        else:
                            st.error("Failed to add to inventory")
                elif req["status"] == "Fulfilled":
                    st.success("✅ Request fulfilled")
                    if req.get("inventory_ids"):
                        st.info(f"Inventory IDs: {', '.join(req['inventory_ids'])}")
                
                st.write(f"**Matched Donors:** {len(req['matched_donors'])}")
                st.write(f"**Pledged Donors:** {len(req['pledged_donors'])}")
                
                if req["matched_donors"]:
                    st.write("#### Potential Donors")
                    df = pd.DataFrame(req["matched_donors"])
                    # Include phone number for hospitals/blood banks
                    df["phone"] = df["phone"].apply(lambda x: x[:3] + "****" + x[7:])
                    st.dataframe(df.drop(columns=['priority']))
                
                if req["pledged_donors"]:
                    st.write("#### Committed Donors")
                    df = pd.DataFrame(req["pledged_donors"])
                    df["phone"] = df["phone"].apply(lambda x: x[:3] + "****" + x[7:])
                    st.dataframe(df)

def show_blood_bank_dashboard():
    st.markdown('<h3 class="section-title">🏪 Blood Bank Dashboard</h3>', unsafe_allow_html=True)
    user = st.session_state.users.get(st.session_state.phone, {})
    
    # Clean expired inventory
    if clean_expired_inventory():
        st.warning("Expired blood units have been removed from inventory")
    
    # Inventory management
    st.write("### 🩸 Blood Inventory")
    if not st.session_state.inventory:
        st.info("No inventory items")
    else:
        # Convert to DataFrame for better display
        inventory_df = pd.DataFrame(st.session_state.inventory)
        if 'expiry' in inventory_df.columns:
            inventory_df['expiry'] = pd.to_datetime(inventory_df['expiry']).dt.date
        
        # Sort by expiry date (soonest first)
        inventory_df = inventory_df.sort_values(by=['blood_type', 'expiry'])
        
        # Show summary by blood type
        st.write("#### Inventory Summary")
        summary = inventory_df.groupby('blood_type')['units'].sum().reset_index()
        st.bar_chart(summary.set_index('blood_type'))
        
        st.write("#### Detailed Inventory")
        st.dataframe(inventory_df)
        
        # Inventory search
        st.write("### 🔍 Inventory Search")
        search_id = st.text_input("Enter Inventory ID")
        if search_id:
            item = next((i for i in st.session_state.inventory if i.get("id") == search_id), None)
            if item:
                st.write(f"**Blood Type:** {item.get('blood_type', 'N/A')}")
                st.write(f"**Units:** {item.get('units', 1)}")
                st.write(f"**Expiry:** {item.get('expiry', 'N/A')}")
                if item.get("donor_phone"):
                    donor = st.session_state.users.get(item["donor_phone"], {})
                    st.write(f"**Donor:** {donor.get('name', 'Unknown')} ({item['donor_phone']})")
                if item.get("test_report"):
                    display_image(item["test_report"])
                if item.get("request_id"):
                    st.write(f"**Request ID:** {item['request_id']}")
            else:
                st.warning("Inventory ID not found")
    
    with st.form("add_inventory_form"):
        st.write("#### ➕ Add to Inventory")
        
        # Blood ID lookup for automatic filling
        blood_id = st.text_input("Blood ID (optional - for auto-fill)")
        existing_item = None
        if blood_id:
            existing_item = next((item for item in st.session_state.inventory if item.get("id") == blood_id), None)
            if existing_item:
                st.success(f"Found blood type: {existing_item['blood_type']}")
            else:
                st.warning("Blood ID not found")
        
        # Form fields with auto-fill from blood ID
        blood_type = st.selectbox(
            "Blood Type", 
            BLOOD_TYPES,
            index=BLOOD_TYPES.index(existing_item["blood_type"]) if existing_item and existing_item.get("blood_type") in BLOOD_TYPES else 0
        ) if existing_item else st.selectbox("Blood Type", BLOOD_TYPES)
        
        units = st.number_input("Units", 1, 100, 1)
        
        # Set expiry date based on existing item or default
        if existing_item and existing_item.get("expiry"):
            expiry_date = datetime.fromisoformat(existing_item["expiry"]).date()
        else:
            expiry_date = datetime.today().date() + timedelta(days=42)  # Default 6 weeks
        
        expiry = st.date_input("Expiry Date", value=expiry_date, min_value=datetime.today())
        
        donor_phone = st.text_input(
            "Donor Phone", 
            value=existing_item.get("donor_phone", "") if existing_item else ""
        )
        
        # Test report handling
        test_report = st.file_uploader("Test Report (optional)", type=["png", "jpg"])
        if existing_item and existing_item.get("test_report"):
            st.write("Existing test report:")
            display_image(existing_item["test_report"])
        
        if st.form_submit_button("Add Inventory", type="primary"):
            # Generate unique inventory ID
            inventory_id = generate_unique_id("INV")
            
            # Process test report
            test_report_base64 = None
            if test_report:
                test_report_base64 = base64.b64encode(test_report.getvalue()).decode("utf-8")
            elif existing_item and existing_item.get("test_report"):
                test_report_base64 = existing_item["test_report"]
            
            st.session_state.inventory.append({
                "id": inventory_id,
                "blood_type": blood_type,
                "units": units,
                "expiry": expiry.isoformat(),
                "added_by": st.session_state.phone,
                "added_at": datetime.now().isoformat(),
                "donor_phone": donor_phone if donor_phone else None,
                "test_report": test_report_base64
            })
            save_data("inventory.json", st.session_state.inventory)
            st.success(f"Inventory updated! ID: {inventory_id}")
            st.rerun()
    
    st.divider()
    st.write("### 📥 Incoming Requests")
    pending_requests = [r for r in st.session_state.requests if r.get("status") == "Pending"]
    
    if not pending_requests:
        st.info("No pending requests")
    else:
        for req in pending_requests:
            requester = st.session_state.users.get(req["requester"], {})
            with st.expander(f"Request #{req['id']}: {req['units']} units {req['blood_type']} from {requester.get('name', 'Unknown')}"):
                st.write(f"**Urgency:** {req['urgency']} {URGENCY_LEVELS[req['urgency']]['notification']}")
                st.write(f"**Location:** {get_location_name(req['district'], req['taluk'], req.get('village', ''))}")
                st.write(f"**Time Left:** {format_timedelta(datetime.fromisoformat(req['expires_at']) - datetime.now())}")
                
                # Check if blood bank has matching inventory
                available_units = sum(
                    item["units"] for item in st.session_state.inventory 
                    if item.get("blood_type") == req["blood_type"]
                )
                
                if available_units >= req["units"]:
                    if st.button(f"Fulfill Request", key=f"fulfill_{req['id']}"):
                        # Update inventory
                        remaining = req["units"]
                        new_inventory = []
                        for item in st.session_state.inventory:
                            if item.get("blood_type") == req["blood_type"] and remaining > 0:
                                if item["units"] <= remaining:
                                    remaining -= item["units"]
                                    # Skip adding to new inventory (fully consumed)
                                else:
                                    item["units"] -= remaining
                                    remaining = 0
                                    new_inventory.append(item)
                            else:
                                new_inventory.append(item)
                        
                        st.session_state.inventory = new_inventory
                        
                        # Update request
                        req["status"] = "Fulfilled"
                        req["fulfilled_by"] = st.session_state.phone
                        req["fulfilled_at"] = datetime.now().isoformat()
                        
                        save_data("requests.json", st.session_state.requests)
                        save_data("inventory.json", st.session_state.inventory)
                        st.success("Request fulfilled!")
                        st.rerun()
                else:
                    st.warning(f"Only {available_units} units available (needed: {req['units']})")
                    if available_units > 0:
                        if st.button(f"Partially Fulfill ({available_units} units)", key=f"partial_{req['id']}"):
                            # Update inventory
                            remaining = available_units
                            new_inventory = []
                            for item in st.session_state.inventory:
                                if item.get("blood_type") == req["blood_type"] and remaining > 0:
                                    if item["units"] <= remaining:
                                        remaining -= item["units"]
                                        # Skip adding to new inventory (fully consumed)
                                    else:
                                        item["units"] -= remaining
                                        remaining = 0
                                        new_inventory.append(item)
                                else:
                                    new_inventory.append(item)
                            
                            st.session_state.inventory = new_inventory
                            
                            # Update request
                            if available_units >= req["units"]:
                                req["status"] = "Fulfilled"
                            else:
                                req["status"] = "Partially Fulfilled"
                                req["fulfilled_units"] = available_units
                            req["fulfilled_by"] = st.session_state.phone
                            req["fulfilled_at"] = datetime.now().isoformat()
                            
                            save_data("requests.json", st.session_state.requests)
                            save_data("inventory.json", st.session_state.inventory)
                            st.success("Partially fulfilled request!")
                            st.rerun()

def show_donor_dashboard():
    st.markdown('<h3 class="section-title">🧑‍⚕️ Donor Dashboard</h3>', unsafe_allow_html=True)
    user = st.session_state.users.get(st.session_state.phone, {})
    
    # Donor status and gamification
    points = user.get("points", 0)
    badge, badge_color, badge_desc = get_donor_badge(points)
    
    st.markdown(f"""
    <div style="border:2px solid {badge_color}; border-radius:10px; padding:15px; text-align:center">
        <h3>{badge} {badge_desc}</h3>
        <p>You have earned <b>{points} points</b> from donations</p>
        <p>Your donations have helped save <b>{points//10} lives</b> ❤️</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.write("### 🏆 Badge Progression")
    cols = st.columns(4)
    cols[0].metric("Bronze", "10 points", "1+ donations")
    cols[1].metric("Silver", "50 points", "5+ donations")
    cols[2].metric("Gold", "100 points", "10+ donations")
    cols[3].metric("Lives Saved", points//10)
    
    # Progress bar
    progress = min(100, points)
    st.progress(progress, f"Progress to next badge: {points}/100 points")
    
    # Donor information
    with st.expander("Your Health Information"):
        st.write(f"**Height:** {user.get('height', 'N/A')} cm")
        st.write(f"**Weight:** {user.get('weight', 'N/A')} kg")
        if user.get("chronic_disease"):
            st.warning(f"**Chronic Disease:** {user['chronic_disease']}")
        else:
            st.success("No chronic diseases reported")
    
    if "last_donation_date" in user and user["last_donation_date"]:
        last_donation = datetime.fromisoformat(user["last_donation_date"])
        days_since = (datetime.now() - last_donation).days
        cooldown_left = max(0, 90 - days_since)
        st.write(f"**Last Donation:** {last_donation.strftime('%d %b %Y')} ({days_since} days ago)")
        st.write(f"**Eligible to donate:** {'Yes' if cooldown_left == 0 or st.session_state.red_alert else 'No'}")
        if cooldown_left > 0 and not st.session_state.red_alert:
            st.warning(f"⏳ {cooldown_left} days left in cooldown period")
    else:
        st.info("You haven't donated blood yet")
    
    # Active requests
    st.divider()
    st.write("### 📋 Blood Requests Near You")
    
    # Get requests in same district first
    eligible_requests = [
        r for r in st.session_state.requests 
        if r.get("status") == "Pending" and 
        r.get("blood_type") == user.get("blood_group") and
        r.get("district") == user.get("district")
    ]
    
    # Focus on specific request if notification clicked
    focus_request = st.session_state.get("focus_request")
    if focus_request:
        req = next((r for r in eligible_requests if r.get("id") == focus_request), None)
        if req:
            # Move focused request to top
            eligible_requests.remove(req)
            eligible_requests.insert(0, req)
    
    if not eligible_requests:
        st.info("No matching requests in your district")
    else:
        for req in eligible_requests:
            requester = st.session_state.users.get(req["requester"], {})
            created_time = datetime.fromisoformat(req["created_at"])
            expires_time = datetime.fromisoformat(req["expires_at"])
            time_left = expires_time - datetime.now()
            
            # Highlight if focused or critical
            is_focused = focus_request == req["id"]
            is_critical = req["urgency"] == "Critical"
            
            expander_title = f"Request #{req['id']}: {req['units']} units {req['blood_type']} ({req['urgency']})"
            if is_focused or is_critical:
                expander_title = f"{URGENCY_LEVELS[req['urgency']]['notification']} {expander_title}"
            
            with st.expander(expander_title, expanded=is_focused or is_critical):
                if is_focused:
                    st.success("🔔 You were notified about this critical request")
                
                st.write(f"**From:** {requester.get('name', 'Unknown')}")
                st.write(f"**Location:** {get_location_name(req['district'], req['taluk'], req.get('village', ''))}")
                
                # Calculate distance
                distance = "Unknown"
                if user.get("village") == req.get("village") and req.get("village"):
                    distance = "0-5 km (Same Village)"
                elif user.get("taluk") == req.get("taluk"):
                    distance = "5-10 km (Same Taluk)"
                elif user.get("district") == req.get("district"):
                    distance = "10-20 km (Same District)"
                else:
                    distance = "20+ km"
                
                st.write(f"**Distance:** {distance}")
                st.write(f"**Time Left:** {format_timedelta(time_left)}")
                
                # Check if donor already pledged
                already_pledged = any(d.get("phone") == st.session_state.phone for d in req.get("pledged_donors", []))
                
                if already_pledged:
                    st.success("✅ You have pledged to donate for this request")
                    if st.button("Withdraw Pledge", key=f"withdraw_{req['id']}"):
                        req["pledged_donors"] = [d for d in req["pledged_donors"] if d.get("phone") != st.session_state.phone]
                        save_data("requests.json", st.session_state.requests)
                        st.success("Pledge withdrawn")
                        st.rerun()
                elif donor_in_cooldown(st.session_state.phone) and not st.session_state.red_alert:
                    last_donation = datetime.fromisoformat(user.get("last_donation_date", datetime.now().isoformat()))
                    days_since = (datetime.now() - last_donation).days
                    st.warning(f"You are in cooldown period. Eligible in {90 - days_since} days.")
                else:
                    if st.button("Pledge to Donate", key=f"pledge_{req['id']}"):
                        if "pledged_donors" not in req:
                            req["pledged_donors"] = []
                            
                        req["pledged_donors"].append({
                            "phone": st.session_state.phone,
                            "name": user.get("name", ""),
                            "pledged_at": datetime.now().isoformat()
                        })
                        
                        # Update request status if enough donors
                        if len(req["pledged_donors"]) >= req["units"]:
                            req["status"] = "Accepted"
                        
                        save_data("requests.json", st.session_state.requests)
                        st.success("Thank you for pledging to donate!")
                        st.balloons()
                        st.rerun()

def show_organization_dashboard():
    st.markdown('<h3 class="section-title">🏢 Organization Dashboard</h3>', unsafe_allow_html=True)
    user = st.session_state.users.get(st.session_state.phone, {})
    
    st.write("### 👥 Volunteer Management")
    
    # CSV upload for bulk volunteers
    with st.expander("📤 Upload Volunteers via CSV"):
        st.write("### Bulk Volunteer Upload")
        st.markdown("""
        **CSV Format Required:**
        ```
        name,age,address,district,taluk,village,blood_group,height_cm,weight_kg,chronic_disease,disease_details
        Aarav Kumar,23,MG Road,Thiruvananthapuram,Nedumangad,Poojappura,B+,180,72,No,
        Neha Menon,26,Rose Street,Thiruvananthapuram,Kattakada,Manickal,O-,165,55,Yes,Thyroid
        ```
        """)
        
        csv_file = st.file_uploader("Upload CSV file", type=["csv"])
        
        if csv_file is not None:
            try:
                # Read and parse CSV
                csv_data = csv_file.read().decode("utf-8")
                csv_reader = csv.DictReader(io.StringIO(csv_data))
                
                # Initialize volunteers list if needed
                if "volunteers" not in user:
                    user["volunteers"] = []
                
                added_count = 0
                for row in csv_reader:
                    # Validate required fields
                    required_fields = ["name", "age", "address", "district", 
                                     "taluk", "village", "blood_group", "height_cm", 
                                     "weight_kg", "chronic_disease"]
                    
                    if not all(field in row for field in required_fields):
                        st.error("CSV is missing required columns")
                        break
                    
                    # Validate district and taluk
                    district = row["district"]
                    taluk = row["taluk"]
                    village = row["village"]
                    
                    if district not in KERALA_LOCATIONS:
                        st.error(f"Invalid district: {district}")
                        break
                        
                    district_data = KERALA_LOCATIONS.get(district, {})
                    if taluk not in district_data.get("taluks", []):
                        st.error(f"Invalid taluk: {taluk} for district {district}")
                        break
                    
                    # Get villages for taluk
                    villages_dict = district_data.get("villages", {})
                    villages = villages_dict.get(taluk, [])
                    if village not in villages:
                        st.error(f"Invalid village: {village} for taluk {taluk}")
                        break
                    
                    # Add volunteer
                    user["volunteers"].append({
                        "name": row["name"],
                        "age": int(row["age"]),
                        "address": row["address"],
                        "district": district,
                        "taluk": taluk,
                        "village": village,
                        "blood_group": row["blood_group"],
                        "height_cm": int(row["height_cm"]),
                        "weight_kg": int(row["weight_kg"]),
                        "chronic_disease": row["chronic_disease"],
                        "disease_details": row.get("disease_details", ""),
                        "added_at": datetime.now().isoformat()
                    })
                    added_count += 1
                
                if added_count > 0:
                    save_data("users.json", st.session_state.users)
                    st.success(f"✅ Successfully added {added_count} volunteers!")
                    st.rerun()
                
            except Exception as e:
                st.error(f"Error processing CSV: {str(e)}")
    
    # Add volunteer form
    with st.form("add_volunteer_form"):
        st.write("#### ➕ Add Single Volunteer")
        name = st.text_input("Volunteer Name")
        age = st.number_input("Age", 18, 100, 25)
        address = st.text_input("Address")
        district = st.selectbox("District", list(KERALA_LOCATIONS.keys()))
        district_data = KERALA_LOCATIONS.get(district, {})
        taluks = district_data.get("taluks", [])
        taluk = st.selectbox("Taluk", taluks)
        
        # Get villages for selected taluk
        villages_dict = district_data.get("villages", {})
        villages = villages_dict.get(taluk, [])
        village = st.selectbox("Village", [""] + villages)
        
        blood_group = st.selectbox("Blood Group", BLOOD_TYPES)
        height_cm = st.number_input("Height (cm)", 140, 220, 170)
        weight_kg = st.number_input("Weight (kg)", 40, 120, 65)
        chronic_disease = st.radio("Chronic Disease?", ["No", "Yes"], index=0)
        disease_details = ""
        if chronic_disease == "Yes":
            disease_details = st.text_input("Disease Details")
        
        if st.form_submit_button("Add Volunteer", type="primary"):
            if "volunteers" not in user:
                user["volunteers"] = []
                
            user["volunteers"].append({
                "name": name,
                "age": age,
                "address": address,
                "district": district,
                "taluk": taluk,
                "village": village if village else None,
                "blood_group": blood_group,
                "height_cm": height_cm,
                "weight_kg": weight_kg,
                "chronic_disease": chronic_disease,
                "disease_details": disease_details,
                "added_at": datetime.now().isoformat()
            })
            
            save_data("users.json", st.session_state.users)
            st.success("Volunteer added!")
            st.rerun()
    
    # Display volunteers
    if user.get("volunteers"):
        st.write("#### 📋 Volunteer List")
        volunteer_df = pd.DataFrame(user["volunteers"])
        st.dataframe(volunteer_df)
        
        # Statistics
        st.write("#### 📊 Volunteer Statistics")
        cols = st.columns(3)
        cols[0].metric("Total Volunteers", len(user["volunteers"]))
        
        if not volunteer_df.empty:
            cols[1].metric("Most Common Blood Type", volunteer_df["blood_group"].mode()[0])
            cols[2].metric("Average Age", f"{volunteer_df['age'].mean():.1f} years")
            
            st.bar_chart(volunteer_df["blood_group"].value_counts())
    else:
        st.info("No volunteers added yet")

def show_admin_dashboard():
    st.markdown('<h3 class="section-title">👑 Admin Dashboard</h3>', unsafe_allow_html=True)
    
    # Check inventory alerts periodically (every 5 minutes)
    last_check = datetime.fromisoformat(st.session_state.last_inventory_check)
    if (datetime.now() - last_check).total_seconds() > 300:  # 5 minutes
        check_inventory_alerts()
        st.session_state.last_inventory_check = datetime.now().isoformat()
    
    # Pending approvals
    st.write("### ⚠️ Pending Approvals")
    pending_approvals = [
        (phone, user) for phone, user in st.session_state.users.items()
        if user.get("role") in ["Hospital", "Blood Bank"] and not user.get("approved", False)
    ]
    
    if not pending_approvals:
        st.success("No pending approvals")
    else:
        for phone, user in pending_approvals:
            with st.expander(f"{user.get('name', '')} ({user.get('role', '')} - {phone})"):
                st.write(f"**District:** {user.get('district', '')}")
                st.write(f"**Taluk:** {user.get('taluk', '')}")
                
                # Display certificate if available
                if user.get("certificate"):
                    display_image(user["certificate"])
                else:
                    st.warning("No certificate uploaded")
                
                # Approval buttons
                cols = st.columns(2)
                if cols[0].button("Approve", key=f"approve_{phone}"):
                    user["approved"] = True
                    save_data("users.json", st.session_state.users)
                    st.success(f"{user.get('name', 'User')} approved successfully!")
                    st.rerun()
                
                if cols[1].button("Reject", key=f"reject_{phone}"):
                    st.session_state.users.pop(phone)
                    save_data("users.json", st.session_state.users)
                    st.success(f"{user.get('name', 'User')} rejected and removed!")
                    st.rerun()
    
    # User management
    st.write("### 👥 User Management")
    users_df = pd.DataFrame([
        {"phone": phone, **info} 
        for phone, info in st.session_state.users.items()
    ])
    
    if not users_df.empty:
        st.dataframe(users_df)
    else:
        st.info("No users registered")
    
    # System status
    st.write("### ⚙️ System Status")
    cols = st.columns(3)
    cols[0].metric("Total Users", len(st.session_state.users))
    cols[1].metric("Active Requests", len([r for r in st.session_state.requests if r.get("status") == "Pending"]))
    cols[2].metric("Blood Banks", len([u for u in st.session_state.users.values() if u.get("role") == "Blood Bank"]))
    
    # Red alert control
    st.write("### 🚨 Red Alert System")
    if st.session_state.red_alert:
        st.error("RED ALERT ACTIVE - All cooldowns suspended")
        if st.button("Deactivate Red Alert"):
            st.session_state.red_alert = False
            save_data("red_alert.json", st.session_state.red_alert)
            st.rerun()
    else:
        st.success("System operating normally")
        if st.button("Activate Red Alert"):
            st.session_state.red_alert = True
            save_data("red_alert.json", st.session_state.red_alert)
            st.rerun()
    
    # Inventory forecasting
    st.write("### 📊 Inventory Forecasting")
    forecast_df = generate_inventory_forecast()
    forecast_df.set_index("date", inplace=True)
    
    st.line_chart(forecast_df)
    st.caption("30-day blood inventory forecast based on current usage patterns")
    
    # Analytics
    st.write("### 📈 System Analytics")
    if st.session_state.requests:
        requests_df = pd.DataFrame(st.session_state.requests)
        requests_df["created_at"] = pd.to_datetime(requests_df["created_at"])
        requests_df["hour"] = requests_df["created_at"].dt.hour
        
        st.write("#### Requests by Hour")
        st.bar_chart(requests_df["hour"].value_counts().sort_index())
        
        st.write("#### Requests by Blood Type")
        st.bar_chart(requests_df["blood_type"].value_counts())
        
        st.write("#### Requests by District")
        st.bar_chart(requests_df["district"].value_counts())
    else:
        st.info("No request data available")

# ================== MAIN APP ==================
def main():
    # Initialize session state
    init_session_state()
    
    # Show header
    show_header()
    
    # Show appropriate screen based on state
    if not st.session_state.get("logged_in", False):
        if st.session_state.stage == "enter_phone":
            phone_login()
        elif st.session_state.stage == "enter_otp":
            otp_verification()
        elif st.session_state.stage == "complete_profile":
            complete_profile()
    else:
        show_dashboard()

if __name__ == "__main__":
    main()