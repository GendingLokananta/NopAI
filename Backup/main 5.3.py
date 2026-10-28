import sys
import sqlite3
from pathlib import Path

import requests

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QTextCharFormat, QTextListFormat, QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel,
    QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout,
    QSplitter, QMessageBox, QInputDialog, QListWidget,
    QListWidgetItem, QComboBox, QDialog, QFormLayout,
    QLineEdit, QDialogButtonBox, QMenu, QFileDialog
)

# =========================
# CONFIGURATION
# =========================

APP_NAME = "NopAI"
MODEL_NAME = "llama3.2:3b"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "nopai.db"


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
                details TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """)
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
        # Keep compatibility with the first NopAI version.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS manuscript (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)

        count = conn.execute(
            "SELECT COUNT(*) FROM projects"
        ).fetchone()[0]

        if count == 0:
            old = conn.execute(
                "SELECT title, content FROM manuscript WHERE id = 1"
            ).fetchone()
            title = old[0] if old else "Novel Pertamaku"
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
                                "Kamu adalah NopAI, asisten penulis novel. "
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

class RecordDialog(QDialog):
    def __init__(self, parent, title, name="", details="", category=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 430)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit(name)
        self.details_input = QTextEdit()
        self.details_input.setPlainText(details)
        self.details_input.setPlaceholderText(
            "Tuliskan detail, fakta, latar belakang, tujuan, rahasia, "
            "aturan, atau informasi lain..."
        )

        form.addRow("Nama:", self.name_input)

        self.category_input = None
        if category is not None:
            self.category_input = QComboBox()
            self.category_input.addItems([
                "Lokasi", "Power System", "Sejarah", "Budaya",
                "Kerajaan", "Organisasi", "Makhluk", "Benda", "Lore"
            ])
            index = self.category_input.findText(category)
            if index >= 0:
                self.category_input.setCurrentIndex(index)
            form.addRow("Kategori:", self.category_input)

        layout.addLayout(form)
        layout.addWidget(QLabel("Detail:"))
        layout.addWidget(self.details_input, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return (
            self.name_input.text().strip(),
            self.details_input.toPlainText().strip(),
            self.category_input.currentText()
            if self.category_input else None
        )


# =========================
# MAIN APPLICATION
# =========================

class NopAI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NopAI — Your Story, Smarter")
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
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 16, 12, 12)
        side.setSpacing(7)

        logo = QLabel("✦  NopAI")
        logo.setObjectName("logo")
        side.addWidget(logo)
        tagline = QLabel("Your Story, Smarter")
        tagline.setObjectName("muted")
        side.addWidget(tagline)
        side.addSpacing(12)

        side.addSpacing(12)
        side.addWidget(QLabel("NOVEL SAYA"))
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
        side.addWidget(QLabel("DAFTAR BAB"))
        self.chapter_list = QListWidget()
        self.chapter_list.currentItemChanged.connect(self.on_chapter_changed)
        self.chapter_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chapter_list.customContextMenuRequested.connect(self.show_chapter_menu)
        side.addWidget(self.chapter_list, 1)
        add_chapter = QPushButton("＋ Bab")
        add_chapter.clicked.connect(self.new_chapter)
        side.addWidget(add_chapter)
        self.save_label = QLabel("● Siap")
        self.save_label.setObjectName("muted")
        side.addWidget(self.save_label)

        # Center editor
        center = QFrame()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(12, 12, 12, 12)
        center_layout.setSpacing(8)
        header = QHBoxLayout()
        self.chapter_heading = QLabel("Editor Novel")
        self.chapter_heading.setObjectName("heading")
        header.addWidget(self.chapter_heading)
        header.addStretch()
        export_button = QPushButton("⇩ Export Novel")
        export_button.clicked.connect(self.show_export_menu)
        header.addWidget(export_button)
        center_layout.addLayout(header)

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
            "Arial", "Calibri", "Cambria", "Georgia", "Times New Roman",
            "Verdana", "Tahoma", "Trebuchet MS", "Segoe UI", "Consolas",
            "Courier New"
        ])
        self.font_family_combo.setCurrentText("Arial")
        self.font_family_combo.setFixedWidth(120)
        self.font_family_combo.setFixedHeight(24)
        self.font_family_combo.setStyleSheet("QComboBox { padding: 1px 3px; font-size: 11px; }")
        self.font_family_combo.setToolTip("Pilih jenis huruf")
        self.font_family_combo.currentTextChanged.connect(self.apply_font_family)
        toolbar.addWidget(self.font_family_combo)

        size_label = QLabel("Uk.")
        size_label.setStyleSheet("font-size: 11px; padding: 0px;")
        toolbar.addWidget(size_label)
        self.font_size_combo = QComboBox()
        self.font_size_combo.setEditable(True)
        self.font_size_combo.setFixedWidth(46)
        self.font_size_combo.setFixedHeight(24)
        self.font_size_combo.setStyleSheet("QComboBox { padding: 1px 2px; font-size: 11px; }")
        self.font_size_combo.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28", "36", "48", "72"])
        self.font_size_combo.setCurrentText("12")
        self.font_size_combo.setToolTip("Ukuran font (pt). Pilih atau ketik ukuran lalu tekan Enter")
        self.font_size_combo.activated.connect(self.apply_font_size)
        self.font_size_combo.lineEdit().returnPressed.connect(self.apply_font_size)
        toolbar.addWidget(self.font_size_combo)
        toolbar.addStretch(1)
        center_layout.addLayout(toolbar)

        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.editor.textChanged.connect(self.update_word_count)
        self.editor.cursorPositionChanged.connect(self.update_format_indicators)
        self.editor.selectionChanged.connect(self.update_format_indicators)
        self.editor.setTabChangesFocus(False)
        center_layout.addWidget(self.editor, 1)

        # Familiar Word shortcuts for paragraph alignment.
        QShortcut(QKeySequence("Ctrl+L"), self.editor, activated=lambda: self.apply_alignment("left"))
        QShortcut(QKeySequence("Ctrl+E"), self.editor, activated=lambda: self.apply_alignment("center"))
        QShortcut(QKeySequence("Ctrl+R"), self.editor, activated=lambda: self.apply_alignment("right"))
        QShortcut(QKeySequence("Ctrl+J"), self.editor, activated=lambda: self.apply_alignment("justify"))
        footer = QHBoxLayout()
        self.word_label = QLabel("0 kata")
        self.word_label.setObjectName("muted")
        footer.addWidget(self.word_label)
        footer.addStretch()
        footer.addWidget(QLabel("Disimpan lokal • Markdown"))
        center_layout.addLayout(footer)

        # AI panel
        ai_panel = QFrame()
        ai_panel.setObjectName("panel")
        ai_panel.setMinimumWidth(280)
        ai_layout = QVBoxLayout(ai_panel)
        ai_layout.setContentsMargins(10, 10, 10, 10)
        ai_title = QLabel("✦ AI Assistant")
        ai_title.setObjectName("heading")
        ai_layout.addWidget(ai_title)
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Hai! Aku NopAI. Aku bisa membantu melanjutkan cerita, memberi saran, dan memeriksa konsistensi.")
        ai_layout.addWidget(self.chat, 1)
        clear_chat_button = QPushButton("Bersihkan Chat")
        clear_chat_button.clicked.connect(self.clear_chat)
        ai_layout.addWidget(clear_chat_button)
        for label, prompt in [
            ("Lanjutkan adegan ini", "Lanjutkan adegan dari bagian akhir bab aktif. Jaga gaya dan konsistensi cerita."),
            ("Ubah gaya tulisan", "Berikan versi revisi dari bagian akhir naskah dengan gaya yang lebih kuat, tanpa mengubah fakta cerita."),
            ("Periksa konsistensi", "Periksa kemungkinan inkonsistensi berdasarkan konteks novel yang tersedia."),
            ("Tanya tentang cerita", "Ringkas informasi penting yang relevan dari konteks novel.")
        ]:
            quick = QPushButton(label)
            quick.clicked.connect(lambda checked=False, p=prompt: self.run_quick_prompt(p))
            ai_layout.addWidget(quick)
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Tulis perintah atau pertanyaan...")
        self.prompt.setMaximumHeight(90)
        ai_layout.addWidget(self.prompt)
        self.send_button = QPushButton("Kirim ke AI ➤")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.ask_ai)
        ai_layout.addWidget(self.send_button)
        insert_button = QPushButton("Masukkan jawaban ke naskah")
        insert_button.clicked.connect(self.insert_answer)
        ai_layout.addWidget(insert_button)

        # Right quick context panel with right-click actions
        context_panel = QFrame()
        context_panel.setObjectName("panel")
        context_panel.setMinimumWidth(210)
        context_layout = QVBoxLayout(context_panel)
        context_layout.setContentsMargins(10, 10, 10, 10)
        context_layout.setSpacing(6)
        context_title = QLabel("KONTEKS CEPAT")
        context_title.setObjectName("heading")
        context_layout.addWidget(context_title)
        context_layout.addWidget(QLabel("Karakter  · klik kanan untuk opsi"))
        self.character_list = QListWidget()
        self.character_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.character_list.customContextMenuRequested.connect(lambda pos: self.show_record_menu("characters", self.character_list, pos))
        self.character_list.itemDoubleClicked.connect(lambda item: self.edit_record_from_item("characters", item))
        context_layout.addWidget(self.character_list, 1)
        add_char = QPushButton("＋ Tambah Karakter")
        add_char.clicked.connect(lambda: self.add_record("characters"))
        context_layout.addWidget(add_char)
        context_layout.addWidget(QLabel("Latar & Power System"))
        self.world_list = QListWidget()
        self.world_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.world_list.customContextMenuRequested.connect(lambda pos: self.show_record_menu("worldbuilding", self.world_list, pos))
        self.world_list.itemDoubleClicked.connect(lambda item: self.edit_record_from_item("worldbuilding", item))
        context_layout.addWidget(self.world_list, 1)
        add_world = QPushButton("＋ Tambah Latar")
        add_world.clicked.connect(lambda: self.add_record("worldbuilding"))
        context_layout.addWidget(add_world)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(center)
        splitter.addWidget(ai_panel)
        splitter.addWidget(context_panel)
        splitter.setSizes([600, 340, 250])

        root_layout.addWidget(sidebar)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

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

    def new_project(self):
        title, ok = QInputDialog.getText(
            self, "Novel Baru", "Judul novel:"
        )
        if not ok or not title.strip():
            return
        project_id = create_project(title.strip())
        self.load_projects(project_id)

    def show_project_menu(self, pos):
        """Menu klik kanan pada pemilih novel."""
        if self.project_id is None:
            return
        menu = QMenu(self)
        rename_action = menu.addAction("✎ Ubah Judul Novel")
        delete_action = menu.addAction("⌫ Hapus Novel")
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
                self, "NopAI",
                "Novel terakhir tidak bisa dihapus. Buat novel baru terlebih dahulu."
            )
            return

        title = self.project_title
        answer = QMessageBox.question(
            self, "Hapus Novel",
            f"Yakin ingin menghapus novel '{title}'?\n\n"
            "Semua bab, karakter, dan latar dalam novel ini juga akan dihapus.\n"
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
            self, "Ubah Judul Novel", "Judul baru:",
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
        self.save_label.setText("● Judul novel disimpan")

    # -------------------------
    # EXPORT NOVEL
    # -------------------------

    def show_export_menu(self):
        menu = QMenu(self)
        word_action = menu.addAction("Export Word (.docx)")
        docs_action = menu.addAction("Export untuk Google Docs…")
        chosen = menu.exec(self.mapToGlobal(self.rect().center()))
        if chosen == word_action:
            self.export_novel(open_google_docs=False)
        elif chosen == docs_action:
            self.export_novel(open_google_docs=True)

    def export_novel(self, open_google_docs=False):
        if self.project_id is None:
            QMessageBox.warning(self, "Export Novel", "Pilih novel terlebih dahulu.")
            return

        # Pastikan isi bab aktif tersimpan sebelum membaca semua bab dari database.
        self.save_current_chapter()
        safe_title = "".join(c for c in self.project_title if c not in '<>:\"/\\|?*').strip()
        safe_title = safe_title or "Novel NopAI"
        default_path = str(Path.home() / f"{safe_title}.docx")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Novel ke Word" if not open_google_docs else "Siapkan Novel untuk Google Docs",
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
                "Buka Command Prompt di folder NopAI lalu jalankan:\n"
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
                    "SELECT name, details FROM characters WHERE project_id = ? ORDER BY name",
                    (self.project_id,)
                ).fetchall()
                lore_entries = conn.execute(
                    "SELECT name, category, details FROM worldbuilding WHERE project_id = ? ORDER BY category, name",
                    (self.project_id,)
                ).fetchall()

            if not project:
                QMessageBox.warning(self, "Export Novel", "Novel tidak ditemukan.")
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
                for character_name, details in characters:
                    document.add_heading(character_name, level=2)
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
                "Novel berhasil diekspor sebagai file Word (.docx).\n\n"
                "Google Docs sudah dibuka. Di Google Docs, pilih pembuka file, lalu upload/pilih file\n"
                f"ini:\n{file_path}\n\n"
                "NopAI tidak mengunggah otomatis ke akun Google; untuk itu diperlukan koneksi dan izin Google API."
            )
        else:
            QMessageBox.information(
                self, "Export berhasil",
                f"Novel berhasil diekspor, termasuk {len(chapters)} bab, {len(characters)} karakter, "
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
            return

        self.save_current_chapter()

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
        if not hasattr(self, "character_list") or self.project_id is None:
            return
        self.character_list.clear()
        self.world_list.clear()
        with db() as conn:
            chars = conn.execute("SELECT id, name, details FROM characters WHERE project_id = ? ORDER BY name", (self.project_id,)).fetchall()
            worlds = conn.execute("SELECT id, name, category, details FROM worldbuilding WHERE project_id = ? ORDER BY category, name", (self.project_id,)).fetchall()
        for record_id, name, details in chars:
            item = QListWidgetItem(name + ("\n" + details[:70] if details else ""))
            item.setData(Qt.ItemDataRole.UserRole, record_id)
            item.setToolTip(details)
            self.character_list.addItem(item)
        for record_id, name, category, details in worlds:
            item = QListWidgetItem(f"{name}\n[{category}]" + (f" — {details[:55]}" if details else ""))
            item.setData(Qt.ItemDataRole.UserRole, record_id)
            item.setToolTip(details)
            self.world_list.addItem(item)

    def add_record(self, kind):
        is_character = kind == "characters"
        heading = "Karakter" if is_character else "Latar / Power System"
        dialog = RecordDialog(self, f"Tambah {heading}", category=None if is_character else "Lore")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, details, category = dialog.values()
        if not name:
            QMessageBox.warning(self, "NopAI", "Nama tidak boleh kosong.")
            return
        with db() as conn:
            if is_character:
                conn.execute("INSERT INTO characters (project_id, name, details) VALUES (?, ?, ?)", (self.project_id, name, details))
            else:
                conn.execute("INSERT INTO worldbuilding (project_id, name, category, details) VALUES (?, ?, ?, ?)", (self.project_id, name, category, details))
        self.refresh_context_lists()

    def edit_record_from_item(self, kind, item):
        if item is None:
            return
        record_id = item.data(Qt.ItemDataRole.UserRole)
        is_character = kind == "characters"
        with db() as conn:
            if is_character:
                row = conn.execute("SELECT name, details FROM characters WHERE id = ? AND project_id = ?", (record_id, self.project_id)).fetchone()
                category = None
            else:
                row = conn.execute("SELECT name, details, category FROM worldbuilding WHERE id = ? AND project_id = ?", (record_id, self.project_id)).fetchone()
                category = row[2] if row else "Lore"
        if not row:
            return
        dialog = RecordDialog(self, "Edit data", row[0], row[1], category)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, details, new_category = dialog.values()
        if not name:
            QMessageBox.warning(self, "NopAI", "Nama tidak boleh kosong.")
            return
        with db() as conn:
            if is_character:
                conn.execute("UPDATE characters SET name = ?, details = ? WHERE id = ? AND project_id = ?", (name, details, record_id, self.project_id))
            else:
                conn.execute("UPDATE worldbuilding SET name = ?, details = ?, category = ? WHERE id = ? AND project_id = ?", (name, details, new_category, record_id, self.project_id))
        self.refresh_context_lists()

    def show_record_menu(self, kind, widget, pos):
        item = widget.itemAt(pos)
        menu = QMenu(self)
        add_action = menu.addAction("＋ Tambah data")
        edit_action = menu.addAction("✎ Edit / Lihat")
        delete_action = menu.addAction("⌫ Hapus")
        edit_action.setEnabled(item is not None)
        delete_action.setEnabled(item is not None)
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen == add_action:
            self.add_record(kind)
        elif chosen == edit_action and item:
            self.edit_record_from_item(kind, item)
        elif chosen == delete_action and item:
            record_id = item.data(Qt.ItemDataRole.UserRole)
            name = item.text().split("\n")[0]
            answer = QMessageBox.question(self, "Hapus data", f"Hapus '{name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                table = "characters" if kind == "characters" else "worldbuilding"
                with db() as conn:
                    conn.execute(f"DELETE FROM {table} WHERE id = ? AND project_id = ?", (record_id, self.project_id))
                self.refresh_context_lists()

    def manage_records(self, kind):
        # Compatibility for older buttons/calls: refresh the in-panel list.
        self.refresh_context_lists()

    def run_quick_prompt(self, prompt):
        self.prompt.setPlainText(prompt)
        self.ask_ai()

    # -------------------------
    # AI CONTEXT
    # -------------------------

    def build_story_context(self):
        with db() as conn:
            characters = conn.execute("""
                SELECT name, details FROM characters
                WHERE project_id = ? ORDER BY name
            """, (self.project_id,)).fetchall()

            world_items = conn.execute("""
                SELECT name, category, details FROM worldbuilding
                WHERE project_id = ? ORDER BY category, name
            """, (self.project_id,)).fetchall()

        character_context = "\n".join(
            f"- {name}: {details}" for name, details in characters
        ) or "Belum ada data karakter."

        world_context = "\n".join(
            f"- [{category}] {name}: {details}"
            for name, category, details in world_items
        ) or "Belum ada data worldbuilding."

        return (
            f"Judul novel: {self.project_title}\n"
            f"Bab aktif: {self.chapter_title}\n\n"
            f"KARAKTER:\n{character_context}\n\n"
            f"WORLDBUILDING:\n{world_context}\n\n"
            f"ISI BAB AKTIF:\n{self.editor.toPlainText()[-5000:]}"
        )

    # -------------------------
    # AI ASSISTANT
    # -------------------------

    def ask_ai(self):
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.information(
                self, "NopAI", "Masukkan perintah untuk AI."
            )
            return

        if self.worker and self.worker.isRunning():
            return

        context = self.build_story_context()
        self.chat.append(f"\nKAMU:\n{prompt}\n")
        self.chat.append("NOPAI: Sedang berpikir...\n")
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
            "Naskah dan data novel tidak akan terhapus.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.chat.clear()
        self.last_answer = ""

    def ai_success(self, answer):
        self.last_answer = answer
        self.chat.append(f"NOPAI:\n{answer}\n")
        self.chat.append("-" * 32)

    def ai_failure(self, message):
        self.chat.append(f"ERROR:\n{message}\n")

    def ai_finished(self):
        self.send_button.setEnabled(True)
        self.send_button.setText("Kirim ke AI ➤")

    def insert_answer(self):
        if not self.last_answer:
            QMessageBox.information(
                self, "NopAI", "Belum ada jawaban AI."
            )
            return
        self.editor.insertPlainText(self.last_answer)
        self.editor.setFocus()

    # -------------------------
    # THEME
    # -------------------------

    def apply_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #0b1020;
                color: #e3e9ff;
                font-family: Segoe UI;
                font-size: 13px;
            }
            QFrame#sidebar {
                background-color: #0e1528;
                border-right: 1px solid #263250;
            }
            QFrame#panel {
                background-color: #111a2e;
                border: 1px solid #283858;
                border-radius: 10px;
            }
            QLabel#logo {
                color: #a99aff;
                font-size: 24px;
                font-weight: bold;
            }
            QLabel#heading {
                color: #c3b8ff;
                font-size: 18px;
                font-weight: bold;
            }
            QLabel#muted {
                color: #91a1c4;
            }
            QPushButton, QComboBox, QListWidget {
                background-color: #1a2641;
                border: 1px solid #2b3b5d;
                border-radius: 6px;
                padding: 7px;
            }
            QPushButton#navButton { text-align: left; background-color: transparent; border-color: transparent; }
            QPushButton:hover {
                background-color: #29385c;
            }
            QPushButton:checked {
                background-color: #5267a5;
                border: 1px solid #8da6ff;
                color: #ffffff;
                font-weight: bold;
            }
            QPushButton#primary {
                background-color: #6654ce;
                font-weight: bold;
            }
            QTextEdit, QLineEdit {
                background-color: #0b1223;
                border: 1px solid #2b3b5d;
                border-radius: 7px;
                padding: 9px;
                selection-background-color: #6654ce;
            }
            QListWidget::item {
                padding: 8px;
                border-radius: 5px;
            }
            QListWidget::item:selected {
                background-color: #293461;
                color: #c7baff;
            }
            QDialog {
                background-color: #111a2e;
            }
        """)

    def closeEvent(self, event):
        self.save_current_chapter()
        if self.worker and self.worker.isRunning():
            self.worker.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    setup_database()
    window = NopAI()
    window.show()
    sys.exit(app.exec())
