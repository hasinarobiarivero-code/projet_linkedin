from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QTabWidget, QWidget,
    QLineEdit, QPushButton, QDialogButtonBox, QMessageBox,
)
from selenium import webdriver

from application.browser import (
    init_chrome_driver,
    inject_li_at_cookie,
    is_linkedin_logged_in,
)
from application.config import LI_LOGIN_URL, load_config, save_config



class LinkedInLoginDialog(QDialog):
    """Fenêtre compacte en thème blanc pour configurer le cookie li_at ou se connecter manuellement."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 Session LinkedIn")
        self.resize(540, 440)
        self.setStyleSheet("background:#FFFFFF;color:#0F172A;")
        self.cfg = load_config()
        self.test_driver: Optional[webdriver.Chrome] = None

        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(16, 16, 16, 16)

        header = QLabel("<h3 style='color:#0F172A;margin:0;'>🔑 Connexion LinkedIn</h3>")
        lay.addWidget(header)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid #CBD5E1;background:#FFFFFF;border-radius:4px;}"
            "QTabBar::tab{background:#F1F5F9;color:#475569;padding:6px 12px;border:1px solid #CBD5E1;border-bottom:none;}"
            "QTabBar::tab:selected{background:#FFFFFF;color:#0A66C2;font-weight:bold;}"
        )

        # Onglet 1 : Cookie li_at
        tab_cookie = QWidget()
        c_lay = QVBoxLayout(tab_cookie)
        c_lay.setSpacing(10)

        c_info = QLabel(
            "<b>Méthode recommandée (instantanée & sans captcha) :</b><br>"
            "1. Ouvrez LinkedIn dans votre navigateur habituel (Chrome/Edge/Firefox).<br>"
            "2. Appuyez sur <b>F12</b> ➔ onglet <b>Application</b> (ou <b>Stockage</b>).<br>"
            "3. Déroulez <b>Cookies</b> ➔ <code>https://www.linkedin.com</code>.<br>"
            "4. Copiez la valeur du cookie nommé <b>li_at</b> et collez-la ci-dessous :"
        )
        c_info.setWordWrap(True)
        c_info.setStyleSheet("background:#F8FAFC;border:1px solid #E2E8F0;border-radius:6px;padding:8px;font-size:11px;color:#334155;")
        c_lay.addWidget(c_info)

        c_lay.addWidget(QLabel("<b>Valeur du cookie li_at :</b>"))
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("Ex: AQEDATW... (longue chaîne de caractères)")
        self.cookie_input.setText(self.cfg.get("li_at", ""))
        self.cookie_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.cookie_input.setStyleSheet("background:#FFFFFF;border:1px solid #CBD5E1;border-radius:4px;padding:6px;font-size:11px;color:#0F172A;")
        c_lay.addWidget(self.cookie_input)

        self.btn_save_cookie = QPushButton("💾 Enregistrer & Tester le cookie")
        self.btn_save_cookie.setStyleSheet(
            "QPushButton{background:#0A66C2;color:white;font-weight:bold;padding:8px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#004182;}"
        )
        self.btn_save_cookie.clicked.connect(self._test_and_save_cookie)
        c_lay.addWidget(self.btn_save_cookie)

        self.cookie_status = QLabel("")
        self.cookie_status.setWordWrap(True)
        c_lay.addWidget(self.cookie_status)
        c_lay.addStretch()

        tabs.addTab(tab_cookie, "🍪 Cookie li_at (Recommandé)")

        # Onglet 2 : Connexion Manuelle
        tab_manual = QWidget()
        m_lay = QVBoxLayout(tab_manual)
        m_lay.setSpacing(10)

        m_info = QLabel(
            "<b>Connexion manuelle dans Chrome :</b><br>"
            "Ouvre Chrome avec le profil persistant.<br>"
            "Connectez-vous une seule fois, votre session restera enregistrée pour toujours."
        )
        m_info.setWordWrap(True)
        m_info.setStyleSheet("background:#F8FAFC;border:1px solid #E2E8F0;border-radius:6px;padding:8px;font-size:11px;color:#334155;")
        m_lay.addWidget(m_info)

        self.btn_open_chrome = QPushButton("🌐 Ouvrir Chrome pour se connecter")
        self.btn_open_chrome.setStyleSheet(
            "QPushButton{background:#16A34A;color:white;font-weight:bold;padding:8px;border-radius:5px;border:none;}"
            "QPushButton:hover{background:#15803D;}"
        )
        self.btn_open_chrome.clicked.connect(self._open_chrome_manual)
        m_lay.addWidget(self.btn_open_chrome)

        self.manual_status = QLabel("Statut : Prêt")
        self.manual_status.setStyleSheet("color:#64748B;font-size:11px;")
        m_lay.addWidget(self.manual_status)

        self.btn_verify_manual = QPushButton("🔄 Vérifier l'état de la connexion")
        self.btn_verify_manual.setEnabled(False)
        self.btn_verify_manual.setStyleSheet(
            "QPushButton{background:#F1F5F9;color:#334155;border:1px solid #CBD5E1;border-radius:4px;padding:6px;}"
            "QPushButton:disabled{color:#94A3B8;}"
        )
        self.btn_verify_manual.clicked.connect(self._verify_manual_login)
        m_lay.addWidget(self.btn_verify_manual)

        m_lay.addStretch()
        tabs.addTab(tab_manual, "🌐 Navigateur Chrome")

        lay.addWidget(tabs)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self._on_close)
        lay.addWidget(btn_box)

    def _test_and_save_cookie(self):
        token = self.cookie_input.text().strip()
        if not token:
            self.cookie_status.setText("<span style='color:#DC2626;'>⚠️ Saisissez une valeur pour le cookie li_at.</span>")
            return

        self.btn_save_cookie.setEnabled(False)
        self.cookie_status.setText("<span style='color:#0284C7;'>⏳ Test du cookie…</span>")
        QApplication.processEvents()

        driver = None
        try:
            driver = init_chrome_driver(headless=True)
            success = inject_li_at_cookie(driver, token)
            if success:
                self.cfg["li_at"] = token
                save_config(self.cfg)
                self.cookie_status.setText("<span style='color:#16A34A;font-weight:bold;'>✅ Cookie valide ! Session enregistrée.</span>")
            else:
                self.cookie_status.setText("<span style='color:#DC2626;'>❌ Cookie non valide ou expiré.</span>")
        except Exception as exc:
            self.cookie_status.setText(f"<span style='color:#DC2626;'>❌ Erreur : {exc}</span>")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.btn_save_cookie.setEnabled(True)

    def _open_chrome_manual(self):
        try:
            self.btn_open_chrome.setEnabled(False)
            self.manual_status.setText("⏳ Ouverture de Chrome…")
            QApplication.processEvents()

            self.test_driver = init_chrome_driver(headless=False)
            self.test_driver.get(LI_LOGIN_URL)
            self.manual_status.setText("👉 Connectez-vous dans Chrome, puis cliquez sur 'Vérifier'.")
            self.btn_verify_manual.setEnabled(True)
        except Exception as exc:
            self.manual_status.setText(f"❌ Erreur : {exc}")
            self.btn_open_chrome.setEnabled(True)

    def _verify_manual_login(self):
        if not self.test_driver:
            return
        if is_linkedin_logged_in(self.test_driver):
            cookies = {c["name"]: c["value"] for c in self.test_driver.get_cookies()}
            if "li_at" in cookies:
                self.cfg["li_at"] = cookies["li_at"]
                save_config(self.cfg)
                self.cookie_input.setText(cookies["li_at"])
            self.manual_status.setText("<span style='color:#16A34A;font-weight:bold;'>✅ Connecté ! Profil enregistré.</span>")
            QMessageBox.information(self, "Succès", "✅ Connexion LinkedIn réussie !")
        else:
            self.manual_status.setText("<span style='color:#DC2626;'>⚠️ Non connecté pour le moment.</span>")

    def _on_close(self):
        if self.test_driver:
            try:
                self.test_driver.quit()
            except Exception:
                pass
            self.test_driver = None
        self.accept()

    def closeEvent(self, event):
        self._on_close()
        event.accept()
