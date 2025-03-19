from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from sqlalchemy import func, distinct, cast, Date
import json
from datetime import datetime, timedelta
from models import User, Match, UserMoreDetails, UserSelfDescription, Message, MatchRequest, MatchBatch
from database import get_session
from sqlalchemy.sql import or_, case
import csv
from io import StringIO
import os
import traceback
import sys
from sqlalchemy import Index

# Initialize Flask app
app = Flask(__name__)

# Configure CORS - only allow requests from your React frontend
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:3000"],  # Your React app's URL
        "methods": ["GET"],
        "allow_headers": ["Content-Type"]
    }
})

# Test route to verify server is running
@app.route("/")
def index():
    return "Penzi  Server is running" 

@app.route("/test-db", methods=['GET'])
def test_db():
    try:
        with get_session() as session:
            users_count = session.query(User).count()
            return jsonify({
                "status": "success",
                "message": "Database connected successfully",
                "users_count": users_count
            })
    except Exception as e:
        print(f"Database Error: {str(e)}")  # Print error to console
        return jsonify({
            "status": "error",
            "message": f"Database error: {str(e)}"
        }), 500
    
class ValidationError(Exception):
    pass

def store_message(session, user_id, direction, message_text, phone_number=None):
    """Store a message in the database.
    
    Args:
        session: Database session
        user_id: ID of the user
        direction: 'incoming' or 'outgoing'
        message_text: The message content
        phone_number: Optional phone number (not stored, only used for response)
    """
    message = Message(
        user_id=user_id,
        message_direction=direction,
        message_text=message_text
    )
    session.add(message)
    return message

def get_help_message():
    """Returns the help message for invalid commands"""
    return (
        "Invalid command. Available commands:\n"
        "1. PENZI (activate service)\n"
        "2. START#name#age#gender#county#town\n"
        "3. DETAILS#education#profession#status#religion#ethnicity\n"
        "4. MYSELF description\n"
        "5. MATCH#age-range#town\n"
        "6. NEXT (for more matches)\n"
        "7. Phone number (to get profile)\n"
        "8. DESCRIBE phone_number\n"
        "9. YES (to confirm interest)"
    )

def validate_age_range(age_range):
    """Validate and parse age range string (e.g., '23-25')"""
    try:
        min_age, max_age = map(int, age_range.split('-'))
        if min_age < 18 or max_age < min_age:
            raise ValidationError("Invalid age range. Minimum age is 18 and maximum age must be greater than minimum.")
        return min_age, max_age
    except ValueError:
        raise ValidationError("Invalid age range format. Use: min-max (e.g., 23-25)")

