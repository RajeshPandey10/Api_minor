from flask import Flask, request, jsonify
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Set backend before importing pyplot
import matplotlib.pyplot as plt
import seaborn as sns
import time
import pickle
import os
from deep_translator import GoogleTranslator
from langdetect import detect
import sys
import joblib  # add this import at the top

app = Flask(__name__)
CORS(app)

def retry_click(driver, selector, max_attempts=3):
    """Retries clicking an element if it fails."""
    for attempt in range(max_attempts):
        try:
            element = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            driver.execute_script("arguments[0].click();", element)
            return True
        except:
            print(f"Retry {attempt + 1} failed")
            time.sleep(2)
    return False

def setup_driver():
    """Sets up the Selenium WebDriver with necessary options."""
    options = webdriver.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--remote-debugging-port=9222')
    # Disable headless unless SHOW_CHROME env variable is "true"
    if os.environ.get("SHOW_CHROME", "false").lower() != "true":
        options.add_argument('--headless')
    
    # Set binary location depending on platform
    if sys.platform == 'darwin':
        mac_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if os.path.exists(mac_path):
            options.binary_location = mac_path
        else:
            raise Exception("Chrome binary not found on macOS. Install Google Chrome (e.g., via 'brew install --cask google-chrome').")
    else:
        binary = os.environ.get('GOOGLE_CHROME_BIN')
        if binary and os.path.exists(binary):
            options.binary_location = binary
        else:
            for path in ['/usr/bin/google-chrome',
                         '/usr/bin/google-chrome-stable',
                         '/usr/bin/chromium-browser',
                         '/usr/bin/chromium']:
                if os.path.exists(path):
                    options.binary_location = path
                    break
    # Remove explicit version to let ChromeDriverManager auto-detect
    service = Service(ChromeDriverManager().install())
    try:
        return webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print("Error creating Chrome session:", str(e))
        raise

def scrape_reviews(url):
    """Scrapes reviews from Daraz and saves them in a CSV file."""
    driver = setup_driver()
    # Lower implicit wait for faster response
    driver.implicitly_wait(10)
    wait = WebDriverWait(driver, 10)
    reviews_list = []
    
    try:
        print("Loading URL...")
        driver.get(url)
        time.sleep(5)  # Reduced initial delay

        # Scroll steps with reduced delay
        for scroll in range(0, 2000, 200):
            driver.execute_script(f"window.scrollTo(0, {scroll})")
            time.sleep(0.5)  # Reduced scrolling delay

        print("Finding reviews section...")
        review_tab = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, '[data-spm-anchor-id*="review"]')))
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth'});", review_tab)
        time.sleep(2)

        if not retry_click(driver, '[data-spm-anchor-id*="review"]'):
            print("Failed to click reviews tab")
            return 0

        page = 1
        while True:
            print(f"Processing page {page}")
            try:
                reviews = wait.until(EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, '.mod-reviews .item')))
            except Exception as e:
                print("No review container found:", e)
                break

            for review in reviews:
                try:
                    text = review.find_element(By.CSS_SELECTOR, '.content').text
                    date = review.find_element(By.CSS_SELECTOR, '.top').text
                    author = review.find_element(By.CSS_SELECTOR, '.middle').text
                    if text.strip():
                        reviews_list.append({
                            'reviewText': text.strip(),
                            'reviewDate': date.strip(),
                            'authorName': author.strip()
                        })
                        print(f"Found review #{len(reviews_list)}")
                except StaleElementReferenceException:
                    continue

            # Refresh page once if first pass no reviews found
            if not reviews_list and page == 1:
                print("No reviews found on first pass, refreshing the page...")
                driver.refresh()
                time.sleep(5)  # Reduced refresh delay
                continue

            if reviews_list:
                df = pd.DataFrame(reviews_list)
                df.to_csv('reviews.csv', index=False)

            try:
                next_button = driver.find_element(By.XPATH, '//button[contains(@class, "next-pagination-item next")]')
                next_button.click()
                if 'ant-pagination-disabled' in next_button.get_attribute("class"):
                    print("No more pages")
                    break
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth'});", next_button)
                time.sleep(1)
                page += 1
            except Exception as e:
                print(f"Pagination error: {str(e)}")
                print("No more pages")
                break
                
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        driver.quit()
    
    return len(reviews_list)

# Load the Logistic Regression model and vectorizer using joblib
try:
    model = joblib.load('model_LogisticRegression.pkl')
except Exception as e:
    print("Error loading model_LogisticRegression.pkl:", str(e))
    raise

try:
    vectorizer = joblib.load('vectorizer.pkl')
except Exception as e:
    print("Error loading vectorizer.pkl:", str(e))
    raise

