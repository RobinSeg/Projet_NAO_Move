# =============================================================================
# modules/logs_module.py — Onglet "Logs"
#
# Affiche l'historique de tous les événements avec horodatage.
# Niveaux : INFO (bleu clair) | WARN (jaune) | ERROR (rouge)
# Fonctions : filtre par niveau, auto-scroll, export .txt, compteur
# =============================================================================
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
from modules.base_module import BaseModule


class LogsModule(BaseModule):

    def _build(self):
        self.tous_les_logs = []
        self.filtre_actif = "ALL"

        self.frame.grid_rowconfigure(0, weight=0)
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_rowconfigure(2, weight=0)
        self.frame.grid_columnconfigure(0, weight=1)

        self._creer_barre_outils()
        self._creer_zone_logs()
        self._creer_barre_bas()
        self.bridge.add_log_callback(self._recevoir_log)

    def _creer_barre_outils(self):
        fb = tk.Frame(self.frame, pady=4, padx=6, relief="groove", borderwidth=1)
        fb.grid(row=0, column=0, sticky="ew")
        tk.Label(fb, text="Logs", font=("Arial", 11, "bold")).pack(side="left", padx=8)
        tk.Label(fb, text="Filtre :").pack(side="left", padx=(16, 4))
        self.filtre_var = tk.StringVar(value="ALL")
        for niveau in ["ALL", "INFO", "WARN", "ERROR"]:
            tk.Radiobutton(fb, text=niveau, variable=self.filtre_var,
                value=niveau, command=self._appliquer_filtre,
                indicatoron=False, padx=6, pady=2, relief="groove"
            ).pack(side="left", padx=2)
        tk.Button(fb, text="🗑 Effacer", command=self._effacer).pack(side="right", padx=4)
        tk.Button(fb, text="💾 Exporter", command=self._exporter).pack(side="right", padx=4)
        self.auto_scroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(fb, text="Auto-scroll", variable=self.auto_scroll_var).pack(side="right", padx=8)

    def _creer_zone_logs(self):
        container = tk.Frame(self.frame)
        container.grid(row=1, column=0, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        scroll = tk.Scrollbar(container)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text = tk.Text(container, state="disabled", wrap="word",
            font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4",
            yscrollcommand=scroll.set, padx=8, pady=4, cursor="arrow")
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.config(command=self.text.yview)
        self.text.tag_config("INFO",  foreground="#6ec9f0")
        self.text.tag_config("WARN",  foreground="#f5c842")
        self.text.tag_config("ERROR", foreground="#f07070")
        self.text.tag_config("TIME",  foreground="#666666")
        self.text.tag_config("MSG",   foreground="#d4d4d4")

    def _creer_barre_bas(self):
        fb = tk.Frame(self.frame, pady=3, padx=6, relief="sunken", borderwidth=1)
        fb.grid(row=2, column=0, sticky="ew")
        self.label_compte = tk.Label(fb, text="0 entrées", fg="#666", font=("Arial", 9))
        self.label_compte.pack(side="right")

    def _recevoir_log(self, level, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.tous_les_logs.append((ts, level, msg))
        if self.filtre_actif in ("ALL", level):
            self._afficher_entree(ts, level, msg)
        self.label_compte.config(text="{} entrées".format(len(self.tous_les_logs)))

    def _afficher_entree(self, ts, level, msg):
        self.text.config(state="normal")
        self.text.insert("end", "[{}] ".format(ts), "TIME")
        self.text.insert("end", "{:<6} ".format(level), level)
        self.text.insert("end", msg + "\n", "MSG")
        self.text.config(state="disabled")
        if self.auto_scroll_var.get():
            self.text.see("end")

    def _appliquer_filtre(self):
        self.filtre_actif = self.filtre_var.get()
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        for ts, level, msg in self.tous_les_logs:
            if self.filtre_actif in ("ALL", level):
                self._afficher_entree(ts, level, msg)

    def _effacer(self):
        self.tous_les_logs.clear()
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self.label_compte.config(text="0 entrées")

    def _exporter(self):
        chemin = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Fichiers texte", "*.txt"), ("Tous", "*.*")],
            initialfile="nao_logs.txt")
        if not chemin:
            return
        with open(chemin, "w", encoding="utf-8") as f:
            for ts, level, msg in self.tous_les_logs:
                f.write("[{}] {:<6} {}\n".format(ts, level, msg))
        self.bridge.log("Logs exportés : {}".format(chemin), "INFO")
