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
As before, enrich the next batch of leads as a CSV file content and output ONLY the enriched CSV string enclosed in triple backticks (```csv ... ```).

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

def get_latest_response(driver):
    """Waits for and extracts the latest response from the AI."""
    try:
        # Wait for a response container to be present
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.response-content-markdown"))
        )
        print("AI response detected. Waiting for it to stabilize...")

        timeout_seconds = 120  # 2 minutes
        start_time = time.time()
        last_text = ""  # Initialize BEFORE the loop
        stable_count = 0

        while time.time() - start_time < timeout_seconds:
            try:
                # Find the last response container
                response_containers = driver.find_elements(By.CSS_SELECTOR, "div.response-content-markdown")
                if not response_containers:
                    time.sleep(1)
                    continue

                # Use innerText for a more reliable text capture
                current_text = response_containers[-1].get_attribute('innerText') or ""
            except StaleElementReferenceException:
                # The element was updated in the DOM, just continue and re-find it
                print("Handled a stale element. Retrying...")
                time.sleep(0.5)
                continue

            if current_text == last_text and current_text != "":
                stable_count += 1
                if stable_count >= 3:  # Stable for 3 seconds
                    print("Message stabilized. Processing...")
                    break
            else:
                stable_count = 0
                if len(current_text) > len(last_text):
                    print(f"Response updating... new length: {len(current_text)} characters")
                last_text = current_text

            time.sleep(1)
        else:
            print("Warning: Timed out waiting for response to stabilize.")

        # --- Final Extraction --- 
        # After stabilization or timeout, get the definitive final content.
        final_response_elements = driver.find_elements(By.CSS_SELECTOR, 'div.response-content-markdown code')
        if not final_response_elements:
            print("Primary selector '... code' failed. Trying fallback 'div.response-content-markdown'.")
            final_response_elements = driver.find_elements(By.CSS_SELECTOR, 'div.response-content-markdown')

        if not final_response_elements:
            print("Error: Could not find any response element after waiting.")
            return None

        final_text = final_response_elements[-1].get_attribute('innerText')
        if not final_text or not final_text.strip():
            print("Warning: Captured final message is empty.")
            return None

        final_text = final_text.strip()
        print(f"Final message length: {len(final_text)} characters")
        print("--- Captured AI Response ---")
        print(final_text[:800] + ('...' if len(final_text) > 800 else ''))
        print("----------------------------")
        return final_text

    except Exception as e:
        print(f"Fatal error in get_latest_response: {e}")
        return None

