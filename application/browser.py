import os
import re
import time
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from .config import (
    BLACKLIST_SLUGS,
    CHROME_PROFILE_DIR,
    LI_FEED_URL,
    LI_HOME_URL,
    PROJECT_DIR,
)


def extract_company_url(raw_url: str) -> Optional[str]:
    """Valide et normalise une URL d'entreprise LinkedIn."""
    if not raw_url:
        return None
    match = re.search(r"https?://(?:www\.)?linkedin\.com/company/([a-zA-Z0-9_\-%]+)", raw_url)
    if match:
        slug = match.group(1).lower()
        if slug not in BLACKLIST_SLUGS and len(slug) > 2:
            return f"https://www.linkedin.com/company/{match.group(1)}"
    return None


def get_chromedriver_service() -> Service:
    """Trouve ChromeDriver localement sans blocage réseau."""
    try:
        user_profile = os.environ.get("USERPROFILE", "")
        wdm_dir = Path(user_profile) / ".wdm" / "drivers"
        drivers = list(wdm_dir.glob("**/chromedriver.exe"))
        if drivers:
            latest = sorted(drivers, key=lambda path: path.stat().st_mtime, reverse=True)[0]
            return Service(str(latest))
    except Exception:
        pass

    local_driver = PROJECT_DIR / "chromedriver.exe"
    if local_driver.exists():
        return Service(str(local_driver.resolve()))

    return Service()


def init_chrome_driver(
    headless: bool = False,
    window_pos: Optional[tuple[int, int]] = None,
    window_size: Optional[tuple[int, int]] = None,
) -> webdriver.Chrome:
    """Initialise Chrome avec profil persistant et positionnement optionnel."""
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    elif window_pos and window_size:
        options.add_argument(f"--window-position={window_pos[0]},{window_pos[1]}")
        options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
    else:
        options.add_argument("--start-maximized")

    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=get_chromedriver_service(), options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )
    return driver


def is_linkedin_logged_in(driver: webdriver.Chrome) -> bool:
    """Vérifie si la session actuelle est connectée à LinkedIn."""
    try:
        cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
        if "li_at" in cookies and len(cookies["li_at"]) > 10:
            current_url = driver.current_url.lower()
            if not any(marker in current_url for marker in ("login", "authwall", "checkpoint")):
                return True

        if driver.find_elements(
            By.CSS_SELECTOR,
            ".global-nav__me, button.global-nav__primary-link-me-menu-trigger, "
            "a[href*='/mynetwork/'], a[href*='/messaging/']",
        ):
            return True
    except Exception:
        pass
    return False


def inject_li_at_cookie(driver: webdriver.Chrome, li_at_token: str) -> bool:
    """Injecte le cookie li_at pour réutiliser une session LinkedIn."""
    if not li_at_token or not li_at_token.strip():
        return False
    try:
        driver.get(LI_HOME_URL)
        time.sleep(1.5)
        driver.add_cookie(
            {
                "name": "li_at",
                "value": li_at_token.strip(),
                "domain": ".linkedin.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            }
        )
        driver.get(LI_FEED_URL)
        time.sleep(2.5)
        return is_linkedin_logged_in(driver)
    except Exception:
        return False