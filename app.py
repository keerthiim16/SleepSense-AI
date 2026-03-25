from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Dict, List, Tuple
from functools import wraps
from datetime import datetime

from openai import OpenAI
import mysql.connector
from mysql.connector import Error as MySQLError
import numpy as np
from datetime import timedelta
from flask import Flask, jsonify, redirect, render_template, request, session, url_for


app = Flask(__name__)
app.secret_key = "sleepsenseai-secret-key-change-in-production"

openai_api_key = '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'

def format_time(created_at: datetime) -> str:
    """Format timestamp to human-readable relative time."""
    now = datetime.now()
    today = now.date()
    created_date = created_at.date()
    
    if created_date == today:
        return f"Today at {created_at.strftime('%I:%M %p')}"
    elif created_date == today - timedelta(days=1):
        return f"Yesterday at {created_at.strftime('%I:%M %p')}"
    else:
        days_ago = (today - created_date).days
        if days_ago < 7:
            return f"{days_ago} days ago"
        else:
            return created_at.strftime("%b %d")
if openai_api_key:
    client = OpenAI(api_key=openai_api_key)
else:
    client = None
    print("WARNING: OPENAI_API_KEY is not set, OpenAI features are disabled.")

MODEL_PATH = Path("model") / "model.pkl"
with MODEL_PATH.open("rb") as model_file:
    model = pickle.load(model_file)

DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "sleepuser",
    "password": "sleep123",
    "database": "sleep_ai",
}

FEATURE_ORDER = [
    "Gender",
    "Age",
    "Occupation",
    "Sleep Duration",
    "Physical Activity Level",
    "Stress Level",
    "BMI Category",
    "Heart Rate",
    "Daily Steps",
    "Systolic_BP",
    "Diastolic_BP",
]

SLEEP_CLASS_MAPPING = {
    0: "Insomnia",
    1: "Sleep Apnea",
}

GENDER_MAP = {"Male": 1, "Female": 0}
OCCUPATION_MAP = {
    "Scientist": 0,
    "Teacher": 1,
    "Accountant": 2,
    "Salesperson": 3,
    "Engineer": 4,
    "Lawyer": 5,
    "Doctor": 6,
    "Manager": 7,
    "Nurse": 8,
    "Software Engineer": 9,
    "Sales Representative": 10,
}
BMI_MAP = {
    "Normal": 0,
    "Normal Weight": 1,
    "Overweight": 2,
    "Obese": 3,
}

# Dataset averages for behavior comparison
DATASET_AVERAGES = {
    "avg_stress": 5.5,
    "avg_sleep": 7.0,
    "avg_activity": 50.0,
}


def parse_bp(bp_value: str) -> Tuple[int, int]:
    parts = bp_value.strip().split("/")
    if len(parts) != 2:
        raise ValueError("Blood Pressure must be in format systolic/diastolic (e.g. 120/80).")
    systolic, diastolic = int(parts[0]), int(parts[1])
    return systolic, diastolic


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def get_db_cursor(dictionary: bool = False):
    conn = get_db_connection()
    return conn, conn.cursor(buffered=True, dictionary=dictionary)


def get_db_health_message() -> str | None:
    try:
        conn = get_db_connection()
        conn.close()
        return None
    except MySQLError as ex:
        return f"Database connection issue: {str(ex)}"


