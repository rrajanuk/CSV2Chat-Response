# AI-Powered Lead Enrichment Tool

This Python script uses Selenium to automate the process of enriching lead data by interacting with a web-based AI chat interface (like Grok).

## Features

- Reads lead data from a CSV file (`leads.csv`).
- Processes leads in configurable batches.
- Automates sending prompts to an AI web interface.
- Extracts and parses JSON data from the AI's response.
- Saves the enriched data to a new CSV file (`enriched_leads.csv`).
- Includes a rate-limiting delay to avoid being blocked.
- Requires manual login to handle authentication and workspace selection securely.

## Prerequisites

- Python 3.8+
- Google Chrome browser

## How to Use

1.  **Clone the repository or download the files.**

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Prepare your data:**
    -   Open `leads.csv`.
    -   Add your lead data with the required columns: `company_name`, `domain`, `person_name`.

4.  **Customize the script (Optional):**
    -   Open `lead_enricher.py`.
    -   Modify the `MAIN_PROMPT_TEMPLATE` or `SUB_PROMPT` to fit your specific needs.
    -   Adjust `RATE_LIMIT_SECONDS` or `BATCH_SIZE` if necessary.

5.  **Run the script:**
    ```bash
    python lead_enricher.py
    ```

6.  **Manual Login:**
    -   The script will open Chrome and navigate to the AI's website.
    -   The script will pause. You must **manually log in** and navigate to the correct workspace you want to use for the enrichment task.
    -   Once you are ready, **press Enter** in the terminal window where the script is running.

7.  **Monitor the process:**
    -   The script will now take over, processing each batch of leads.
    -   The enriched data will be saved progressively to `enriched_leads.csv`.

## Important Notes

-   **Web Scraper Stability:** The script relies on CSS selectors to find elements on the webpage (e.g., the chat input box). If the website's design changes, these selectors (`By.CSS_SELECTOR, ...`) in `lead_enricher.py` may need to be updated.
-   **Error Handling:** If the script encounters an error (e.g., it cannot parse the AI's response), it will print a message and continue to the next batch.
