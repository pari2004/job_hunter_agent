"""
probe_companies.py — Test company names against Greenhouse and Lever APIs.
Outputs valid tokens/slugs to add to sources.json.
"""
import requests
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {"User-Agent": "JobHunterPersonal/2.0"}
TIMEOUT = 10

# ── Greenhouse token candidates ─────────────────────────────────────────────
# Format: actual board token to try (lowercase, as used in greenhouse URL)
GREENHOUSE_CANDIDATES = [
    # IT, AI & Technology
    "microsoft", "google", "amazon", "meta", "apple", "nvidia",
    "ibm", "oracle", "salesforce", "adobe", "servicenow",
    "palantir", "snowflake", "databricks", "cisco",
    # IT Services
    "accenture", "tcs", "infosys", "wipro", "hcltech", "cognizant",
    "capgemini", "techmahindra", "ltimindtree", "nttdata", "dxc",
    "atos", "genpact", "exlservice", "wns", "mphasis",
    "persistent", "coforge", "cyient", "zensar", "birlasoft",
    "sonata", "hexaware", "happiestminds", "kpit", "tataelxsi",
    "ust", "epam", "endava", "globant", "softserve",
    "thoughtworks", "virtusa", "publicissapient",
    # Banking / Fintech
    "jpmorgan", "jpmorganchase", "bankofamerica", "morganstanley",
    "goldmansachs", "citi", "citigroup", "wellsfargo", "hsbc",
    "barclays", "ubs", "bnpparibas", "deutschebank", "standardchartered",
    "americanexpress", "capitalone", "discover", "visa", "mastercard",
    "paypal", "stripe", "block", "fidelity", "blackrock",
    "vanguard", "statestreet", "charlesschwab", "bnymellon",
    "prudential", "metlife", "aig", "travelers", "allstate",
    "progressive", "chubb", "marshmclennan", "axa", "allianz",
    "hdfcbank", "icicibank", "axisbank", "sbi", "kotakbank",
    "bajajfinance", "paytm", "razorpay",
    # Healthcare
    "jnj", "pfizer", "roche", "novartis", "merck", "abbvie",
    "astrazeneca", "sanofi", "bms", "gsk", "lilly", "amgen",
    "gilead", "bayer", "novonordisk", "unitedhealth", "elevancehealth",
    "humana", "cvshealth", "cigna", "medtronic", "abbott",
    "thermofisher", "danaher", "siemenshealthineers", "gehealthcare",
    "philips", "stryker", "bostonscientific", "illumina",
    "iqvia", "labcorp", "questdiagnostics", "mckesson", "cencora",
    # Automotive
    "tesla", "toyota", "volkswagen", "mercedes", "bmw", "ford",
    "gm", "stellantis", "honda", "hyundai", "volvo", "rivian",
    "lucidmotors", "mahindra", "tatamotors", "bosch", "continental",
    "denso", "magna", "zf", "boeing", "airbus", "lockheedmartin",
    "northropgrumman", "rtx", "generaldynamics", "baesystems",
    "honeywell", "rollsroyce", "safran",
    # E-Commerce / Logistics
    "walmart", "target", "homedepot", "lowes", "costco", "bestbuy",
    "kroger", "alibaba", "jd", "rakuten", "ebay", "shopify",
    "wayfair", "zalando", "flipkart", "meesho", "myntra",
    "relianceretail", "swiggy", "zomato", "uber", "lyft",
    "grab", "doordash", "fedex", "ups", "dhl", "maersk",
    "schneiderelectric",
    # Telecom / Media / Gaming
    "att", "verizon", "tmobile", "vodafone", "telefonica", "orange",
    "airtel", "jio", "comcast", "charter", "disney", "netflix",
    "warnerbros", "paramount", "sony", "ea", "activision",
    "taketwo", "ubisoft", "epicgames", "unity", "spotify",
    "bytedance", "tencent", "netease",
    # Consulting
    "mckinsey", "bcg", "bain", "deloitte", "pwc", "ey", "kpmg",
    "oliverwyman", "boozallen", "gartner", "forrester",
    "alvarezandmarsal", "fticonsulting", "huron", "mercer",
    # Semiconductors / Cybersecurity
    "amd", "intel", "qualcomm", "broadcom", "ti", "micron",
    "appliedmaterials", "asml", "lamresearch", "kla",
    "synopsys", "cadence", "marvell", "arm", "tsmc",
    "paloaltonetworks", "fortinet", "crowdstrike", "cloudflare",
    "zscaler", "checkpoint", "trendmicro", "okta", "sentinelone",
    # Energy / Industrial
    "exxonmobil", "chevron", "shell", "totalenergies", "bp",
    "aramco", "ge", "siemens", "abb", "emerson",
    "rockwellautomation", "eaton", "caterpillar", "deere",
    "3m", "dow", "dupont", "basf", "riotinto", "bhp", "slb",
    "halliburton",
    # AI Companies
    "openai", "anthropic", "cohere", "mistral", "perplexity",
    "midjourney", "runway", "stabilityai", "scaleai", "huggingface",
    "langchain", "cognition", "poolside", "harvey", "glean",
    "writer", "jasper", "copyai", "c3ai", "ai21labs",
    "characterai", "synthesia", "elevenlabs", "soundhound",
    "datarobot", "h2oai", "dominodatalab", "pinecone", "weaviate",
    "neo4j", "assemblyai", "deepgram", "unstructured",
    "wandb", "arizeai",
    # Indian AI / High-growth
    "fractalanalytics", "tigeranalytics", "musigma", "tredence",
    "latentview", "leewayhertz", "krutrim", "sarvam",
    "yellowai", "gupshup", "uniphore", "haptik", "inmobi",
    "zoho", "freshworks", "browserstack", "postman", "druva",
    "icertis", "zenoti", "chargebee", "darwinbox", "mindtickle",
    "leadsquared", "amagi", "rategain",
    # Alternative token formats
    "palantirtechnologies", "snowflakecomputing", "databricksinc",
    "servicenowjobs", "nvidiacareers", "metaplatforms",
    "alphabetinc", "amazondotcom",
    "jpmc", "chase", "bofa",
    "lti", "ltimindtree",
    "hcl", "hcltech",
    "tata", "tataconsultancy",
    "infosystechnologies",
    "cognizanttechnology",
    "capgeminijobs",
    "publicis",
    "paloalto",
    "crowdstrikeinc",
    "cloudflareincjobs",
    "zscalerworks",
    "sentineloneinc",
    "okta",
    "fortinetsecurity",
    "checkpointsoftware",
    "amdcareers",
    "intelcareers",
    "qualcommcareers",
    "broadcominc",
    "texasinstruments",
    "microntechnology",
    "appliedmaterialsinc",
    "synopsysinc",
    "cadencedesign",
    "marvelltech",
    "armholdings",
    "openairesearch",
    "anthropicpbc",
    "cohereinc",
    "scaleintelligence",
    "huggingfaceinc",
    "pineconedb",
    "weaviatedb",
    "neo4jinc",
    "assemblyaiinc",
    "deepgramvoiceai",
    "weightsandbiases",
    "glassdoor",
    "workday",
    "rippling",
    "deel",
    "remote",
    "gusto",
    "zendesk",
    "atlassian",
    "elastic",
    "mongodb",
    "confluent",
    "hashicorp",
    "terraform",
    "datadog",
    "newrelic",
    "splunk",
    "dynatrace",
    "sumo",
    "grafana",
    "influxdata",
]

