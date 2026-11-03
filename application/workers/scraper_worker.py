from __future__ import annotations

import re
import time
import urllib.parse
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

from application.browser import (
    extract_company_url,
    init_chrome_driver,
    inject_li_at_cookie,
    is_linkedin_logged_in,
)
from application.config import (
    GOOGLE_SEARCH,
    LI_FEED_URL,
    LI_HOME_URL,
    LI_LOGIN_URL,
    LI_SEARCH_URL,
    WAIT_BETWEEN,
    load_config,
    save_config,
)
from calcul.matching import (
    calculate_precision_resemblance,
    clean_company_name,
    clean_linkedin_title,
)



class ScraperWorker(QThread):
    """
    Pilote Chrome positionné à côté de l'application :
      - En mode 'web' (Google) : Recherche et extrait sans AUCUN compte LinkedIn requis !
      - En mode 'linkedin' : Recherche directement sur LinkedIn (si connecté)
      - Analyse de données stricte : rejette systématiquement les faux positifs
      - Émet les détails pour affichage dans le terminal blanc
    """
    company_started = pyqtSignal(int, int, dict)
    result          = pyqtSignal(str, str, object, list, str)
    log             = pyqtSignal(str)
    progress        = pyqtSignal(int, int)
    finished        = pyqtSignal()
    need_login      = pyqtSignal()

    def __init__(
        self,
        companies: list[dict],
        existing: dict,
        delay: float = WAIT_BETWEEN,
        li_at_cookie: str = "",
        search_mode: str = "web",
        window_pos: Optional[tuple[int, int]] = None,
        window_size: Optional[tuple[int, int]] = None,
        wait_for_start: bool = False,
    ):
        super().__init__()
        self.companies    = companies
        self.existing     = existing
        self.delay        = delay
        self.li_at_cookie = li_at_cookie
        self.search_mode  = search_mode
        self.window_pos   = window_pos
        self.window_size  = window_size
        self.wait_for_start = wait_for_start
        self._pause       = False
        self._stop        = False
        self._start_requested = False
        self.driver: Optional[webdriver.Chrome] = None

    def pause(self):  self._pause = True
    def resume(self): self._pause = False
    def stop(self):   self._stop  = True

    def begin_scraping(
        self,
        companies: list[dict],
        existing: dict,
        delay: float,
        li_at_cookie: str,
        search_mode: str,
    ) -> None:
        self.companies = companies
        self.existing = existing
        self.delay = delay
        self.li_at_cookie = li_at_cookie
        self.search_mode = search_mode
        self._start_requested = True

    def _ensure_login(self) -> bool:
        """Garantit la connexion en mode LinkedIn Direct."""
        if self.li_at_cookie:
            self.log.emit("🍪 Injection du cookie li_at de session…")
            if inject_li_at_cookie(self.driver, self.li_at_cookie):
                self.log.emit("✅ Connecté à LinkedIn via cookie li_at !")
                return True
            else:
                self.log.emit("⚠️ Cookie li_at expiré ou non valide.")

        self.driver.get(LI_FEED_URL)
        time.sleep(2)
        if is_linkedin_logged_in(self.driver):
            self.log.emit("✅ Session LinkedIn active (profil persistant) !")
            return True

        self.log.emit("🔑 Connexion requise — ouverture de LinkedIn dans Chrome…")
        self.driver.get(LI_LOGIN_URL)
        self.need_login.emit()

        deadline = time.time() + 300
        while time.time() < deadline:
            if self._stop:
                return False
            if is_linkedin_logged_in(self.driver):
                self.log.emit("✅ Connexion LinkedIn validée !")
                try:
                    cookies = {c["name"]: c["value"] for c in self.driver.get_cookies()}
                    if "li_at" in cookies:
                        cfg = load_config()
                        cfg["li_at"] = cookies["li_at"]
                        save_config(cfg)
                except Exception:
                    pass
                return True
            time.sleep(2)

        self.log.emit("❌ Délai d'attente de connexion dépassé.")
        return False

    def _search_via_web(self, company: dict) -> tuple[Optional[str], list[dict]]:
        """Recherche via Google SANS AUCUNE CONNEXION avec filtrage de haute précision."""
        name = company.get("companyName") or company.get("tradeName") or ""
        city = company.get("location") or ""
        cleaned_name = clean_company_name(name)

        queries = [
            f'"{cleaned_name}" site:linkedin.com/company',
        ]
        if city:
            queries.insert(0, f'"{cleaned_name}" {city} site:linkedin.com/company')

        all_candidates = []
        seen_urls = set()

        for q in queries:
            query_enc = urllib.parse.quote(q)
            self.driver.get(GOOGLE_SEARCH.format(query=query_enc))
            time.sleep(2.0)

            # Passer le consentement Google si présent
            try:
                for btn in self.driver.find_elements(By.TAG_NAME, "button"):
                    t = btn.text.lower()
                    if any(w in t for w in ["tout accepter", "accepter tout", "accept all", "i agree"]):
                        btn.click()
                        time.sleep(1.0)
                        break
            except Exception:
                pass

            elements = self.driver.find_elements(By.CSS_SELECTOR, "a")
            for el in elements:
                try:
                    href = el.get_attribute("href") or ""
                    clean_url = extract_company_url(href)
                    if not clean_url or clean_url in seen_urls:
                        continue

                    # Extraire le nom nettoyé depuis la balise h3
                    cand_name = ""
                    h3s = el.find_elements(By.TAG_NAME, "h3")
                    if h3s:
                        cand_name = clean_linkedin_title(h3s[0].text)
                    if not cand_name:
                        cand_name = clean_linkedin_title(el.text) or name

                    seen_urls.add(clean_url)
                    cand = {
                        "name": cand_name,
                        "link": clean_url,
                        "snippet": ""
                    }
                    score, details = calculate_precision_resemblance(cand, company)
                    cand["resemblance"] = score
                    cand["is_valid"] = details["is_valid"]
                    all_candidates.append(cand)
                except Exception:
                    continue

            if any(c["is_valid"] for c in all_candidates):
                break

        valid_candidates = [c for c in all_candidates if c["is_valid"]]
        if not valid_candidates:
            return None, all_candidates

        valid_candidates.sort(key=lambda x: x["resemblance"], reverse=True)
        return valid_candidates[0]["link"], valid_candidates

    def _search_via_linkedin(self, company: dict) -> tuple[Optional[str], list[dict]]:
        """Recherche directement sur LinkedIn avec filtrage de haute précision."""
        name = company.get("companyName") or company.get("tradeName") or ""
        cleaned_name = clean_company_name(name)
        queries = [cleaned_name]
        if cleaned_name.lower() != name.strip().lower() and name.strip():
            queries.append(name.strip())

        all_candidates = []
        seen_urls = set()

        for q_text in queries:
            query_encoded = urllib.parse.quote(q_text)
            search_url = LI_SEARCH_URL.format(query=query_encoded)
            self.driver.get(search_url)

            try:
                WebDriverWait(self.driver, 10).until(
                    lambda driver: driver.find_elements(
                        By.CSS_SELECTOR,
                        "li.reusable-search__result-container, div.entity-result__item, "
                        "div[data-chameleon-result-urn*='organization'], "
                        "main a[href*='/company/']"
                    )
                    or any(
                        marker in driver.current_url.lower()
                        for marker in ("authwall", "login", "checkpoint")
                    )
                )
            except TimeoutException:
                self.log.emit(f"  ⏱ Aucun résultat LinkedIn chargé à temps pour : {name}")

            current = self.driver.current_url.lower()
            if "authwall" in current or "login" in current or "checkpoint" in current:
                if not self._ensure_login():
                    return None, []
                self.driver.get(search_url)
                try:
                    WebDriverWait(self.driver, 10).until(
                        lambda driver: driver.find_elements(
                            By.CSS_SELECTOR,
                            "li.reusable-search__result-container, div.entity-result__item, "
                            "div[data-chameleon-result-urn*='organization'], "
                            "main a[href*='/company/']"
                        )
                    )
                except TimeoutException:
                    self.log.emit(f"  ⏱ Aucun résultat après connexion pour : {name}")

            try:
                containers = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "li.reusable-search__result-container, div.entity-result__item, div[data-chameleon-result-urn*='organization']"
                )
                for c in containers:
                    try:
                        link_el = c.find_element(By.CSS_SELECTOR, "a[href*='/company/']")
                        href = link_el.get_attribute("href") or ""
                        clean_url = extract_company_url(href)
                        if not clean_url or clean_url in seen_urls:
                            continue

                        title_text = ""
                        for title_sel in (
                            ".entity-result__title-text",
                            ".artdeco-entity-lockup__title",
                            "a[data-test-app-aware-link]",
                        ):
                            title_els = c.find_elements(By.CSS_SELECTOR, title_sel)
                            if title_els:
                                title_text = title_els[0].text.strip()
                                if title_text:
                                    break
                        if not title_text:
                            title_text = link_el.text.strip()
                        cand_name = next(
                            (
                                clean_linkedin_title(line.strip())
                                for line in title_text.splitlines()
                                if line.strip()
                                and line.strip().lower() not in {"follow", "suivre"}
                            ),
                            "",
                        )
                        if not cand_name:
                            slug = urllib.parse.unquote(
                                clean_url.rsplit("/company/", 1)[-1]
                            )
                            cand_name = re.sub(r"[-_]+", " ", slug).strip()

                        snippet_texts = []
                        for sub_sel in [".entity-result__primary-subtitle", ".entity-result__secondary-subtitle", ".entity-result__summary"]:
                            for sub_el in c.find_elements(By.CSS_SELECTOR, sub_sel):
                                t = sub_el.text.strip()
                                if t:
                                    snippet_texts.append(t)
                        full_snippet = " • ".join(snippet_texts)

                        seen_urls.add(clean_url)
                        cand = {
                            "name": cand_name,
                            "link": clean_url,
                            "snippet": full_snippet
                        }
                        score, details = calculate_precision_resemblance(cand, company)
                        cand["resemblance"] = score
                        cand["is_valid"] = details["is_valid"]
                        all_candidates.append(cand)
                    except Exception:
                        continue

                if not containers:
                    elements = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "main a[href*='/company/'], [role='main'] a[href*='/company/']"
                    )
                    for el in elements:
                        href = el.get_attribute("href") or ""
                        clean_url = extract_company_url(href)
                        if clean_url and clean_url not in seen_urls:
                            seen_urls.add(clean_url)
                            title_text = el.text.strip()
                            cand_name = next(
                                (
                                    clean_linkedin_title(line.strip())
                                    for line in title_text.splitlines()
                                    if line.strip()
                                    and line.strip().lower() not in {"follow", "suivre"}
                                ),
                                "",
                            )
                            if not cand_name:
                                slug = urllib.parse.unquote(
                                    clean_url.rsplit("/company/", 1)[-1]
                                )
                                cand_name = re.sub(r"[-_]+", " ", slug).strip()
                            cand = {
                                "name": cand_name,
                                "link": clean_url,
                                "snippet": ""
                            }
                            score, details = calculate_precision_resemblance(cand, company)
                            cand["resemblance"] = score
                            cand["is_valid"] = details["is_valid"]
                            all_candidates.append(cand)

                if any(c["is_valid"] for c in all_candidates):
                    break

            except TimeoutException:
                self.log.emit(f"  ⏱ Timeout pour : {name}")
            except Exception as exc:
                self.log.emit(f"  ⚠️ Erreur extraction pour {name} : {exc}")

        valid_candidates = [c for c in all_candidates if c["is_valid"]]
        if not valid_candidates:
            return None, all_candidates

        valid_candidates.sort(key=lambda x: x["resemblance"], reverse=True)
        return valid_candidates[0]["link"], valid_candidates

    def run(self):
        try:
            mode_desc = "Web Google (sans connexion requise)" if self.search_mode == "web" else "LinkedIn Direct"
            self.log.emit(f"🚀 Démarrage de Chrome à droite en mode : <b>{mode_desc}</b>…")
            self.driver = init_chrome_driver(
                headless=False,
                window_pos=self.window_pos,
                window_size=self.window_size,
            )
            self.driver.get(LI_HOME_URL)

            if self.wait_for_start:
                self.log.emit("🌐 LinkedIn est ouvert dans Chrome. Cliquez sur « Lancer » pour commencer le scraping.")
                while not self._start_requested and not self._stop:
                    time.sleep(0.2)
                if self._stop:
                    return
                self.wait_for_start = False

            if self.search_mode == "linkedin":
                if not self._ensure_login():
                    self.log.emit("❌ Impossible d'accéder à LinkedIn sans connexion. Basculez en mode 'Recherche Web' pour chercher sans compte.")
                    return

            to_process = [
                c for c in self.companies
                if c["_id"] not in self.existing
            ]
            total = len(to_process)
            self.log.emit(f"🎯 <b>{total}</b> entreprises à traiter dans ce lot")

            for idx, company in enumerate(to_process, 1):
                if self._stop:
                    break

                while self._pause and not self._stop:
                    time.sleep(0.5)
                if self._stop:
                    break

                name = company.get("companyName") or company.get("tradeName") or "?"
                self.company_started.emit(idx, total, company)
                self.progress.emit(idx, total)

                t_start = time.time()
                try:
                    if self.search_mode == "web":
                        best_url, candidates = self._search_via_web(company)
                    else:
                        best_url, candidates = self._search_via_linkedin(company)
                except WebDriverException as exc:
                    self.log.emit(f"  ⚠️ WebDriver error : {exc}")
                    best_url, candidates = None, []

                elapsed = round(time.time() - t_start, 1)

                if best_url:
                    self.result.emit(company["_id"], name, best_url, candidates, f"found_{elapsed}s")
                else:
                    self.result.emit(company["_id"], name, None, candidates, f"not_found_{elapsed}s")

                time.sleep(self.delay)

        except Exception as exc:
            self.log.emit(f"❌ Erreur inattendue : {exc}")
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
            self.log.emit("🏁 Traitement terminé.")
            self.finished.emit()