# Function to analyze reviews using the Logistic Regression model
def analyze_reviews_with_rf():
    try:
        df = pd.read_csv('reviews.csv')
        print("CSV loaded, shape:", df.shape)
    except Exception as csv_err:
        print("Error reading CSV:", csv_err)
        raise

    # Check model and vectorizer loading (make sure these files are valid)
    try:
        with open('model_LogisticRegression.pkl', 'rb') as file:
            model = pickle.load(file)
        with open('vectorizer.pkl', 'rb') as file:
            vectorizer = pickle.load(file)
    except Exception as pkl_err:
        print("Error loading model/vectorizer:", pkl_err)
        raise

    # Handle missing values in the reviewText column
    df['reviewText'] = df['reviewText'].fillna('')  # Replace NaN with an empty string

    # Function to translate text to English
    def translate_to_english(text):
        try:
            lang = detect(text)  # Detect language
            if lang != "en":  # If not English, translate
                return GoogleTranslator(source='auto', target='en').translate(text)
            return text  # If already English, return as is
        except:
            return text  # If detection fails, return original

    # Apply translation to reviewText column
    df["translated_review"] = df["reviewText"].astype(str).apply(translate_to_english)

    # Save the translated dataset
    df.to_csv("translated_reviews.csv", index=False)

    print("Translation completed and saved!")

    # Transform reviews using the saved vectorizer
    try:
        X_test = vectorizer.transform(df['translated_review'])
        predictions = model.predict(X_test)
    except Exception as pred_err:
        print("Error during model prediction:", pred_err)
        raise

    # Manually map numeric predictions to sentiment labels
    sentiment_mapping = {
        0: "Negative",
        1: "Neutral",
        2: "Positive"
    }

    # Apply mapping to predictions
    df['sentiment'] = [sentiment_mapping[pred] for pred in predictions]

    # # Calculate the percentage of each sentiment label
    # sentiment_counts = df['sentiment'].value_counts(normalize=True) * 100

    # positive_percentage = sentiment_counts.get("Positive", 0)
    # negative_percentage = sentiment_counts.get("Negative", 0)
    # neutral_percentage = sentiment_counts.get("Neutral", 0)

    sentiment_distribution = df['sentiment'].value_counts(normalize=True).to_dict()
    # Ensure keys are lowercase for frontend compatibility
    sentiment_distribution = {k.lower(): v * 100 for k, v in sentiment_distribution.items()}

    # Mapping sentiment labels to numerical scores
    sentiment_scores = {
        "Negative": -1,
        "Neutral": 0,
        "Positive": 1
    }

    # Function to calculate compound score based on sentiment labels
    def get_compound_score(sentiment):
        return sentiment_scores.get(sentiment, 0)  # Default to 0 if sentiment is missing

    # Apply the function to calculate compound scores for each review
    df['compound'] = df['sentiment'].apply(get_compound_score)

    # Save the results to a new CSV file
    df[['reviewText', 'sentiment', 'compound']].to_csv('review_with_compound_scores.csv', index=False)

    # Calculate the overall compound score
    compound_score = (df['compound'].mean()+1)/2 * 10  # Scale compound score to 0-10

    # # Display results
    # print("SENTIMENT DISTRIBUTION".center(50, '-'))
    # print(f"Positive: {positive_percentage:.2f}%")
    # print(f"Negative: {negative_percentage:.2f}%")
    # print(f"Neutral: {neutral_percentage:.2f}%")

    print("CONFIDENCE SCORE".center(50, '-'))
    # Print the overall compound score
    print(f"Overall Compound Score for the product is: {compound_score:.2f} out of 10")
    # Return the results
    return {
        'confidence_score': compound_score,
        'total_reviews': len(df),
        'sentiment_distribution': sentiment_distribution,
        'sentiment_plot': 'static/sentiment.png'
    }

@app.route('/', methods=['POST'])
def analyze():
    """API endpoint to analyze product reviews."""
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({"error": "URL is required"}), 400
            
        num_reviews = scrape_reviews(url)
        if num_reviews == 0:
            return jsonify({"error": "No reviews found"}), 404
            
        # Analyze the reviews using the RandomForest model
        results = analyze_reviews_with_rf()
        
        # Visualization: Sentiment Distribution
        sentiment_counts = results['sentiment_distribution']
        plt.figure(figsize=(8, 6))
        sns.barplot(x=list(sentiment_counts.keys()), y=list(sentiment_counts.values()), hue=list(sentiment_counts.keys()), palette='viridis', legend=False)
        plt.title('Sentiment Distribution', fontsize=16)
        plt.xlabel('Sentiment', fontsize=14)
        plt.ylabel('Percentage (%)', fontsize=14)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.tight_layout()
        # Ensure the "static" directory exists before saving the file
        if not os.path.exists('static'):
            os.makedirs('static')
        plt.savefig('static/sentiment.png')  # Save the plot as an image
        plt.close()

        return jsonify({
            'success': True,
            'data': results
        })
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=8000, debug=True)