# ── Lever slug candidates ────────────────────────────────────────────────────
LEVER_CANDIDATES = [
    "microsoft", "google", "amazon", "meta", "apple", "nvidia",
    "ibm", "oracle", "salesforce", "adobe", "servicenow",
    "palantir", "snowflake", "databricks", "cisco",
    "accenture", "tcs", "infosys", "wipro", "hcltech", "cognizant",
    "capgemini", "techmahindra", "ltimindtree", "nttdata", "dxc",
    "genpact", "mphasis", "persistent", "coforge", "zensar",
    "ust", "epam", "endava", "globant", "softserve",
    "thoughtworks", "virtusa",
    "jpmorgan", "morganstanley", "goldmansachs", "citi",
    "capitalone", "discover", "paypal", "stripe", "block",
    "fidelity", "blackrock",
    "tesla", "rivian", "lucidmotors",
    "shopify", "wayfair", "flipkart", "swiggy", "zomato",
    "uber", "lyft", "grab", "doordash",
    "netflix", "spotify", "unity", "epicgames",
    "openai", "anthropic", "cohere", "scaleai", "huggingface",
    "glean", "writer", "harvey", "cognition", "poolside",
    "pinecone", "weaviate", "neo4j", "assemblyai", "deepgram",
    "wandb", "datarobot",
    "crowdstrike", "cloudflare", "zscaler", "sentinelone", "okta",
    "paloaltonetworks", "fortinet",
    "databricks", "confluent", "mongodb", "elastic", "hashicorp",
    "atlassian", "zendesk", "freshworks", "browserstack",
    "zoho", "postman", "chargebee", "darwinbox",
    "fractalanalytics", "latentview", "inmobi",
    "cred", "razorpay", "paytm",
    "thoughtworks",
    "globant",
    "endava",
    "softserve",
]


