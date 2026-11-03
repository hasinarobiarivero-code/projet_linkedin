from __future__ import annotations

import difflib
import re
import time
import urllib.parse
from datetime import datetime, timezone
from html import escape as escape_html
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPalette, QTextCursor, QFont
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
    QLineEdit, QCheckBox, QDialog, QTabWidget, QDialogButtonBox,
    QComboBox, QStatusBar,
)

from bson import ObjectId
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)

from application.browser import (
    extract_company_url,
    get_chromedriver_service,
    init_chrome_driver,
    inject_li_at_cookie,
    is_linkedin_logged_in,
)
from application.config import (
    CHECKPOINT_COLLECTION,
    CHECKPOINT_ID,
    COLLECTION,
    DB_NAME,
    GOOGLE_SEARCH,
    LI_FEED_URL,
    LI_HOME_URL,
    LI_LOGIN_URL,
    LI_SEARCH_URL,
    MONGO_BATCH_SIZE,
    MONGO_URI,
    WAIT_BETWEEN,
    WAIT_PAGE,
    load_config,
    load_results,
    save_config,
    save_results,
)
from calcul.matching import (
    calculate_precision_resemblance,
    clean_company_name,
    clean_linkedin_title,
)

from application.ui.login_dialog import LinkedInLoginDialog
from application.workers.mongo_loader import MongoLoader
from application.workers.scraper_worker import ScraperWorker



