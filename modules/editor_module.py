# =============================================================================
# modules/editor_module.py — Onglet "Éditeur de scène"
#
# Permet de dessiner la carte de navigation sous forme de grille 2D.
#
# Symboles :
#   X = mur/obstacle   ○ = case praticable   N = départ NAO
#   E = orientation    ◘ = objectif          1 = obstacle simulé
#   ░ = case vide
#
# Fonctionnalités :
#   Zoom : slider + Ctrl+molette | Scroll : molette + Shift+molette
#   Undo/Redo : historique par copie profonde de la scène
#   E uniquement adjacent à N (surbrillance cyan)
#   Tooltips sur les boutons (1 seconde de survol)
#   Sauvegarde/chargement JSON | Vérification N/E/◘ avant lancement
# =============================================================================
import tkinter as tk
from tkinter import filedialog
import json

from modules.base_module import BaseModule

TAILLE = 40
SYMBOLES = ["X", "○", "N", "E", "◘", "1"]
COULEURS = {
    "X": "black",
    "○": "yellow",
    "N": "blue",
    "E": "orange",
    "◘": "green",
    "1": "#ff6666",
    "░": "white"
}

TOOLTIPS = {
    "X":  "Mur / obstacle",
    "○":  "Case praticable (itinéraire)",
    "N":  "Position de départ de NAO",
    "E":  "Orientation initiale (adjacent à N)",
    "◘":  "Objectif à atteindre",
    "1":  "Obstacle simulé (détecté en temps réel)",
    "🧼": "Effacer une case",
}

GRILLE_ROW_OFFSET = 0
HAUTEUR_MAX_PAR_COLONNE = 5
LARGEUR_MIN, LARGEUR_MAX = 5, 30
HAUTEUR_MIN, HAUTEUR_MAX = 5, 30


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._job = None
        self._tip = None
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)

    def _on_enter(self, event):
        self._job = self.widget.after(1000, self._afficher)

    def _on_leave(self, event):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        self._masquer()

    def _afficher(self):
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        lbl = tk.Label(
            self._tip, text=self.text,
            background="#ffffc0", relief="solid", borderwidth=1,
            font=("Arial", 9), padx=6, pady=3
        )
        lbl.pack()
        self._tip.update_idletasks()
        tw = self._tip.winfo_width()
        screen_w = self.widget.winfo_screenwidth()
        x_droite = self.widget.winfo_rootx() + self.widget.winfo_width() + 4
        x_gauche = self.widget.winfo_rootx() - tw - 4
        y = self.widget.winfo_rooty() + self.widget.winfo_height() // 2
        x = x_gauche if x_droite + tw > screen_w else x_droite
        self._tip.wm_geometry("+{}+{}".format(x, y))

    def _masquer(self):
        if self._tip:
            self._tip.destroy()
            self._tip = None


