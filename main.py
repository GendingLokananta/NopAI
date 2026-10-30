import sys
import sqlite3
import json
from pathlib import Path

import requests

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QTextCharFormat, QTextListFormat, QFont, QShortcut, QKeySequence, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel,
    QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout,
    QSplitter, QMessageBox, QInputDialog, QListWidget,
    QListWidgetItem, QComboBox, QDialog, QFormLayout,
    QLineEdit, QDialogButtonBox, QMenu, QFileDialog, QStackedWidget,
    QTabWidget, QCheckBox
)

# =========================
# CONFIGURATION
# =========================

APP_NAME = "Stomake"
MODEL_NAME = "llama3.2:3b"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "Stomake.db"
LEGACY_DB_PATH = DATA_DIR / "nopai.db"

# Preserve existing data by renaming the legacy database on first upgrade.
# If Stomake.db already exists, leave both files untouched.
if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
    LEGACY_DB_PATH.replace(DB_PATH)


# =========================
# DATABASE
# =========================

def db():
    return sqlite3.connect(DB_PATH)


def setup_database():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """)
        # Rich-text HTML is stored separately so formatting survives reopening,
        # while the plain-text content column remains compatible with AI features.
        chapter_columns = {row[1] for row in conn.execute("PRAGMA table_info(chapters)").fetchall()}
        if "content_html" not in chapter_columns:
            conn.execute("ALTER TABLE chapters ADD COLUMN content_html TEXT NOT NULL DEFAULT ''")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'Karakter Pendukung',
                details TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """)
        # Upgrade databases created by older Stomake versions without losing data.
        character_columns = {row[1] for row in conn.execute("PRAGMA table_info(characters)").fetchall()}
        if "role" not in character_columns:
            conn.execute("ALTER TABLE characters ADD COLUMN role TEXT NOT NULL DEFAULT 'Karakter Pendukung'")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS worldbuilding (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Lore',
                details TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """)
        # Keep compatibility with the first Stomake version.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS manuscript (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(section, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL DEFAULT 0,
                field_key TEXT NOT NULL,
                value TEXT NOT NULL,
                UNIQUE(project_id, field_key, value)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS story_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """)
        # Extensible profile fields and connections for Story/World Bible.
        story_record_columns = {row[1] for row in conn.execute("PRAGMA table_info(story_records)").fetchall()}
        if "metadata" not in story_record_columns:
            conn.execute("ALTER TABLE story_records ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}' ")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS story_record_chapters (
                record_id INTEGER NOT NULL, chapter_id INTEGER NOT NULL,
                PRIMARY KEY(record_id, chapter_id),
                FOREIGN KEY(record_id) REFERENCES story_records(id) ON DELETE CASCADE,
                FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS character_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL, source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL, relation TEXT NOT NULL DEFAULT 'Terhubung',
                notes TEXT NOT NULL DEFAULT '',
                UNIQUE(source_id, target_id, relation),
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(source_id) REFERENCES story_records(id) ON DELETE CASCADE,
                FOREIGN KEY(target_id) REFERENCES story_records(id) ON DELETE CASCADE
            )
        """)

        count = conn.execute(
            "SELECT COUNT(*) FROM projects"
        ).fetchone()[0]

        if count == 0:
            old = conn.execute(
                "SELECT title, content FROM manuscript WHERE id = 1"
            ).fetchone()
            title = old[0] if old else "Cerita Pertamaku"
            content = old[1] if old else ""
            cur = conn.execute(
                "INSERT INTO projects (title) VALUES (?)", (title,)
            )
            project_id = cur.lastrowid
            conn.execute("""
                INSERT INTO chapters
                (project_id, title, content, position)
                VALUES (?, 'Bab 1', ?, 1)
            """, (project_id, content))

        # Ensure projects created by earlier versions have at least one chapter.
        projects = conn.execute("SELECT id FROM projects").fetchall()
        for (project_id,) in projects:
            chapter_count = conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE project_id = ?",
                (project_id,)
            ).fetchone()[0]
            if chapter_count == 0:
                conn.execute("""
                    INSERT INTO chapters
                    (project_id, title, content, position)
                    VALUES (?, 'Bab 1', '', 1)
                """, (project_id,))


def get_projects():
    with db() as conn:
        return conn.execute(
            "SELECT id, title FROM projects ORDER BY id"
        ).fetchall()


def create_project(title):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO projects (title) VALUES (?)", (title,)
        )
        project_id = cur.lastrowid
        conn.execute("""
            INSERT INTO chapters
            (project_id, title, content, position)
            VALUES (?, 'Bab 1', '', 1)
        """, (project_id,))
        return project_id


def get_chapters(project_id):
    with db() as conn:
        return conn.execute("""
            SELECT id, title, content, position
            FROM chapters
            WHERE project_id = ?
            ORDER BY position, id
        """, (project_id,)).fetchall()


def create_chapter(project_id, title):
    with db() as conn:
        position = conn.execute("""
            SELECT COALESCE(MAX(position), 0) + 1
            FROM chapters WHERE project_id = ?
        """, (project_id,)).fetchone()[0]
        cur = conn.execute("""
            INSERT INTO chapters
            (project_id, title, content, position)
            VALUES (?, ?, '', ?)
        """, (project_id, title, position))
        return cur.lastrowid


def save_chapter(chapter_id, title, content, content_html=None):
    with db() as conn:
        if content_html is None:
            conn.execute("""
                UPDATE chapters SET title = ?, content = ?
                WHERE id = ?
            """, (title, content, chapter_id))
        else:
            conn.execute("""
                UPDATE chapters SET title = ?, content = ?, content_html = ?
                WHERE id = ?
            """, (title, content, content_html, chapter_id))


# =========================
# AI WORKER
# =========================

class AIWorker(QThread):
    success = Signal(str)
    failure = Signal(str)

    def __init__(self, prompt, context):
        super().__init__()
        self.prompt = prompt
        self.context = context

    def run(self):
        try:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": MODEL_NAME,
                    "stream": False,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Kamu adalah Stomake, asisten penulis cerita. "
                                "Bantu mengembangkan cerita, menyunting prosa, "
                                "dan menjaga konsistensi berdasarkan konteks "
                                "yang diberikan. Jangan mengarang fakta sebagai "
                                "fakta jika tidak ada di konteks. Jawab dengan "
                                "bahasa yang digunakan pengguna.\n\n"
                                "KONTEKS PROYEK:\n" + self.context
                            )
                        },
                        {"role": "user", "content": self.prompt}
                    ],
                    "options": {"num_ctx": 4096}
                },
                timeout=300
            )
            response.raise_for_status()
            answer = response.json().get("message", {}).get("content", "")
            self.success.emit(answer or "AI tidak memberikan jawaban.")
        except requests.exceptions.ConnectionError:
            self.failure.emit(
                "Tidak dapat terhubung ke Ollama. Pastikan Ollama berjalan "
                "dan model llama3.2:3b sudah diunduh."
            )
        except requests.exceptions.Timeout:
            self.failure.emit(
                "AI terlalu lama merespons. Coba prompt yang lebih pendek."
            )
        except Exception as error:
            self.failure.emit(str(error))


# =========================
# RECORD EDITOR DIALOG
# =========================

# =========================
# MAIN APPLICATION
# =========================

class Stomake(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stomake — Ruang Cerita Kreatif")
        self.resize(1450, 880)
        self.setMinimumSize(1000, 650)

        self.project_id = None
        self.project_title = ""
        self.chapter_id = None
        self.chapter_title = ""
        self.last_answer = ""
        self.worker = None
        self.loading = False
        self.active_records_kind = None
        self.active_record_id = None
        self.reference_record_kind = None
        self.reference_record_id = None
        self.record_windows = {}

        setup_database()
        self.build_ui()
        self.load_projects()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_current_chapter)
        self.autosave_timer.start(1500)

        self.apply_theme()

    # -------------------------
    # UI
    # -------------------------

    def build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Left navigation / project tree
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 20, 16, 16)
        side.setSpacing(9)

        logo = QLabel("✦  Stomake")
        logo.setObjectName("logo")
        side.addWidget(logo)
        tagline = QLabel("Ruang Cerita Kreatif")
        tagline.setObjectName("muted")
        side.addWidget(tagline)
        side.addSpacing(12)

        side.addSpacing(12)
        side.addWidget(QLabel("CERITA SAYA"))
        project_row = QHBoxLayout()
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self.on_project_changed)
        self.project_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_combo.customContextMenuRequested.connect(self.show_project_menu)
        project_row.addWidget(self.project_combo, 1)
        add_project = QPushButton("＋")
        add_project.setFixedWidth(34)
        add_project.clicked.connect(self.new_project)
        project_row.addWidget(add_project)
        side.addLayout(project_row)

        side.addSpacing(8)
        side.addWidget(QLabel("MANUSKRIP"))
        self.chapter_list = QListWidget()
        self.chapter_list.currentItemChanged.connect(self.on_chapter_changed)
        self.chapter_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chapter_list.customContextMenuRequested.connect(self.show_chapter_menu)
        self.chapter_list.setMaximumHeight(145)
        side.addWidget(self.chapter_list)
        add_chapter = QPushButton("＋ Tambah Bab")
        add_chapter.clicked.connect(self.new_chapter)
        side.addWidget(add_chapter)

        # Story/World Bible categories are user-defined to keep the sidebar clean.
        side.addSpacing(5)
        self.nav_buttons = {}
        self.nav_section_layouts = {}
        self.nav_section_widgets = {}
        for section_key, section_title in (("story", "STORY BIBLE"), ("world", "WORLD BIBLE")):
            section = QLabel(section_title)
            section.setObjectName("sectionLabel")
            side.addWidget(section)
            self.nav_section_widgets[section_key] = section
            self.nav_section_layouts[section_key] = side
            if section_key == "world":
                self.add_nav_entry("characters", "♙  Karakter", section_key)
            add_category = QPushButton("＋ Tambah Kategori")
            add_category.setObjectName("navButton")
            add_category.clicked.connect(lambda checked=False, sec=section_key: self.add_custom_category(sec))
            side.addWidget(add_category)
            self.nav_section_widgets[section_key + "_add"] = add_category
        self.load_custom_category_navigation(side)
        side.addStretch(1)
        self.save_label = QLabel("● Siap")
        self.save_label.setObjectName("muted")
        side.addWidget(self.save_label)

        # Center editor
        center = QFrame()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(18, 16, 18, 14)
        center_layout.setSpacing(12)
        header = QHBoxLayout()
        self.chapter_heading = QLabel("Editor Cerita")
        self.chapter_heading.setObjectName("heading")
        header.addWidget(self.chapter_heading)
        header.addStretch()
        self.focus_button = QPushButton("◉ Fokus")
        self.focus_button.setToolTip("Aktif/nonaktifkan Focus Writing (Ctrl+Shift+F)")
        self.focus_button.clicked.connect(self.toggle_focus_mode)
        header.addWidget(self.focus_button)
        self.ai_toggle_button = QPushButton("Sembunyikan AI")
        self.ai_toggle_button.setToolTip("Tampilkan atau sembunyikan AI Assistant (Ctrl+Shift+A)")
        self.ai_toggle_button.clicked.connect(self.toggle_ai_panel)
        header.addWidget(self.ai_toggle_button)
        export_button = QPushButton("⇩ Export Cerita")
        export_button.clicked.connect(self.show_export_menu)
        header.addWidget(export_button)
        center_layout.addLayout(header)

        # Area tengah memakai halaman bertumpuk: cerita atau detail karakter/latar.
        self.center_stack = QStackedWidget()
        center_layout.addWidget(self.center_stack, 1)
        self.chapter_page = QWidget()
        chapter_page_layout = QVBoxLayout(self.chapter_page)
        chapter_page_layout.setContentsMargins(0, 0, 0, 0)
        chapter_page_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(3)
        toolbar.setContentsMargins(0, 2, 0, 4)
        self.format_buttons = {}
        for key, label, tooltip in [
            ("bold", "B", "Tebal (Ctrl+B)"),
            ("italic", "I", "Miring (Ctrl+I)"),
            ("underline", "U", "Garis bawah (Ctrl+U)"),
            ("strike", "S̶", "Coret"),
            ("bullet", "•", "Daftar bullet"),
            ("number", "1.", "Daftar bernomor"),
        ]:
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.setCheckable(True)
            # Compact Word-style toolbar buttons, especially the list controls.
            button.setFixedSize(24, 24)
            button.setStyleSheet("QPushButton { padding: 0px; margin: 0px; border-radius: 4px; font-size: 12px; }")
            button.setProperty("formatKey", key)
            button.clicked.connect(lambda checked=False, k=key: self.apply_format(k))
            self.format_buttons[key] = button
            toolbar.addWidget(button)

        separator = QLabel("│")
        separator.setObjectName("muted")
        toolbar.addWidget(separator)
        self.alignment_buttons = {}
        for key, label, tooltip in [
            ("left", "≡", "Rata kiri"),
            ("center", "☰", "Rata tengah"),
            ("right", "≡→", "Rata kanan"),
            ("justify", "☷", "Rata kiri-kanan"),
        ]:
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setFixedSize(24, 24)
            button.setStyleSheet("QPushButton { padding: 0px; margin: 0px; border-radius: 4px; font-size: 11px; }")
            button.clicked.connect(lambda checked=False, k=key: self.apply_alignment(k))
            self.alignment_buttons[key] = button
            toolbar.addWidget(button)

        font_label = QLabel("Font")
        font_label.setStyleSheet("font-size: 11px; padding: 0px;")
        toolbar.addWidget(font_label)
        self.font_family_combo = QComboBox()
        # Daftar font umum yang relatif konsisten tersedia di Windows.
        # Menghindari enumerasi font legacy yang memicu warning DirectWrite.
        self.font_family_combo.addItems([
            "Arial", "Calibri", "Cambria", "Garamond", "Georgia", "Times New Roman",
            "Verdana", "Tahoma", "Trebuchet MS", "Segoe UI", "Consolas",
            "Courier New"
        ])
        self.font_family_combo.setCurrentText("Arial")
        self.font_family_combo.setFixedWidth(120)
        self.font_family_combo.setFixedHeight(24)
        self.font_family_combo.setStyleSheet("""
            QComboBox {
                padding: 1px 22px 1px 6px;
                font-size: 11px;
                border-radius: 8px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: right center;
                width: 18px;
                margin: 2px;
                border: 1px solid #555363;
                border-radius: 9px;
                background-color: #454552;
            }
            QComboBox::drop-down:hover {
                background-color: #8170c9;
                border-color: #b8a5ff;
            }
        """)
        self.font_family_combo.setToolTip("Pilih jenis huruf")
        self.font_family_combo.currentTextChanged.connect(self.apply_font_family)
        toolbar.addWidget(self.font_family_combo)

        size_label = QLabel("Uk.")
        size_label.setStyleSheet("font-size: 11px; padding: 0px;")
        toolbar.addWidget(size_label)
        self.font_size_combo = QComboBox()
        self.font_size_combo.setEditable(True)
        self.font_size_combo.setFixedWidth(68)
        self.font_size_combo.setFixedHeight(24)
        self.font_size_combo.setStyleSheet("""
            QComboBox {
                padding: 0px 22px 0px 5px;
                font-size: 11px;
                border-radius: 8px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: right center;
                width: 18px;
                margin: 2px;
                border: 1px solid #555363;
                border-radius: 9px;
                background-color: #454552;
            }
            QComboBox::drop-down:hover {
                background-color: #8170c9;
                border-color: #b8a5ff;
            }
            QComboBox QLineEdit {
                background-color: #30303b;
                color: #ffffff;
                border: none;
                border-radius: 0px;
                padding: 0px 2px;
                margin: 0px;
                min-width: 28px;
                selection-background-color: #6654a8;
                selection-color: #ffffff;
            }
            QComboBox QAbstractItemView {
                padding: 4px;
                border-radius: 9px;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px 8px;
                border-radius: 6px;
            }
        """)
        self.font_size_combo.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28", "36", "48", "72"])
        self.font_size_combo.setCurrentText("12")
        self.font_size_combo.lineEdit().setText("12")
        self.font_size_combo.lineEdit().setStyleSheet(
            "QLineEdit { color: #ffffff; background-color: #30303b; border: none; padding: 0px 2px; }"
        )
        self.font_size_combo.setToolTip("Ukuran font (pt). Pilih atau ketik ukuran lalu tekan Enter")
        self.font_size_combo.activated.connect(self.apply_font_size)
        self.font_size_combo.lineEdit().returnPressed.connect(self.apply_font_size)
        toolbar.addWidget(self.font_size_combo)
        toolbar.addStretch(1)
        chapter_page_layout.addLayout(toolbar)

        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.editor.textChanged.connect(self.update_word_count)
        self.editor.cursorPositionChanged.connect(self.update_format_indicators)
        self.editor.selectionChanged.connect(self.update_format_indicators)
        self.editor.setTabChangesFocus(False)

        # Panel referensi ini muncul saat halaman karakter/latar diminimize.
        # Editor cerita tetap aktif sehingga pengguna bisa menulis sambil membaca referensi.
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.addWidget(self.editor)

        self.reference_panel = QFrame()
        self.reference_panel.setObjectName("panel")
        self.reference_panel.setMinimumWidth(190)
        reference_layout = QVBoxLayout(self.reference_panel)
        reference_layout.setContentsMargins(10, 10, 10, 10)
        reference_layout.setSpacing(7)
        reference_header = QHBoxLayout()
        self.reference_heading = QLabel("Referensi")
        self.reference_heading.setObjectName("heading")
        reference_header.addWidget(self.reference_heading, 1)
        self.reference_close_button = QPushButton("×")
        self.reference_close_button.setFixedSize(28, 28)
        self.reference_close_button.setToolTip("Tutup panel referensi")
        self.reference_close_button.clicked.connect(self.hide_reference_panel)
        reference_header.addWidget(self.reference_close_button)
        reference_layout.addLayout(reference_header)
        self.reference_details = QTextEdit()
        self.reference_details.setReadOnly(True)
        self.reference_details.setAcceptRichText(False)
        self.reference_details.setPlaceholderText("Minimize halaman karakter atau latar untuk menampilkan referensi di sini.")
        reference_layout.addWidget(self.reference_details, 1)
        self.reference_open_button = QPushButton("Buka halaman untuk edit")
        self.reference_open_button.clicked.connect(self.restore_reference_page)
        reference_layout.addWidget(self.reference_open_button)
        self.reference_panel.hide()
        self.editor_splitter.addWidget(self.reference_panel)
        self.editor_splitter.setSizes([700, 0])
        chapter_page_layout.addWidget(self.editor_splitter, 1)

        # Familiar Word shortcuts for paragraph alignment.
        QShortcut(QKeySequence("Ctrl+L"), self.editor, activated=lambda: self.apply_alignment("left"))
        QShortcut(QKeySequence("Ctrl+E"), self.editor, activated=lambda: self.apply_alignment("center"))
        QShortcut(QKeySequence("Ctrl+R"), self.editor, activated=lambda: self.apply_alignment("right"))
        QShortcut(QKeySequence("Ctrl+J"), self.editor, activated=lambda: self.apply_alignment("justify"))
        # Rich-text shortcuts must be attached to the editor and work while it has focus.
        for sequence, key in (("Ctrl+B", "bold"), ("Ctrl+I", "italic"), ("Ctrl+U", "underline"), ("Ctrl+Shift+X", "strike")):
            shortcut = QShortcut(QKeySequence(sequence), self.editor)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda k=key: self.toggle_format_shortcut(k))
        footer = QHBoxLayout()
        self.word_label = QLabel("0 kata")
        self.word_label.setObjectName("muted")
        footer.addWidget(self.word_label)
        footer.addStretch()
        footer.addWidget(QLabel("Disimpan lokal • Markdown"))
        chapter_page_layout.addLayout(footer)
        self.center_stack.addWidget(self.chapter_page)

        # Halaman karakter/latar di area tengah, bukan dialog pop-up.
        self.record_page = QWidget()
        record_layout = QVBoxLayout(self.record_page)
        record_layout.setContentsMargins(8, 8, 8, 8)
        record_layout.setSpacing(10)
        self.record_page_heading = QLabel("Detail Karakter / Latar")
        self.record_page_heading.setObjectName("heading")
        record_layout.addWidget(self.record_page_heading)
        record_layout.addWidget(QLabel("Nama"))
        self.record_name_input = QLineEdit()
        self.record_name_input.setPlaceholderText("Masukkan nama karakter atau latar")
        record_layout.addWidget(self.record_name_input)
        self.record_role_label = QLabel("Role Karakter")
        record_layout.addWidget(self.record_role_label)
        self.record_role_input = QComboBox()
        self.record_role_input.setEditable(True)
        self.record_role_input.addItems([
            "Protagonis", "Antagonis", "Deuteragonis", "Tritagonis",
            "Karakter Pendukung", "Mentor", "Love Interest", "Sidekick",
            "Figuran", "Lainnya"
        ])
        self.record_role_input.setToolTip("Pilih role karakter atau ketik role buatan sendiri")
        record_layout.addWidget(self.record_role_input)
        self.record_category_label = QLabel("Kategori")
        record_layout.addWidget(self.record_category_label)
        self.record_category_input = QComboBox()
        self.record_category_input.setEditable(True)
        self.record_category_input.addItems(["Lore", "Lokasi", "Faksi", "Sistem Kekuatan", "Benda", "Sejarah", "Lainnya"])
        record_layout.addWidget(self.record_category_input)
        record_layout.addWidget(QLabel("Detail / Deskripsi"))
        self.record_details_input = QTextEdit()
        self.record_details_input.setPlaceholderText("Tulis detail karakter atau latar di sini...")
        record_layout.addWidget(self.record_details_input, 1)
        record_buttons = QHBoxLayout()
        record_buttons.addStretch()
        self.record_back_button = QPushButton("Kembali ke Cerita")
        self.record_back_button.clicked.connect(self.minimize_record_page)
        record_buttons.addWidget(self.record_back_button)
        self.record_save_button = QPushButton("Simpan")
        self.record_save_button.setObjectName("primary")
        self.record_save_button.clicked.connect(self.save_record_form)
        record_buttons.addWidget(self.record_save_button)
        record_layout.addLayout(record_buttons)
        self.center_stack.addWidget(self.record_page)

        # Data-driven pages for the story bible. Each section has persistent CRUD.
        self.data_pages = {}
        self.data_lists = {}
        self.data_searches = {}
        self.data_titles = {
            "characters": ("Karakter", "Karakter", "Profil karakter, peran, dan trait.")
        }
        with db() as conn:
            custom_rows = conn.execute("SELECT id, section, name FROM custom_categories ORDER BY id").fetchall()
        for category_id, section, name in custom_rows:
            key = f"custom_{category_id}"
            self.data_titles[key] = (name, name, f"Kategori cerita buatanmu: {name}.")
        for key, (title, category, description) in self.data_titles.items():
            self.create_data_page(key, title, category, description)

        # AI panel
        ai_panel = QFrame()
        self.ai_panel = ai_panel
        ai_panel.setObjectName("panel")
        ai_panel.setMinimumWidth(280)
        ai_layout = QVBoxLayout(ai_panel)
        ai_layout.setContentsMargins(12, 12, 12, 12)
        ai_layout.setSpacing(8)
        ai_header = QHBoxLayout()
        ai_title = QLabel("✦ AI Assistant")
        ai_title.setObjectName("heading")
        ai_header.addWidget(ai_title, 1)
        ai_hide_button = QPushButton("×")
        ai_hide_button.setObjectName("iconButton")
        ai_hide_button.setFixedSize(28, 28)
        ai_hide_button.setToolTip("Sembunyikan AI Assistant")
        ai_hide_button.clicked.connect(self.toggle_ai_panel)
        ai_header.addWidget(ai_hide_button)
        ai_layout.addLayout(ai_header)
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Hai, aku asistenmu. Aku bisa membantu melanjutkan cerita, memberi saran, dan memeriksa konsistensi.")
        ai_layout.addWidget(self.chat, 1)
        clear_chat_button = QPushButton("Bersihkan Chat")
        clear_chat_button.clicked.connect(self.clear_chat)
        ai_layout.addWidget(clear_chat_button)
        for label, prompt in [
            ("Lanjutkan adegan ini", "Lanjutkan adegan dari bagian akhir bab aktif. Jaga gaya dan konsistensi cerita."),
            ("Ubah gaya tulisan", "Berikan versi revisi dari bagian akhir naskah dengan gaya yang lebih kuat, tanpa mengubah fakta cerita."),
            ("Periksa konsistensi", "Periksa kemungkinan inkonsistensi berdasarkan konteks cerita yang tersedia."),
            ("Tanya tentang cerita", "Ringkas informasi penting yang relevan dari konteks cerita.")
        ]:
            quick = QPushButton(label)
            quick.clicked.connect(lambda checked=False, p=prompt: self.run_quick_prompt(p))
            ai_layout.addWidget(quick)
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Tanya asisten tentang ceritamu...")
        self.prompt.setMaximumHeight(105)
        ai_layout.addWidget(self.prompt)
        self.send_button = QPushButton("Kirim ke AI ➤")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.ask_ai)
        ai_layout.addWidget(self.send_button)
        insert_button = QPushButton("Masukkan jawaban ke naskah")
        insert_button.clicked.connect(self.insert_answer)
        ai_layout.addWidget(insert_button)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter = splitter
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(center)
        splitter.addWidget(ai_panel)
        splitter.setSizes([900, 360])

        root_layout.addWidget(sidebar)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self._last_splitter_sizes = [900, 360]
        self._focus_mode = False
        self._focus_ai_was_visible = True
        QShortcut(QKeySequence("Ctrl+Shift+A"), self, activated=self.toggle_ai_panel)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self.toggle_focus_mode)

    def toggle_ai_panel(self):
        """Tampilkan/sembunyikan AI tanpa mengubah panel lain."""
        if not hasattr(self, "ai_panel"):
            return
        if self.ai_panel.isVisible():
            sizes = self.main_splitter.sizes()
            if len(sizes) == 2 and sizes[1] > 0:
                self._last_splitter_sizes = sizes
            self.ai_panel.hide()
            self.ai_toggle_button.setText("Tampilkan AI")
            self.ai_toggle_button.setToolTip("Tampilkan AI Assistant (Ctrl+Shift+A)")
            visible_sizes = self.main_splitter.sizes()
            if len(visible_sizes) == 2:
                self.main_splitter.setSizes([visible_sizes[0] + visible_sizes[1], 0])
        else:
            self.ai_panel.show()
            self.ai_toggle_button.setText("Sembunyikan AI")
            self.ai_toggle_button.setToolTip("Sembunyikan AI Assistant (Ctrl+Shift+A)")
            sizes = self._last_splitter_sizes or [900, 360]
            self.main_splitter.setSizes(sizes)

    def toggle_focus_mode(self):
        """Mode menulis fokus; tombol header tetap tersedia untuk keluar."""
        if not hasattr(self, "main_splitter"):
            return
        if not self._focus_mode:
            sizes = self.main_splitter.sizes()
            if len(sizes) == 2:
                self._last_splitter_sizes = sizes
            self._focus_ai_was_visible = self.ai_panel.isVisible()
            self._focus_mode = True
            self.sidebar.hide()
            self.ai_panel.hide()
            self.focus_button.setText("Keluar Fokus")
            self.ai_toggle_button.setText("Tampilkan AI")
            self.main_splitter.setSizes([1, 0])
        else:
            self._focus_mode = False
            self.sidebar.show()
            if self._focus_ai_was_visible:
                self.ai_panel.show()
                self.ai_toggle_button.setText("Sembunyikan AI")
            else:
                self.ai_panel.hide()
                self.ai_toggle_button.setText("Tampilkan AI")
            self.main_splitter.setSizes(self._last_splitter_sizes or [900, 360])
            self.focus_button.setText("◉ Fokus")

    def add_nav_entry(self, key, label, section_key):
        button = QPushButton(label)
        button.setObjectName("navButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setCheckable(True)
        button.setAutoExclusive(False)
        button.clicked.connect(lambda checked=False, k=key: self.open_navigation_page(k))
        self.nav_buttons[key] = button
        add_button = self.nav_section_widgets.get(section_key + "_add")
        layout = self.nav_section_layouts[section_key]
        if add_button is not None:
            layout.insertWidget(layout.indexOf(add_button), button)
        else:
            layout.addWidget(button)
        return button

    def load_custom_category_navigation(self, side):
        with db() as conn:
            rows = conn.execute("SELECT id, section, name FROM custom_categories ORDER BY id").fetchall()
        for category_id, section, name in rows:
            key = f"custom_{category_id}"
            self.add_nav_entry(key, "  " + name, section)

    def add_custom_category(self, section):
        section_label = "Story Bible" if section == "story" else "World Bible"
        # Offer useful built-in category suggestions while still allowing custom names.
        defaults = (["Karakter", "Hubungan", "Konflik", "Alur Cerita", "Tema", "Lore", "Catatan"]
                    if section == "story" else
                    ["Lokasi", "Kelompok", "Item", "Konsep", "Sistem Kekuatan", "Aturan", "Sejarah", "Budaya", "Organisasi", "Makhluk", "Lore", "Lainnya"])
        dialog = QDialog(self)
        dialog.setWindowTitle("Tambah Kategori")
        dialog.setMinimumWidth(360)
        form = QVBoxLayout(dialog)
        form.addWidget(QLabel(f"Pilih kategori bawaan atau ketik kategori baru untuk {section_label}:"))
        category_combo = QComboBox()
        category_combo.setEditable(True)
        category_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        category_combo.addItems(defaults)
        category_combo.setCurrentText("")
        category_combo.setPlaceholderText("Pilih atau ketik nama kategori")
        form.addWidget(category_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = category_combo.currentText().strip()
        if not name:
            return
        try:
            with db() as conn:
                cur = conn.execute("INSERT INTO custom_categories (section, name) VALUES (?, ?)", (section, name))
                category_id = cur.lastrowid
        except sqlite3.IntegrityError:
            QMessageBox.information(self, "Kategori sudah ada", "Kategori dengan nama itu sudah ada di bagian ini.")
            return
        key = f"custom_{category_id}"
        self.data_titles[key] = (name, name, f"Kategori cerita buatanmu: {name}.")
        self.create_data_page(key, name, name, self.data_titles[key][2])
        self.add_nav_entry(key, "  " + name, section)
        self.open_navigation_page(key)

    def create_data_page(self, key, title, category, description):
        # Bible opens as a movable, non-modal window so the manuscript editor
        # remains visible and editable at the same time.
        page = QDialog(self, Qt.WindowType.Window)
        page.setWindowTitle(f"{title} — Stomake")
        page.resize(620, 680)
        page.setMinimumSize(480, 420)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        page_header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("heading")
        page_header.addWidget(heading)
        page_header.addStretch()
        add_btn = QPushButton("＋ Tambah " + category)
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(lambda checked=False, k=key: self.create_story_record(k))
        page_header.addWidget(add_btn)
        layout.addLayout(page_header)
        desc = QLabel(description)
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        search = QLineEdit()
        search.setPlaceholderText("Cari " + title.lower() + "...")
        search.textChanged.connect(lambda text, k=key: self.refresh_story_records(k))
        layout.addWidget(search)
        record_list = QListWidget()
        record_list.itemDoubleClicked.connect(lambda item, k=key: self.edit_story_record(k, item))
        record_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        record_list.customContextMenuRequested.connect(lambda pos, k=key: self.story_record_menu(k, pos))
        layout.addWidget(record_list, 1)
        actions = QHBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(lambda checked=False, k=key: self.edit_selected_story_record(k))
        delete_btn = QPushButton("Hapus")
        delete_btn.clicked.connect(lambda checked=False, k=key: self.delete_selected_story_record(k))
        actions.addWidget(edit_btn)
        actions.addWidget(delete_btn)
        actions.addStretch()
        layout.addLayout(actions)
        self.data_pages[key] = page
        self.data_lists[key] = record_list
        self.data_searches[key] = search

    # -------------------------
    # STORY BIBLE NAVIGATION / CRUD
    # -------------------------

    def open_navigation_page(self, key):
        if key in self.data_pages:
            self.save_current_chapter()
            self.refresh_story_records(key)
            page = self.data_pages[key]
            page.show()
            page.raise_()
            page.activateWindow()
            self.chapter_heading.setText(self.chapter_title or "Editor Cerita")
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)

    def refresh_story_records(self, kind):
        if kind not in self.data_lists or self.project_id is None:
            return
        query = self.data_searches[kind].text().strip() if kind in self.data_searches else ""
        with db() as conn:
            rows = conn.execute(
                "SELECT id, name, category, details, status FROM story_records "
                "WHERE project_id = ? AND kind = ? AND (name LIKE ? OR details LIKE ? OR category LIKE ? OR status LIKE ? OR metadata LIKE ?) "
                "ORDER BY id DESC",
                (self.project_id, kind, f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%")
            ).fetchall()
        widget = self.data_lists[kind]
        widget.clear()
        for record_id, name, category, details, status in rows:
            subtitle = " · ".join(x for x in (category, status) if x)
            item = QListWidgetItem(name + ("\n" + subtitle if subtitle else ""))
            item.setData(Qt.ItemDataRole.UserRole, record_id)
            item.setToolTip(details[:1000])
            widget.addItem(item)
        if not rows:
            widget.addItem(QListWidgetItem("Belum ada data. Klik tombol Tambah untuk membuat entri pertama."))

    def create_story_record(self, kind, record_id=None):
        if self.project_id is None:
            QMessageBox.information(self, "Stomake", "Buat atau pilih cerita terlebih dahulu.")
            return
        existing = None
        metadata = {}
        linked_chapter_ids = set()
        existing_relationships = []
        if record_id is not None:
            with db() as conn:
                existing = conn.execute(
                    "SELECT name, category, details, status, metadata FROM story_records WHERE id=? AND project_id=? AND kind=?",
                    (record_id, self.project_id, kind)
                ).fetchone()
                linked_chapter_ids = {r[0] for r in conn.execute(
                    "SELECT chapter_id FROM story_record_chapters WHERE record_id=?", (record_id,)
                ).fetchall()}
                if kind == "characters":
                    existing_relationships = conn.execute(
                        "SELECT cr.id, cr.relation, cr.notes, other.name, other.id "
                        "FROM character_relationships cr JOIN story_records other ON "
                        "other.id = CASE WHEN cr.source_id=? THEN cr.target_id ELSE cr.source_id END "
                        "WHERE cr.project_id=? AND (cr.source_id=? OR cr.target_id=?) ORDER BY other.name",
                        (record_id, self.project_id, record_id, record_id)
                    ).fetchall()
            if not existing:
                return
            try:
                metadata = json.loads(existing[4] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}

        title, category_default, _ = self.data_titles[kind]
        dialog = QDialog(self.data_pages.get(kind, self))
        dialog.setWindowTitle(("Edit " if existing else "Tambah ") + title)
        dialog.resize(720, 700)
        dialog.setMinimumSize(560, 500)
        dialog.setStyleSheet("""
            QDialog, QWidget { background-color: #17191f; color: #e8edf5; }
            QLabel { color: #e8edf5; background: transparent; }
            QLineEdit, QTextEdit, QComboBox, QListWidget {
                background-color: #242832; color: #f2f5fa;
                border: 1px solid #3d4655; border-radius: 5px; padding: 6px;
                selection-background-color: #087f8c; selection-color: #ffffff;
            }
            QComboBox QAbstractItemView {
                background-color: #242832; color: #f2f5fa;
                selection-background-color: #087f8c; selection-color: #ffffff;
            }
            QTabWidget::pane { border: 1px solid #3d4655; background-color: #17191f; }
            QTabBar::tab { background-color: #242832; color: #cbd5e1; padding: 7px 12px; border: 1px solid #3d4655; }
            QTabBar::tab:selected { background-color: #087f8c; color: #ffffff; }
            QPushButton { background-color: #2a303b; color: #f2f5fa; border: 1px solid #465164; border-radius: 5px; padding: 6px 10px; }
            QPushButton:hover { background-color: #374151; }
        """)
        outer = QVBoxLayout(dialog)
        tabs = QTabWidget()
        outer.addWidget(tabs, 1)

        basic_page = QWidget()
        basic_layout = QVBoxLayout(basic_page)
        form = QFormLayout()
        name_input = QLineEdit(existing[0] if existing else "")
        name_input.setPlaceholderText("Nama / judul entri")
        category_input = QComboBox()
        category_input.setEditable(True)
        category_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        category_defaults = ["Lokasi", "Kelompok", "Item", "Konsep", "Lore", "Aturan", "Sejarah", "Budaya", "Organisasi", "Lainnya"]
        if kind == "characters":
            category_defaults = ["Protagonis", "Antagonis", "Pendukung", "NPC", "Lainnya"]
        with db() as conn:
            saved_categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM story_records WHERE project_id=? AND kind=? AND category<>'' ORDER BY category", (self.project_id, kind)).fetchall()]
            saved_custom_categories = [r[0] for r in conn.execute("SELECT value FROM custom_options WHERE project_id IN (0, ?) AND field_key=? ORDER BY value", (self.project_id, f"category:{kind}")).fetchall()]
        for option in list(dict.fromkeys(category_defaults + saved_categories + saved_custom_categories)):
            category_input.addItem(option)
        category_input.setCurrentText(existing[1] if existing else category_default)
        category_input.setToolTip("Pilih kategori bawaan atau ketik kategori sendiri.")

        status_input = QComboBox()
        status_input.setEditable(True)
        status_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if kind == "characters":
            trait_defaults = ["Protagonis", "Antagonis", "Pendukung", "Manipulatif", "Ambisius", "Pemberani", "Pemalu", "Dingin", "Cerdas", "Setia", "Licik", "Humoris", "Introver", "Ekstrover"]
            status_input.setPlaceholderText("Pilih/ketik trait; pisahkan tiap trait dengan koma")
            status_label = "Trait karakter"
            option_key = "traits:characters"
        else:
            trait_defaults = ["Penting", "Rahasia", "Misterius", "Berbahaya", "Magis", "Terlarang", "Legendaris"]
            status_input.setPlaceholderText("Pilih/ketik tag; pisahkan dengan koma")
            status_label = "Tag / Status"
            option_key = f"tags:{kind}"
        with db() as conn:
            saved_statuses = [r[0] for r in conn.execute("SELECT DISTINCT status FROM story_records WHERE project_id=? AND kind=? AND status<>'' ORDER BY status", (self.project_id, kind)).fetchall()]
            custom_statuses = [r[0] for r in conn.execute("SELECT value FROM custom_options WHERE project_id IN (0, ?) AND field_key=? ORDER BY value", (self.project_id, option_key)).fetchall()]
        for option in list(dict.fromkeys(trait_defaults + saved_statuses + custom_statuses)):
            status_input.addItem(option)
        status_input.setCurrentText(existing[3] if existing else "")
        status_input.setToolTip("Bisa pilih saran atau ketik sendiri. Gunakan koma untuk beberapa trait/tag.")
        # When a comma is typed, remember everything before the current trait.
        # QComboBox replaces its edit text on activation, so restore the prefix ourselves.
        trait_state = {"prefix": "", "waiting": False}
        def show_next_trait_suggestions(text):
            if text.rstrip().endswith(","):
                trait_state["prefix"] = text.rstrip()[:-1].rstrip()
                trait_state["waiting"] = True
                QTimer.singleShot(0, status_input.showPopup)
            elif trait_state["waiting"] and text.strip():
                # The user started typing a custom next trait; stop treating it as a selection.
                trait_state["waiting"] = False
        status_input.lineEdit().textEdited.connect(show_next_trait_suggestions)
        def append_selected_trait(index):
            chosen = status_input.itemText(index).strip()
            if not chosen:
                return
            if trait_state["waiting"]:
                prefix = trait_state["prefix"]
                parts = [part.strip() for part in prefix.split(",") if part.strip()]
                if not parts or parts[-1].casefold() != chosen.casefold():
                    result = (prefix + ", " if prefix else "") + chosen + ", "
                else:
                    result = prefix + ", "
                status_input.setEditText(result)
                status_input.lineEdit().setCursorPosition(len(result))
                trait_state["waiting"] = True
                trait_state["prefix"] = result.rstrip()[:-1].rstrip()
                QTimer.singleShot(0, status_input.showPopup)
        status_input.activated.connect(append_selected_trait)
        def remember_custom_values(combo, field_key):
            raw = combo.currentText()
            values = [part.strip() for part in raw.split(",") if part.strip()]
            with db() as conn:
                for value in values:
                    try:
                        conn.execute("INSERT OR IGNORE INTO custom_options (project_id, field_key, value) VALUES (?, ?, ?)", (self.project_id, field_key, value))
                    except sqlite3.Error:
                        pass
        category_input.lineEdit().editingFinished.connect(lambda: remember_custom_values(category_input, f"category:{kind}"))
        status_input.lineEdit().editingFinished.connect(lambda: remember_custom_values(status_input, option_key))
        details_input = QTextEdit()
        details_input.setPlaceholderText("Deskripsi umum, catatan, rahasia, aturan, atau informasi lain...")
        details_input.setPlainText(existing[2] if existing else "")
        form.addRow("Nama / Judul", name_input)
        form.addRow("Kategori", category_input)
        form.addRow(status_label, status_input)
        basic_layout.addLayout(form)
        basic_layout.addWidget(QLabel("Deskripsi umum"))
        basic_layout.addWidget(details_input, 1)
        tabs.addTab(basic_page, "Umum")

        profile_inputs = {}
        if kind == "characters":
            profile_page = QWidget()
            profile_layout = QVBoxLayout(profile_page)
            profile_form = QFormLayout()
            profile_fields = [
                ("age", "Usia", "Contoh: 17 tahun"),
                ("appearance", "Penampilan", "Ciri fisik, pakaian, warna mata..."),
                ("personality", "Kepribadian", "Sifat dan cara berperilaku..."),
                ("background", "Latar belakang", "Sejarah hidup karakter..."),
                ("motivation", "Motivasi", "Apa yang mendorong karakter?"),
                ("goals_conflicts", "Tujuan & konflik", "Tujuan, hambatan, konflik pribadi..."),
                ("strengths_weaknesses", "Kelebihan & kelemahan", "Kemampuan dan kelemahan..."),
                ("development", "Perkembangan karakter", "Perubahan karakter sepanjang cerita..."),
                ("ai_notes", "Catatan untuk AI", "Fakta penting yang perlu dijaga AI...")
            ]
            for field_key, label, placeholder in profile_fields:
                edit = QTextEdit()
                edit.setPlaceholderText(placeholder)
                edit.setPlainText(str(metadata.get(field_key, "")))
                edit.setMaximumHeight(76 if field_key in ("age",) else 100)
                profile_inputs[field_key] = edit
                profile_form.addRow(label + ":", edit)
            profile_layout.addLayout(profile_form)
            tabs.addTab(profile_page, "Profil Karakter")

        links_page = QWidget()
        links_layout = QVBoxLayout(links_page)
        links_layout.addWidget(QLabel("Hubungkan entri ini dengan bab yang relevan:"))
        chapter_checks = []
        for chapter_row in get_chapters(self.project_id):
            chapter_id, chapter_title = chapter_row[0], chapter_row[1]
            check = QCheckBox(chapter_title)
            check.setProperty("chapter_id", chapter_id)
            check.setChecked(chapter_id in linked_chapter_ids)
            chapter_checks.append(check)
            links_layout.addWidget(check)
        if not chapter_checks:
            links_layout.addWidget(QLabel("Belum ada bab di proyek ini."))
        links_layout.addStretch(1)
        tabs.addTab(links_page, "Bab terkait")

        relation_list = None
        relation_target = None
        relation_label = None
        relation_notes = None
        relation_rows = []
        if kind == "characters":
            rel_page = QWidget()
            rel_layout = QVBoxLayout(rel_page)
            rel_layout.addWidget(QLabel("Hubungkan karakter dengan karakter lain. Simpan karakter ini dahulu jika masih baru."))
            relation_list = QListWidget()
            relation_list.setStyleSheet("""
                QListWidget { background-color: #20242d; color: #f2f5fa;
                    border: 1px solid #3d4655; border-radius: 5px; padding: 6px; }
                QListWidget::item { color: #f2f5fa; padding: 7px; }
                QListWidget::item:selected { background-color: #087f8c; color: #ffffff; }
            """)
            rel_page.setStyleSheet("QWidget { background-color: #17191f; color: #e8edf5; }")
            for rel_id, relation, notes, other_name, other_id in existing_relationships:
                item = QListWidgetItem(f"{name_input.text() or (existing[0] if existing else 'Karakter')} — {relation} — {other_name}" + (f"\n{notes}" if notes else ""))
                item.setData(Qt.ItemDataRole.UserRole, rel_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, other_id)
                relation_list.addItem(item)
            rel_layout.addWidget(relation_list, 1)
            rel_form = QFormLayout()
            relation_target = QComboBox()
            with db() as conn:
                others = conn.execute("SELECT id, name FROM story_records WHERE project_id=? AND kind='characters' AND id<>? ORDER BY name", (self.project_id, record_id or -1)).fetchall()
            for other_id, other_name in others:
                relation_target.addItem(other_name, other_id)
            relation_label = QLineEdit()
            relation_label.setPlaceholderText("Teman, musuh, keluarga, mentor...")
            relation_notes = QLineEdit()
            relation_notes.setPlaceholderText("Catatan hubungan (opsional)")
            rel_form.addRow("Karakter", relation_target)
            rel_form.addRow("Hubungan", relation_label)
            rel_form.addRow("Catatan", relation_notes)
            rel_layout.addLayout(rel_form)
            rel_actions = QHBoxLayout()
            add_rel = QPushButton("＋ Tambah hubungan")
            remove_rel = QPushButton("Hapus hubungan terpilih")
            rel_actions.addWidget(add_rel)
            rel_actions.addWidget(remove_rel)
            rel_layout.addLayout(rel_actions)
            def add_relationship_to_list():
                if record_id is None:
                    QMessageBox.information(dialog, "Simpan karakter dahulu", "Simpan karakter ini dahulu, lalu buka kembali untuk menambahkan hubungan.")
                    return
                target_id = relation_target.currentData()
                relation = relation_label.text().strip()
                if target_id is None or not relation:
                    QMessageBox.information(dialog, "Data belum lengkap", "Pilih karakter dan isi jenis hubungannya.")
                    return
                with db() as conn:
                    try:
                        cur = conn.execute("INSERT INTO character_relationships (project_id, source_id, target_id, relation, notes) VALUES (?, ?, ?, ?, ?)", (self.project_id, record_id, target_id, relation, relation_notes.text().strip()))
                        rel_id = cur.lastrowid
                    except sqlite3.IntegrityError:
                        QMessageBox.information(dialog, "Hubungan sudah ada", "Hubungan dengan label yang sama sudah tercatat.")
                        return
                target_name = relation_target.currentText()
                item = QListWidgetItem(f"{name_input.text()} — {relation} — {target_name}" + (f"\n{relation_notes.text().strip()}" if relation_notes.text().strip() else ""))
                item.setData(Qt.ItemDataRole.UserRole, rel_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, target_id)
                relation_list.addItem(item)
                relation_label.clear(); relation_notes.clear()
            def remove_relationship_from_list():
                item = relation_list.currentItem() if relation_list else None
                if item is None:
                    return
                rel_id = item.data(Qt.ItemDataRole.UserRole)
                if rel_id is not None:
                    with db() as conn:
                        conn.execute("DELETE FROM character_relationships WHERE id=? AND project_id=?", (rel_id, self.project_id))
                relation_list.takeItem(relation_list.row(item))
            add_rel.clicked.connect(add_relationship_to_list)
            remove_rel.clicked.connect(remove_relationship_from_list)
            tabs.addTab(rel_page, "Hubungan")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Simpan")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        outer.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Stomake", "Nama atau judul tidak boleh kosong.")
            return
        if kind == "characters":
            metadata = {key: edit.toPlainText().strip() for key, edit in profile_inputs.items()}
        else:
            metadata = {}
        with db() as conn:
            if record_id is None:
                cur = conn.execute(
                    "INSERT INTO story_records (project_id, kind, name, category, details, status, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.project_id, kind, name, category_input.currentText().strip(), details_input.toPlainText(), status_input.currentText().strip(), json.dumps(metadata, ensure_ascii=False))
                )
                record_id = cur.lastrowid
            else:
                conn.execute(
                    "UPDATE story_records SET name=?, category=?, details=?, status=?, metadata=? WHERE id=? AND project_id=? AND kind=?",
                    (name, category_input.currentText().strip(), details_input.toPlainText(), status_input.currentText().strip(), json.dumps(metadata, ensure_ascii=False), record_id, self.project_id, kind)
                )
            # Replace chapter associations with the currently checked chapters.
            conn.execute("DELETE FROM story_record_chapters WHERE record_id=?", (record_id,))
            for check in chapter_checks:
                if check.isChecked():
                    conn.execute("INSERT OR IGNORE INTO story_record_chapters (record_id, chapter_id) VALUES (?, ?)", (record_id, check.property("chapter_id")))
        self.refresh_story_records(kind)
        self.save_label.setText("● " + title + " tersimpan")

    def edit_story_record(self, kind, item):
        if item is None:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        if record_id is not None:
            self.create_story_record(kind, record_id)

    def edit_selected_story_record(self, kind):
        self.edit_story_record(kind, self.data_lists[kind].currentItem())

    def delete_selected_story_record(self, kind):
        item = self.data_lists[kind].currentItem()
        record_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if record_id is None:
            return
        title = self.data_titles[kind][0]
        answer = QMessageBox.question(self, "Hapus entri", f"Hapus entri ini dari {title}?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        with db() as conn:
            conn.execute("DELETE FROM story_records WHERE id=? AND project_id=? AND kind=?", (record_id, self.project_id, kind))
        self.refresh_story_records(kind)

    def story_record_menu(self, kind, pos):
        item = self.data_lists[kind].itemAt(pos)
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        menu = QMenu(self)
        edit_action = menu.addAction("Edit")
        delete_action = menu.addAction("Hapus")
        action = menu.exec(self.data_lists[kind].mapToGlobal(pos))
        if action == edit_action:
            self.edit_story_record(kind, item)
        elif action == delete_action:
            self.data_lists[kind].setCurrentItem(item)
            self.delete_selected_story_record(kind)

    # -------------------------
    # PROJECT MANAGEMENT
    # -------------------------

    def load_projects(self, select_id=None):
        self.loading = True
        self.project_combo.clear()
        projects = get_projects()

        for project_id, title in projects:
            self.project_combo.addItem(title, project_id)

        target_id = select_id
        if target_id is None and projects:
            target_id = projects[0][0]

        index = self.project_combo.findData(target_id)
        if index >= 0:
            self.project_combo.setCurrentIndex(index)

        self.loading = False

        if target_id is not None:
            self.open_project(target_id)

    def on_project_changed(self, index):
        if self.loading or index < 0:
            return
        project_id = self.project_combo.currentData()
        if project_id is not None:
            self.open_project(project_id)

    def open_project(self, project_id):
        self.save_current_chapter()
        self.project_id = project_id
        self.project_title = self.project_combo.currentText()
        self.load_chapters()
        self.refresh_context_lists()
        if hasattr(self, "center_stack"):
            self.center_stack.setCurrentWidget(self.chapter_page)
            self.reference_record_kind = None
            self.reference_record_id = None
            self.hide_reference_panel()

    def new_project(self):
        title, ok = QInputDialog.getText(
            self, "Cerita Baru", "Judul cerita:"
        )
        if not ok or not title.strip():
            return
        project_id = create_project(title.strip())
        self.load_projects(project_id)

    def show_project_menu(self, pos):
        """Menu klik kanan pada pemilih cerita."""
        if self.project_id is None:
            return
        menu = QMenu(self)
        rename_action = menu.addAction("✎ Ubah Judul Cerita")
        delete_action = menu.addAction("⌫ Hapus Cerita")
        chosen = menu.exec(self.project_combo.mapToGlobal(pos))
        if chosen == rename_action:
            self.rename_project()
        elif chosen == delete_action:
            self.delete_project()

    def delete_project(self):
        if self.project_id is None:
            return

        projects = get_projects()
        if len(projects) <= 1:
            QMessageBox.information(
                self, "Stomake",
                "Cerita terakhir tidak bisa dihapus. Buat cerita baru terlebih dahulu."
            )
            return

        title = self.project_title
        answer = QMessageBox.question(
            self, "Hapus Cerita",
            f"Yakin ingin menghapus cerita '{title}'?\n\n"
            "Semua bab, karakter, dan latar dalam cerita ini juga akan dihapus.\n"
            "Tindakan ini tidak bisa dibatalkan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.save_current_chapter()
        deleting_id = self.project_id
        with db() as conn:
            conn.execute("DELETE FROM chapters WHERE project_id = ?", (deleting_id,))
            conn.execute("DELETE FROM characters WHERE project_id = ?", (deleting_id,))
            conn.execute("DELETE FROM worldbuilding WHERE project_id = ?", (deleting_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (deleting_id,))

        remaining = get_projects()
        if remaining:
            self.load_projects(remaining[0][0])

    def rename_project(self):
        if self.project_id is None:
            return
        title, ok = QInputDialog.getText(
            self, "Ubah Judul Cerita", "Judul baru:",
            text=self.project_title
        )
        if not ok or not title.strip():
            return

        with db() as conn:
            conn.execute(
                "UPDATE projects SET title = ? WHERE id = ?",
                (title.strip(), self.project_id)
            )

        self.project_title = title.strip()
        self.loading = True
        index = self.project_combo.findData(self.project_id)
        if index >= 0:
            self.project_combo.setItemText(index, self.project_title)
        self.loading = False
        self.save_label.setText("● Judul cerita disimpan")

    # -------------------------
    # EXPORT CERITA
    # -------------------------

    def show_export_menu(self):
        menu = QMenu(self)
        word_action = menu.addAction("Export Word (.docx)")
        docs_action = menu.addAction("Export untuk Google Docs…")
        chosen = menu.exec(self.mapToGlobal(self.rect().center()))
        if chosen == word_action:
            self.export_cerita(open_google_docs=False)
        elif chosen == docs_action:
            self.export_cerita(open_google_docs=True)

    def export_cerita(self, open_google_docs=False):
        if self.project_id is None:
            QMessageBox.warning(self, "Export Cerita", "Pilih cerita terlebih dahulu.")
            return

        # Pastikan isi bab aktif tersimpan sebelum membaca semua bab dari database.
        self.save_current_chapter()
        safe_title = "".join(c for c in self.project_title if c not in '<>:\"/\\|?*').strip()
        safe_title = safe_title or "Cerita Stomake"
        default_path = str(Path.home() / f"{safe_title}.docx")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Cerita ke Word" if not open_google_docs else "Siapkan Cerita untuk Google Docs",
            default_path,
            "Dokumen Word (*.docx)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".docx"):
            file_path += ".docx"

        try:
            from docx import Document
            from docx.shared import Inches, Pt
        except ImportError:
            QMessageBox.warning(
                self, "Library belum tersedia",
                "Fitur export Word membutuhkan python-docx.\n\n"
                "Buka Command Prompt di folder Stomake lalu jalankan:\n"
                "py -m pip install python-docx"
            )
            return

        try:
            with db() as conn:
                project = conn.execute(
                    "SELECT title FROM projects WHERE id = ?", (self.project_id,)
                ).fetchone()
                chapters = conn.execute(
                    "SELECT title, content FROM chapters WHERE project_id = ? ORDER BY position, id",
                    (self.project_id,)
                ).fetchall()
                characters = conn.execute(
                    "SELECT name, role, details FROM characters WHERE project_id = ? ORDER BY role, name",
                    (self.project_id,)
                ).fetchall()
                lore_entries = conn.execute(
                    "SELECT name, category, details FROM worldbuilding WHERE project_id = ? ORDER BY category, name",
                    (self.project_id,)
                ).fetchall()

            if not project:
                QMessageBox.warning(self, "Export Cerita", "Cerita tidak ditemukan.")
                return

            document = Document()
            styles = document.styles
            styles["Normal"].font.name = "Times New Roman"
            styles["Normal"].font.size = Pt(12)
            section = document.sections[0]
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1.25)
            section.right_margin = Inches(1)

            document.add_heading(project[0], level=0)
            document.add_paragraph("")
            for index, (chapter_title, content) in enumerate(chapters):
                if index > 0:
                    document.add_page_break()
                document.add_heading(chapter_title, level=1)
                # Preserve paragraph breaks in the editor's plain text.
                paragraphs = (content or "").replace("\r\n", "\n").split("\n")
                for paragraph in paragraphs:
                    document.add_paragraph(paragraph)

            # Tambahkan lampiran karakter dan lore/worldbuilding setelah semua bab.
            document.add_page_break()
            document.add_heading("Karakter", level=1)
            if characters:
                for character_name, role, details in characters:
                    document.add_heading(character_name, level=2)
                    document.add_paragraph(f"Role: {role or 'Karakter Pendukung'}")
                    for paragraph in (details or "").replace("\r\n", "\n").split("\n"):
                        document.add_paragraph(paragraph)
            else:
                document.add_paragraph("Belum ada data karakter.")

            document.add_page_break()
            document.add_heading("Lore dan Worldbuilding", level=1)
            if lore_entries:
                for lore_name, category, details in lore_entries:
                    heading = f"{lore_name} ({category})" if category else lore_name
                    document.add_heading(heading, level=2)
                    for paragraph in (details or "").replace("\r\n", "\n").split("\n"):
                        document.add_paragraph(paragraph)
            else:
                document.add_paragraph("Belum ada data lore/worldbuilding.")

            document.save(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Export gagal", f"Dokumen tidak bisa dibuat.\n\n{exc}")
            return

        if open_google_docs:
            # Google Docs needs a signed-in Google account to import the generated DOCX.
            QDesktopServices.openUrl(QUrl("https://docs.google.com/document/u/0/"))
            QMessageBox.information(
                self, "Dokumen siap untuk Google Docs",
                "Cerita berhasil diekspor sebagai file Word (.docx).\n\n"
                "Google Docs sudah dibuka. Di Google Docs, pilih pembuka file, lalu upload/pilih file\n"
                f"ini:\n{file_path}\n\n"
                "Stomake tidak mengunggah otomatis ke akun Google; untuk itu diperlukan koneksi dan izin Google API."
            )
        else:
            QMessageBox.information(
                self, "Export berhasil",
                f"Cerita berhasil diekspor, termasuk {len(chapters)} bab, {len(characters)} karakter, "
                f"dan {len(lore_entries)} data lore/worldbuilding.\n\n{file_path}"
            )

    # -------------------------
    # CHAPTER MANAGEMENT
    # -------------------------

    def load_chapters(self, select_id=None):
        self.loading = True
        self.chapter_list.clear()

        chapters = get_chapters(self.project_id)
        for chapter_id, title, content, position in chapters:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, chapter_id)
            self.chapter_list.addItem(item)

        target_row = 0
        if select_id is not None:
            for i in range(self.chapter_list.count()):
                if self.chapter_list.item(i).data(
                    Qt.ItemDataRole.UserRole
                ) == select_id:
                    target_row = i
                    break

        if self.chapter_list.count():
            self.chapter_list.setCurrentRow(target_row)
        else:
            self.chapter_id = None
            self.chapter_title = ""
            self.editor.clear()

        self.loading = False

        item = self.chapter_list.currentItem()
        if item:
            self.open_chapter(item.data(Qt.ItemDataRole.UserRole))

    def on_chapter_changed(self, current, previous):
        if self.loading:
            return
        if previous is not None:
            previous_id = previous.data(Qt.ItemDataRole.UserRole)
            if previous_id == self.chapter_id:
                self.save_current_chapter()
        if current is not None:
            self.open_chapter(current.data(Qt.ItemDataRole.UserRole))

    def open_chapter(self, chapter_id):
        if chapter_id == self.chapter_id:
            # Klik bab aktif juga bisa dipakai untuk kembali dari halaman karakter/latar.
            if hasattr(self, "center_stack") and self.center_stack.currentWidget() is self.record_page:
                if self.save_record_form(return_to_cerita=False):
                    self.center_stack.setCurrentWidget(self.chapter_page)
                    self.chapter_heading.setText(self.chapter_title or "Editor Cerita")
            return

        self.save_current_chapter()
        if hasattr(self, "center_stack") and self.center_stack.currentWidget() is self.record_page:
            self.save_record_form(return_to_cerita=False)
            self.center_stack.setCurrentWidget(self.chapter_page)

        with db() as conn:
            row = conn.execute("""
                SELECT title, content, content_html FROM chapters
                WHERE id = ? AND project_id = ?
            """, (chapter_id, self.project_id)).fetchone()

        if row is None:
            return

        self.chapter_id = chapter_id
        self.chapter_title, content, content_html = row

        self.loading = True
        if content_html:
            self.editor.setHtml(content_html)
        else:
            self.editor.setPlainText(content or "")
        self.loading = False
        self.update_format_indicators()

        self.chapter_heading.setText(self.chapter_title)
        if hasattr(self, "center_stack"):
            self.center_stack.setCurrentWidget(self.chapter_page)
        self.update_word_count()
        self.save_label.setText("● Bab dimuat")

    def new_chapter(self):
        if self.project_id is None:
            return
        title, ok = QInputDialog.getText(
            self, "Bab Baru", "Judul bab:"
        )
        if not ok or not title.strip():
            return
        self.save_current_chapter()
        chapter_id = create_chapter(self.project_id, title.strip())
        self.load_chapters(chapter_id)

    def show_chapter_menu(self, pos):
        item = self.chapter_list.itemAt(pos)
        menu = QMenu(self)
        add_action = menu.addAction("＋ Bab Baru")
        rename_action = menu.addAction("✎ Ubah Judul Bab")
        delete_action = menu.addAction("⌫ Hapus Bab")
        rename_action.setEnabled(item is not None)
        delete_action.setEnabled(item is not None)
        chosen = menu.exec(self.chapter_list.mapToGlobal(pos))
        if chosen == add_action:
            self.new_chapter()
        elif chosen == rename_action and item is not None:
            row = self.chapter_list.row(item)
            self.chapter_list.setCurrentRow(row)
            self.rename_chapter()
        elif chosen == delete_action and item is not None:
            self.delete_chapter(item)

    def delete_chapter(self, item=None):
        if item is None:
            item = self.chapter_list.currentItem()
        if item is None or self.project_id is None:
            return

        chapter_id = item.data(Qt.ItemDataRole.UserRole)
        chapter_title = item.text()
        answer = QMessageBox.question(
            self, "Hapus Bab",
            f"Yakin ingin menghapus bab '{chapter_title}'?\n\n"
            "Isi bab ini akan dihapus permanen.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        # Simpan bab aktif terlebih dahulu, lalu hapus bab yang dipilih.
        self.save_current_chapter()
        with db() as conn:
            conn.execute(
                "DELETE FROM chapters WHERE id = ? AND project_id = ?",
                (chapter_id, self.project_id)
            )

        self.chapter_id = None
        self.chapter_title = ""
        self.loading = True
        self.editor.clear()
        self.chapter_list.clearSelection()
        self.loading = False
        self.load_chapters()
        self.save_label.setText("● Bab dihapus")

    def rename_chapter(self):
        if self.chapter_id is None:
            return
        title, ok = QInputDialog.getText(
            self, "Ubah Judul Bab", "Judul baru:",
            text=self.chapter_title
        )
        if not ok or not title.strip():
            return

        self.chapter_title = title.strip()
        self.chapter_heading.setText(self.chapter_title)

        item = self.chapter_list.currentItem()
        if item:
            item.setText(self.chapter_title)

        self.save_current_chapter()

    def save_current_chapter(self):
        if self.loading or self.chapter_id is None:
            return
        try:
            save_chapter(
                self.chapter_id,
                self.chapter_title,
                self.editor.toPlainText(),
                self.editor.toHtml()
            )
            self.save_label.setText("● Tersimpan lokal")
        except sqlite3.Error as error:
            self.save_label.setText("● Gagal menyimpan")
            print("Database error:", error)

    def toggle_format_shortcut(self, key):
        """Toggle inline formatting from the keyboard without relying on toolbar focus."""
        if key not in self.format_buttons:
            return
        current = self.editor.currentCharFormat()
        if key == "bold":
            enabled = current.fontWeight() < 600
        elif key == "italic":
            enabled = not current.fontItalic()
        elif key == "underline":
            enabled = not current.fontUnderline()
        else:
            enabled = not current.fontStrikeOut()
        self.format_buttons[key].setChecked(enabled)
        self.apply_format(key)

    def apply_format(self, key):
        """Apply rich-text formatting to the selection or current typing position."""
        if key in ("bold", "italic", "underline", "strike"):
            fmt = QTextCharFormat()
            if key == "bold":
                fmt.setFontWeight(700 if self.format_buttons[key].isChecked() else 400)
            elif key == "italic":
                fmt.setFontItalic(self.format_buttons[key].isChecked())
            elif key == "underline":
                fmt.setFontUnderline(self.format_buttons[key].isChecked())
            elif key == "strike":
                fmt.setFontStrikeOut(self.format_buttons[key].isChecked())
            self.editor.mergeCurrentCharFormat(fmt)
        elif key in ("bullet", "number"):
            cursor = self.editor.textCursor()
            current_list = cursor.currentList()
            want_checked = self.format_buttons[key].isChecked()
            if current_list is not None and not want_checked:
                current_list.remove(cursor.block())
            else:
                list_format = QTextListFormat()
                list_format.setStyle(
                    QTextListFormat.Style.ListDisc if key == "bullet"
                    else QTextListFormat.Style.ListDecimal
                )
                cursor.createList(list_format)
            self.editor.setTextCursor(cursor)
        self.update_format_indicators()
        self.editor.setFocus()

    def apply_alignment(self, key):
        alignments = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
            "justify": Qt.AlignmentFlag.AlignJustify,
        }
        alignment = alignments.get(key)
        if alignment is not None:
            self.editor.setAlignment(alignment)
        self.update_format_indicators()
        self.editor.setFocus()

    def apply_font_family(self, family):
        """Apply the selected font family to selected text or future typing."""
        if not family or not hasattr(self, "editor") or getattr(self, "loading", False):
            return
        fmt = QTextCharFormat()
        fmt.setFont(QFont(family))
        self.editor.mergeCurrentCharFormat(fmt)
        self.editor.setFocus()

    def apply_font_size(self, *_):
        raw_size = self.font_size_combo.currentText().strip()
        try:
            size = float(raw_size)
            if not 6 <= size <= 200:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Ukuran font tidak valid", "Masukkan ukuran font antara 6 sampai 200 pt.")
            self.update_format_indicators()
            self.editor.setFocus()
            return
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self.editor.mergeCurrentCharFormat(fmt)
        self.update_format_indicators()
        self.editor.setFocus()

    def update_format_indicators(self):
        if not hasattr(self, "format_buttons") or not hasattr(self, "editor"):
            return
        fmt = self.editor.currentCharFormat()
        cursor = self.editor.textCursor()
        current_list = cursor.currentList()
        states = {
            "bold": fmt.fontWeight() >= 600,
            "italic": fmt.fontItalic(),
            "underline": fmt.fontUnderline(),
            "strike": fmt.fontStrikeOut(),
            "bullet": current_list is not None and current_list.format().style() == QTextListFormat.Style.ListDisc,
            "number": current_list is not None and current_list.format().style() == QTextListFormat.Style.ListDecimal,
        }
        for key, button in self.format_buttons.items():
            button.blockSignals(True)
            button.setChecked(states.get(key, False))
            button.blockSignals(False)

        if hasattr(self, "alignment_buttons"):
            alignment = cursor.blockFormat().alignment()
            align_states = {
                "left": bool(alignment & Qt.AlignmentFlag.AlignLeft),
                "center": bool(alignment & Qt.AlignmentFlag.AlignHCenter),
                "right": bool(alignment & Qt.AlignmentFlag.AlignRight),
                "justify": bool(alignment & Qt.AlignmentFlag.AlignJustify),
            }
            # Qt may report a default/zero alignment for a left-aligned paragraph.
            if not any(align_states.values()):
                align_states["left"] = True
            for key, button in self.alignment_buttons.items():
                button.blockSignals(True)
                button.setChecked(align_states[key])
                button.blockSignals(False)

        if hasattr(self, "font_family_combo"):
            # Read the font through QFont instead of the deprecated
            # QTextCharFormat.fontFamily() API. Avoid resetting the native
            # font combo on every cursor movement when the selection is unchanged.
            family = fmt.font().family()
            if family and self.font_family_combo.findText(family) >= 0 and self.font_family_combo.currentText() != family:
                self.font_family_combo.blockSignals(True)
                try:
                    self.font_family_combo.setCurrentText(family)
                finally:
                    self.font_family_combo.blockSignals(False)

        if hasattr(self, "font_size_combo"):
            size = fmt.fontPointSize()
            if size > 0:
                size_text = str(int(size) if float(size).is_integer() else size)
                if self.font_size_combo.currentText() != size_text:
                    self.font_size_combo.blockSignals(True)
                    try:
                        self.font_size_combo.setCurrentText(size_text)
                    finally:
                        self.font_size_combo.blockSignals(False)

    def update_word_count(self):
        text = self.editor.toPlainText().strip()
        count = len(text.split()) if text else 0
        self.word_label.setText(f"{count:,} kata")

    # -------------------------
    # CHARACTER & WORLDBUILDING
    # -------------------------

    def refresh_context_lists(self):
        if not hasattr(self, "character_list") or not hasattr(self, "world_list") or self.project_id is None:
            return
        self.character_list.clear()
        self.world_list.clear()
        with db() as conn:
            chars = conn.execute("SELECT id, name, role, details FROM characters WHERE project_id = ? ORDER BY role, name", (self.project_id,)).fetchall()
            worlds = conn.execute("SELECT id, name, category, details FROM worldbuilding WHERE project_id = ? ORDER BY category, name", (self.project_id,)).fetchall()
        # Kelompokkan karakter berdasarkan role, serupa dengan pengelompokan latar.
        current_role = None
        for record_id, name, role, details in chars:
            role = role or "Karakter Pendukung"
            if role != current_role:
                current_role = role
                header = QListWidgetItem(role.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setData(Qt.ItemDataRole.UserRole, None)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                # Warna judul kelompok dibuat terang agar jelas di tema gelap.
                header.setForeground(QColor("#c3b8ff"))
                self.character_list.addItem(header)
            item = QListWidgetItem("   " + name)
            item.setData(Qt.ItemDataRole.UserRole, record_id)
            item.setToolTip(f"Role: {role}\nKlik dua kali untuk membuka halaman karakter")
            self.character_list.addItem(item)

        # Kelompokkan latar berdasarkan kategori supaya daftar panjang tetap rapi.
        current_category = None
        for record_id, name, category, details in worlds:
            if category != current_category:
                current_category = category
                header = QListWidgetItem(category.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setData(Qt.ItemDataRole.UserRole, None)
                # Gunakan warna terang yang sama dengan judul kelompok karakter.
                header.setForeground(QColor("#c3b8ff"))
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                self.world_list.addItem(header)
            item = QListWidgetItem("   " + name)
            item.setData(Qt.ItemDataRole.UserRole, record_id)
            item.setToolTip("Klik dua kali untuk membuka halaman latar")
            self.world_list.addItem(item)

        if getattr(self, "reference_record_id", None) is not None:
            self.show_reference_for_active_record()

    def add_record(self, kind):
        if self.project_id is None:
            QMessageBox.information(self, "Stomake", "Pilih atau buat cerita terlebih dahulu.")
            return
        self.open_record_window(kind)

    def edit_record_from_item(self, kind, item):
        if item is None or self.project_id is None:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        if record_id is None:
            return
        self.open_record_window(kind, record_id)

    def open_record_window(self, kind, record_id=None):
        """Buka editor karakter/latar sebagai jendela mengambang non-modal.

        Jendela dapat dipindahkan, diubah ukurannya, diminimalkan, dan tetap
        membiarkan pengguna mengetik di editor cerita di belakangnya.
        """
        if kind not in ("characters", "worldbuilding") or self.project_id is None:
            return

        key = (self.project_id, kind, record_id)
        existing = self.record_windows.get(key)
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.showNormal()
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                pass

        is_character = kind == "characters"
        record = None
        if record_id is not None:
            with db() as conn:
                if is_character:
                    record = conn.execute(
                        "SELECT name, role, details FROM characters WHERE id = ? AND project_id = ?",
                        (record_id, self.project_id)
                    ).fetchone()
                else:
                    record = conn.execute(
                        "SELECT name, category, details FROM worldbuilding WHERE id = ? AND project_id = ?",
                        (record_id, self.project_id)
                    ).fetchone()
            if not record:
                return

        window = QDialog(self, Qt.WindowType.Window)
        window.setWindowTitle(("Karakter" if is_character else "Latar / Worldbuilding") + (f" — {record[0]}" if record else " — Baru"))
        window.resize(520, 560)
        window.setMinimumSize(380, 360)
        window.setModal(False)
        layout = QVBoxLayout(window)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        form = QFormLayout()
        name_input = QLineEdit(record[0] if record else "")
        name_input.setPlaceholderText("Nama karakter atau latar")
        form.addRow("Nama:", name_input)

        role_input = None
        category_input = None
        if is_character:
            role_input = QComboBox()
            role_input.setEditable(True)
            role_input.addItems([
                "Protagonis", "Antagonis", "Deuteragonis", "Tritagonis",
                "Karakter Pendukung", "Mentor", "Love Interest", "Sidekick",
                "Figuran", "Lainnya"
            ])
            role_input.setCurrentText((record[1] if record else "Karakter Pendukung") or "Karakter Pendukung")
            role_input.setToolTip("Pilih role atau ketik role buatan sendiri")
            form.addRow("Role:", role_input)
        else:
            category_input = QComboBox()
            category_input.setEditable(True)
            category_input.addItems(["Lore", "Lokasi", "Faksi", "Sistem Kekuatan", "Benda", "Sejarah", "Lainnya"])
            category_input.setCurrentText((record[1] if record else "Lore") or "Lore")
            form.addRow("Kategori:", category_input)

        layout.addLayout(form)
        layout.addWidget(QLabel("Detail / Deskripsi:"))
        details_input = QTextEdit()
        details_input.setPlaceholderText("Tulis detail karakter atau latar di sini...")
        details_input.setPlainText((record[2] if record else "") or "")
        layout.addWidget(details_input, 1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        save_button = QPushButton("Simpan")
        save_button.setObjectName("primary")
        close_button = QPushButton("Tutup")
        button_row.addWidget(close_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

        key_holder = [key]

        def save_record():
            nonlocal record_id
            name = name_input.text().strip()
            if not name:
                QMessageBox.warning(window, "Stomake", "Nama tidak boleh kosong.")
                name_input.setFocus()
                return
            details = details_input.toPlainText().strip()
            with db() as conn:
                if is_character:
                    role = role_input.currentText().strip() or "Karakter Pendukung"
                    if record_id is None:
                        cur = conn.execute(
                            "INSERT INTO characters (project_id, name, role, details) VALUES (?, ?, ?, ?)",
                            (self.project_id, name, role, details)
                        )
                        record_id = cur.lastrowid
                    else:
                        conn.execute(
                            "UPDATE characters SET name = ?, role = ?, details = ? WHERE id = ? AND project_id = ?",
                            (name, role, details, record_id, self.project_id)
                        )
                else:
                    category = category_input.currentText().strip() or "Lore"
                    if record_id is None:
                        cur = conn.execute(
                            "INSERT INTO worldbuilding (project_id, name, category, details) VALUES (?, ?, ?, ?)",
                            (self.project_id, name, category, details)
                        )
                        record_id = cur.lastrowid
                    else:
                        conn.execute(
                            "UPDATE worldbuilding SET name = ?, category = ?, details = ? WHERE id = ? AND project_id = ?",
                            (name, category, details, record_id, self.project_id)
                        )
            # Sesuaikan judul jendela sesudah penyimpanan; daftar terkelompok ikut diperbarui.
            window.setWindowTitle(("Karakter" if is_character else "Latar / Worldbuilding") + f" — {name}")
            # Jendela tambah berubah menjadi jendela edit setelah record pertama disimpan.
            new_key = (self.project_id, kind, record_id)
            if key_holder[0] != new_key:
                self.record_windows.pop(key_holder[0], None)
                self.record_windows[new_key] = window
                key_holder[0] = new_key
            self.refresh_context_lists()
            self.save_label.setText("● Data karakter/latar tersimpan")

        save_button.clicked.connect(save_record)
        close_button.clicked.connect(window.close)
        window.finished.connect(lambda _result: self.record_windows.pop(key_holder[0], None))
        self.record_windows[key] = window
        window.show()
        window.raise_()
        window.activateWindow()

    def save_record_form(self, return_to_cerita=False):
        if self.project_id is None or self.active_records_kind not in ("characters", "worldbuilding"):
            return False
        name = self.record_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Stomake", "Nama tidak boleh kosong.")
            self.record_name_input.setFocus()
            return False

        details = self.record_details_input.toPlainText()
        is_character = self.active_records_kind == "characters"
        category = self.record_category_input.currentText().strip() or "Lore"
        role = self.record_role_input.currentText().strip() or "Karakter Pendukung"
        with db() as conn:
            if is_character:
                if self.active_record_id is None:
                    cur = conn.execute(
                        "INSERT INTO characters (project_id, name, role, details) VALUES (?, ?, ?, ?)",
                        (self.project_id, name, role, details)
                    )
                    self.active_record_id = cur.lastrowid
                else:
                    conn.execute(
                        "UPDATE characters SET name = ?, role = ?, details = ? WHERE id = ? AND project_id = ?",
                        (name, role, details, self.active_record_id, self.project_id)
                    )
            else:
                if self.active_record_id is None:
                    cur = conn.execute(
                        "INSERT INTO worldbuilding (project_id, name, category, details) VALUES (?, ?, ?, ?)",
                        (self.project_id, name, category, details)
                    )
                    self.active_record_id = cur.lastrowid
                else:
                    conn.execute(
                        "UPDATE worldbuilding SET name = ?, details = ?, category = ? WHERE id = ? AND project_id = ?",
                        (name, details, category, self.active_record_id, self.project_id)
                    )

        self.record_page_heading.setText(("Karakter: " if is_character else "Latar: ") + name)
        self.chapter_heading.setText(self.record_page_heading.text())
        self.refresh_context_lists()
        self.save_label.setText("● Data karakter/latar tersimpan")
        if return_to_cerita:
            self.reference_record_kind = self.active_records_kind
            self.reference_record_id = self.active_record_id
            self.show_reference_for_active_record()
            self.center_stack.setCurrentWidget(self.chapter_page)
            self.chapter_heading.setText(self.chapter_title or "Editor Cerita")
        return True

    def minimize_record_page(self):
        # Form tambah yang masih kosong boleh ditutup tanpa membuat data kosong.
        if self.active_record_id is None and not self.record_name_input.text().strip():
            self.center_stack.setCurrentWidget(self.chapter_page)
            self.chapter_heading.setText(self.chapter_title or "Editor Cerita")
            self.active_records_kind = None
            self.active_record_id = None
            return
        # Simpan sebelum mengecilkan halaman agar perubahan tidak hilang.
        self.save_record_form(return_to_cerita=True)

    def restore_reference_page(self):
        """Buka kembali halaman edit dari panel referensi yang sedang diminimize."""
        kind = self.reference_record_kind
        record_id = self.reference_record_id
        if kind not in ("characters", "worldbuilding") or record_id is None:
            return
        is_character = kind == "characters"
        with db() as conn:
            if is_character:
                row = conn.execute(
                    "SELECT name, details, role FROM characters WHERE id = ? AND project_id = ?",
                    (record_id, self.project_id)
                ).fetchone()
                category = None
                role = row[2] if row else "Karakter Pendukung"
            else:
                row = conn.execute(
                    "SELECT name, details, category FROM worldbuilding WHERE id = ? AND project_id = ?",
                    (record_id, self.project_id)
                ).fetchone()
                category = row[2] if row else "Lore"
                role = "Karakter Pendukung"
        if not row:
            self.hide_reference_panel()
            return
        self.active_records_kind = kind
        self.active_record_id = record_id
        self.record_name_input.setText(row[0])
        self.record_details_input.setPlainText(row[1] or "")
        self.record_page_heading.setText(("Karakter: " if is_character else "Latar: ") + row[0])
        self.record_role_label.setVisible(is_character)
        self.record_role_input.setVisible(is_character)
        self.record_category_label.setVisible(not is_character)
        self.record_category_input.setVisible(not is_character)
        if is_character:
            self.record_role_input.setCurrentText(role or "Karakter Pendukung")
        else:
            self.record_category_input.setCurrentText(category or "Lore")
        self.center_stack.setCurrentWidget(self.record_page)
        self.chapter_heading.setText(self.record_page_heading.text())

    def show_reference_for_active_record(self):
        if self.reference_record_kind not in ("characters", "worldbuilding") or self.reference_record_id is None:
            return
        is_character = self.reference_record_kind == "characters"
        with db() as conn:
            if is_character:
                row = conn.execute(
                    "SELECT name, details, role FROM characters WHERE id = ? AND project_id = ?",
                    (self.reference_record_id, self.project_id)
                ).fetchone()
                category = None
                role = row[2] if row else "Karakter Pendukung"
            else:
                row = conn.execute(
                    "SELECT name, details, category FROM worldbuilding WHERE id = ? AND project_id = ?",
                    (self.reference_record_id, self.project_id)
                ).fetchone()
                category = row[2] if row else None
        if not row:
            return
        name, details = row[0], row[1] or ""
        heading_prefix = f"{role or 'Karakter Pendukung'}: " if is_character else f"{category or 'Latar'}: "
        self.reference_heading.setText(heading_prefix + name)
        self.reference_details.setPlainText(details or "Belum ada detail.")
        self.reference_panel.show()
        self.editor_splitter.setSizes([max(350, self.editor_splitter.width() - 250), 250])

    def hide_reference_panel(self):
        self.reference_panel.hide()
        self.editor_splitter.setSizes([self.editor_splitter.width(), 0])

    def run_quick_prompt(self, prompt):
        self.prompt.setPlainText(prompt)
        self.ask_ai()

    # -------------------------
    # AI CONTEXT
    # -------------------------

    def build_story_context(self):
        with db() as conn:
            characters = conn.execute("""
                SELECT name, role, details FROM characters
                WHERE project_id = ? ORDER BY role, name
            """, (self.project_id,)).fetchall()

            world_items = conn.execute("""
                SELECT name, category, details FROM worldbuilding
                WHERE project_id = ? ORDER BY category, name
            """, (self.project_id,)).fetchall()

        character_context = "\n".join(
            f"- [{role or 'Karakter Pendukung'}] {name}: {details}"
            for name, role, details in characters
        ) or "Belum ada data karakter."

        world_context = "\n".join(
            f"- [{category}] {name}: {details}"
            for name, category, details in world_items
        ) or "Belum ada data worldbuilding."

        # Include the extensible Story/World Bible and its chapter/relationship links.
        with db() as conn:
            records = conn.execute(
                "SELECT id, kind, name, category, details, status, metadata FROM story_records WHERE project_id=? ORDER BY kind, name",
                (self.project_id,)
            ).fetchall()
            linked = conn.execute(
                "SELECT src.name, ch.title FROM story_record_chapters rc JOIN story_records src ON src.id=rc.record_id JOIN chapters ch ON ch.id=rc.chapter_id WHERE src.project_id=? ORDER BY src.name, ch.position",
                (self.project_id,)
            ).fetchall()
            relationships = conn.execute(
                "SELECT a.name, r.relation, b.name, r.notes FROM character_relationships r JOIN story_records a ON a.id=r.source_id JOIN story_records b ON b.id=r.target_id WHERE r.project_id=? ORDER BY a.name, b.name",
                (self.project_id,)
            ).fetchall()
        extra_records = []
        for rid, kind, name, category, details, status, raw_meta in records:
            try:
                meta = json.loads(raw_meta or "{}")
            except (TypeError, json.JSONDecodeError):
                meta = {}
            profile = "; ".join(f"{k}: {v}" for k, v in meta.items() if v)
            extra_records.append(f"- [{kind} / {category}] {name}; trait/tag: {status}; detail: {details}; {profile}")
        linked_context = "\n".join(f"- {name} terkait dengan {chapter}" for name, chapter in linked) or "Belum ada tautan bab."
        relationship_context = "\n".join(f"- {a} — {relation} — {b}" + (f" ({notes})" if notes else "") for a, relation, b, notes in relationships) or "Belum ada hubungan karakter yang dicatat."
        return (
            f"Judul cerita: {self.project_title}\n"
            f"Bab aktif: {self.chapter_title}\n\n"
            f"KARAKTER LAMA:\n{character_context}\n\n"
            f"WORLDBUILDING LAMA:\n{world_context}\n\n"
            f"STORY BIBLE / WORLD BIBLE:\n" + ("\n".join(extra_records) or "Belum ada entri.") +
            f"\n\nTAUTAN BAB:\n{linked_context}\n\nHUBUNGAN KARAKTER:\n{relationship_context}\n\n"
            f"ISI BAB AKTIF:\n{self.editor.toPlainText()[-5000:]}"
        )

    # -------------------------
    # AI ASSISTANT
    # -------------------------

    def ask_ai(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.information(
                self, "Stomake", "Masukkan perintah untuk AI."
            )
            return

        if self.worker and self.worker.isRunning():
            return

        context = self.build_story_context()
        self.chat.append(f"\nKAMU:\n{prompt}\n")
        self.chat.append("Stomake: Sedang berpikir...\n")
        self.prompt.clear()

        self.send_button.setEnabled(False)
        self.send_button.setText("Memproses...")

        self.worker = AIWorker(prompt, context)
        self.worker.success.connect(self.ai_success)
        self.worker.failure.connect(self.ai_failure)
        self.worker.finished.connect(self.ai_finished)
        self.worker.start()

    def clear_chat(self):
        answer = QMessageBox.question(
            self, "Bersihkan Chat",
            "Hapus seluruh percakapan yang terlihat di panel AI?\n\n"
            "Naskah dan data cerita tidak akan terhapus.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.chat.clear()
        self.last_answer = ""

    def ai_success(self, answer):
        self.last_answer = answer
        self.chat.append(f"Stomake:\n{answer}\n")
        self.chat.append("-" * 32)

    def ai_failure(self, message):
        self.chat.append(f"ERROR:\n{message}\n")

    def ai_finished(self):
        self.send_button.setEnabled(True)
        self.send_button.setText("Kirim ke AI ➤")

    def insert_answer(self):
        if not self.last_answer:
            QMessageBox.information(
                self, "Stomake", "Belum ada jawaban AI."
            )
            return
        self.editor.insertPlainText(self.last_answer)
        self.editor.setFocus()

    # -------------------------
    # THEME
    # -------------------------

    def apply_theme(self):
        # Stomake editor palette inspired by the supplied VS Code screenshot.
        self.setStyleSheet("""
            QWidget { background: #050607; color: #e7edf1; font-family: "Segoe UI"; font-size: 13px; }
            QFrame#sidebar { background: #050607; border-right: 1px solid #20c9e8; }
            QFrame#sidebar QLabel { background: transparent; color: #dbe6eb; }
            QLabel#logo { color: #20c9e8; font-size: 22px; font-weight: 750; }
            QLabel#heading { color: #f1f5f7; font-size: 19px; font-weight: 700; }
            QLabel#muted { color: #9aa8b0; }
            QLabel#sectionLabel { color: #7f9ba6; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding-top: 8px; }
            QFrame#panel { background: #080a0d; border: 1px solid #1fc8e6; border-radius: 7px; }
            QPushButton, QComboBox, QListWidget, QLineEdit {
                background: #07090b; color: #e4edf2; border: 1px solid #155b6b; border-radius: 5px; padding: 6px 9px;
            }
            QPushButton:hover, QComboBox:hover { border-color: #20c9e8; background: #0c1519; }
            QPushButton:pressed { background: #10262d; }
            QPushButton:checked { background: #17252b; color: #ffb347; border: 1px solid #ff9e27; }
            QPushButton#primary { background: #e9a51a; color: #111; border: 1px solid #ffb52d; font-weight: 700; }
            QPushButton#primary:hover { background: #ffc247; }
            QPushButton#navButton { text-align: left; border: 1px solid transparent; padding: 6px 8px; min-height: 18px; }
            QPushButton#navButton:checked { background: #151b1e; color: #ffb347; border-left: 2px solid #ff9e27; border-radius: 3px; }
            QPushButton#iconButton { padding: 0; min-height: 0; border-radius: 5px; font-size: 18px; }
            QComboBox QAbstractItemView { background: #080a0d; color: #e4edf2; selection-background-color: #153b45; selection-color: #fff; }
            QTextEdit { background: #020304; color: #e7edf1; border: 1px solid #155b6b; border-radius: 5px; padding: 9px; selection-background-color: #12677a; }
            QTextEdit:focus, QLineEdit:focus, QListWidget:focus { border: 1px solid #20c9e8; }
            QListWidget { padding: 4px; outline: none; }
            QListWidget::item { padding: 8px; border-radius: 3px; }
            QListWidget::item:hover { background: #0d1c21; }
            QListWidget::item:selected { background: #14262b; color: #ffb347; border-left: 2px solid #ff9e27; }
            QSplitter::handle { background: #155b6b; width: 3px; }
            QSplitter::handle:hover { background: #20c9e8; }
            QScrollBar:vertical { background: #050607; width: 9px; margin: 2px; }
            QScrollBar::handle:vertical { background: #24535e; min-height: 24px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #20c9e8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QDialog { background: #080a0d; }
            QMenu { background: #080a0d; color: #e7edf1; border: 1px solid #20c9e8; padding: 5px; }
            QMenu::item { padding: 7px 18px; }
            QMenu::item:selected { background: #14262b; color: #ffb347; }
            QToolTip { background: #080a0d; color: #e7edf1; border: 1px solid #20c9e8; padding: 5px; }
        """)

    def closeEvent(self, event):
        self.save_current_chapter()
        if self.worker and self.worker.isRunning():
            self.worker.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    setup_database()
    window = Stomake()
    window.show()
    sys.exit(app.exec())
