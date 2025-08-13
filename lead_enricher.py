import pandas as pd
import time
import json
import os
import io
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

# --- CONFIGURATION ---
CSV_INPUT_FILE = 'leads.csv'
CSV_OUTPUT_FILE = 'enriched_leads.csv'
# The script will pause on this page to allow you to manually log in and select your workspace.
GROK_URL = 'https://grok.com'
RATE_LIMIT_SECONDS = 120
  # 8 minutes delay between queries
BATCH_SIZE = 5

# --- PROMPT ENGINEERING SECTION ---
# This is the main prompt sent for each batch of leads.
# The '{leads_csv}' placeholder will be replaced with the actual lead data.
MAIN_PROMPT_TEMPLATE = """
You are an expert lead enrichment AI optimized for batch processing.

Input: A batch of leads as a CSV file content.

<DOCUMENT filename="leads.csv">
{leads_csv}												
</DOCUMENT>

Your task: enrich each lead with the required fields, and output ONLY the enriched leads as a **CSV string**, including all original columns plus new enrichment columns.

**Important:**

- Do NOT include any explanation, commentary, or summary.  
- Respond ONLY with the CSV string enclosed in triple backticks (```csv
- The CSV must be properly formatted and parsable.

Here is the CSV header you must include exactly as the first row:

Agency Name,Agency LinkedIn URL,ICP Score,Funding Details,Business Description,Pain Points Noted,Decision Maker Name,Decision Maker LinkedIn Profile,X Handle,MRR,Annual Revenue,Accounting - Departmental Head Count,Finance - Department Head Count,Decision Maker First Name,Decision Maker Last Name,Decision Maker Linkedin Profile URL,Connection Request Message,Follow-Up on Unaccepted Connection,Message After Connection Acceptance,Follow-Up Message (No Reply After Acceptance),Second Follow-Up Message (Persistent No Reply),Initial Outreach Message (Reference Pain Point, No Pitch),First Follow-Up Message (Prompt for Response),Second Follow-Up Message (After No Reply)

Process the input leads and enrich them accordingly.
"""

# This is the follow-up prompt. It can be used to ask for more details or corrections.
SUB_PROMPT = """
As before, enrich the next batch of leads as a CSV file content and output ONLY the enriched CSV string enclosed in triple backticks (```csv

<DOCUMENT filename="leads.csv">
{leads_csv}												
</DOCUMENT>
"""


def setup_driver():
    """Initializes and returns a Selenium Chrome WebDriver instance."""
    print("Setting up Chrome WebDriver...")
    options = uc.ChromeOptions()
    # Disabling extensions to prevent them from interfering with the script.
    options.add_argument('--disable-extensions')

    # Use undetected_chromedriver which is better at avoiding bot detection.
    # We pass the user_data_dir directly and specify the browser version for stability.
    driver = uc.Chrome(
        options=options,
        user_data_dir=r"C:\Users\Robin Rajan\AppData\Local\Google\Chrome\User Data\Profile 1",
        browser_executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        use_subprocess=True
    )
    driver.maximize_window()
    return driver

def read_leads_in_batches(df, batch_size):
    """Yields batches of leads from a DataFrame."""
    for i in range(0, len(df), batch_size):
        yield df.iloc[i:i + batch_size]

def send_prompt(driver, prompt):
    """Finds the chat input box, sends the prompt, and presses Enter."""
    try:
        print("Sending prompt to the AI...")
        # This selector targets the specific content-editable div used by Grok's chat input.
        chat_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[contenteditable="true"]'))
        )
        # For contenteditable divs, we need to set innerText instead of value.
        driver.execute_script("arguments[0].innerText = arguments[1];", chat_input, prompt)
        chat_input.send_keys(Keys.ENTER)
        print("Prompt sent successfully.")
    except Exception as e:
        print(f"Error sending prompt: {e}")

