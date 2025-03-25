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
        with get_session() as session:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
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