def init_db() -> None:
    conn = mysql.connector.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cursor = conn.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS sleep_ai")
    cursor.close()
    conn.close()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) UNIQUE,
            password VARCHAR(100)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            username VARCHAR(100),
            input_data TEXT,
            result VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_user_by_username(username: str) -> Dict | None:
    conn, cursor = get_db_cursor(dictionary=True)
    cursor.execute("SELECT id, username, password FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def get_sleep_score(payload: Dict) -> int:
    sleep_duration = float(payload["Sleep Duration"])
    stress = int(payload["Stress Level"])
    activity = int(payload["Physical Activity Level"])
    steps = int(payload["Daily Steps"])
    heart_rate = int(payload["Heart Rate"])
    systolic = int(payload["Systolic_BP"])
    diastolic = int(payload["Diastolic_BP"])
    bmi_text = payload["BMI Category"]

    score = 55.0
    score += max(min((sleep_duration - 6.5) * 10.0, 22), -22)
    score += max(min((activity - 45) * 0.25, 12), -10)
    score -= stress * 3.0
    score += max(min((steps - 7000) / 700, 8), -8)

    if heart_rate > 80:
        score -= min((heart_rate - 80) * 0.6, 10)
    elif heart_rate < 60:
        score -= min((60 - heart_rate) * 0.3, 5)
    else:
        score += 3

    if systolic > 130 or diastolic > 85:
        score -= 8
    elif systolic < 100 or diastolic < 65:
        score -= 4
    else:
        score += 4

    if bmi_text in ("Overweight", "Obese"):
        score -= 6 if bmi_text == "Overweight" else 10
    else:
        score += 4

    return int(max(0, min(100, round(score))))


def get_risk_level(disorder_idx: int, score: int) -> str:
    if disorder_idx == 0 and score >= 70:
        return "Low"
    if disorder_idx == 2 or score < 45:
        return "High"
    return "Medium"


def get_persona(payload: Dict) -> str:
    stress = int(payload["Stress Level"])
    sleep = float(payload["Sleep Duration"])
    activity = int(payload["Physical Activity Level"])

    if stress >= 7 and sleep < 6.5:
        return "Overworked Individual"
    if stress <= 4 and sleep >= 7 and activity >= 50:
        return "Healthy Individual"
    return "Balanced Lifestyle"


def get_explanations(payload: Dict) -> List[str]:
    stress = int(payload["Stress Level"])
    sleep = float(payload["Sleep Duration"])
    activity = int(payload["Physical Activity Level"])
    steps = int(payload["Daily Steps"])
    bmi = payload["BMI Category"]

    explanations: List[str] = []
    if stress >= 7:
        explanations.append("High stress reduced sleep quality and increased recovery load.")
    elif stress <= 3:
        explanations.append("Lower stress supports better sleep continuity and deeper rest.")

    if sleep < 6.5:
        explanations.append("Short sleep duration lowered your overall sleep stability score.")
    elif sleep >= 7.5:
        explanations.append("Adequate sleep duration improved your resilience and recovery.")

    if activity < 35 or steps < 6000:
        explanations.append("Low activity increased risk and reduced day-night sleep balance.")
    elif activity >= 55 and steps >= 8000:
        explanations.append("Healthy activity levels helped maintain stronger sleep health.")

    if bmi in ("Overweight", "Obese"):
        explanations.append("Higher BMI category contributed to elevated breathing-related sleep risk.")

    if not explanations:
        explanations.append("Your current profile is relatively stable with mixed but manageable sleep factors.")
    return explanations


def generate_structured_assessment(payload: Dict, sleep_score: int, risk: str, disorder: str) -> Dict:
    key_factors = []
    suggestions = []

    sleep_duration = float(payload["Sleep Duration"])
    stress = int(payload["Stress Level"])
    activity = int(payload["Physical Activity Level"])
    heart_rate = int(payload["Heart Rate"])
    systolic = int(payload["Systolic_BP"])
    diastolic = int(payload["Diastolic_BP"])

    if sleep_duration < 6.5:
        key_factors.append(f"Sleep duration is low ({sleep_duration}h)")
        suggestions.append(f"Improve sleep duration from {sleep_duration}h toward 7-8h.")
    elif sleep_duration > 9:
        key_factors.append(f"Sleep duration is high ({sleep_duration}h)")
        suggestions.append(f"Keep sleep timing consistent to avoid oversleep dysregulation.")

    if stress >= 7:
        key_factors.append(f"High stress level ({stress}/10)")
        suggestions.append(f"Reduce stress level from {stress}/10 using stress management techniques.")
    elif stress <= 3:
        key_factors.append(f"Low stress level ({stress}/10)")

    if activity < 40:
        key_factors.append(f"Low activity ({activity})")
        suggestions.append(f"Increase daily activity to raise sleep score and resilience.")
    elif activity > 90:
        key_factors.append(f"Very high activity ({activity})")

    if heart_rate < 60 or heart_rate > 100:
        key_factors.append(f"Heart rate out of optimal range ({heart_rate} bpm)")
        suggestions.append(f"Monitor heart rate {heart_rate} bpm and adjust recovery practices.")

    if systolic > 130 or diastolic > 85:
        key_factors.append(f"Elevated blood pressure ({systolic}/{diastolic})")
        suggestions.append(f"Track blood pressure readings and manage as needed.")
    elif systolic < 100 or diastolic < 60:
        key_factors.append(f"Low blood pressure ({systolic}/{diastolic})")

    if sleep_score < 70:
        key_factors.append(f"Moderate sleep score ({sleep_score}/100)")
        suggestions.append(f"Improve sleep score from {sleep_score}/100 by addressing key factors.")

    if not key_factors:
        key_factors = ["All metrics are within normal ranges"]
        suggestions = ["Continue the current routine and monitor regularly."]

    return {
        "key_factors": key_factors,
        "suggestions": suggestions,
    }


def generate_ai_response(data: Dict, prediction: str) -> Dict:
    prompt = f"""
You are a sleep expert AI.

User Data:
- Stress Level: {data['stress']}
- Sleep Duration: {data['sleep']}
- Activity Level: {data['activity']}
- Occupation: {data['occupation']}

Prediction: {prediction}

Give:
1. Short explanation
2. 3 personalized suggestions
3. One key insight

Keep it short and clear.
"""

    if client is None:
        # OpenAI is unavailable; return safe fallback text.
        return {
            "explanation": "OpenAI API key missing. Use the model recommendations and behavior insights instead.",
            "suggestions": [
                "Follow behavior insights and model-based recommendations.",
                "Improve stress and sleep consistency.",
                "Track your metrics daily and adjust slowly."
            ],
            "insight": "Consistent tracking and guided improvements reduce risk over time.",
            "raw": "",
        }

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=180,
            temperature=0.7,
        )
        text = response.choices[0].message.content.strip()

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        explanation = lines[0] if lines else "Sleep data indicates mixed risk factors."
        suggestions = []
        insight = ""

        for line in lines[1:]:
            if line.lower().startswith("1") or line.lower().startswith("2") or line.lower().startswith("3"):
                suggestions.append(line)
            elif "insight" in line.lower() or line.lower().startswith("key insight"):
                insight = line

        if not suggestions:
            suggestions = ["Maintain routines and focus on key sleep factors."]
        if not insight:
            insight = "A focused approach to the identified issues will improve sleep quality."

        return {
            "explanation": explanation,
            "suggestions": suggestions,
            "insight": insight,
            "raw": text,
        }
    except Exception as exc:
        print(f"OpenAI call failed: {exc}")
        return {
            "explanation": "Sleep profile shows mixed risk indicators; follow the current recommendations.",
            "suggestions": [
                "Follow behavior insights and models suggestions.",
                "Improve stress and sleep consistency.",
                "Track your metrics daily and adjust slowly."
            ],
            "insight": "Consistent tracking and guided improvements reduce risk over time.",
            "raw": "",
        }