def check_greenhouse(token: str) -> tuple[str, str, int]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if r.status_code == 200:
            data = r.json()
            count = len(data.get("jobs", []))
            return ("greenhouse", token, count)
    except Exception:
        pass
    return None


def check_lever(slug: str) -> tuple[str, str, int]:
    url = f"https://api.lever.co/v0/postings/{slug}"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if r.status_code == 200:
            data = r.json()
            count = len(data) if isinstance(data, list) else 0
            return ("lever", slug, count)
    except Exception:
        pass
    return None


def main():
    print("[*] Probing Greenhouse tokens...")
    gh_results = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(check_greenhouse, t): t for t in GREENHOUSE_CANDIDATES}
        for f in as_completed(futures):
            res = f.result()
            if res:
                gh_results.append(res)
                print(f"  [OK] GH: {res[1]} ({res[2]} jobs)")

    print("\n[*] Probing Lever slugs...")
    lv_results = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(check_lever, s): s for s in LEVER_CANDIDATES}
        for f in as_completed(futures):
            res = f.result()
            if res:
                lv_results.append(res)
                print(f"  [OK] LV: {res[1]} ({res[2]} jobs)")

    # Load current sources
    with open("sources.json", "r") as f:
        sources = json.load(f)

    existing_gh = set(sources.get("greenhouse", []))
    existing_lv = set(sources.get("lever", []))

    new_gh = sorted({r[1] for r in gh_results} - existing_gh)
    new_lv = sorted({r[1] for r in lv_results} - existing_lv)

    print(f"\n[SUMMARY]")
    print(f"  Greenhouse: {len(gh_results)} valid tokens ({len(new_gh)} new)")
    print(f"  Lever: {len(lv_results)} valid slugs ({len(new_lv)} new)")
    print(f"\n[NEW] Greenhouse tokens:\n  {new_gh}")
    print(f"\n[NEW] Lever slugs:\n  {new_lv}")

    # Save results
    all_gh = sorted(existing_gh | {r[1] for r in gh_results})
    all_lv = sorted(existing_lv | {r[1] for r in lv_results})

    sources["greenhouse"] = all_gh
    sources["lever"] = all_lv

    with open("sources_updated.json", "w") as f:
        json.dump(sources, f, indent=2)

    print(f"\n[SAVED] sources_updated.json")
    print(f"  Total Greenhouse: {len(all_gh)}, Total Lever: {len(all_lv)}")


if __name__ == "__main__":
    main()