def save_enriched_data(data, filename):
    """Appends a list of enriched data to the output CSV file."""
    # Helper to extract and normalize different response formats to a DataFrame
    def _extract_code_block(text: str) -> str | None:
        import re
        match = re.search(r"```(?:\w+)?\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
        return None

    def _parse_markdown_table(text: str) -> pd.DataFrame | None:
        # Keep only lines with '|' to approximate markdown table
        lines = [ln.strip() for ln in text.splitlines() if '|' in ln]
        if len(lines) < 2:
            return None
        # Remove alignment row like: | --- | :---: | ---: |
        cleaned = []
        for ln in lines:
            parts = [p.strip() for p in ln.strip('|').split('|')]
            if all(set(p) <= set('-: ') and p for p in parts):
                # alignment row, skip
                continue
            cleaned.append(ln)
        if len(cleaned) < 2:
            return None
        try:
            # Convert to CSV-like string
            header = [h.strip() for h in cleaned[0].strip('|').split('|')]
            rows = []
            for ln in cleaned[1:]:
                cols = [c.strip() for c in ln.strip('|').split('|')]
                # Pad/truncate to header length
                if len(cols) < len(header):
                    cols += [''] * (len(header) - len(cols))
                elif len(cols) > len(header):
                    cols = cols[:len(header)]
                rows.append(cols)
            df = pd.DataFrame(rows, columns=header)
            # Drop completely empty rows
            df = df.dropna(how='all')
            return df
        except Exception:
            return None

    def _normalize_to_dataframe(d) -> pd.DataFrame | None:
        # Already a DataFrame
        if isinstance(d, pd.DataFrame):
            return d
        # List of dicts or list-like
        if isinstance(d, list):
            try:
                return pd.DataFrame(d)
            except Exception:
                return None
        # Single dict
        if isinstance(d, dict):
            try:
                return pd.DataFrame([d])
            except Exception:
                return None
        # String: could be JSON, CSV, or Markdown table
        if isinstance(d, str):
            text = d.strip()
            # If the entire string is huge raw message, try to extract fenced block first
            block = _extract_code_block(text)
            candidate = block if block else text
            # Try JSON
            try:
                obj = json.loads(candidate)
                return _normalize_to_dataframe(obj)
            except Exception:
                pass
            # Try CSV by locating the header
            try:
                lines = candidate.splitlines()
                # Find the header row - it should contain expected column names
                header_idx = -1
                for i, line in enumerate(lines):
                    # A good heuristic for the header is the presence of several commas
                    if 'Agency Name' in line and 'ICP Score' in line and line.count(',') > 5:
                        header_idx = i
                        break
                
                if header_idx != -1:
                    # Reconstruct the CSV from the header onwards
                    csv_data = "\n".join(lines[header_idx:])
                    return pd.read_csv(io.StringIO(csv_data))
            except Exception:
                pass
            # Try Markdown table
            md_df = _parse_markdown_table(candidate)
            if md_df is not None:
                return md_df
            return None
        return None

    if data is None:
        print("No data passed to save_enriched_data; skipping.")
        return

    df = _normalize_to_dataframe(data)
    if df is None or df.empty:
        # Provide a short preview for debugging
        preview = (data[:200] + '...') if isinstance(data, str) and len(data) > 200 else data
        print(f"Could not parse AI response into a table. Nothing saved. Preview: {preview}")
        return

    print(f"Saving {len(df)} enriched leads to {filename}...")
    try:
        # Append to the file, creating it if it doesn't exist.
        header_needed = not os.path.isfile(filename)
        df.to_csv(filename, mode='a', header=header_needed, index=False)
        print("Data saved successfully.")
    except Exception as e:
        print(f"Error saving data to CSV: {e}")

def main():
    """Main function to orchestrate the lead enrichment process."""
    driver = setup_driver()
    driver.get(GROK_URL)

    # Manual intervention step
    input("Please log in to Grok, select your desired workspace, and then press Enter here to continue...")

    # --- Resume Logic: Read inputs and skip already enriched leads ---
    try:
        all_leads_df = pd.read_csv(CSV_INPUT_FILE)
        print(f"Loaded {len(all_leads_df)} total leads from {CSV_INPUT_FILE}.")
    except FileNotFoundError:
        print(f"Error: Input file '{CSV_INPUT_FILE}' not found. Please create it.")
        return

    # Validate that the input CSV has an identifier column and choose the best one
    preferred_cols = ["Agency Name", "Name"]
    available_id_cols = [c for c in preferred_cols if c in all_leads_df.columns]
    if not available_id_cols:
        print(f"Error: None of the identifier columns {preferred_cols} found in '{CSV_INPUT_FILE}'.")
        print(f"Available columns in '{CSV_INPUT_FILE}': {list(all_leads_df.columns)}")
        return
    required_column = available_id_cols[0]
    print(f"Using '{required_column}' as the lead identifier from '{CSV_INPUT_FILE}'.")

    if os.path.exists(CSV_OUTPUT_FILE):
        try:
            enriched_df = pd.read_csv(CSV_OUTPUT_FILE)
            print(f"Found existing '{CSV_OUTPUT_FILE}'.")
            # Validate that the enriched CSV also has an identifier column
            if required_column in enriched_df.columns:
                id_col_used = required_column
            else:
                # Try the alternative identifier in enriched CSV
                alternatives = [c for c in preferred_cols if c != required_column and c in enriched_df.columns]
                if alternatives:
                    id_col_used = alternatives[0]
                    print(f"Note: Using '{id_col_used}' from '{CSV_OUTPUT_FILE}' to determine processed leads (different from input's '{required_column}').")
                else:
                    id_col_used = None

            if id_col_used:
                processed_leads = set(enriched_df[id_col_used].dropna().unique())
                print(f"Found {len(processed_leads)} already enriched leads in {CSV_OUTPUT_FILE} using '{id_col_used}'.")
            else:
                processed_leads = set()
                print(f"Warning: None of the identifier columns {preferred_cols} found in {CSV_OUTPUT_FILE}. Starting from scratch.")
                print(f"Available columns in '{CSV_OUTPUT_FILE}': {list(enriched_df.columns) if not enriched_df.empty else '(None)'}")
        except pd.errors.EmptyDataError:
            processed_leads = set()
            print(f"Warning: {CSV_OUTPUT_FILE} is empty. Starting from scratch.")
    else:
        processed_leads = set()
        print(f"No existing {CSV_OUTPUT_FILE} found. Starting fresh.")

    # Filter out processed leads
    unprocessed_leads_df = all_leads_df[~all_leads_df[required_column].isin(processed_leads)]
    
    if unprocessed_leads_df.empty:
        print("All leads from the input file have already been enriched. Exiting.")
        return

    print(f"Found {len(unprocessed_leads_df)} new leads to process.")

    # Get lead batches from the unprocessed DataFrame
    lead_batches = read_leads_in_batches(unprocessed_leads_df, BATCH_SIZE)

    is_first_batch = True

    for batch_df in lead_batches:
        if not is_first_batch:
            # The wait for the AI response to generate serves as a natural rate limit.
            # The hardcoded sleep is removed to accelerate processing.
            pass
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
        
        send_prompt(driver, prompt)
        
        # Wait for a new response to appear
        WebDriverWait(driver, 60).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, "div.response-content-markdown")) > current_num_responses
        )
        
        enriched_data = get_latest_response(driver)
        
        if enriched_data:
            save_enriched_data(enriched_data, CSV_OUTPUT_FILE)
        else:
            print("Skipping save due to an error in the previous step.")

        is_first_batch = False

    print("\nAll leads have been processed.")
    driver.quit()

if __name__ == "__main__":
    main()