@app.route("/receive-sms", methods=["POST"])
def receive_sms():
    """
    Unified endpoint to handle all SMS messages.
    """
    try:
        data = request.json or {}
        phone_number = data.get("phone_number", "254722000000")
        message = data.get("message", "PENZI").strip()
        message_upper = message.upper()

        with get_session() as session:
            # Check if user exists
            existing_match = session.query(Match).filter_by(phone_number=phone_number).first()
            user = session.query(User).get(existing_match.matched_user_id) if existing_match else None

            # Store incoming message if user exists (except for initial START command)
            if user and not message_upper.startswith("START#"):
                store_message(session, user.id, "incoming", message)

            if message_upper == "PENZI":
                response = (
                    "Welcome to our dating service with 6000 potential dating partners!\n"
                    "To register SMS start#name#age#gender#county#town to 22141.\n"
                    "E.g., start#John Doe#26#Male#Nakuru#Naivasha"
                )
                if user:
                    store_message(session, user.id, "outgoing", response)
                return jsonify({"message": response}), 200

            elif message_upper == "YES":
                if not user:
                    error_msg = (
                        "Welcome to our dating service with 6000 potential dating partners!\n"
                        "To register SMS start#name#age#gender#county#town to 22141.\n"
                        "E.g., start#John Doe#26#Male#Nakuru#Naivasha"
                    )
                    return jsonify({"message": error_msg}), 400

                # Find the notification message about who was interested
                notification = session.query(Message)\
                    .filter(
                        Message.user_id == user.id,
                        Message.message_direction == "outgoing",
                        Message.message_text.like("Hi %called%is interested in you%")
                    )\
                    .order_by(Message.created_at.desc())\
                    .first()

                if not notification:
                    return jsonify({"message": "No pending requests found"}), 200

                # Extract the requester's name
                try:
                    requester_name = notification.message_text.split("called ")[1].split(" is")[0]
                except:
                    return jsonify({"message": "Error processing request"}), 400

                # Get the requester's details and phone number
                requester_info = session.query(User, UserMoreDetails, Match)\
                    .join(UserMoreDetails, User.id == UserMoreDetails.user_id)\
                    .join(Match, User.id == Match.matched_user_id)\
                    .filter(User.name == requester_name)\
                    .first()

                if not requester_info:
                    return jsonify({"message": "Requester not found"}), 404

                user_basic, user_details, match = requester_info

                # Format the response
                response = (
                    f"{user_basic.name} aged {user_basic.age}, {user_basic.county} County, {user_basic.town} town, "
                    f"{user_details.level_of_education}, {user_details.profession}, {user_details.marital_status}, "
                    f"{user_details.religion}, {user_details.ethnicity}.\n"
                    f"Send DESCRIBE {match.phone_number} to get more details about {user_basic.name}."
                )

                # Store and return the response
                store_message(session, user.id, "outgoing", response)
                return jsonify({"message": response}), 200

            elif message_upper.startswith("START#"):
                print(f"\n=== Registration Debug ===")
                print(f"Message: {message}")
                print(f"Phone: {phone_number}")
                
                parts = message.split("#")
                print(f"Parts: {parts}")
                
                if len(parts) != 6:
                    return jsonify({
                        "message": "Invalid format. Use: start#name#age#gender#county#town"
                    }), 400

                _, name, age, gender, county, town = parts
                print(f"Parsed data: name={name}, age={age}, gender={gender}, county={county}, town={town}")

                try:
                    age = int(age)
                    if age < 18:
                        return jsonify({"message": "You must be 18 or older to register"}), 400
                except ValueError:
                    return jsonify({"message": "Age must be a number"}), 400

                if gender.upper() not in ["MALE", "FEMALE"]:
                    return jsonify({"message": "Gender must be Male or Female"}), 400

                try:
                    new_user = User(
                        name=name,
                        age=age,
                        gender=gender.title(),
                        county=county,
                        town=town
                    )
                    session.add(new_user)
                    session.flush()
                    print(f"Created user with ID: {new_user.id}")

                    # Create initial match request
                    initial_request = MatchRequest(
                        user_id=new_user.id,
                        age_range="18-99",
                        county=county,
                        status="Initial"
                    )
                    session.add(initial_request)
                    session.flush()
                    print(f"Created match request with ID: {initial_request.id}")

                    # Create match record
                    new_match = Match(
                        request_id=initial_request.id,
                        matched_user_id=new_user.id,
                        phone_number=phone_number,
                        displayed=0
                    )
                    session.add(new_match)
                    print(f"Created match record")

                    # Store messages
                    store_message(session, new_user.id, "incoming", message)
                    
                    response = (
                        f"Your profile has been created successfully {name}.\n"
                        f"SMS details#levelOfEducation#profession#maritalStatus#religion#ethnicity to 22141.\n"
                        f"E.g. details#diploma#driver#single#christian#mijikenda"
                    )
                    
                    store_message(session, new_user.id, "outgoing", response)
                    session.commit()
                    print("Transaction committed successfully")

                    return jsonify({"message": response}), 201
                except Exception as e:
                    print(f"Error during registration: {str(e)}")
                    session.rollback()
                    raise

            elif message_upper.startswith("DETAILS#"):
                if not user:
                    error_msg = (
                        "Welcome to our dating service with 6000 potential dating partners!\n"
                        "To register SMS start#name#age#gender#county#town to 22141.\n"
                        "E.g., start#John Doe#26#Male#Nakuru#Naivasha"
                    )
                    return jsonify({"message": error_msg}), 400

                parts = message.split("#")
                if len(parts) != 6:
                    error_msg = (
                        "Invalid format. Use: DETAILS#education#profession#status#religion#ethnicity\n"
                        "E.g., DETAILS#graduate#teacher#single#christian#kikuyu"
                    )
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 400

                _, education, profession, marital_status, religion, ethnicity = parts

                # Store or update user details
                user_details = session.query(UserMoreDetails).filter_by(user_id=user.id).first()
                if user_details:
                    user_details.level_of_education = education
                    user_details.profession = profession
                    user_details.marital_status = marital_status
                    user_details.religion = religion
                    user_details.ethnicity = ethnicity
                else:
                    user_details = UserMoreDetails(
                        user_id=user.id,
                        level_of_education=education,
                        profession=profession,
                        marital_status=marital_status,
                        religion=religion,
                        ethnicity=ethnicity
                    )
                    session.add(user_details)

                response = (
                    "This is the last stage of registration.\n"
                    "SMS a brief description of yourself to 22141 starting with the word MYSELF.\n"
                    "E.g., MYSELF chocolate, lovely, sexy etc."
                )

                store_message(session, user.id, "outgoing", response)
                session.commit()
                return jsonify({"message": response}), 200

            elif message_upper.startswith("MYSELF"):
                if not user:
                    error_msg = (
                        "Welcome to our dating service with 6000 potential dating partners!\n"
                        "To register SMS start#name#age#gender#county#town to 22141.\n"
                        "E.g., start#John Doe#26#Male#Nakuru#Naivasha"
                    )
                    return jsonify({"message": error_msg}), 400

                description = message[6:].strip()  # Remove "MYSELF" and leading/trailing spaces
                if not description:
                    error_msg = "Please provide a description after MYSELF"
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 400

                # Store or update user description
                user_description = session.query(UserSelfDescription).filter_by(user_id=user.id).first()
                if user_description:
                    user_description.description = description
                else:
                    user_description = UserSelfDescription(
                        user_id=user.id,
                        description=description
                    )
                    session.add(user_description)

                response = (
                    "You are now registered for dating.\n"
                    "To search for a MPENZI, SMS match#age#town to 22141 and meet the person of your dreams.\n"
                    "E.g., match#23-25#Kisumu"
                )

                store_message(session, user.id, "outgoing", response)
                session.commit()
                return jsonify({"message": response}), 200

            # 5. MATCH# - Match Request
            elif message_upper.startswith("MATCH#"):
                parts = message.split("#")
                if len(parts) != 3:
                    error_msg = "Invalid format. Use: match#age-range#town\nE.g., match#23-25#Nairobi"
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 400

                _, age_range, town = parts

                try:
                    min_age, max_age = validate_age_range(age_range)
                except ValidationError as e:
                    error_msg = str(e)
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 400

                # Find matches
                opposite_gender = "Female" if user.gender == "Male" else "Male"
                matching_users = session.query(User).filter(
                    User.gender == opposite_gender,
                    User.age.between(min_age, max_age),
                    func.lower(User.county) == func.lower(town)
                ).all()

                if not matching_users:
                    error_msg = f"No {opposite_gender.lower()} matches found in {town} between ages {min_age}-{max_age}"
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 200

                # Format response
                gender_term = "ladies" if opposite_gender == "Female" else "men"
                gender_singular = "lady" if opposite_gender == "Female" else "man"
                gender_pronoun = "her" if opposite_gender == "Female" else "his"
                num_matches = len(matching_users)
                show_matches = min(num_matches, 3)  # Show up to 3 matches
                
                response = f"We have {num_matches} {gender_term} who match your choice! "
                if num_matches > 1:
                    response += f"We will send you details of {show_matches} of them shortly.\n"
                else:
                    response += "We will send you their details shortly.\n"
                    
                response += f"To get more details about a {gender_singular}, SMS {gender_pronoun} number e.g., 0722010203 to 22141\n"
                
                # Get matches with their phone numbers
                for i, match_user in enumerate(matching_users[:show_matches]):
                    match_phone = session.query(Match).filter_by(matched_user_id=match_user.id).first()
                    phone = match_phone.phone_number if match_phone else "No phone"
                    response += f"{match_user.name} aged {match_user.age}, {phone}.\n"
                
                remaining = num_matches - show_matches
                if remaining > 0:
                    response += f"Send NEXT to 22141 to receive details of the remaining {remaining} {gender_term}"

                store_message(session, user.id, "outgoing", response)
                session.commit()
                return jsonify({"message": response}), 200

            elif message_upper == "NEXT":
                if not user:
                    error_msg = (
                        "Welcome to our dating service with 6000 potential dating partners!\n"
                        "To register SMS start#name#age#gender#county#town to 22141.\n"
                        "E.g., start#John Doe#26#Male#Nakuru#Naivasha"
                    )
                    return jsonify({"message": error_msg}), 400

                print("\n=== NEXT Command Processing ===")
                print(f"User: {user.name}")

                # Get the user's latest match batch that has remaining matches
                latest_batch = session.query(MatchBatch)\
                    .filter(
                        MatchBatch.user_id == user.id,
                        MatchBatch.total_matches > MatchBatch.matches_shown
                    )\
                    .order_by(MatchBatch.created_at.desc())\
                    .first()

                print(f"Latest batch found: {latest_batch is not None}")

                if not latest_batch:
                    error_msg = "No more matches available. Please send a new MATCH request."
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 404

                # Load match data from JSON
                match_data = json.loads(latest_batch.match_data)
                total_matches = latest_batch.total_matches
                shown_so_far = latest_batch.matches_shown
                remaining = total_matches - shown_so_far

                print(f"Total matches: {total_matches}")
                print(f"Shown so far: {shown_so_far}")
                print(f"Remaining: {remaining}")

                # Get next batch of up to 3 matches
                next_matches = match_data[shown_so_far:shown_so_far + 3]
                matches_to_show = len(next_matches)

                print(f"Showing next {matches_to_show} matches")

                # Format match details
                match_details = []
                for match in next_matches:
                    match_details.append(f"{match['name']} aged {match['age']}, {match['phone']}.")

                # Update matches shown
                latest_batch.matches_shown = shown_so_far + matches_to_show
                
                # Format response
                response = "\n".join(match_details)
                remaining_after = total_matches - (shown_so_far + matches_to_show)

                if remaining_after > 0:
                    if user.gender == "Female":
                        gender_term = "man" if remaining_after == 1 else "men"
                    else:
                        gender_term = "lady" if remaining_after == 1 else "ladies"
                    
                    response += f"\n\nSend NEXT to 22141 to receive details of the remaining {remaining_after} {gender_term}"

                print(f"Response: {response}")
                store_message(session, user.id, "outgoing", response)
                session.commit()
                return jsonify({"message": response}), 200

            # Before the NEXT command's return statement
            elif message_upper.startswith("DESCRIBE"):
                if not user:
                    error_msg = (
                        "Welcome to our dating service with 6000 potential dating partners!\n"
                        "To register SMS start#name#age#gender#county#town to 22141.\n"
                        "E.g., start#John Doe#26#Male#Nakuru#Naivasha"
                    )
                    return jsonify({"message": error_msg}), 400

                try:
                    phone_number = message.split(" ")[1]
                except IndexError:
                    return jsonify({"message": "Please provide a phone number to describe"}), 400

                # Find the user by phone number
                match_record = session.query(Match).filter(
                    or_(
                        Match.phone_number == phone_number,
                        Match.phone_number.like(f"%{phone_number[-9:]}")
                    )
                ).first()

                if not match_record:
                    return jsonify({"message": "User not found"}), 404

                target_user = session.query(User).get(match_record.matched_user_id)
                if not target_user:
                    return jsonify({"message": "User not found"}), 404

                # Get self description
                description = session.query(UserSelfDescription)\
                    .filter_by(user_id=target_user.id)\
                    .first()

                if not description:
                    return jsonify({"message": f"{target_user.name} has not added a self description yet"}), 404

                # Use gender-specific pronouns
                reflexive_pronoun = "herself" if target_user.gender == "Female" else "himself"
                
                response = f"{target_user.name} describes {reflexive_pronoun} as {description.description}"
                
                # Store the message
                store_message(session, user.id, "outgoing", response)

                return jsonify({"message": response}), 200

            # Handle phone number inputs
            elif message.replace("+", "").strip().isdigit():
                if not user:
                    error_msg = (
                        "Welcome to our dating service with 6000 potential dating partners!\n"
                        "To register SMS start#name#age#gender#county#town to 22141.\n"
                        "E.g., start#John Doe#26#Male#Nakuru#Naivasha"
                    )
                    return jsonify({"message": error_msg}), 400

                target_phone = message.strip()
                target_match = session.query(Match).filter(
                    Match.phone_number.like(f"%{target_phone[-9:]}")
                ).first()

                if not target_match:
                    error_msg = "User not found with that number"
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 404

                target_user = session.query(User).get(target_match.matched_user_id)
                target_details = session.query(UserMoreDetails).filter_by(
                    user_id=target_user.id
                ).first()

                if not target_details:
                    error_msg = "User details not found"
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 404

                if target_user.gender == user.gender:
                    error_msg = "Invalid request. Please try another number."
                    store_message(session, user.id, "outgoing", error_msg)
                    return jsonify({"message": error_msg}), 400

                # Format the profile details message
                profile_msg = (
                    f"{target_user.name} aged {target_user.age}, {target_user.county} County, {target_user.town} town, "
                    f"{target_details.level_of_education}, {target_details.profession}, {target_details.marital_status}, "
                    f"{target_details.religion}, {target_details.ethnicity}. "
                    f"Send DESCRIBE {target_match.phone_number} to get more details about {target_user.name}."
                )

                # Format the notification message for the viewed user
                gender_term = "lady" if user.gender == "Female" else "man"
                pronoun = "her" if user.gender == "Female" else "him"
                subject_pronoun = "she" if user.gender == "Female" else "he"
                
                notification_msg = (
                    f"Hi {target_user.name}, a {gender_term} called {user.name} is interested in you "
                    f"and requested your details.\n{subject_pronoun.capitalize()} is aged {user.age} based in {user.county}.\n"
                    f"Do you want to know more about {pronoun}? Send YES to 22141"
                )

                # Store messages without phone number
                store_message(session, user.id, "outgoing", profile_msg)
                store_message(session, target_user.id, "outgoing", notification_msg)

                return jsonify({
                    "messages": [
                        {"message": profile_msg},
                        {"message": notification_msg, "to": target_match.phone_number}
                    ]
                }), 200

            else:
                error_msg = get_help_message()
                if user:
                    store_message(session, user.id, "outgoing", error_msg)
                return jsonify({"message": error_msg}), 400

    except Exception as e:
        print("\n=== ERROR DETAILS ===")
        print("Error Type:", type(e).__name__)
        print("Error Message:", str(e))
        print("\nFull Traceback:")
        traceback.print_exc(file=sys.stdout)
        print("\nRequest Data:")
        print("Headers:", dict(request.headers))
        print("Data:", request.get_json())
        print("=== END ERROR DETAILS ===\n")
        
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500
    