def simulate_7_day_trend(score: int, disorder_idx: int) -> List[int]:
    if disorder_idx == 1:
        drift = [0, -1, -2, -1, 0, 1, 1]
    elif disorder_idx == 2:
        drift = [0, -2, -2, -1, 0, 1, 2]
    else:
        drift = [0, 1, 1, 0, 1, 2, 2]
    trend = [max(0, min(100, score + d)) for d in drift]
    return trend


def behavior_insight(user_stress: int, user_sleep: float, user_activity: int) -> Dict:
    avg_stress = DATASET_AVERAGES["avg_stress"]
    avg_sleep = DATASET_AVERAGES["avg_sleep"]
    avg_activity = DATASET_AVERAGES["avg_activity"]
    
    insights = []
    if user_stress > avg_stress:
        insights.append("Your stress level is higher than average")
    elif user_stress < avg_stress:
        insights.append("Your stress level is lower than average")
    else:
        insights.append("Your stress level is average")
    
    if user_sleep < avg_sleep:
        insights.append("Your sleep duration is lower than average")
    elif user_sleep > avg_sleep:
        insights.append("Your sleep duration is higher than average")
    else:
        insights.append("Your sleep duration is average")
    
    if user_activity > avg_activity:
        insights.append("Your activity level is above average")
    elif user_activity < avg_activity:
        insights.append("Your activity level is below average")
    else:
        insights.append("Your activity level is average")
    
    return {
        "stress_comparison": "Higher than average" if user_stress > avg_stress else ("Lower than average" if user_stress < avg_stress else "Normal"),
        "sleep_comparison": "Lower than average" if user_sleep < avg_sleep else ("Higher than average" if user_sleep > avg_sleep else "Normal"),
        "activity_comparison": "Above average" if user_activity > avg_activity else ("Below average" if user_activity < avg_activity else "Normal"),
        "insights": insights,
    }


