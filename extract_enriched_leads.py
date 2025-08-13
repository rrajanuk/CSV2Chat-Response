import pandas as pd
import time
import io
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, NoSuchElementException

# --- CONFIGURATION ---
CSV_OUTPUT_FILE = 'all_enriched_leads.csv'
GROK_URL = 'https://grok.com'

# Expected columns for validation
EXPECTED_COLUMNS = [
    "Agency Name", "Agency LinkedIn URL", "ICP Score", "Funding Details", "Business Description",
    "Pain Points Noted", "Decision Maker Name", "LinkedIn Profile", "X Handle", "MRR",
    "Annual Revenue", "Accounting - Departmental Head Count", "Finance - Department Head Count",
    "Decision Maker First Name", "Decision Maker Last Name", "Decision Maker Linkedin Profile URL",
    "Connection Request Message", "Follow-Up on Unaccepted Connection", "Message After Connection Acceptance",
    "Follow-Up Message (No Reply After Acceptance)", "Second Follow-Up Message (Persistent No Reply)",
    "Initial Outreach Message (Reference Pain Point, No Pitch)", "First Follow-Up Message (Prompt for Response)",
    "Second Follow-Up Message (After No Reply)"
]

def setup_driver():
    """Initializes and returns a Selenium Chrome WebDriver instance."""
    print("Setting up Chrome WebDriver...")
    options = uc.ChromeOptions()
    options.add_argument('--disable-extensions')
    driver = uc.Chrome(
        options=options,
        user_data_dir=r"C:\Users\Robin Rajan\AppData\Local\Google\Chrome\User Data\Profile 1",
        browser_executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        use_subprocess=True
    )
    driver.maximize_window()
    return driver

def extract_csv_from_response(response_element):
    """Extracts the CSV text from a response element."""
    try:
        # The response_element is now the markdown container itself.
        code_element = response_element.find_element(By.CSS_SELECTOR, 'code')
        csv_text = code_element.get_attribute('innerText').strip()
        return csv_text
    except NoSuchElementException:
        # This can happen if a response is just text, not a code block.
        # We can try getting the text from the parent element as a fallback.
        print("No code block found, trying to get text from parent.")
        try:
            return response_element.get_attribute('innerText').strip()
        except Exception:
            return None

def parse_and_append_csv(csv_text, output_file):
    """Parses CSV text flexibly, logs column differences, and appends to the output file."""
    if not csv_text:
        return False
    try:
        # Use the 'python' engine for more flexibility and to handle errors.
        df_new = pd.read_csv(io.StringIO(csv_text), engine='python', on_bad_lines='skip')

        if df_new.empty:
            print("--> Skipping response: unparsable or resulted in empty data.")
            return False

        # --- Enhanced Column Logging (Non-Blocking) ---
        found_cols = set(df_new.columns)
        expected_cols = set(EXPECTED_COLUMNS)
        if found_cols != expected_cols:
            print("--> Info: Column mismatch detected. Data will still be saved.")
            missing_cols = expected_cols - found_cols
            extra_cols = found_cols - expected_cols
            if missing_cols:
                print(f"    - Missing: {sorted(list(missing_cols))}")
            if extra_cols:
                print(f"    - Extra: {sorted(list(extra_cols))}")
        # -------------------------------------------------

        # Load existing data and combine
        print(f"--> Reading existing data from {output_file}...")
        df_existing = pd.read_csv(output_file)
        print(f"--> Found {len(df_existing)} existing leads.")
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)

        # Deduplicate if possible
        if 'Agency Name' in df_combined.columns:
            df_combined.drop_duplicates(subset=['Agency Name'], keep='last', inplace=True)
        else:
            print("--> Warning: 'Agency Name' column not found. Cannot deduplicate this batch.")

        # Save back to the file
        print(f"--> Writing {len(df_combined)} total leads back to {output_file}...")
        df_combined.to_csv(output_file, index=False)
        print(f"--> Successfully processed and saved {len(df_new)} new lead(s). Total unique leads: {len(df_combined)}.")
        return True
    except Exception as e:
        print(f"--> Skipping response due to critical parsing error: {e}")
        return False

def main():
    driver = setup_driver()
    driver.get(GROK_URL)

    # Manual intervention step
    input("Please log in to Grok, open the specific chat with all responses, and then press Enter here to continue...")

    # Ensure the output file exists with a header
    if not os.path.isfile(CSV_OUTPUT_FILE):
        print(f"Creating output file: {CSV_OUTPUT_FILE}")
        pd.DataFrame(columns=EXPECTED_COLUMNS).to_csv(CSV_OUTPUT_FILE, index=False)

    # This selector specifically targets the markdown content within AI responses (which are aligned left, 'items-start')
    # and ignores user prompts (which are aligned right, 'items-end').
    response_elements = driver.find_elements(By.CSS_SELECTOR, "div.items-start div.response-content-markdown")
    print(f"Found {len(response_elements)} AI responses to process.")

    processed_count = 0
    for idx, elem in enumerate(response_elements, 1):
        print(f"\nProcessing response {idx} of {len(response_elements)}...")
        csv_text = extract_csv_from_response(elem)
        if csv_text:
            if parse_and_append_csv(csv_text, CSV_OUTPUT_FILE):
                processed_count += 1

    print(f"\n✅ Reached the end of the page. All responses processed.")
    print(f"Total responses successfully parsed and saved: {processed_count}")
    driver.quit()

if __name__ == "__main__":
    main()