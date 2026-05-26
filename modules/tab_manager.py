# =============================================================================
# modules/tab_manager.py — Gestionnaire des onglets (ttk.Notebook)
# Fournit add_tab() pour enregistrer chaque module comme onglet.
# =============================================================================
import tkinter as tk
from tkinter import ttk


class TabManager:
    def __init__(self, root):
        self.root = root
        style = ttk.Style()
        style.configure("TNotebook.Tab", padding=[12, 6], font=("Arial", 10))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)
        self.tabs = {}

    def add_tab(self, title, module):
        self.tabs[title] = module
        self.notebook.add(module.frame, text=title)