def generate_occupation_recommendations(occupation: str, stress_level: int, sleep_duration: float, disorder: str) -> List[str]:
    recommendations = []
    
    # Occupation-specific recommendations
    occupation_lower = occupation.lower()
    if "student" in occupation_lower:
        recommendations.append("Avoid late-night study sessions and take regular breaks during study periods")
        recommendations.append("Create a consistent study schedule that aligns with your natural sleep rhythm")
    elif "teacher" in occupation_lower:
        recommendations.append("Prepare lesson plans earlier in the day to avoid evening work")
        recommendations.append("Use weekends for lesson planning to maintain work-life boundaries")
    elif "accountant" in occupation_lower:
        recommendations.append("Set strict work hours and avoid overtime during tax season")
        recommendations.append("Take short breaks every hour to prevent mental fatigue")
    elif "salesperson" in occupation_lower or "sales representative" in occupation_lower:
        recommendations.append("Schedule client meetings during optimal energy hours")
        recommendations.append("Practice stress management techniques before high-pressure sales calls")
    elif "engineer" in occupation_lower or "software engineer" in occupation_lower:
        recommendations.append("Take regular screen breaks using the 20-20-20 rule")
        recommendations.append("Complete complex coding tasks earlier in the day when focus is highest")
    elif "lawyer" in occupation_lower:
        recommendations.append("Set boundaries between work and personal time")
        recommendations.append("Use weekends to disconnect from case-related stress")
    elif "doctor" in occupation_lower:
        recommendations.append("Optimize shift schedules to allow adequate recovery time")
        recommendations.append("Practice mindfulness during high-stress medical procedures")
    elif "manager" in occupation_lower:
        recommendations.append("Delegate tasks effectively to prevent work overload")
        recommendations.append("Schedule team meetings during peak productivity hours")
    elif "nurse" in occupation_lower:
        recommendations.append("Take advantage of shift breaks for short rest periods")
        recommendations.append("Communicate with supervisors about shift fatigue concerns")
    else:
        recommendations.append("Maintain work-life balance appropriate to your profession")
        recommendations.append("Schedule demanding tasks during your peak energy periods")
    
    # Stress-based recommendations
    if stress_level >= 7:
        recommendations.append("Practice deep breathing exercises before bedtime")
        recommendations.append("Consider professional stress management counseling")
    elif stress_level >= 5:
        recommendations.append("Incorporate daily stress-reduction activities like meditation")
        recommendations.append("Limit caffeine intake, especially in the afternoon")
    
    # Sleep-based recommendations
    if sleep_duration < 6.5:
        recommendations.append("Aim for at least 7-8 hours of sleep nightly")
        recommendations.append("Create a wind-down routine 1 hour before bedtime")
    elif sleep_duration > 8.5:
        recommendations.append("Maintain consistent sleep duration even on weekends")
    
    # Disorder-specific recommendations
    if "insomnia" in disorder.lower():
        recommendations.append("Establish a consistent sleep schedule, even on weekends")
        recommendations.append("Create a sleep-friendly environment: cool, dark, and quiet")
    elif "sleep apnea" in disorder.lower():
        recommendations.append("Maintain a healthy weight to reduce apnea symptoms")
        recommendations.append("Consult a sleep specialist for proper diagnosis and treatment")
    
    # General recommendations
    recommendations.append("Limit screen time 1 hour before bed")
    recommendations.append("Exercise regularly, but not within 3 hours of bedtime")
    recommendations.append("Keep your bedroom cool (around 65°F/18°C)")
    
    return recommendations[:5]  # Return top 5 recommendations


