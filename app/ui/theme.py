"""Tema visual: colores, tipografía y hoja de estilos (QSS)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

BG = "#F4F5FA"
SURFACE = "#FFFFFF"
BORDER = "#E3E5EE"
TEXT = "#1B1F3B"
MUTED = "#6B7090"
PRIMARY = "#4F46E5"
PRIMARY_DARK = "#4338CA"
PRIMARY_SOFT = "#EEF0FF"
OK = "#059669"
OK_SOFT = "#E6F7F1"
WARN = "#B45309"
WARN_SOFT = "#FEF3E2"
DANGER = "#DC2626"
DANGER_SOFT = "#FDECEC"
INFO = "#2563EB"
INFO_SOFT = "#E8F0FE"
PURPLE = "#7C3AED"
PURPLE_SOFT = "#F1EAFE"
GRIS_SOFT = "#EEF0F5"

# estatus → (color de texto, color de fondo)
ESTATUS_COLORES: dict[str, tuple[str, str]] = {
    "PENDIENTE": (WARN, WARN_SOFT), "PAGADO": (INFO, INFO_SOFT), "ENVIADO": (PURPLE, PURPLE_SOFT),
    "ENTREGADO": (OK, OK_SOFT), "CANCELADO": (DANGER, DANGER_SOFT),
    "APROBADO": (OK, OK_SOFT), "RECHAZADO": (DANGER, DANGER_SOFT), "REEMBOLSADO": (MUTED, GRIS_SOFT),
    "ACTIVO": (OK, OK_SOFT), "INACTIVO": (MUTED, GRIS_SOFT), "SUSPENDIDO": (DANGER, DANGER_SOFT),
    "ADMIN": (PURPLE, PURPLE_SOFT), "VENDEDOR": (INFO, INFO_SOFT), "COMPRADOR": (OK, OK_SOFT),
}

ETIQUETAS_ESTATUS = {
    "PENDIENTE": "Pendiente", "PAGADO": "Pagado", "ENVIADO": "Enviado", "ENTREGADO": "Entregado",
    "CANCELADO": "Cancelado", "APROBADO": "Aprobado", "RECHAZADO": "Rechazado", "REEMBOLSADO": "Reembolsado",
    "ACTIVO": "Activo", "INACTIVO": "Pausado", "SUSPENDIDO": "Suspendido",
    "ADMIN": "Administrador", "VENDEDOR": "Vendedor", "COMPRADOR": "Comprador",
}

ETIQUETAS_METODO = {"TARJETA": "Tarjeta de crédito/débito", "TRANSFERENCIA": "Transferencia SPEI",
                    "PAYPAL": "PayPal", "OXXO": "Pago en OXXO"}


def color_estatus(estatus: str) -> tuple[QColor, QColor]:
    fg, bg = ESTATUS_COLORES.get(estatus, (MUTED, GRIS_SOFT))
    return QColor(fg), QColor(bg)


QSS = f"""
* {{ color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#raiz, QWidget[pagina="true"] {{ background: {BG}; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 6px 8px; border-radius: 6px; }}

QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame[card="true"] QLabel {{ background: transparent; border: none; }}
QFrame[flat="true"] {{ background: transparent; border: none; }}

QLabel[rol="titulo"] {{ font-size: 20pt; font-weight: 700; }}
QLabel[rol="subtitulo"] {{ color: {MUTED}; font-size: 10pt; }}
QLabel[rol="h2"] {{ font-size: 13pt; font-weight: 700; }}
QLabel[rol="muted"] {{ color: {MUTED}; }}
QLabel[rol="precio"] {{ font-size: 18pt; font-weight: 700; color: {PRIMARY}; }}
QLabel[rol="ok"] {{ color: {OK}; font-weight: 600; }}
QLabel[rol="error"] {{ color: {DANGER}; font-weight: 600; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {PRIMARY_SOFT}; border-color: {PRIMARY}; }}
QPushButton:pressed {{ background: #DDE0FF; }}
QPushButton:disabled {{ color: #A3A7BF; background: #F2F3F8; border-color: {BORDER}; }}
QPushButton[variante="primary"] {{ background: {PRIMARY}; color: white; border: 1px solid {PRIMARY}; }}
QPushButton[variante="primary"]:hover {{ background: {PRIMARY_DARK}; border-color: {PRIMARY_DARK}; }}
QPushButton[variante="primary"]:disabled {{ background: #B9B6F3; border-color: #B9B6F3; color: white; }}
QPushButton[variante="danger"] {{ color: {DANGER}; border-color: #F3B8B8; }}
QPushButton[variante="danger"]:hover {{ background: {DANGER_SOFT}; border-color: {DANGER}; }}
QPushButton[variante="link"] {{ border: none; background: transparent; color: {PRIMARY}; padding: 4px 6px; }}
QPushButton[variante="link"]:hover {{ background: {PRIMARY_SOFT}; }}
QPushButton[variante="chip"] {{ border-radius: 14px; padding: 4px 12px; font-weight: 500; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px;
    selection-background-color: {PRIMARY}; selection-color: white; }}
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {{ border: none; padding: 0; background: transparent; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; border: none; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1.5px solid {PRIMARY}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ background: #F2F3F8; color: #A3A7BF; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {PRIMARY_SOFT};
    selection-color: {TEXT}; outline: none; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1.5px solid #B5B9D3; border-radius: 5px; background: white; }}
QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}

QTableWidget, QTableView {{ background: {SURFACE}; alternate-background-color: #FAFAFE; border: 1px solid {BORDER};
    border-radius: 10px; gridline-color: transparent; selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT}; outline: none; }}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #F0F1F7; }}
QTableWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {TEXT}; }}
QHeaderView::section {{ background: #F7F8FC; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 9px 8px; font-weight: 700; font-size: 9pt; }}
QHeaderView {{ background: transparent; }}
QTableCornerButton::section {{ background: #F7F8FC; border: none; }}

QListView {{ background: transparent; border: none; outline: none; }}
QListWidget#sidebar {{ background: {SURFACE}; border: none; border-right: 1px solid {BORDER}; padding: 10px 8px; outline: none; }}
QListWidget#sidebar::item {{ padding: 10px 12px; border-radius: 8px; margin: 1px 0; color: {TEXT}; }}
QListWidget#sidebar::item:hover {{ background: #F3F4FA; }}
QListWidget#sidebar::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; font-weight: 700; }}

QTreeWidget {{ background: transparent; border: none; outline: none; }}
QTreeWidget::item {{ padding: 6px 4px; border-radius: 6px; }}
QTreeWidget::item:hover {{ background: #F3F4FA; }}
QTreeWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; font-weight: 600; }}

QTabBar::tab {{ background: transparent; padding: 10px 16px; margin-right: 4px; border: none; border-bottom: 3px solid transparent;
    color: {MUTED}; font-weight: 600; }}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 3px solid {PRIMARY}; }}
QTabBar::tab:hover {{ color: {PRIMARY}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CDD0E3; border-radius: 4px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: #A9AECB; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CDD0E3; border-radius: 4px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ background: transparent; border: none; max-height: 3px; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 1px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QMessageBox {{ background: {SURFACE}; }}
QSplitter::handle {{ background: transparent; }}
"""


def aplicar_tema(app: QApplication) -> None:
    app.setStyle("Fusion")
    fuente = QFont()
    fuente.setFamilies(["Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Roboto", "DejaVu Sans", "Arial"])
    fuente.setPointSize(10)
    app.setFont(fuente)
    app.setStyleSheet(QSS)
