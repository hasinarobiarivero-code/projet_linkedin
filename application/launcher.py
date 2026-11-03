from __future__ import annotations

import sys

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from application.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LinkedIn Auto-Enricher")
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,        QColor("#F8FAFC"))
    palette.setColor(QPalette.ColorRole.WindowText,    QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Base,          QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F1F5F9"))
    palette.setColor(QPalette.ColorRole.Text,          QColor("#0F172A"))
    palette.setColor(QPalette.ColorRole.Button,        QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ButtonText,    QColor("#0F172A"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