def get_unprocessed_leads(max_leads=250):
    """Prepares a list of unprocessed leads based on LinkedIn URL, creates a temp CSV, and returns the DataFrame."""
    try:
        all_leads_df = pd.read_csv(CSV_INPUT_FILE)
        print(f"Loaded {len(all_leads_df)} total leads from {CSV_INPUT_FILE}.")
    except FileNotFoundError:
        print(f"Error: Input file '{CSV_INPUT_FILE}' not found. Please create it.")
        return pd.DataFrame(), None

    if 'Agency LinkedIn URL' not in all_leads_df.columns:
        print(f"Error: 'Agency LinkedIn URL' column not found in '{CSV_INPUT_FILE}'.")
        print(f"Available columns: {list(all_leads_df.columns)}")
        return pd.DataFrame(), None

    # Only check the all_enriched_leads.csv file to track processed leads
    try:
        all_enriched_df = pd.read_csv('all_enriched_leads.csv')
        print(f"Loaded {len(all_enriched_df)} enriched leads from all_enriched_leads.csv")
        processed_urls = set(all_enriched_df['Agency LinkedIn URL'].dropna().tolist())
        print(f"Found {len(processed_urls)} unique processed LinkedIn URLs")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        all_enriched_df = pd.DataFrame()
        processed_urls = set()
        print("No existing all_enriched_leads.csv found. All leads will be considered unprocessed.")

    # Find leads that haven't been processed yet
    unprocessed = []
    total_leads_checked = 0
    log_interval = 50

    print("Starting lead analysis...")
    for index, lead in all_leads_df.iterrows():
        total_leads_checked += 1
        if total_leads_checked % log_interval == 0:
            print(f"...checked {total_leads_checked} of {len(all_leads_df)} leads.")

        url = lead['Agency LinkedIn URL']
        if pd.isna(url) or url == '':
            continue

        # Include the lead if its URL is not in the processed URLs set
        if url not in processed_urls:
            unprocessed.append(lead)
            if len(unprocessed) >= max_leads:
                print(f"Reached the limit of {max_leads} unprocessed leads. Stopping search.")
                break
    
    print(f"Analysis complete. Found {len(unprocessed)} leads to process.")

    unprocessed_df = pd.DataFrame(unprocessed)
    unprocessed_df = unprocessed_df.head(max_leads)
    print(f"--> Selecting the top {len(unprocessed_df)} leads for the next batch.")

    if unprocessed_df.empty:
        print("No leads need processing.")
        return unprocessed_df, None

    temp_csv = 'temp_leads.csv'
    print(f"--> Clearing and writing {len(unprocessed_df)} leads to temporary file '{temp_csv}'...")
    unprocessed_df.to_csv(temp_csv, index=False)
    print(f"--> Successfully created temporary CSV '{temp_csv}'.")

    return unprocessed_df, temp_csv

def wait_for_response_stabilization(driver, previous_response_count):
    """Waits for a new AI response to appear and for its content to stabilize."""
    print("Waiting for AI response to generate and stabilize...")
    try:
        # 1. Wait for a new response container to appear
        WebDriverWait(driver, 60).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, "div.response-content-markdown")) > previous_response_count
        )
        print("New response detected. Monitoring for stabilization...")

        # 2. Monitor the last response for stabilization
        timeout_seconds = 120  # 2 minutes
        start_time = time.time()
        last_text = ""
        stable_count = 0

        while time.time() - start_time < timeout_seconds:
            try:
                response_containers = driver.find_elements(By.CSS_SELECTOR, "div.response-content-markdown")
                # Ensure we are looking at the new response
                if len(response_containers) <= previous_response_count:
                    time.sleep(0.5)
                    continue
                
                current_text = response_containers[-1].get_attribute('innerText') or ""
            except StaleElementReferenceException:
                print("Handled a stale element. Retrying...")
                time.sleep(0.5)
                continue

            # Check for stability
            if current_text == last_text and len(current_text) > 100: # Ensure it's not empty
                stable_count += 1
                if stable_count >= 3:  # Stable for 3 seconds
                    print(f"Response stabilized with {len(current_text)} characters. Proceeding.")
                    return
            else:
                stable_count = 0
                if len(current_text) > len(last_text):
                    print(f"Response updating... length: {len(current_text)} characters")
                last_text = current_text

            time.sleep(1)
        
        print("Warning: Timed out waiting for response to stabilize, but proceeding anyway.")

    except TimeoutException:
        print("Warning: Timed out waiting for a new response to appear. Proceeding might cause issues.")
    except Exception as e:
        print(f"An error occurred while waiting for response: {e}")

def main():
    """Main function to orchestrate the lead enrichment process."""
    driver = setup_driver()
    driver.get(GROK_URL)

    # Manual intervention step
    input("Please log in to Grok, select your desired workspace, and then press Enter here to continue...")

    # Get unprocessed leads and create a temporary CSV for this session
    print("\nChecking for unprocessed leads and creating temporary file...")
    unprocessed_leads_df, temp_csv = get_unprocessed_leads()

    if unprocessed_leads_df.empty:
        print("All leads are already fully enriched or no leads to process. Exiting.")
        driver.quit()
        return

    print(f"Found {len(unprocessed_leads_df)} leads to process.")

    # Get lead batches from the unprocessed DataFrame
    lead_batches = read_leads_in_batches(unprocessed_leads_df, BATCH_SIZE)

    is_first_batch = True
    batch_num = 1
    total_batches = -(-len(unprocessed_leads_df) // BATCH_SIZE)  # Ceiling division

    for batch_df in lead_batches:
        if not is_first_batch:
            # Use the sub-prompt for subsequent batches
            prompt_template = SUB_PROMPT
        else:
            # Use the main prompt for the very first batch
            prompt_template = MAIN_PROMPT_TEMPLATE
        
        # Format the chosen prompt with the current batch of leads
        leads_csv = batch_df.to_csv(index=False)
        prompt = prompt_template.format(leads_csv=leads_csv)
        
        # Wait for new response: Get current count before sending
        current_num_responses = len(driver.find_elements(By.CSS_SELECTOR, "div.response-content-markdown"))
        print(f"\n--- Sending Batch {batch_num}/{total_batches} ---")
        
        send_prompt(driver, prompt)

        # Wait for the response to be fully generated before sending the next prompt
        wait_for_response_stabilization(driver, current_num_responses)
        
        is_first_batch = False
        batch_num += 1

    print("\nAll leads have been processed.")
    driver.quit()

if __name__ == "__main__":
    main()