@app.route("/api/penzi/location-analytics", methods=["GET"])
def get_location_analytics():
    try:
        with get_session() as session:
            # Get county distribution
            county_distribution = (
                session.query(
                    User.county,
                    func.count(User.id).label('count')
                )
                .group_by(User.county)
                .all()
            )

            # Get top active counties
            top_counties = (
                session.query(
                    User.county,
                    func.count(distinct(User.id)).label('user_count'),
                    func.count(distinct(Message.id)).label('message_count')
                )
                .outerjoin(Message, User.id == Message.user_id)
                .group_by(User.county)
                .order_by(func.count(distinct(User.id)).desc())
                .limit(10)
                .all()
            )

            # Get popular towns
            popular_towns = (
                session.query(
                    User.town,
                    User.county,
                    func.count(User.id).label('count')
                )
                .group_by(User.town, User.county)
                .order_by(func.count(User.id).desc())
                .limit(10)
                .all()
            )

            return jsonify({
                "countyDistribution": [
                    {"county": county, "count": count}
                    for county, count in county_distribution
                ],
                "topCounties": [
                    {
                        "county": county,
                        "userCount": user_count,
                        "messageCount": message_count
                    }
                    for county, user_count, message_count in top_counties
                ],
                "popularTowns": [
                    {
                        "town": town,
                        "county": county,
                        "count": count
                    }
                    for town, county, count in popular_towns
                ]
            })

    except Exception as e:
        print(f"Error in location analytics: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/penzi/users", methods=["GET"])