def generate_faq(disorder: str) -> List[Dict]:
    faq = []
    
    if "insomnia" in disorder.lower():
        faq = [
            {
                "question": "Why am I getting insomnia risk?",
                "answer": "High stress levels and reduced sleep duration are the main contributing factors."
            },
            {
                "question": "How can I reduce stress before sleep?",
                "answer": "Try relaxation techniques like meditation, deep breathing, and avoiding screens before bed."
            },
            {
                "question": "How can I improve my sleep routine?",
                "answer": "Maintain a consistent sleep schedule and avoid caffeine in the evening."
            }
        ]
    elif "sleep apnea" in disorder.lower():
        faq = [
            {
                "question": "What is sleep apnea?",
                "answer": "Sleep apnea is a condition where breathing repeatedly stops during sleep."
            },
            {
                "question": "Should I consult a doctor?",
                "answer": "Yes, if symptoms persist, medical consultation is strongly recommended."
            },
            {
                "question": "How can I improve breathing during sleep?",
                "answer": "Maintain healthy weight, sleep position, and avoid alcohol before bed."
            }
        ]
    else:  # No disorder
        faq = [
            {
                "question": "How can I maintain good sleep?",
                "answer": "Keep a consistent sleep schedule and stay physically active."
            },
            {
                "question": "What habits improve sleep quality?",
                "answer": "Reduce screen time, manage stress, and create a relaxing sleep environment."
            },
            {
                "question": "How to avoid future sleep issues?",
                "answer": "Maintain healthy lifestyle habits and monitor stress levels regularly."
            }
        ]
    
    return faq


def get_expert_tips() -> List[str]:
    return [
        "Maintain a consistent sleep schedule, even on weekends",
        "Create a cool, dark, and quiet sleep environment",
        "Limit screen time and blue light exposure 1 hour before bed",
        "Exercise regularly, but complete workouts at least 3 hours before bedtime",
        "Practice stress management techniques like meditation or deep breathing",
        "Avoid caffeine, nicotine, and heavy meals close to bedtime",
        "Use your bed only for sleep and intimacy, not work or TV",
        "Keep your bedroom temperature between 60-67°F (15-19°C)",
        "Establish a relaxing pre-sleep routine",
        "Get natural sunlight exposure during the day",
        "Limit daytime naps to 20-30 minutes",
        "Consider a white noise machine for background sound",
        "Keep pets out of the bedroom if they disrupt sleep",
        "Use blackout curtains to block morning light",
        "Practice mental unloading - write down worries before bed"
    ]


def to_model_input(payload: Dict) -> List[float]:
    return [
        float(GENDER_MAP[payload["Gender"]]),
        float(payload["Age"]),
        float(OCCUPATION_MAP[payload["Occupation"]]),
        float(payload["Sleep Duration"]),
        float(payload["Physical Activity Level"]),
        float(payload["Stress Level"]),
        float(BMI_MAP[payload["BMI Category"]]),
        float(payload["Heart Rate"]),
        float(payload["Daily Steps"]),
        float(payload["Systolic_BP"]),
        float(payload["Diastolic_BP"]),
    ]


