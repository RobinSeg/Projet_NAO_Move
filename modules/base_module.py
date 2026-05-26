# =============================================================================
# modules/base_module.py — Classe de base pour tous les modules
#
# Fournit : self.frame (tk.Frame dans le Notebook) et self.bridge (NaoBridge)
# Chaque module surcharge _build() pour construire son interface.
# =============================================================================
import tkinter as tk


class BaseModule:
    """
    Classe de base pour chaque module de l'application.
    Chaque module expose un tk.Frame principal.
    """

    def __init__(self, tab_manager, bridge):
        self.tab_manager = tab_manager
        self.bridge = bridge
        self.frame = tk.Frame(tab_manager.notebook)
        self._build()

    def _build(self):
        """À surcharger dans chaque module."""
        raise NotImplementedError