def get_users():
    try:
        print("Attempting to fetch users...")  # Debug log
        with get_session() as session:
            users = session.query(User).all()
            user_count = len(users)
            print(f"Found {user_count} users")  # Debug log
            return jsonify({
                "users": [{
                    'id': user.id,
                    'name': user.name,
                    'age': user.age,
                    'gender': user.gender,
                    'county': user.county,
                    'town': user.town,
                    'created_at': user.created_at.isoformat()
                } for user in users]
            })
    except Exception as e:
        print(f"Error in get_users: {str(e)}")  # Debug log
        return jsonify({"error": str(e)}), 500

@app.route("/api/penzi/messages", methods=["GET"])
def get_messages():
    try:
        # Add some debug logging
        print("Fetching messages...")
        with get_session() as session:
            messages = session.query(Message).all()
            print(f"Found {len(messages)} messages")
            return jsonify({
                "messages": [{
                    'id': message.id,
                    'direction': message.message_direction,
                    'text': message.message_text,
                    'created_at': message.created_at.isoformat()
                } for message in messages]
            })
    except Exception as e:
        print(f"Error fetching messages: {str(e)}")
        return jsonify({"error": "Failed to fetch messages"}), 500

@app.route("/api/penzi/dashboard/stats", methods=["GET"])
def get_stats():
    try:
        with get_session() as session:
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            
            # Get daily stats for the last 7 days
            timeline_labels = []
            timeline_users = []
            timeline_messages = []
            timeline_matches = []

            for i in range(6, -1, -1):  # 7 days, from oldest to newest
                date = today - timedelta(days=i)
                date_start = date
                date_end = date + timedelta(days=1)
                
                daily_users = session.query(func.count(User.id)).filter(
                    func.date(User.created_at) == date
                ).scalar() or 0
                
                daily_messages = session.query(func.count(Message.id)).filter(
                    Message.created_at >= date_start,
                    Message.created_at < date_end
                ).scalar() or 0
                
                daily_matches = session.query(func.count(Message.id)).filter(
                    Message.created_at >= date_start,
                    Message.created_at < date_end,
                    Message.message_text.like('match%')
                ).scalar() or 0

                timeline_labels.append(date.strftime("%d %b"))
                timeline_users.append(daily_users)
                timeline_messages.append(daily_messages)
                timeline_matches.append(daily_matches)

            # Get gender distribution
            gender_stats = session.query(
                User.gender,
                func.count(User.id).label('count')
            ).group_by(User.gender).all()

            gender_labels = [g[0] for g in gender_stats]
            gender_data = [g[1] for g in gender_stats]

            # Get age distribution
            age_ranges = [
                (18, 25, "18-25"),
                (26, 35, "26-35"),
                (36, 45, "36-45"),
                (46, 55, "46-55"),
                (56, 100, "56+")
            ]

            age_labels = []
            age_data = []

            for min_age, max_age, label in age_ranges:
                count = session.query(func.count(User.id)).filter(
                    User.age >= min_age,
                    User.age <= max_age
                ).scalar() or 0
                age_labels.append(label)
                age_data.append(count)

            # Calculate main stats
            total_users = session.query(func.count(User.id)).scalar()
            users_yesterday = session.query(func.count(User.id)).filter(
                func.date(User.created_at) < today
            ).scalar() or 1

            active_matches_today = session.query(func.count(Message.id)).filter(
                Message.created_at >= today,
                Message.message_text.like('match%')
            ).scalar()
            active_matches_yesterday = session.query(func.count(Message.id)).filter(
                Message.created_at >= yesterday,
                Message.created_at < today,
                Message.message_text.like('match%')
            ).scalar() or 1

            messages_today = session.query(func.count(Message.id)).filter(
                Message.created_at >= today
            ).scalar()
            messages_yesterday = session.query(func.count(Message.id)).filter(
                Message.created_at >= yesterday,
                Message.created_at < today
            ).scalar() or 1

            # Calculate percentage changes
            users_change = ((total_users - users_yesterday) / users_yesterday * 100)
            matches_change = ((active_matches_today - active_matches_yesterday) / active_matches_yesterday * 100)
            messages_change = ((messages_today - messages_yesterday) / messages_yesterday * 100)

            # Success rate calculation
            total_matches = session.query(func.count(Message.id)).filter(
                Message.message_text.like('match%')
            ).scalar() or 1
            successful_matches = session.query(func.count(Message.id)).filter(
                Message.message_text.like('NEXT%')
            ).scalar()
            success_rate = (successful_matches / total_matches * 100)
            success_rate_yesterday = ((successful_matches - 1) / total_matches * 100) if successful_matches > 0 else 0
            success_change = success_rate - success_rate_yesterday

            return jsonify({
                "totalUsers": total_users,
                "activeMatches": active_matches_today,
                "messagesToday": messages_today,
                "successRate": round(success_rate, 1),
                "dailyChange": {
                    "users": round(users_change, 1),
                    "matches": round(matches_change, 1),
                    "messages": round(messages_change, 1),
                    "success": round(success_change, 1)
                },
                "charts": {
                    "timeline": {
                        "labels": timeline_labels,
                        "datasets": {
                            "users": timeline_users,
                            "messages": timeline_messages,
                            "matches": timeline_matches
                        }
                    },
                    "gender": {
                        "labels": gender_labels,
                        "data": gender_data
                    },
                    "ageDistribution": {
                        "labels": age_labels,
                        "data": age_data
                    }
                }
            })

    except Exception as e:
        print(f"Error in dashboard stats: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/penziusers/export", methods=['GET'])