def build_response(feature_payload: Dict) -> Dict:
    input_row = to_model_input(feature_payload)
    prediction = int(model.predict(np.array([input_row], dtype=float))[0])

    # Extract values for rule override
    sleep_duration = float(feature_payload["Sleep Duration"])
    stress = int(feature_payload["Stress Level"])
    heart_rate = int(feature_payload["Heart Rate"])

    # RULE OVERRIDE: Healthy users get "No Sleep Disorder"
    if sleep_duration >= 7 and stress <= 4 and heart_rate < 80:
        disorder = "No Sleep Disorder"
    else:
        disorder = SLEEP_CLASS_MAPPING.get(prediction, "Unknown")

    # Calculate all metrics (applies to both override and model predictions)
    sleep_score = get_sleep_score(feature_payload)
    if disorder == "No Sleep Disorder":
        risk = "Low"
    else:
        risk = get_risk_level(prediction, sleep_score)
    persona = get_persona(feature_payload)
    explanations = get_explanations(feature_payload)
    behavior_insight_data = behavior_insight(
        int(feature_payload["Stress Level"]),
        float(feature_payload["Sleep Duration"]),
        int(feature_payload["Physical Activity Level"]),
    )
    structured_assessment = generate_structured_assessment(
        feature_payload,
        sleep_score,
        risk,
        disorder,
    )

    openai_input = {
        "stress": feature_payload["Stress Level"],
        "sleep": feature_payload["Sleep Duration"],
        "activity": feature_payload["Physical Activity Level"],
        "occupation": feature_payload["Occupation"],
    }
    openai_response = generate_ai_response(openai_input, disorder)

    ai_explanation = openai_response.get("explanation")
    openai_suggestions = openai_response.get("suggestions", [])
    openai_insight = openai_response.get("insight")

    occupation_recommendations = generate_occupation_recommendations(
        feature_payload["Occupation"],
        int(feature_payload["Stress Level"]),
        float(feature_payload["Sleep Duration"]),
        disorder
    )
    faq = generate_faq(disorder)
    expert_tips = get_expert_tips()

    return {
        "sleep_disorder": disorder,
        "sleep_class": prediction,
        "sleep_score": sleep_score,
        "risk_level": risk,
        "persona": persona,
        "explanations": explanations,
        "behavior_insights": behavior_insight_data,
        "ai_explanation": ai_explanation,
        "openai_suggestions": openai_suggestions,
        "openai_insight": openai_insight,
        "occupation_recommendations": occupation_recommendations,
        "faq": faq,
        "expert_tips": expert_tips,
    }


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    db_error = get_db_health_message()
    if request.method == "POST":
        if db_error:
            return render_template("signup.html", error=db_error, db_error=db_error)
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not username or not password:
            error = "Username and password are required."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif get_user_by_username(username):
            error = "Username already exists."
        else:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, password) VALUES (%s, %s)",
                    (username, password),
                )
                conn.commit()
                cursor.close()
                conn.close()
                return redirect(url_for("login", signup_success=1))
            except MySQLError as ex:
                error = f"Signup failed: {str(ex)}"
    return render_template("signup.html", error=error, db_error=db_error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    db_error = get_db_health_message()
    signup_success = request.args.get("signup_success") == "1"
    if request.method == "POST":
        if db_error:
            return render_template("login.html", error=db_error, db_error=db_error, signup_success=signup_success)
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = get_user_by_username(username)
        if not user or user["password"] != password:
            error = "Invalid username or password."
        else:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
    return render_template("login.html", error=error, db_error=db_error, signup_success=signup_success)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "index.html",
        username=session.get("username"),
        db_error=get_db_health_message(),
    )


@app.route("/sleep-calculator")
@login_required
def sleep_calculator():
    return render_template("calculator.html", username=session.get("username"))


@app.route("/blogs")
@login_required
def blogs():
    return render_template("blogs.html", username=session.get("username"))


@app.route("/faq")
@login_required
def faq():
    return render_template("faq.html", username=session.get("username"))