class EditorModule(BaseModule):

    def _build(self):
        self.largeur = 10
        self.hauteur = 10
        self.scene = [["░" for _ in range(self.largeur)] for _ in range(self.hauteur)]
        self.labels = []
        self.zoom_manuel = TAILLE
        self.zoom_min = 20
        self.zoom_max = 120
        self.selection = 0
        self.mode = "dessin"
        self.historique = []
        self.futur = []
        self.chemin_courant = None
        # Surbrillance cases adjacentes à N pour placement de E
        self._cases_surbrillance = []

        self.frame.grid_rowconfigure(0, weight=0)
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_rowconfigure(2, weight=0)
        self.frame.grid_rowconfigure(3, weight=0)
        self.frame.grid_columnconfigure(0, weight=0)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_columnconfigure(2, weight=0)

        self._creer_barre_zoom()
        self._creer_panneau_gauche()
        self._creer_canvas()
        self._creer_panneau_droite()
        self._creer_barre_bas()
        self._creer_grille()

        self.frame.bind("<Control-z>", lambda e: self.undo())
        self.frame.bind("<Control-y>", lambda e: self.redo())
        self.frame.after(200, self.centrer_grille)

    # ── Barre zoom ────────────────────────────────────────────────────────────

    def _creer_barre_zoom(self):
        fz = tk.Frame(self.frame, pady=4, padx=6)
        fz.grid(row=0, column=0, columnspan=3, sticky="ew")
        tk.Label(fz, text="Zoom :").pack(side="left", padx=(0, 6))
        self.slider_zoom = tk.Scale(
            fz, from_=self.zoom_min, to=self.zoom_max,
            orient="horizontal", showvalue=True, length=220,
            command=self._on_slider_zoom
        )
        self.slider_zoom.set(TAILLE)
        self.slider_zoom.pack(side="left")

    def _on_slider_zoom(self, val):
        self.zoom_manuel = int(val)
        self._appliquer_zoom(self.zoom_manuel)

    # ── Panneau gauche ────────────────────────────────────────────────────────

    def _creer_panneau_gauche(self):
        p = tk.Frame(self.frame, padx=12, pady=8, relief="groove", borderwidth=1)
        p.grid(row=1, column=0, sticky="n", padx=(6, 4), pady=4)

        tk.Label(p, text="Dimensions", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 2))
        tk.Label(p, text="actuelles", font=("Arial", 10, "bold")).grid(row=1, column=0, columnspan=2, pady=(0, 6))
        self.label_dims = tk.Label(p, text="{}x{}".format(self.largeur, self.hauteur), font=("Arial", 10))
        self.label_dims.grid(row=2, column=0, columnspan=2, pady=(0, 12))

        tk.Label(p, text="Largeur :").grid(row=3, column=0, sticky="e", pady=2)
        self.entry_largeur = tk.Entry(p, width=5)
        self.entry_largeur.insert(0, str(self.largeur))
        self.entry_largeur.grid(row=3, column=1, sticky="w", pady=2)

        tk.Label(p, text="Hauteur :").grid(row=4, column=0, sticky="e", pady=2)
        self.entry_hauteur = tk.Entry(p, width=5)
        self.entry_hauteur.insert(0, str(self.hauteur))
        self.entry_hauteur.grid(row=4, column=1, sticky="w", pady=2)

        tk.Label(p, text="({}-{})".format(LARGEUR_MIN, LARGEUR_MAX), font=("Arial", 8), fg="gray").grid(row=3, column=2, sticky="w", padx=2)
        tk.Label(p, text="({}-{})".format(HAUTEUR_MIN, HAUTEUR_MAX), font=("Arial", 8), fg="gray").grid(row=4, column=2, sticky="w", padx=2)
        tk.Button(p, text="Appliquer", command=self._appliquer_dimensions).grid(row=5, column=0, columnspan=3, pady=(10, 0))

    def _appliquer_dimensions(self):
        try:
            nw = int(self.entry_largeur.get())
            nh = int(self.entry_hauteur.get())
            if not (LARGEUR_MIN <= nw <= LARGEUR_MAX): return
            if not (HAUTEUR_MIN <= nh <= HAUTEUR_MAX): return
        except ValueError:
            return
        for w in self.canvas_frame.winfo_children():
            w.destroy()
        self.largeur, self.hauteur = nw, nh
        self.scene = [["░"] * self.largeur for _ in range(self.hauteur)]
        self.labels = []
        self.label_dims.config(text="{}x{}".format(self.largeur, self.hauteur))
        self._creer_grille()
        self.frame.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        t = min(max(self.zoom_min, min(cw // self.largeur, ch // self.hauteur)), self.zoom_max)
        self.zoom_manuel = t
        self.slider_zoom.set(t)
        self._appliquer_zoom(t)
        self.frame.after(50, self.centrer_grille)

    # ── Canvas scrollable ─────────────────────────────────────────────────────

    def _creer_canvas(self):
        self.scroll_y = tk.Scrollbar(self.frame, orient="vertical")
        self.scroll_y.grid(row=1, column=1, sticky="nse")
        self.scroll_x = tk.Scrollbar(self.frame, orient="horizontal")
        self.scroll_x.grid(row=2, column=1, sticky="ew")

        self.canvas = tk.Canvas(
            self.frame,
            xscrollcommand=self.scroll_x.set,
            yscrollcommand=self.scroll_y.set,
            bg="#e8e8e8"
        )
        self.canvas.grid(row=1, column=1, sticky="nsew")
        self.scroll_x.config(command=self.canvas.xview)
        self.scroll_y.config(command=self.canvas.yview)

        self.canvas_frame = tk.Frame(self.canvas, bg="#e8e8e8")
        self.canvas_window = self.canvas.create_window((0, 0), window=self.canvas_frame, anchor="nw")

        self.canvas_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Molette seule = scroll vertical
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        # Shift+molette = scroll horizontal
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_mousewheel_x)
        # Ctrl+molette = zoom
        self.canvas.bind_all("<Control-MouseWheel>", self._on_mousewheel_zoom)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.centrer_grille()

    def _on_canvas_configure(self, event):
        self.centrer_grille()

    def centrer_grille(self):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        fw = self.canvas_frame.winfo_reqwidth()
        fh = self.canvas_frame.winfo_reqheight()
        x = max(0, (cw - fw) // 2)
        y = max(0, (ch - fh) // 2)
        self.canvas.coords(self.canvas_window, x, y)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_x(self, event):
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_zoom(self, event):
        # Ctrl+molette : zoom +5 ou -5
        delta = 5 if event.delta > 0 else -5
        nouveau = max(self.zoom_min, min(self.zoom_max, self.zoom_manuel + delta))
        self.zoom_manuel = nouveau
        self.slider_zoom.set(nouveau)
        self._appliquer_zoom(nouveau)

    # ── Panneau droite ────────────────────────────────────────────────────────

    def _creer_panneau_droite(self):
        p = tk.Frame(self.frame, padx=8, pady=8, relief="groove", borderwidth=1)
        p.grid(row=1, column=2, sticky="n", padx=(4, 6), pady=4)

        tous = SYMBOLES + ["🧼"]
        self.boutons_symboles = []
        nb_cols = 0

        for i, sym in enumerate(tous):
            col = i // HAUTEUR_MAX_PAR_COLONNE
            row = i % HAUTEUR_MAX_PAR_COLONNE
            nb_cols = max(nb_cols, col + 1)

            if sym == "🧼":
                btn = tk.Button(p, text=sym, width=3, command=self.effacer)
                self.bouton_effacer = btn
            else:
                idx = SYMBOLES.index(sym)
                btn = tk.Button(p, text=sym, width=3, command=lambda i=idx: self.set_selection(i))
                self.boutons_symboles.append(btn)
            btn.grid(row=row, column=col, padx=2, pady=2)
            if sym in TOOLTIPS:
                Tooltip(btn, TOOLTIPS[sym])

        nb_rows = min(len(tous), HAUTEUR_MAX_PAR_COLONNE)
        tk.Frame(p, height=1, bg="gray").grid(row=nb_rows, column=0, columnspan=nb_cols, sticky="ew", pady=6)

        # Boutons undo/redo plus grands avec texte
        self.btn_undo = tk.Button(p, text="↩ Annuler", command=self.undo, padx=4)
        self.btn_undo.grid(row=nb_rows + 1, column=0, columnspan=nb_cols, padx=2, pady=2, sticky="ew")
        self.btn_redo = tk.Button(p, text="↪ Rétablir", command=self.redo, padx=4)
        self.btn_redo.grid(row=nb_rows + 2, column=0, columnspan=nb_cols, padx=2, pady=2, sticky="ew")
        Tooltip(self.btn_undo, "Annuler (Ctrl+Z)")
        Tooltip(self.btn_redo, "Rétablir (Ctrl+Y)")

        self._actualiser_selection()

    # ── Barre bas ─────────────────────────────────────────────────────────────

    def _creer_barre_bas(self):
        fb = tk.Frame(self.frame, pady=4)
        fb.grid(row=3, column=0, columnspan=3, sticky="ew")
        for i in range(5):
            fb.grid_columnconfigure(i, weight=1)

        tk.Button(fb, text="💾 Enregistrer", command=self.sauvegarder).grid(row=0, column=0, sticky="ew", padx=4)
        tk.Button(fb, text="💾 Enregistrer sous", command=self.sauvegarder_sous).grid(row=0, column=1, sticky="ew", padx=4)
        tk.Button(fb, text="♻️ Charger", command=self.charger).grid(row=0, column=2, sticky="ew", padx=4)
        tk.Button(fb, text="🗑️ Clear", command=self.clear).grid(row=0, column=3, sticky="ew", padx=4)
        tk.Button(fb, text="▶ Lancer NAO", command=self._lancer_nao,
                  bg="#4a9", fg="white", font=("Arial", 10, "bold")).grid(row=0, column=4, sticky="ew", padx=4)

    def _lancer_nao(self):
        if not self.chemin_courant:
            self.bridge.log("Sauvegardez d'abord la scène (Enregistrer sous) avant de lancer NAO.", "WARN")
            return
        # Vérification que N, E et ◘ sont présents dans la scène
        manquants = []
        for sym, nom in [("N", "N (départ)"), ("E", "E (orientation)"), ("◘", "◘ (objectif)")]:
            trouve = any(self.scene[y][x] == sym
                        for y in range(self.hauteur)
                        for x in range(self.largeur))
            if not trouve:
                manquants.append(nom)
        if manquants:
            self.bridge.log(
                "Scène incomplète — symboles manquants : {}".format(", ".join(manquants)),
                "ERROR")
            return
        with open(self.chemin_courant, "w", encoding="utf-8") as f:
            json.dump(self.scene, f, ensure_ascii=False, indent=2)
        self.bridge.set_scene(self.scene, self.chemin_courant)
        self.bridge.launch_nao(self.chemin_courant)

    # ── Grille ────────────────────────────────────────────────────────────────

    def _creer_grille(self):
        for y in range(self.hauteur):
            ligne = []
            for x in range(self.largeur):
                lbl = tk.Label(self.canvas_frame, text="", bg="white", borderwidth=1, relief="solid")
                lbl.grid(row=GRILLE_ROW_OFFSET + y, column=x, sticky="nsew")
                lbl.bind("<Button-1>", lambda e, x=x, y=y: self._debut_action(x, y))
                lbl.bind("<B1-Motion>", self._glisser)
                ligne.append(lbl)
            self.labels.append(ligne)
        self._appliquer_zoom(self.zoom_manuel)

    def _glisser(self, event):
        ax = event.widget.winfo_rootx() + event.x
        ay = event.widget.winfo_rooty() + event.y
        widget = self.frame.winfo_containing(ax, ay)
        if widget is None or not isinstance(widget, tk.Label):
            return
        info = widget.grid_info()
        if not info:
            return
        x = info.get("column")
        row = info.get("row")
        if x is None or row is None:
            return
        y = row - GRILLE_ROW_OFFSET
        if y < 0 or y >= self.hauteur or x >= self.largeur:
            return
        self.cliquer(x, y)

    # ── Surbrillance cases adjacentes à N ────────────────────────────────────

    def _cases_adjacentes_N(self):
        """Retourne les cases (x,y) valides adjacentes à N."""
        nao = None
        for y in range(self.hauteur):
            for x in range(self.largeur):
                if self.scene[y][x] == "N":
                    nao = (x, y)
                    break
        if not nao:
            return []
        nx, ny = nao
        adjacentes = []
        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            ax, ay = nx + dx, ny + dy
            if 0 <= ax < self.largeur and 0 <= ay < self.hauteur:
                adjacentes.append((ax, ay))
        return adjacentes

    def _activer_surbrillance_E(self):
        """Met en surbrillance les cases adjacentes à N."""
        self._desactiver_surbrillance()
        adjacentes = self._cases_adjacentes_N()
        if not adjacentes:
            self.bridge.log("Placez d'abord N (position de départ) avant de placer E.", "WARN")
            return
        for (x, y) in adjacentes:
            sym = self.scene[y][x]
            couleur_actuelle = COULEURS.get(sym, "white")
            # Surbrillance cyan par-dessus la couleur actuelle
            self.labels[y][x].config(bg="#00e5ff", relief="raised", borderwidth=2)
            self._cases_surbrillance.append((x, y, couleur_actuelle))

    def _desactiver_surbrillance(self):
        """Retire la surbrillance des cases."""
        for (x, y, couleur) in self._cases_surbrillance:
            sym = self.scene[y][x]
            self.labels[y][x].config(bg=COULEURS.get(sym, "white"), relief="solid", borderwidth=1)
        self._cases_surbrillance = []

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _appliquer_zoom(self, taille):
        font_size = max(8, taille // 3)
        for x in range(self.largeur):
            self.canvas_frame.grid_columnconfigure(x, weight=0, minsize=taille)
        for y in range(self.hauteur):
            self.canvas_frame.grid_rowconfigure(GRILLE_ROW_OFFSET + y, weight=0, minsize=taille)
        for y in range(self.hauteur):
            for x in range(self.largeur):
                self.labels[y][x].config(width=1, height=1, font=("Arial", font_size))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _sauvegarder_etat(self):
        self.historique.append([ligne[:] for ligne in self.scene])
        self.futur.clear()

    def undo(self):
        if not self.historique:
            return
        self.futur.append([ligne[:] for ligne in self.scene])
        self.scene = self.historique.pop()
        self.refresh()

    def redo(self):
        if not self.futur:
            return
        self.historique.append([ligne[:] for ligne in self.scene])
        self.scene = self.futur.pop()
        self.refresh()

    def _actualiser_selection(self):
        for i, btn in enumerate(self.boutons_symboles):
            btn.config(bg="lightblue" if i == self.selection and self.mode == "dessin" else "SystemButtonFace")
        self.bouton_effacer.config(bg="lightblue" if self.mode == "effacer" else "SystemButtonFace")

    def set_selection(self, i):
        sym = SYMBOLES[i]
        self.selection = i
        self.mode = "dessin"
        self._actualiser_selection()
        # Si on sélectionne E, activer la surbrillance des cases adjacentes à N
        if sym == "E":
            self._activer_surbrillance_E()
        else:
            self._desactiver_surbrillance()

    def effacer(self):
        self.mode = "effacer"
        self._desactiver_surbrillance()
        self._actualiser_selection()

    def _debut_action(self, x, y):
        self._sauvegarder_etat()
        self.cliquer(x, y)

    def cliquer(self, x, y):
        if self.mode == "effacer":
            self.scene[y][x] = "░"
            self.labels[y][x].config(bg="white", text="", relief="solid", borderwidth=1)
        else:
            sym = SYMBOLES[self.selection]

            # Restriction placement E : uniquement sur les cases adjacentes à N
            if sym == "E":
                adjacentes = self._cases_adjacentes_N()
                if not adjacentes:
                    self.bridge.log("Placez d'abord N avant de placer E.", "WARN")
                    return
                if (x, y) not in adjacentes:
                    self.bridge.log("E doit être placé sur une case adjacente à N.", "WARN")
                    return

            if sym in ("E", "N", "◘"):
                for iy in range(self.hauteur):
                    for ix in range(self.largeur):
                        if self.scene[iy][ix] == sym:
                            self.scene[iy][ix] = "░"
                            self.labels[iy][ix].config(bg="white", text="", relief="solid", borderwidth=1)

            self.scene[y][x] = sym
            self.labels[y][x].config(
                bg=COULEURS[sym],
                text="" if sym in ("X", "○", "░", "1") else sym,
                relief="solid", borderwidth=1
            )

            # Si on vient de poser N, réactiver la surbrillance E si E est l'outil actif
            if sym == "N" and SYMBOLES[self.selection] == "E":
                self._activer_surbrillance_E()

        self.bridge.set_scene(self.scene, self.chemin_courant)
        # Désactiver surbrillance après placement de E
        if self.mode == "dessin" and SYMBOLES[self.selection] == "E" and (x, y) in [c[:2] for c in self._cases_surbrillance]:
            self._desactiver_surbrillance()

    def sauvegarder(self):
        if self.chemin_courant:
            with open(self.chemin_courant, "w", encoding="utf-8") as f:
                json.dump(self.scene, f, ensure_ascii=False, indent=2)
            self.bridge.log("Scène sauvegardée : {}".format(self.chemin_courant), "INFO")
            self.bridge.update_status("Sauvegardé : {}".format(self.chemin_courant))
        else:
            self.sauvegarder_sous()

    def sauvegarder_sous(self):
        chemin = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Fichiers JSON", "*.json")],
            initialfile="scene.json"
        )
        if not chemin:
            return
        self.chemin_courant = chemin
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(self.scene, f, ensure_ascii=False, indent=2)
        self.bridge.log("Scène sauvegardée : {}".format(chemin), "INFO")
        self.bridge.update_status("Sauvegardé : {}".format(chemin))
        self.bridge.set_scene(self.scene, chemin)

    def charger(self):
        chemin = filedialog.askopenfilename(filetypes=[("Fichiers JSON", "*.json")])
        if not chemin:
            return
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                data = json.load(f)
            nh = len(data)
            nw = len(data[0]) if data else 0
            if not (LARGEUR_MIN <= nw <= LARGEUR_MAX):
                return
            if not (HAUTEUR_MIN <= nh <= HAUTEUR_MAX):
                return
            if nw != self.largeur or nh != self.hauteur:
                for w in self.canvas_frame.winfo_children():
                    w.destroy()
                self.largeur, self.hauteur = nw, nh
                self.labels = []
                self.label_dims.config(text="{}x{}".format(nw, nh))
                self.entry_largeur.delete(0, tk.END)
                self.entry_largeur.insert(0, str(nw))
                self.entry_hauteur.delete(0, tk.END)
                self.entry_hauteur.insert(0, str(nh))
                self._creer_grille()
                self.frame.update_idletasks()
                cw = self.canvas.winfo_width()
                ch = self.canvas.winfo_height()
                t = min(max(self.zoom_min, min(cw // nw, ch // nh)), self.zoom_max)
                self.zoom_manuel = t
                self.slider_zoom.set(t)
                self._appliquer_zoom(t)
            self.scene = data
            self.chemin_courant = chemin
            self.refresh()
            self.frame.after(50, self.centrer_grille)
            self.bridge.log("Scène chargée : {}".format(chemin), "INFO")
            self.bridge.update_status("Chargé : {}".format(chemin))
            self.bridge.set_scene(self.scene, chemin)
        except Exception as e:
            self.bridge.log("Erreur chargement : {}".format(e), "ERROR")

    def clear(self):
        self._sauvegarder_etat()
        self._desactiver_surbrillance()
        for y in range(self.hauteur):
            for x in range(self.largeur):
                self.scene[y][x] = ""
                self.labels[y][x].config(text="", bg="white", relief="solid", borderwidth=1)
        self.bridge.log("Scène réinitialisée.", "INFO")

    def refresh(self):
        self._desactiver_surbrillance()
        for y in range(self.hauteur):
            for x in range(self.largeur):
                sym = self.scene[y][x]
                self.labels[y][x].config(
                    bg=COULEURS.get(sym, "white"),
                    text="" if sym in ("X", "○", "░", "1") else sym,
                    relief="solid", borderwidth=1
                )