def export_users():
    try:
        with get_session() as session:
            # Get all users with their details
            users = session.query(User).all()
            
            # Create a StringIO object to write CSV data
            si = StringIO()
            writer = csv.writer(si)
            
            # Write headers
            writer.writerow([
                'ID', 'Name', 'Age', 'Gender', 'County', 'Town', 
                'Education', 'Profession', 'Marital Status', 
                'Religion', 'Ethnicity', 'Description', 'Joined Date'
            ])
            
            # Write user data
            for user in users:
                # Get additional details
                details = session.query(UserMoreDetails).filter_by(user_id=user.id).first()
                description = session.query(UserSelfDescription).filter_by(user_id=user.id).first()
                
                writer.writerow([
                    user.id,
                    user.name,
                    user.age,
                    user.gender,
                    user.county,
                    user.town,
                    details.level_of_education if details else '',
                    details.profession if details else '',
                    details.marital_status if details else '',
                    details.religion if details else '',
                    details.ethnicity if details else '',
                    description.description if description else '',
                    user.created_at.strftime('%Y-%m-%d %H:%M:%S')
                ])
            
            # Create the response
            output = make_response(si.getvalue())
            output.headers["Content-Disposition"] = f"attachment; filename=users-{datetime.now().strftime('%Y-%m-%d')}.csv"
            output.headers["Content-type"] = "text/csv"
            return output
            
    except Exception as e:
        print(f"Error exporting users: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

@app.route('/api/penzi/users/<int:user_id>', methods=['GET'])
def get_user_details(user_id):
    try:
        print(f"Fetching details for user ID: {user_id}")
        with get_session() as session:
            # Get all messages for the user
            messages = session.query(Message).filter(
                Message.user_id == user_id
            ).order_by(Message.created_at.asc()).all()

            user = session.query(User).filter(User.id == user_id).first()
            
            if not user:
                print(f"User {user_id} not found")
                return jsonify({"error": "User not found"}), 404

            print(f"Found {len(messages)} messages for user")

            # Initialize data containers
            registration_data = {}
            details_data = {}
            description = None

            # Process all messages to extract information
            for message in messages:
                text = message.message_text.lower()
                print(f"Processing message: {text[:50]}...")  # Log first 50 chars

                # Process START message
                if text.startswith('start#'):
                    parts = message.message_text.split('#')
                    if len(parts) >= 6:
                        registration_data = {
                            'name': parts[1],
                            'age': parts[2],
                            'gender': parts[3],
                            'county': parts[4],
                            'town': parts[5].strip()
                        }
                        print(f"Extracted registration data: {registration_data}")

                # Process DETAILS message
                elif text.startswith('details#'):
                    parts = message.message_text.split('#')
                    if len(parts) >= 6:
                        details_data = {
                            'education': parts[1],
                            'profession': parts[2],
                            'marital_status': parts[3],
                            'religion': parts[4],
                            'ethnicity': parts[5].strip()
                        }
                        print(f"Extracted details data: {details_data}")

                # Process MYSELF message
                elif text.startswith('myself'):
                    description = message.message_text.replace('MYSELF', '', 1).strip()
                    print(f"Extracted description: {description}")

            # Combine all data
            user_data = {
                'id': user.id,
                'name': registration_data.get('name', user.name),
                'age': int(registration_data.get('age', user.age)),
                'gender': registration_data.get('gender', user.gender),
                'county': registration_data.get('county', user.county),
                'town': registration_data.get('town', user.town),
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'details': {
                    'education': details_data.get('education'),
                    'profession': details_data.get('profession'),
                    'marital_status': details_data.get('marital_status'),
                    'religion': details_data.get('religion'),
                    'ethnicity': details_data.get('ethnicity')
                },
                'description': description
            }
            
            print(f"Final user data being returned: {user_data}")
            return jsonify(user_data)
            
    except Exception as e:
        print(f"Error in get_user_details: {str(e)}")
        print(f"Exception type: {type(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/penzi/users/<int:user_id>/messages', methods=['GET'])
def get_user_messages(user_id):
    try:
        print(f"Fetching messages for user_id: {user_id}")
        with get_session() as session:
            messages = session.query(Message).filter(
                Message.user_id == user_id
            ).order_by(Message.created_at.desc()).all()
            
            print(f"Found {len(messages)} messages")
            
            formatted_messages = [{
                'id': message.id,
                'message_text': message.message_text,
                'message_direction': message.message_direction,
                'created_at': message.created_at.isoformat(),
                'user_id': message.user_id
            } for message in messages]
            
            print(f"Returning {len(formatted_messages)} formatted messages")
            return jsonify({"messages": formatted_messages})
            
    except Exception as e:
        print(f"Error fetching messages: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Only run the app if this file is run directly
if __name__ == "__main__":
    print("Starting Penzi SMS Server...")
    app.run(host='localhost', port=5001, debug=True)
