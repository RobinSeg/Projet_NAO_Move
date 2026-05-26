# =============================================================================
# main.py — Point d'entrée de l'application NAO Move
#
# Rôle :
#   - Crée la fenêtre principale et les 4 onglets
#     (Éditeur de scène | Vue NAO | Contrôle Manuel | Logs)
#   - Instancie NaoBridge (bus partagé entre tous les modules)
#   - Gère la barre de connexion (simulation 127.0.0.1 / robot réel + IP)
#   - Affiche les popups de choix : chemin BFS, obstacle, contournement
#
# Modes :
#   Simulation  → IP 127.0.0.1, Chorégraphe en local
#   Robot réel  → IP saisie par l'utilisateur, robot physique sur le réseau
# =============================================================================
import tkinter as tk
import sys
import os

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

from modules.tab_manager import TabManager
from modules.editor_module import EditorModule
from modules.view_module import ViewModule
from modules.logs_module import LogsModule
from modules.control_module import ControlModule
from modules.nao_bridge import NaoBridge


def afficher_tutoriel(root):
    """Popup tutoriel au premier lancement."""
    popup = tk.Toplevel(root)
    popup.title("Bienvenue dans NAO Move")
    popup.resizable(False, False)
    popup.grab_set()
    popup.transient(root)  # reste au-dessus de la fenêtre principale

    try:
        popup.iconbitmap(resource_path("scene-icon.ico"))
    except Exception:
        pass

    pw, ph = 620, 780

    # IMPORTANT : forcer le calcul des tailles
    popup.update_idletasks()
    root.update_idletasks()

    # Dimensions et position de la fenêtre principale
    root_x = root.winfo_x()
    root_y = root.winfo_y()
    root_w = root.winfo_width()
    root_h = root.winfo_height()

    # Calcul du centrage relatif à root
    x = root_x + (root_w - pw) // 2
    y = root_y + (root_h - ph) // 2

    popup.geometry(f"{pw}x{ph}+{x}+{y}")

    # Zone scrollable pour le contenu
    outer = tk.Frame(popup)
    outer.pack(fill="both", expand=True, padx=20, pady=16)

    tk.Label(outer, text="🤖 NAO Move",
             font=("Arial", 18, "bold")).pack(pady=(0, 2))
    tk.Label(outer, text="Guide de démarrage rapide",
             font=("Arial", 11), fg="#666").pack(pady=(0, 14))

    etapes = [
        ("1 - Prérequis",
         "Choisir le mode en haut de la fenêtre :\n"
         "  🖥  Simulation → Ouvrir Chorégraphe, charger serveur_nao.pml\n"
         "  🤖  Robot réel → Entrer l'IP du robot et cliquer Appliquer\n"
         "Dans les deux cas, lancer ServeurNao.bat avant de naviguer."),

        ("2 - Éditeur de scène — les symboles",
         "X  =  mur / obstacle\n"
         "○  =  case praticable (chemin possible)\n"
         "N  =  position de départ de NAO\n"
         "E  =  case adjacente à N → indique l'orientation initiale\n"
         "◘  =  objectif à atteindre\n"
         "1  =  obstacle physique à détecter par sonar\n"
         "       (le BFS passe dessus, le robot vérifie en temps réel)"),

        ("3 - Lancer NAO",
         "1. Dessiner la scène dans l'éditeur\n"
         "2. Enregistrer (💾 Enregistrer sous)\n"
         "3. Cliquer ▶ Lancer NAO\n"
         "→ La navigation démarre en arrière-plan (aucune fenêtre)\n"
         "→ Le chemin est calculé automatiquement par BFS"),

        ("4 - Vue NAO",
         "Suivre le déplacement du robot en temps réel.\n"
         "Le chemin BFS est surligné sur la carte au lancement.\n"
         "Le robot (♦) se déplace case par case."),

        ("5 - Logs",
         "Historique de toutes les commandes envoyées au robot.\n"
         "Filtrer par niveau : INFO / WARN / ERROR.\n"
         "Exporter les logs si besoin."),
    ]

    for titre, contenu in etapes:
        bloc = tk.Frame(outer, relief="groove", borderwidth=1, padx=12, pady=8)
        bloc.pack(fill="x", pady=4)
        tk.Label(bloc, text=titre, font=("Arial", 10, "bold"),
                 anchor="w", justify="left").pack(fill="x")
        tk.Label(bloc, text=contenu, font=("Arial", 9),
                 anchor="w", justify="left", fg="#333",
                 wraplength=560).pack(fill="x", padx=4, pady=(2, 0))

    tk.Button(
        outer, text="C'est parti ! 🚀",
        font=("Arial", 11, "bold"),
        bg="#4a9", fg="white", padx=20, pady=6,
        relief="flat", command=popup.destroy
    ).pack(pady=(14, 0))

    popup.protocol("WM_DELETE_WINDOW", popup.destroy)

class NaoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NAO Move")
        self.root.minsize(800, 600)

        try:
            self.root.iconbitmap(resource_path("scene-icon.ico"))
        except Exception:
            pass

        self.root.geometry("1080x720")

        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        self.root.geometry("{}x{}+{}+{}".format(w, h, x, 0))
        self.root.state('zoomed')

        self.bridge = NaoBridge()
        self.tab_manager = TabManager(self.root)

        self.editor  = EditorModule(self.tab_manager, self.bridge)
        self.viewer  = ViewModule(self.tab_manager, self.bridge)
        self.logs    = LogsModule(self.tab_manager, self.bridge)
        self.control = ControlModule(self.tab_manager, self.bridge)

        self.tab_manager.add_tab("✏️ Éditeur de scène", self.editor)
        self.tab_manager.add_tab("🤖 Vue NAO",          self.viewer)
        self.tab_manager.add_tab("🎮 Contrôle Manuel",  self.control)
        self.tab_manager.add_tab("📋 Logs",             self.logs)

        self._creer_barre_statut()
        self.bridge.start(self.root)

        # Enregistrement des callbacks de choix
        self.bridge.set_choix_chemin_callback(self._popup_choix_chemin)
        self.bridge.set_choix_obstacle_callback(self._popup_choix_obstacle)
        self.bridge.set_obstacle_cases_callback(self._popup_obstacle_cases)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Popup tutoriel après que la fenêtre principale soit prête
        self.root.after(300, lambda: afficher_tutoriel(self.root))

    def _popup_choix_chemin(self, chemins):
        """Popup pour choisir parmi plusieurs chemins de même longueur."""
        popup = tk.Toplevel(self.root)
        popup.title("Plusieurs chemins possibles")
        popup.grab_set()
        popup.resizable(False, False)

        pw, ph = 400, 200 + len(chemins) * 40
        x = (self.root.winfo_screenwidth() - pw) // 2
        y = (self.root.winfo_screenheight() - ph) // 2
        popup.geometry("{}x{}+{}+{}".format(pw, ph, x, y))

        tk.Label(popup, text="Plusieurs chemins optimaux trouvés.",
                 font=("Arial", 11, "bold")).pack(pady=(16, 4))
        tk.Label(popup, text="Choisissez l'itinéraire à suivre :",
                 font=("Arial", 10), fg="#666").pack(pady=(0, 12))

        for i, chemin in enumerate(chemins):
            nb = len(chemin)
            label = "Chemin {} — {} cases ({} étapes)".format(i+1, nb, nb-1)
            tk.Button(
                popup, text=label, font=("Arial", 10),
                bg="#4a9", fg="white", pady=6,
                command=lambda idx=i, p=popup: self._confirmer_chemin(idx, p)
            ).pack(fill="x", padx=20, pady=4)

    def _confirmer_chemin(self, idx, popup):
        popup.destroy()
        self.bridge.envoyer_stdin(str(idx))
        self.bridge.log("Chemin {} sélectionné.".format(idx+1), "INFO")

    def _popup_choix_obstacle(self):
        """Popup pour choisir contourner ou retour quand obstacle détecté."""
        popup = tk.Toplevel(self.root)
        popup.title("Obstacle détecté !")
        popup.grab_set()
        popup.resizable(False, False)

        pw, ph = 380, 220
        x = (self.root.winfo_screenwidth() - pw) // 2
        y = (self.root.winfo_screenheight() - ph) // 2
        popup.geometry("{}x{}+{}+{}".format(pw, ph, x, y))

        tk.Label(popup, text="⚠️ Obstacle détecté !",
                 font=("Arial", 13, "bold"), fg="#c44").pack(pady=(20, 6))
        tk.Label(popup, text="Que doit faire NAO ?",
                 font=("Arial", 10), fg="#666").pack(pady=(0, 16))

        frame_btn = tk.Frame(popup)
        frame_btn.pack(pady=4)

        tk.Button(
            frame_btn, text="🔄 Contourner", font=("Arial", 11, "bold"),
            bg="#4a9", fg="white", padx=16, pady=8,
            command=lambda p=popup: self._confirmer_obstacle("contourner", p)
        ).pack(side="left", padx=10)

        tk.Button(
            frame_btn, text="↩ Faire demi-tour", font=("Arial", 11, "bold"),
            bg="#c44", fg="white", padx=16, pady=8,
            command=lambda p=popup: self._confirmer_obstacle("retour", p)
        ).pack(side="left", padx=10)

        tk.Label(popup, text="(La popup se fermera automatiquement\ndans 60 secondes → demi-tour)",
                 font=("Arial", 8), fg="#aaa").pack(pady=(12, 0))

    def _confirmer_obstacle(self, choix, popup):
        popup.destroy()
        self.bridge.envoyer_stdin(choix)
        self.bridge.log("Choix obstacle : {}.".format(choix), "INFO")

    def _popup_obstacle_cases(self, data):
        """
        Obstacle simulé détecté.
        - Si des cases itinéraires ou blanches sont disponibles :
          les met en surbrillance dans le viewer, l'utilisateur clique.
        - Propose toujours demi-tour via popup flottante.
        """
        obstacle      = data.get("obstacle", [])
        cases_itin    = data.get("cases_itin", [])
        cases_blanches= data.get("cases_blanches", [])

        # Popup flottante (non modale) avec bouton demi-tour
        popup = tk.Toplevel(self.root)
        popup.title("⚠️ Obstacle simulé")
        popup.resizable(False, False)
        popup.attributes("-topmost", True)
        popup.geometry("360x160+{}+{}".format(
            self.root.winfo_x() + 20,
            self.root.winfo_y() + self.root.winfo_height() - 200
        ))

        tk.Label(popup, text="⚠️ Obstacle détecté !",
                 font=("Arial", 12, "bold"), fg="#c44").pack(pady=(12, 4))

        if cases_itin or cases_blanches:
            n_total = len(cases_itin) + len(cases_blanches)
            tk.Label(popup,
                text="Cliquez une case dans le viewer pour contourner\n"
                     "({} case(s) disponible(s) — vert = praticable, orange = à créer)".format(n_total),
                font=("Arial", 9), fg="#555", justify="center").pack(pady=(0, 8))
        else:
            tk.Label(popup,
                text="Aucune case disponible pour contourner.",
                font=("Arial", 9), fg="#555").pack(pady=(0, 8))

        tk.Button(popup, text="↩ Faire demi-tour",
                  bg="#c44", fg="white", font=("Arial", 11, "bold"),
                  padx=16, pady=6,
                  command=lambda p=popup: self._obstacle_demi_tour(p)).pack()

        # Activer surbrillance dans le viewer
        if cases_itin or cases_blanches:
            def on_case_cliquee(x, y):
                popup.destroy()
                # Envoyer la case cliquée
                self.bridge.envoyer_stdin("case:{}:{}".format(x, y))
                self.bridge.log(
                    "Case ({},{}) sélectionnée pour contournement.".format(x, y), "INFO")

            self.viewer.activer_surbrillance_obstacle(
                obstacle, cases_itin, cases_blanches, on_case_cliquee)
        else:
            # Aucune case dispo → envoyer retour auto après 30s
            self.root.after(30000, lambda: self._obstacle_demi_tour(popup))

    def _obstacle_demi_tour(self, popup):
        try:
            popup.destroy()
        except Exception:
            pass
        # Désactiver surbrillance
        try:
            self.viewer._desactiver_surbrillance()
            self.viewer._redessiner()
        except Exception:
            pass
        self.bridge.envoyer_stdin("retour")
        self.bridge.log("Demi-tour choisi.", "INFO")

    def _creer_barre_statut(self):
        # ── Barre connexion (haut) ────────────────────────────────────────────
        barre_conn = tk.Frame(self.root, relief="groove", borderwidth=1,
                              bg="#f0f0f0", pady=4, padx=8)
        barre_conn.pack(side="top", fill="x")

        tk.Label(barre_conn, text="Mode :", bg="#f0f0f0",
                 font=("Arial", 10, "bold")).pack(side="left", padx=(0, 4))

        self.mode_var = tk.StringVar(value="simulation")
        tk.Radiobutton(barre_conn, text="🖥  Simulation",
            variable=self.mode_var, value="simulation",
            bg="#f0f0f0", font=("Arial", 10),
            command=self._on_mode_change
        ).pack(side="left", padx=(0, 6))

        tk.Radiobutton(barre_conn, text="🤖  Robot réel",
            variable=self.mode_var, value="reel",
            bg="#f0f0f0", font=("Arial", 10),
            command=self._on_mode_change
        ).pack(side="left", padx=(0, 8))

        # Bouton IP — ouvre popup modale (reste accessible peu importe la taille)
        self.btn_ip = tk.Button(
            barre_conn, text="🔧 IP du robot",
            font=("Arial", 9), bg="#555", fg="white",
            relief="flat", padx=6, pady=2,
            command=self._popup_configurer_ip,
            state="disabled"
        )
        self.btn_ip.pack(side="left", padx=(0, 8))

        self.label_mode = tk.Label(
            barre_conn, text="● Simulation  (127.0.0.1)",
            fg="#2563eb", bg="#f0f0f0", font=("Arial", 9, "bold")
        )
        self.label_mode.pack(side="right", padx=8)

        # ── Barre statut (bas) ────────────────────────────────────────────────
        barre = tk.Frame(self.root, relief="sunken", borderwidth=1)
        barre.pack(side="bottom", fill="x")
        self.label_statut = tk.Label(barre, text="Prêt.", anchor="w", padx=6)
        self.label_statut.pack(side="left")
        self.bridge.set_status_callback(self._update_statut)
        tk.Button(barre, text="❓ Aide", relief="flat", padx=6,
                  command=lambda: afficher_tutoriel(self.root)).pack(side="right")

    def _popup_configurer_ip(self):
        popup = tk.Toplevel(self.root)
        popup.title("IP du robot NAO")
        popup.resizable(False, False)
        popup.grab_set()
        popup.transient(self.root)
        popup.geometry("300x150+{}+{}".format(
            self.root.winfo_x() + self.root.winfo_width()//2 - 150,
            self.root.winfo_y() + self.root.winfo_height()//2 - 75
        ))
        tk.Label(popup, text="Adresse IP du robot :",
                 font=("Arial", 11, "bold")).pack(pady=(18, 6))
        entry = tk.Entry(popup, width=16, font=("Arial", 13), justify="center")
        ip_def = self.bridge.robot_ip if self.bridge.robot_ip != "127.0.0.1" else "192.168.1.1"
        entry.insert(0, ip_def)
        entry.pack(pady=2)
        entry.focus_set()
        entry.select_range(0, tk.END)

        def _ok():
            ip = entry.get().strip()
            parties = ip.split(".")
            if len(parties) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parties):
                self.bridge.robot_ip = ip
                self.label_mode.config(text="● Robot réel  ({})".format(ip), fg="#15803d")
                self.bridge.log("IP robot réel : {}".format(ip), "INFO")
                self.bridge.update_status("Mode robot réel — {}.".format(ip))
                popup.destroy()
            else:
                entry.config(bg="#fee2e2")

        tk.Button(popup, text="✔ Appliquer", bg="#4a9", fg="white",
                  font=("Arial", 11, "bold"), padx=16, pady=4,
                  command=_ok).pack(pady=10)
        entry.bind("<Return>", lambda e: _ok())
        popup.bind("<Escape>", lambda e: popup.destroy())

    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == "simulation":
            self.bridge.robot_ip = "127.0.0.1"
            self.label_mode.config(text="● Simulation  (127.0.0.1)", fg="#2563eb")
            self.btn_ip.config(state="disabled")
            self.bridge.log("Mode simulation — IP : 127.0.0.1", "INFO")
            self.bridge.update_status("Mode simulation.")
        else:
            self.btn_ip.config(state="normal")
            self.label_mode.config(text="● Robot réel  — IP non configurée", fg="#c44")
            self.bridge.log("Mode robot réel — cliquez 'IP du robot' pour configurer.", "WARN")
            self._popup_configurer_ip()

    def _update_statut(self, msg):
        self.label_statut.config(text=msg)

    def _on_close(self):
        self.bridge.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = NaoApp(root)
    root.mainloop()