@app.route("/history", methods=["GET"])
@login_required
def history():
    try:
        conn, cursor = get_db_cursor(dictionary=True)
        cursor.execute(
            """
            SELECT input_data, result, created_at
            FROM history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 12
            """,
            (session["user_id"],),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except MySQLError as ex:
        return jsonify({"error": f"Failed to load history: {str(ex)}"}), 500

    return jsonify(
        {
            "history": [
                {
                    "input_data": row["input_data"],
                    "result": row["result"],
                    "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
                    "formatted_time": format_time(row["created_at"]),
                }
                for row in rows
            ]
        }
    )


@app.route("/clear_history", methods=["POST"])
@login_required
def clear_history():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history WHERE user_id = %s", (session["user_id"],))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True})
    except MySQLError as ex:
        return jsonify({"error": f"Failed to clear history: {str(ex)}"}), 500


@app.route("/sleep-log", methods=["POST"])
@login_required
def sleep_log():
    try:
        data = request.get_json(force=True)
        duration = data.get("durationMinutes")
        quality = data.get("quality")
        logged_at = data.get("loggedAt", datetime.now().isoformat())
        entry_text = f"Sleep log: {duration} min, {quality} quality"

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO history (user_id, username, input_data, result, created_at) VALUES (%s, %s, %s, %s, %s)",
            (session["user_id"], session["username"], str(data), entry_text, datetime.fromisoformat(logged_at) if isinstance(logged_at, str) else datetime.now()),
        )
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"success": True, "message": "Sleep log saved"})
    except MySQLError as ex:
        return jsonify({"error": f"Failed to save sleep log: {str(ex)}"}), 500
    except Exception as ex:
        return jsonify({"error": f"Invalid sleep log request: {str(ex)}"}), 400


@app.route("/predict", methods=["POST"])
@login_required
def predict():
    data = request.get_json(force=True)
    try:
        systolic, diastolic = parse_bp(data["Blood Pressure"])

        payload = {
            "Gender": data["Gender"],
            "Age": int(data["Age"]),
            "Occupation": data["Occupation"],
            "Sleep Duration": float(data["Sleep Duration"]),
            "Physical Activity Level": int(data["Physical Activity Level"]),
            "Stress Level": int(data["Stress Level"]),
            "BMI Category": data["BMI Category"],
            "Heart Rate": int(data["Heart Rate"]),
            "Daily Steps": int(data["Daily Steps"]),
            "Systolic_BP": systolic,
            "Diastolic_BP": diastolic,
        }

        result = build_response(payload)

        increased_sleep_payload = dict(payload)
        increased_sleep_payload["Sleep Duration"] = min(10.0, payload["Sleep Duration"] + 1.0)
        increased_sleep_result = build_response(increased_sleep_payload)
        increased_sleep_result["scenario"] = "Increase Sleep"

        reduced_stress_payload = dict(payload)
        reduced_stress_payload["Stress Level"] = max(1, payload["Stress Level"] - 2)
        reduced_stress_result = build_response(reduced_stress_payload)
        reduced_stress_result["scenario"] = "Reduce Stress"

        increased_activity_payload = dict(payload)
        increased_activity_payload["Physical Activity Level"] = min(
            100, payload["Physical Activity Level"] + 15
        )
        increased_activity_payload["Daily Steps"] = min(50000, payload["Daily Steps"] + 2000)
        increased_activity_result = build_response(increased_activity_payload)
        increased_activity_result["scenario"] = "Increase Activity"

        response = dict(result)
        response["scenarios"] = {
            "increase_sleep": increased_sleep_result,
            "reduce_stress": reduced_stress_result,
            "increase_activity": increased_activity_result,
        }
        response["feature_order_used"] = FEATURE_ORDER

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO history (user_id, username, input_data, result, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    session["user_id"],
                    session["username"],
                    str(payload),
                    result["sleep_disorder"],
                    datetime.now(),
                ),
            )
            conn.commit()
            cursor.close()
            conn.close()
        except MySQLError as ex:
            response["history_warning"] = f"Prediction saved failed: {str(ex)}"

        return jsonify(response)
    except KeyError as key_error:
        return jsonify({"error": f"Missing required field: {key_error}"}), 400
    except ValueError as value_error:
        return jsonify({"error": str(value_error)}), 400
    except Exception as ex:  # pragma: no cover
        return jsonify({"error": f"Prediction failed: {str(ex)}"}), 500


if __name__ == "__main__":
    try:
        init_db()
    except MySQLError:
        pass
    app.run(debug=True)
