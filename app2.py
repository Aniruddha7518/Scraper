from flask import Flask, request, render_template, send_file
import json, requests, re, phonenumbers, logging, csv, os
from serpapi import GoogleSearch
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# Logging setup
logging.getLogger().handlers.clear()
logger = logging.getLogger()
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)
fh = logging.FileHandler('failures.log')
fh.setLevel(logging.WARNING)
fh.setFormatter(formatter)
logger.addHandler(fh)

headers = {"User-Agent": "Mozilla/5.0"}
session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

def fetch_contacts(link, email_patterns):
    logging.info(f"Fetching contacts from: {link}")
    try:
        response = session.get(link, headers=headers, timeout=10)
        content = response.text
    except Exception as e:
        logging.warning(f"Failed to fetch {link}: {e}")
        return None

    emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", content)
    valid_emails = [email for email in emails if any(pat in email for pat in email_patterns)]

    raw_phones = re.findall(r'(\+?\d{1,4}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5})', content)
    valid_phones = set()
    for phone in raw_phones:
        try:
            parsed_phone = phonenumbers.parse(phone, None)
            if phonenumbers.is_valid_number(parsed_phone):
                valid_phones.add(phonenumbers.format_number(parsed_phone, phonenumbers.PhoneNumberFormat.E164))
        except:
            continue

    if valid_emails or valid_phones:
        return {"url": link, "emails": list(set(valid_emails)), "phones": list(valid_phones)}
    return None

# info@, contact@, support@, sales@, admin@, help@, hello@, care@, service@, team@
# another sam - 88d3c42c0d49b61b6f5261b1ce136860e36794987ffcd4fa04b7d24c7ed29888


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        location = request.form["location"]
        industries = [i.strip() for i in request.form["industries"].split(",") if i.strip()]
        email_patterns = [e.strip() for e in request.form["email_patterns"].split(",") if e.strip()]
        site_domain = [d.strip() for d in request.form["site_domain"].split(",") if d.strip()]
        api_key = "961e34b70a4769746e93f82c92e80aa0d9a015d4628f118ac4f90d34435fc68d"

        country_map = {
            "IN": {"gl": "in", "google_domain": "google.co.in"},
            "US": {"gl": "us", "google_domain": "google.com"},
            "UK": {"gl": "uk", "google_domain": "google.co.uk"},
            "AE": {"gl": "ae", "google_domain": "google.ae"},
            "CA": {"gl": "ca", "google_domain": "google.ca"},
            "AU": {"gl": "au", "google_domain": "google.com.au"},
        }
        country_code = request.form.get("country", "IN")
        gl = country_map[country_code]["gl"]
        google_domain = country_map[country_code]["google_domain"]

        all_results = []
        visited_links = set()

        for keyword in industries:
            start = 0
            while start < 100:
                search = GoogleSearch({
                    "q": f"{keyword} in {location}",
                    "location": location,
                    "hl": "en",
                    "gl": gl,
                    "num": 100,
                    "start": start,
                    "google_domain": google_domain,
                    "safe": "active",
                    "engine": "google",
                    "api_key": api_key
                })

                result = search.get_dict()
                organic_results = result.get("organic_results", [])
                if not organic_results:
                    break

                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = []
                    for item in organic_results:
                        link = item.get("link", "")
                        snippet = item.get("snippet", "")
                        if (link and link not in visited_links and any(domain in link for domain in site_domain)
                            and (location.lower() in snippet.lower() or location.lower() in link.lower())):
                            visited_links.add(link)
                            futures.append(executor.submit(fetch_contacts, link, email_patterns))

                    for future in as_completed(futures):
                        contact = future.result()
                        if contact:
                            contact["industry"] = keyword
                            all_results.append(contact)
                start += 100

        logging.info(f"Total contacts found: {len(all_results)}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = f"results/results_{timestamp}.json"
        csv_file = f"results/results_{timestamp}.csv"
        os.makedirs("results", exist_ok=True)

        with open(json_file, "w", encoding="utf-8") as jf:
            json.dump(all_results, jf, indent=2, ensure_ascii=False)

        with open(csv_file, "w", newline="", encoding="utf-8") as cf:
            writer = csv.writer(cf)
            writer.writerow(["Industry", "Website URL", "Emails", "Phone Numbers"])
            for entry in all_results:
                writer.writerow([
                    entry["industry"],
                    entry["url"],
                    "; ".join(entry.get("emails", [])) or "Not Found",
                    "; ".join(entry.get("phones", [])) or "Not Found"
                ])

        return render_template("index.html", results=all_results, json_file=json_file, csv_file=csv_file)

    return render_template("index.html")

@app.route("/download/<filetype>")
def download(filetype):
    files = [f for f in os.listdir("results") if f.endswith(filetype)]
    if files:
        latest_file = sorted(files)[-1]
        return send_file(f"results/{latest_file}", as_attachment=True)
    return "No file available."

if __name__ == "__main__":
    app.run(debug=False)
