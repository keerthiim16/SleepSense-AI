# SleepSense-AI
# SleepSenseAI

SleepSenseAI is a web application that uses AI to analyze sleep patterns and provide personalized sleep recommendations. It features a sleep calculator, user authentication, and a blog section for sleep-related articles.

## Features

- **Sleep Calculator**: Input your sleep data to get AI-powered predictions and recommendations
- **User Authentication**: Sign up and log in to save your sleep history
- **Blog Section**: Read articles about sleep health and tips
- **FAQ**: Common questions about sleep and the app
- **History Tracking**: View your past sleep analyses

## Prerequisites

- Python 3.8 or higher
- MySQL Server
- OpenAI API Key (for AI features)

## Installation

1. Clone or download the project files.

2. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

3. Set up the MySQL database:
   - Create a MySQL database server
   - Run the `database_setup.sql` script to create the database and tables:
     ```
     mysql -u your_username -p < database_setup.sql
     ```

4. Configure the application:
   - Open `app.py` and update the `DB_CONFIG` with your MySQL credentials
   - Replace the `openai_api_key` with your actual OpenAI API key

5. Ensure the model file is present:
   - The `model/model.pkl` file should contain the trained XGBoost model

## Running the Application

1. Start the Flask application:
   ```
   python app.py
   ```

2. Open your web browser and navigate to `http://localhost:5000`

## Usage

- **Home**: Overview of the app
- **Calculator**: Enter your sleep data (age, sleep hours, etc.) to get predictions
- **Login/Signup**: Create an account to save your history
- **Blogs**: Read sleep-related articles
- **FAQ**: Get answers to common questions

## Demo Account

A demo account is available:
- Username: demo
- Password: demo123

## Technologies Used

- **Backend**: Flask (Python)
- **Database**: MySQL
- **AI**: OpenAI API, XGBoost model
- **Frontend**: HTML, CSS, JavaScript

## Contributing

Feel free to contribute to the project by submitting issues or pull requests.

## License

This project is for educational purposes. Please ensure compliance with OpenAI's terms of service.