class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("🔗 LinkedIn Auto-Enricher (Haute Précision)")

        self.companies: list[dict] = []
        self.total_count: int      = 0
        self.results: dict         = load_results()
        self.config: dict          = load_config()

        self.mongo_worker:   Optional[MongoLoader]    = None
        self.scraper_worker: Optional[ScraperWorker] = None
        self.autoscroll: bool = True
        self.mongo_ready: bool = False
        self.scraping_active: bool = False
        self.auto_process_missing: bool = False
        self.direct_mongo_search: bool = False
        self.mongo_write_failed: bool = False
        self.search_total: int = 0
        self.search_processed: int = 0
        self.last_batch_progress: int = 0

        self._calculate_side_by_side_layout()
        self._build_ui()
        self._start_browser_preview()
        self._load_from_mongo()

    def _calculate_side_by_side_layout(self):
        """Calcule le découpage d'écran : Interface à gauche (42%), Chrome à droite (58%)."""
        screen = QApplication.primaryScreen().availableGeometry()
        sw = screen.width()
        sh = screen.height()

        self.app_w = int(sw * 0.42)
        self.app_h = sh
        self.chrome_pos  = (screen.x() + self.app_w, screen.y())
        self.chrome_size = (sw - self.app_w, sh)

        self.setGeometry(screen.x(), screen.y(), self.app_w, self.app_h)

    # ── Construction UI Thème BLANC ───────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet("background:#F8FAFC;")
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setSpacing(0)
        root_lay.setContentsMargins(0, 0, 0, 0)

        # ── Header Blanc ──
        header = QWidget()
        header.setStyleSheet("background:#FFFFFF;border-bottom:1px solid #E2E8F0;")
        header.setFixedHeight(54)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 0, 14, 0)

        title = QLabel("🔗 LinkedIn Auto-Enricher <span style='font-size:11px;color:#16A34A;font-weight:normal;'>[Filtre Anti-Faux Positifs Actif]</span>")
        title.setStyleSheet("color:#0A66C2;font-size:15px;font-weight:bold;")
        h_lay.addWidget(title)

        h_lay.addStretch()

        self.btn_auth = QPushButton("🔑 Session LinkedIn")
        self._update_auth_button_style()
        self.btn_auth.clicked.connect(self._open_auth_dialog)
        h_lay.addWidget(self.btn_auth)

        root_lay.addWidget(header)

        # ── Barre de Contrôle Blanche ──
        ctrl_bar = QWidget()
        ctrl_bar.setStyleSheet("background:#FFFFFF;border-bottom:1px solid #E2E8F0;")
        c_lay = QVBoxLayout(ctrl_bar)
        c_lay.setContentsMargins(12, 10, 12, 10)
        c_lay.setSpacing(8)

        # Ligne 1 : Boutons d'action principaux
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.btn_start = QPushButton("⏳ Chargement MongoDB…")
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet(self._btn_style("#CBD5E1", "#94A3B8", text_color="#64748B"))
        self.btn_start.clicked.connect(self._on_start_clicked)
        row1.addWidget(self.btn_start, stretch=2)

        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(self._btn_style("#D97706", "#B45309"))
        self.btn_pause.clicked.connect(self._toggle_pause)
        row1.addWidget(self.btn_pause, stretch=1)

        self.btn_stop = QPushButton("⏹ Arrêter")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(self._btn_style("#DC2626", "#B91C1C"))
        self.btn_stop.clicked.connect(self._stop_scraping)
        row1.addWidget(self.btn_stop, stretch=1)

        c_lay.addLayout(row1)

        # Ligne 2 : Options & Mode de recherche
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        row2.addWidget(self._label_dark("Mode :"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("🌐 Recherche Web Google (Sans compte LinkedIn)", "web")
        self.combo_mode.addItem("🔒 LinkedIn Direct (Compte requis)", "linkedin")
        saved_search_mode = self.config.get("search_mode", "linkedin")
        saved_mode_index = self.combo_mode.findData(saved_search_mode)
        if saved_mode_index >= 0:
            self.combo_mode.setCurrentIndex(saved_mode_index)
        self.combo_mode.setStyleSheet(self._combo_style())
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        row2.addWidget(self.combo_mode)

        row2.addWidget(self._label_dark("Délai :"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(1, 30)
        self.delay_spin.setValue(self.config.get("delay", 3))
        self.delay_spin.setSuffix("s")
        self.delay_spin.setStyleSheet(self._spin_style())
        row2.addWidget(self.delay_spin)

        self.check_sync_mongo = QCheckBox("Sync MongoDB")
        self.check_sync_mongo.setToolTip(
            "Si activé, écrit dans MongoDB le lien LinkedIn validé après chaque recherche."
        )
        self.check_sync_mongo.setChecked(self.config.get("sync_mongo", True))
        self.check_sync_mongo.setStyleSheet("color:#1E293B;font-size:11px;font-weight:500;")
        self.check_sync_mongo.toggled.connect(self._on_sync_toggled)
        row2.addWidget(self.check_sync_mongo)

        row2.addStretch()
        c_lay.addLayout(row2)

        root_lay.addWidget(ctrl_bar)

        # ── Barre de progression & Métriques ──
        prog_bar_widget = QWidget()
        prog_bar_widget.setStyleSheet("background:#F1F5F9;border-bottom:1px solid #E2E8F0;")
        pb_lay = QVBoxLayout(prog_bar_widget)
        pb_lay.setContentsMargins(12, 6, 12, 6)
        pb_lay.setSpacing(4)

        metrics_row = QHBoxLayout()
        self.current_label = QLabel("Prêt")
        self.current_label.setStyleSheet("color:#475569;font-size:11px;")
        metrics_row.addWidget(self.current_label)

        metrics_row.addStretch()

        self.stats_label = QLabel("Trouvés : 0  |  Non trouvés : 0")
        self.stats_label.setStyleSheet("color:#0F172A;font-size:11px;font-weight:bold;")
        metrics_row.addWidget(self.stats_label)

        pb_lay.addLayout(metrics_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("%v / %m (%p%)")
        self.progress_bar.setStyleSheet(
            "QProgressBar{border:1px solid #CBD5E1;border-radius:4px;height:14px;text-align:center;font-size:10px;color:#0F172A;background:#FFFFFF;font-weight:bold;}"
            "QProgressBar::chunk{background:#0A66C2;border-radius:3px;}"
        )
        pb_lay.addWidget(self.progress_bar)

        root_lay.addWidget(prog_bar_widget)

        # ── Terminal Blanc Épuré (Corps Principal) ──
        term_wrap = QWidget()
        term_wrap.setStyleSheet("background:#F8FAFC;")
        t_lay = QVBoxLayout(term_wrap)
        t_lay.setContentsMargins(10, 8, 10, 6)
        t_lay.setSpacing(6)

        term_top = QHBoxLayout()
        term_title = QLabel("🖥 Terminal d'enrichissement (Thème Blanc • Analyse Précise)")
        term_title.setStyleSheet("color:#475569;font-size:12px;font-weight:bold;font-family:Consolas,monospace;")
        term_top.addWidget(term_title)
        term_top.addStretch()

        self.check_autoscroll = QCheckBox("Auto-scroll")
        self.check_autoscroll.setChecked(True)
        self.check_autoscroll.setStyleSheet("color:#64748B;font-size:11px;")
        self.check_autoscroll.toggled.connect(lambda v: setattr(self, "autoscroll", v))
        term_top.addWidget(self.check_autoscroll)

        btn_copy = QPushButton("📋 Copier")
        btn_copy.setStyleSheet(self._btn_terminal())
        btn_copy.clicked.connect(self._copy_terminal_text)
        term_top.addWidget(btn_copy)

        btn_clear = QPushButton("🗑 Effacer")
        btn_clear.setStyleSheet(self._btn_terminal())
        btn_clear.clicked.connect(self._clear_terminal)
        term_top.addWidget(btn_clear)

        t_lay.addLayout(term_top)

        self.term_text = QTextEdit()
        self.term_text.setReadOnly(True)
        self.term_text.setStyleSheet(
            "QTextEdit{background:#FFFFFF;color:#0F172A;font-family:Consolas,'Segoe UI',monospace;"
            "font-size:11px;border:1px solid #CBD5E1;border-radius:6px;padding:10px;line-height:1.5;}"
        )
        t_lay.addWidget(self.term_text, stretch=1)

        root_lay.addWidget(term_wrap, stretch=1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("background:#FFFFFF;color:#64748B;font-size:11px;border-top:1px solid #E2E8F0;")
        self.status_bar.showMessage("Chargement des entreprises depuis MongoDB…")

    # ── Styles Blancs Helpers ─────────────────────────────────────────────────

    def _btn_style(self, bg: str, hover: str, text_color: str = "white") -> str:
        return (
            f"QPushButton{{background:{bg};color:{text_color};border-radius:5px;"
            f"padding:7px 14px;font-size:11px;font-weight:bold;border:none;}}"
            f"QPushButton:hover{{background:{hover};}}"
            f"QPushButton:disabled{{background:#E2E8F0;color:#94A3B8;}}"
        )

    def _btn_terminal(self) -> str:
        return (
            "QPushButton{background:#FFFFFF;color:#334155;border:1px solid #CBD5E1;"
            "border-radius:4px;padding:3px 10px;font-size:11px;font-family:Consolas,monospace;}"
            "QPushButton:hover{background:#F1F5F9;color:#0F172A;}"
        )

    def _label_dark(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#1E293B;font-size:11px;font-weight:600;")
        return lbl

    def _spin_style(self) -> str:
        return (
            "QSpinBox{background:#FFFFFF;color:#0F172A;border:1px solid #CBD5E1;"
            "border-radius:4px;padding:3px 6px;font-size:11px;width:60px;font-weight:500;}"
        )

    def _combo_style(self) -> str:
        return (
            "QComboBox{background:#FFFFFF;color:#0F172A;border:1px solid #CBD5E1;"
            "border-radius:4px;padding:3px 8px;font-size:11px;font-weight:500;}"
            "QComboBox::drop-down{border:none;}"
        )

    def _update_auth_button_style(self):
        cfg = load_config()
        if cfg.get("li_at"):
            self.btn_auth.setText("🔑 LinkedIn (🟢 Connecté)")
            self.btn_auth.setStyleSheet(
                "QPushButton{background:#DCFCE7;color:#166534;border:1px solid #86EFAC;"
                "border-radius:4px;padding:5px 12px;font-size:11px;font-weight:bold;}"
                "QPushButton:hover{background:#BBF7D0;}"
            )
        else:
            self.btn_auth.setText("🔑 LinkedIn (Configurer)")
            self.btn_auth.setStyleSheet(
                "QPushButton{background:#F1F5F9;color:#334155;border:1px solid #CBD5E1;"
                "border-radius:4px;padding:5px 12px;font-size:11px;font-weight:500;}"
                "QPushButton:hover{background:#E2E8F0;}"
            )

    def _open_auth_dialog(self):
        dialog = LinkedInLoginDialog(self)
        dialog.exec()
        self.config = load_config()
        self._update_auth_button_style()

    def _on_mode_changed(self):
        self.config["search_mode"] = self.combo_mode.currentData()
        save_config(self.config)

    def _on_sync_toggled(self, checked: bool):
        self.config["sync_mongo"] = checked
        save_config(self.config)

    def _clear_terminal(self):
        self.term_text.clear()

    def _copy_terminal_text(self):
        self.term_text.selectAll()
        self.term_text.copy()
        cursor = self.term_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.term_text.setTextCursor(cursor)
        self.status_bar.showMessage("📋 Logs copiés dans le presse-papier.", 3000)

    # ── MongoDB Loading ───────────────────────────────────────────────────────

    def _load_from_mongo(self):
        self.mongo_ready = False
        self.btn_start.setEnabled(False)
        self.btn_start.setText("⏳ Chargement MongoDB…")
        self.btn_start.setStyleSheet(self._btn_style("#CBD5E1", "#94A3B8", text_color="#64748B"))

        self.mongo_worker = MongoLoader(
            batch=MONGO_BATCH_SIZE,
        )
        self.mongo_worker.done.connect(self._on_mongo_done)
        self.mongo_worker.error.connect(self._on_mongo_error)
        self.mongo_worker.log.connect(self._log_info)
        self.mongo_worker.start()

    def _connect_scraper_worker(self, worker: ScraperWorker):
        worker.company_started.connect(self._on_company_started)
        worker.result.connect(self._on_result)
        worker.log.connect(self._log_info)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_scraper_finished)
        worker.need_login.connect(self._on_need_login)

    def _start_browser_preview(self):
        self.scraper_worker = ScraperWorker(
            companies=[],
            existing={},
            delay=self.delay_spin.value(),
            li_at_cookie=self.config.get("li_at", ""),
            search_mode=self.combo_mode.currentData(),
            window_pos=self.chrome_pos,
            window_size=self.chrome_size,
            wait_for_start=True,
        )
        self._connect_scraper_worker(self.scraper_worker)
        self.scraper_worker.start()

    def _load_next_batch(self):
        self._load_from_mongo()

    def _on_mongo_done(self, companies: list, total: int):
        self.companies   = companies
        self.total_count = total
        self.mongo_ready = True

        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ Lancer / reprendre")
        self.btn_start.setStyleSheet(self._btn_style("#16A34A", "#15803D"))

        self._update_stats()
        self.status_bar.showMessage(
            f"✅ Analyse prête | {total:,} entreprise(s) à traiter après le point de reprise"
        )
        if self.auto_process_missing and self.search_total == 0:
            self.search_total = total
        self.last_batch_progress = 0
        self.progress_bar.setMaximum(
            self.search_total if self.auto_process_missing else len(self.companies)
        )
        self.progress_bar.setValue(0)
        self._log_info("✨ Entreprises prêtes. Analyse de haute précision active !")
        if self.auto_process_missing:
            if self.companies:
                self._start_scraping()
            else:
                self._finish_missing_search()

    def _on_mongo_error(self, msg: str):
        self.auto_process_missing = False
        self.scraping_active = False
        self.mongo_ready = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("🔄 Réessayer MongoDB")
        self.btn_start.setStyleSheet(self._btn_style("#DC2626", "#B91C1C"))
        self._log_error(f"MongoDB Erreur de connexion : {msg}")
        self.status_bar.showMessage("❌ Erreur de connexion MongoDB")

    def _update_stats(self):
        found   = sum(1 for r in self.results.values() if r.get("linkedin_url"))
        skipped = sum(1 for r in self.results.values() if r.get("status") == "not_found")
        self.stats_label.setText(
            f"Trouvés : <span style='color:#16A34A;'>{found}</span>  |  "
            f"Non trouvés : <span style='color:#DC2626;'>{skipped}</span>"
        )

    # ── Gestion du Clic Lancer & Résolution ────────────────────────────────────

    def _on_start_clicked(self):
        self.auto_process_missing = True
        self.direct_mongo_search = True
        self.mongo_write_failed = False
        self.search_processed = 0
        self.last_batch_progress = 0
        self.search_total = self.total_count if self.mongo_ready else 0
        if not self.mongo_ready:
            self._log_info("⏳ Chargement de la suite depuis le dernier point enregistré dans MongoDB…")
            self._load_from_mongo()
            return

        if not self.companies:
            self._log_info("⏳ Recherche des prochaines entreprises sans lien LinkedIn…")
            self._load_from_mongo()
            return

        if not self.check_sync_mongo.isChecked():
            self.check_sync_mongo.setChecked(True)
        self._log_info("🗄️ Analyse automatique démarrée ; la progression est sauvegardée dans MongoDB.")
        self._start_scraping()

    def _start_scraping(self):
        self.scraping_active = True
        self.btn_start.setEnabled(False)
        self.btn_start.setText("🔄 Traitement en cours…")
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)

        self.config["delay"]       = self.delay_spin.value()
        self.config["sync_mongo"]  = self.check_sync_mongo.isChecked()
        self.config["search_mode"] = self.combo_mode.currentData()
        save_config(self.config)

        existing_filter = {}

        search_mode = self.combo_mode.currentData()
        if self.scraper_worker and self.scraper_worker.isRunning() and self.scraper_worker.wait_for_start:
            self.scraper_worker.begin_scraping(
                companies=self.companies,
                existing=existing_filter,
                delay=self.delay_spin.value(),
                li_at_cookie=self.config.get("li_at", ""),
                search_mode=search_mode,
            )
        else:
            self.scraper_worker = ScraperWorker(
                companies=self.companies,
                existing=existing_filter,
                delay=self.delay_spin.value(),
                li_at_cookie=self.config.get("li_at", ""),
                search_mode=search_mode,
                window_pos=self.chrome_pos,
                window_size=self.chrome_size,
            )
            self._connect_scraper_worker(self.scraper_worker)
            self.scraper_worker.start()
        self._log_info("▶ Démarrage de l'analyse précise côte-à-côte avec Chrome…")

    def _toggle_pause(self):
        if self.scraper_worker is None:
            return
        if self.scraper_worker._pause:
            self.scraper_worker.resume()
            self.btn_pause.setText("⏸ Pause")
            self._log_info("▶ Reprise du traitement")
        else:
            self.scraper_worker.pause()
            self.btn_pause.setText("▶ Reprendre")
            self._log_info("⏸ Traitement en pause")

    def _stop_scraping(self):
        if self.scraper_worker:
            self.auto_process_missing = False
            self.scraper_worker.stop()
            self._log_info("⏹ Arrêt demandé par l'utilisateur…")

    def _update_mongo_document(self, cid: str, linkedin_profiles: list[dict]) -> bool:
        try:
            with MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) as client:
                col = client[DB_NAME][COLLECTION]
                obj_id = ObjectId(cid) if ObjectId.is_valid(cid) else cid
                result = col.update_one(
                    {
                        "_id": obj_id,
                        "$or": [
                            {"socialAccounts.linkedin": {"$exists": False}},
                            {"socialAccounts.linkedin": None},
                            {"socialAccounts.linkedin": []},
                            {"socialAccounts.linkedin": ""},
                        ],
                    },
                    {"$set": {"socialAccounts.linkedin": linkedin_profiles}}
                )
                if result.matched_count == 0:
                    self._log_error(
                        f"Le document MongoDB {cid} n'est plus sans LinkedIn ; "
                        "aucun lien existant n'a été remplacé."
                    )
                    return False
                return True
        except Exception as exc:
            self._log_error(f"Sync MongoDB échouée pour {cid} : {exc}")
            return False

    def _save_mongo_checkpoint(self, cid: str) -> bool:
        try:
            checkpoint_id = ObjectId(cid) if ObjectId.is_valid(cid) else cid
            with MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) as client:
                progress = client[DB_NAME][CHECKPOINT_COLLECTION]
                progress.update_one(
                    {"_id": CHECKPOINT_ID},
                    {
                        "$set": {
                            "last_id": checkpoint_id,
                            "status": "running",
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                    upsert=True,
                )
            return True
        except Exception as exc:
            self._log_error(
                f"Impossible d'enregistrer le point de reprise pour {cid} : {exc}"
            )
            return False

    # ── Événements Terminal Formatés en Thème BLANC ───────────────────────────

    def _on_company_started(self, idx: int, total: int, company: dict):
        name     = company.get("companyName") or company.get("tradeName") or "?"
        country  = company.get("countryCode") or "—"
        street   = company.get("street") or company.get("streetName") or ""
        location = company.get("location") or company.get("region") or ""
        domains  = ", ".join(company.get("domains") or []) or company.get("url") or "—"

        addr = f"{street} {location}".strip() or "Non renseignée"

        html = [
            f"<div style='margin-top:10px; border-left:3px solid #0A66C2; padding:4px 8px; background:#F1F5F9; border-radius:0 4px 4px 0;'>",
            f"  <span style='color:#0A66C2; font-weight:bold;'>[{idx}/{total}]</span> ",
            f"  <span style='color:#0F172A; font-weight:bold; font-size:12px;'>{name}</span> ",
            f"  <span style='color:#64748B;'>({country})</span><br>",
            f"  <span style='color:#475569; font-size:10px;'>📍 {addr} &nbsp;|&nbsp; 🌐 {domains}</span>",
            f"</div>"
        ]
        self._append_html("".join(html))

    def _on_result(self, cid: str, name: str, best_url: Optional[str], candidates: list[dict], status: str):
        company = next((c for c in self.companies if c["_id"] == cid), {})
        existing_social = dict(company.get("socialAccounts") or {})

        matched_candidates = [
            candidate
            for candidate in candidates
            if isinstance(candidate.get("resemblance"), (int, float))
            and candidate["resemblance"] > 0
        ]
        linkedin_profiles = [
            {
                "link": candidate.get("link", ""),
                "name": candidate.get("name", ""),
                "resemblance": candidate.get("resemblance", 0),
            }
            for candidate in matched_candidates
        ]
        validated_profiles = [
            profile
            for candidate, profile in zip(matched_candidates, linkedin_profiles)
            if candidate.get("is_valid") is True
        ]
        if linkedin_profiles:
            existing_social["linkedin"] = linkedin_profiles

        if not self.direct_mongo_search:
            self.results[cid] = {
                "_id":                 cid,
                "companyName":         company.get("companyName") or company.get("tradeName"),
                "tradeName":           company.get("tradeName"),
                "countryCode":         company.get("countryCode"),
                "street":              company.get("street") or company.get("streetName"),
                "location":            company.get("location"),
                "url":                 company.get("url"),
                "domains":             company.get("domains", []),
                "resultsSignals":      company.get("resultsSignals"),
                "resultsWebsite":      company.get("resultsWebsite"),
                "socialAccounts":      existing_social,
                "linkedin":            linkedin_profiles,
                "linkedinStatus":      "TROUVE" if best_url else "NON TROUVE",
                "linkedin_url":        best_url,
                "enriched_at":         datetime.now(timezone.utc).isoformat(),
                "status":              "found" if best_url else "not_found",
            }
            save_results(self.results)

        # In automatic mode, persist only validated matches and checkpoint each result.
        synced_str = ""
        if self.direct_mongo_search:
            saved = True
            if self.mongo_write_failed:
                saved = False
            elif best_url and validated_profiles:
                saved = self._update_mongo_document(cid, validated_profiles)
                if saved:
                    synced_str = " <span style='color:#15803D;'>& MongoDB synchronisé</span>"

            if saved and not self.mongo_write_failed:
                saved = self._save_mongo_checkpoint(cid)
            if not saved:
                self.mongo_write_failed = True
                self.auto_process_missing = False
                if self.scraper_worker and self.scraper_worker.isRunning():
                    self.scraper_worker.stop()
                synced_str = " <span style='color:#DC2626;'>& arrêt : vérifier MongoDB puis reprendre</span>"
        elif self.check_sync_mongo.isChecked() and best_url and validated_profiles:
            if self._update_mongo_document(cid, validated_profiles):
                synced_str = " <span style='color:#15803D;'>& MongoDB synchronisé</span>"
            else:
                synced_str = " <span style='color:#DC2626;'>& échec Sync MongoDB</span>"

        # Rendu haute précision dans le terminal blanc
        html = ["<div style='margin-left:12px; margin-bottom:8px; border-left:2px solid #E2E8F0; padding-left:8px;'>"]
        if best_url and matched_candidates:
            html.append("  <span style='color:#B45309; font-size:10px; font-weight:bold;'>📋 Profils vérifiés & validés :</span><br>")
            for i, cand in enumerate(matched_candidates[:3]):
                score = cand.get("resemblance", 0)
                if i == 0:
                    html.append(
                        f"    <span style='color:#0F172A; font-weight:bold;'>[{i}] {cand.get('name')}</span> "
                        f"— <span style='background:#DCFCE7; color:#15803D; font-weight:bold; padding:1px 5px; border-radius:3px;'>Concordance : {score}% ⭐ SÉLECTIONNÉ</span><br>"
                        f"      <span style='color:#0A66C2;'>↳ <a href='{cand.get('link')}' style='color:#0A66C2; text-decoration:none;'>{cand.get('link')}</a></span><br>"
                    )
                else:
                    html.append(
                        f"    <span style='color:#64748B;'>[{i}] {cand.get('name')}</span> — <span style='color:#B45309;'>{score}%</span><br>"
                        f"      <span style='color:#64748B;'>↳ {cand.get('link')}</span><br>"
                    )

            html.append(f"  <span style='color:#0369A1; font-weight:bold;'>💾 socialAccounts.linkedin</span> : <span style='color:#15803D; font-weight:bold;'>\"{best_url}\"</span><br>")
            if self.direct_mongo_search:
                html.append(
                    f"  <span style='color:#16A34A; font-size:10px; font-weight:bold;'>"
                    f"✅ Recherche directe MongoDB{synced_str}</span>"
                )
            else:
                html.append(
                    f"  <span style='color:#16A34A; font-size:10px; font-weight:bold;'>"
                    f"✅ Sauvegardé dans JSON{synced_str}</span>"
                )
        else:
            html.append("  <span style='color:#DC2626; font-size:11px;'>❌ Aucun profil LinkedIn fiable trouvé.</span>")
            if candidates:
                best_candidate = max(
                    candidates,
                    key=lambda candidate: candidate.get("resemblance", 0),
                )
                html.append(
                    f" <span style='color:#64748B;'>"
                    f"{len(candidates)} résultat(s) examinés ; meilleur score : "
                    f"{best_candidate.get('resemblance', 0)}% "
                    f"({escape_html(str(best_candidate.get('name', 'nom indisponible')))})."
                    "</span>"
                )
            else:
                html.append(
                    " <span style='color:#64748B;'>Aucun résultat extrait ; "
                    "vérifiez la connexion LinkedIn et le chargement de la recherche.</span>"
                )

        html.append("</div>")
        self._append_html("".join(html))
        self._update_stats()

    def _on_progress(self, current: int, total: int):
        if self.auto_process_missing:
            self.search_processed += max(0, current - self.last_batch_progress)
            self.last_batch_progress = current
            display_total = max(self.search_total, self.search_processed)
            self.progress_bar.setMaximum(display_total)
            self.progress_bar.setValue(self.search_processed)
            pct = int(self.search_processed / display_total * 100) if display_total else 0
            self.current_label.setText(
                f"Analyse complète : {self.search_processed}/{display_total} ({pct}%)"
            )
            self.status_bar.showMessage(
                f"Analyse en cours : {self.search_processed}/{display_total}"
            )
            return

        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        pct = int(current / total * 100) if total else 0
        self.current_label.setText(f"Traitement : {current}/{total} ({pct}%)")
        self.status_bar.showMessage(f"En cours : {current}/{total}")

    def _on_scraping_done(self):
        self.auto_process_missing = False
        self.companies = []
        self.mongo_ready = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ Reprendre depuis MongoDB")
        self.btn_start.setStyleSheet(self._btn_style("#16A34A", "#15803D"))
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText("⏸ Pause")
        self._update_auth_button_style()
        self._update_stats()

        self._log_info(
            "⏸ Analyse interrompue. Le dernier résultat confirmé est enregistré "
            "dans MongoDB ; cliquez sur « Reprendre depuis MongoDB » pour continuer."
        )
        self.status_bar.showMessage("⏸ Analyse interrompue — reprise possible")
        QMessageBox.information(
            self,
            "Analyse interrompue",
            "Le point de reprise est conservé dans MongoDB.\n"
            "Cliquez sur « Reprendre depuis MongoDB » pour continuer sans repartir du début.",
        )

    def _on_scraper_finished(self):
        if self.scraping_active:
            self.scraping_active = False
            if self.auto_process_missing:
                if self.last_batch_progress < len(self.companies):
                    self.auto_process_missing = False
                    self._log_error(
                        "Le bloc en cours n'a pas été entièrement analysé ; "
                        "la recherche automatique des lots suivants est arrêtée."
                    )
                    self._on_scraping_done()
                    return
                self._load_next_batch()
                return
            self._on_scraping_done()
        elif self.scraper_worker and self.scraper_worker.wait_for_start:
            self._log_error("Chrome n'a pas pu rester ouvert. Vérifiez que Chrome et ChromeDriver sont installés, puis relancez l'application.")

    def _finish_missing_search(self):
        self.auto_process_missing = False
        self.direct_mongo_search = False
        self.scraping_active = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("▶ Relancer l'analyse")
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self._update_stats()
        self._log_info(
            f"✅ Analyse terminée : {self.search_processed} entreprise(s) traitée(s)."
        )
        QMessageBox.information(
            self,
            "Analyse terminée",
            f"Analyse terminée : {self.search_processed} entreprise(s) traitée(s).\n"
            "Les profils validés ont été enregistrés directement dans MongoDB.",
        )

    def closeEvent(self, event):
        if self.scraper_worker and self.scraper_worker.isRunning():
            self.scraper_worker.stop()
            self.scraper_worker.wait()
        event.accept()

    def _on_need_login(self):
        html = (
            "<div style='background:#FEF3C7; border:1px solid #F59E0B; padding:10px; border-radius:6px; margin:8px 0;'>"
            "  <b style='color:#B45309; font-size:12px;'>🔑 CONNEXION LINKEDIN REQUISE :</b><br>"
            "  <span style='color:#92400E; font-size:11px;'>"
            "    👉 Connectez-vous avec votre compte dans la fenêtre Chrome ouverte à droite.<br>"
            "    <b>OU</b> cliquez sur '🔑 Session LinkedIn' en haut pour coller votre cookie <code>li_at</code>.<br>"
            "    <i>(Note : Vous pouvez aussi sélectionner le mode 'Recherche Web' pour chercher SANS compte LinkedIn !)</i>"
            "  </span>"
            "</div>"
        )
        self._append_html(html)

    # ── Helpers écriture terminal blanc ───────────────────────────────────────

    def _append_html(self, html: str):
        self.term_text.append(html)
        if self.autoscroll:
            cursor = self.term_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.term_text.setTextCursor(cursor)

    def _log_info(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._append_html(f"<div style='color:#334155; font-size:11px;'><span style='color:#94A3B8;'>[{ts}]</span> {msg}</div>")

    def _log_error(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._append_html(f"<div style='color:#DC2626; font-size:11px;'><span style='color:#94A3B8;'>[{ts}]</span> ❌ {msg}</div>")
