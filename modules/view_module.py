# =============================================================================
# modules/view_module.py — Onglet "Vue NAO"
#
# Affiche en temps réel :
#   - La grille 2D de la scène (Canvas tkinter redessiné à chaque update)
#   - La position du robot (♦ rouge) après chaque déplacement
#   - Le chemin BFS surligné (jaune = itinéraire, rouge = obstacle simulé)
#   - En mode robot réel : flux vidéo caméra dans un panel PanedWindow
#
# Surbrillance contournement :
#   Vert   = cases ○ praticables disponibles
#   Orange = cases ░ convertibles en ○
#   Rouge  = case obstacle
#   Clic sur une case → envoie "case:x:y" via NaoBridge.envoyer_stdin()
#
# Caméra (robot réel, port 8080) :
#   Protocole : 4 octets big-endian (taille) + données JPEG
#   Pillow requis pour l'affichage (pip install Pillow)
# =============================================================================
import tkinter as tk
import threading
import socket
import io
import struct
from modules.base_module import BaseModule

COULEURS = {
    "X": "#222222", "○": "#f5d000", "1": "#ff6666",
    "0": "#888888", "N": "#3366cc", "E": "#ff8800",
    "◘": "#33aa44", "░": "#f0f0f0", "": "#f0f0f0",
}
TAILLE_CASE = 48
PORT_CAM = 8080


class ViewModule(BaseModule):

    def _build(self):
        self.scene = None
        self.nao_pos = None
        self.chemin_positions = []
        self.taille_case = TAILLE_CASE

        # Caméra
        self._cam_active = False
        self._cam_photo = None
        self._cam_mode = "socket"  # "socket" ou "off"

        # Surbrillance obstacle
        self._cases_surbrillance = []   # [(x, y, type)] type = "itin" ou "blanc"
        self._obstacle_pos = None
        self._callback_case_cliquee = None

        self.frame.grid_rowconfigure(0, weight=0)
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_rowconfigure(2, weight=0)
        self.frame.grid_columnconfigure(0, weight=1)

        self._creer_barre_outils()
        self._creer_paned()
        self._creer_statut()

        self.bridge.add_position_callback(self._on_position_update)
        self.bridge.add_chemin_callback(self._on_chemin_update)
        self.frame.after(300, self._poll_scene)
        self.frame.after(1000, self._poll_mode)

    # ── Barre outils ──────────────────────────────────────────────────────────

    def _creer_barre_outils(self):
        fb = tk.Frame(self.frame, pady=4, padx=6, relief="groove", borderwidth=1)
        fb.grid(row=0, column=0, sticky="ew")
        tk.Label(fb, text="Vue NAO", font=("Arial", 11, "bold")).pack(side="left", padx=8)
        tk.Button(fb, text="⏹ Arrêter", bg="#c44", fg="white",
                  command=self.bridge.stop_nao).pack(side="right", padx=4)
        self.slider_zoom = tk.Scale(fb, from_=20, to=100, orient="horizontal",
            showvalue=True, length=150, command=self._on_zoom)
        self.slider_zoom.set(TAILLE_CASE)
        self.slider_zoom.pack(side="right")
        tk.Label(fb, text="Zoom :").pack(side="right", padx=(12, 2))

    def _on_zoom(self, val):
        self.taille_case = int(val)
        self._redessiner()

    
    def _creer_paned(self):
        self.paned = tk.PanedWindow(
            self.frame,
            orient="horizontal",
            sashwidth=6,
            sashrelief="raised",
            bg="#555"
        )

        self.paned.grid(row=1, column=0, sticky="nsew")

        left = tk.Frame(self.paned)

        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self._creer_canvas(left)

        self.paned.add(left, stretch="always", minsize=200)

        self.right_panel = tk.Frame(self.paned, bg="#111")

        self.right_panel.pack_propagate(False)
        self.right_panel.grid_rowconfigure(0, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)

        self._creer_panel_camera(self.right_panel)

    # ── Canvas scène ──────────────────────────────────────────────────────────

    def _creer_canvas(self, parent):
        container = tk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        sy = tk.Scrollbar(container, orient="vertical")
        sy.grid(row=0, column=1, sticky="ns")
        sx = tk.Scrollbar(container, orient="horizontal")
        sx.grid(row=1, column=0, sticky="ew")
        self.canvas = tk.Canvas(container, bg="#2a2a2a",
            xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sx.config(command=self.canvas.xview)
        sy.config(command=self.canvas.yview)
        self.canvas.bind("<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self.canvas.bind("<Shift-MouseWheel>",
            lambda e: self.canvas.xview_scroll(int(-1*(e.delta/120)), "units"))
        # Clic sur le canvas pour sélectionner une case de contournement
        self.canvas.bind("<Button-1>", self._on_canvas_click)

    def _on_canvas_click(self, event):
        """Gère le clic sur le canvas — sélection de case de contournement."""
        if not self._cases_surbrillance or not self._callback_case_cliquee:
            return
        t = self.taille_case
        # Convertir coordonnées canvas (scrollées) en coordonnées grille
        cx = int(self.canvas.canvasx(event.x) / t)
        cy = int(self.canvas.canvasy(event.y) / t)
        for (sx2, sy2, typ) in self._cases_surbrillance:
            if sx2 == cx and sy2 == cy:
                cb = self._callback_case_cliquee
                self._desactiver_surbrillance()
                cb(sx2, sy2)
                return

    
    def _creer_panel_camera(self, parent):

        tk.Label(
            parent,
            text="📷 Caméra NAO",
            bg="#111",
            fg="white",
            font=("Arial", 10, "bold")
        ).pack(pady=(6, 2))

        # Sélecteur de mode caméra
        frame_mode = tk.Frame(parent, bg="#111")
        frame_mode.pack(pady=(0, 4))

        self._cam_mode_var = tk.StringVar(value="socket")

        for val, label in [
            ("socket", "Socket 8080"),
            ("off", "Désactivée")
        ]:

            tk.Radiobutton(
                frame_mode,
                text=label,
                variable=self._cam_mode_var,
                value=val,
                bg="#111",
                fg="#aaa",
                selectcolor="#333",
                activebackground="#111",
                activeforeground="white",
                command=self._changer_mode_cam
            ).pack(side="left", padx=6)

        self.canvas_cam = tk.Canvas(
            parent,
            bg="#000",
            width=320,
            height=240
        )

        self.canvas_cam.pack(
            fill="both",
            expand=True,
            padx=4,
            pady=2
        )

        self._afficher_texte_cam("En attente de connexion...")

        self.label_cam_statut = tk.Label(
            parent,
            text="",
            bg="#111",
            fg="#aaa",
            font=("Arial", 8)
        )

        self.label_cam_statut.pack()

    def _changer_mode_cam(self):
        self._cam_mode = self._cam_mode_var.get()
        self._arreter_camera()
        if self._cam_mode != "off":
            self._demarrer_camera()
        else:
            self._afficher_texte_cam("Caméra désactivée.")

    def _afficher_texte_cam(self, msg, couleur="white"):
        self.canvas_cam.delete("all")
        self.canvas_cam.create_text(160, 120, text=msg,
            fill=couleur, font=("Arial", 10), justify="center")

    # ── Statut ────────────────────────────────────────────────────────────────

    def _creer_statut(self):
        sf = tk.Frame(self.frame, relief="sunken", borderwidth=1, pady=2)
        sf.grid(row=2, column=0, sticky="ew")
        self.label_pos = tk.Label(sf, text="Position NAO : —", anchor="w", padx=8)
        self.label_pos.pack(side="left")
        # Instruction surbrillance
        self.label_instruction = tk.Label(sf, text="", anchor="e", padx=8,
            fg="#f5c842", font=("Arial", 9, "bold"))
        self.label_instruction.pack(side="right")

    
    def _poll_mode(self):
        # Afficher le panel caméra uniquement si robot réel
        est_reel = getattr(self.bridge, "robot_ip", "127.0.0.1") != "127.0.0.1"

        volets = self.paned.panes()
        panel_present = str(self.right_panel) in [str(v) for v in volets]

        if est_reel and not panel_present:
            self.paned.add(self.right_panel, stretch="always", minsize=280)

            if self._cam_mode != "off":
                self._demarrer_camera()

        elif not est_reel and panel_present:
            self.paned.remove(self.right_panel)
            self._arreter_camera()

        self.frame.after(1000, self._poll_mode)

    # ── Caméra via socket 8080 ────────────────────────────────────────────────

    def _demarrer_camera(self):
        if self._cam_active:
            return
        self._cam_active = True
        threading.Thread(target=self._lire_flux_camera, daemon=True).start()

    def _arreter_camera(self):
        self._cam_active = False

    def _lire_flux_camera(self):
        """
        Connexion au serveur camera port 8080.
        Protocole : 4 octets big-endian (taille JPEG) + donnees JPEG.
        Inspire de nao_app_ia.
        """
        ip = self.bridge.robot_ip
        self.frame.after(0, lambda: self._afficher_texte_cam(
            "Connexion caméra\n{}:{}...".format(ip, PORT_CAM)))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((ip, PORT_CAM))
        except Exception as e:
            self.frame.after(0, lambda err=str(e): self._afficher_texte_cam(
                "Caméra inaccessible :\n{}\n\nVérifiez que ServeurNao.bat\nest lancé.".format(err),
                "#f07070"))
            self._cam_active = False
            return

        self.frame.after(0, lambda: self.label_cam_statut.config(
            text="Connecté — port {}".format(PORT_CAM), fg="#4a9"))

        sock.settimeout(10)

        def recv_exact(s, n):
            data = b""
            while len(data) < n:
                chunk = s.recv(n - len(data))
                if not chunk:
                    raise Exception("Connexion fermee")
                data += chunk
            return data

        while self._cam_active:
            try:
                taille_bytes = recv_exact(sock, 4)
                taille = struct.unpack(">I", taille_bytes)[0]
                jpeg_data = recv_exact(sock, taille)
                self._afficher_frame_jpeg(jpeg_data)
            except socket.timeout:
                continue
            except Exception:
                break

        sock.close()
        self.frame.after(0, lambda: self._afficher_texte_cam("Caméra déconnectée."))
        self.frame.after(0, lambda: self.label_cam_statut.config(text="Déconnecté", fg="#aaa"))

# ── Affichage frame JPEG ──────────────────────────────────────────────────

    def _afficher_frame_jpeg(self, jpeg_data):

        def _update():

            try:

                from PIL import Image, ImageTk

                img = Image.open(io.BytesIO(jpeg_data))

                cw = max(1, self.canvas_cam.winfo_width())
                ch = max(1, self.canvas_cam.winfo_height())

                img = img.resize((cw, ch))

                self._cam_photo = ImageTk.PhotoImage(img)

                self.canvas_cam.delete("all")

                self.canvas_cam.create_image(
                    0,
                    0,
                    anchor="nw",
                    image=self._cam_photo
                )

            except ImportError:

                self._afficher_texte_cam(
                    "Installez Pillow :\npip install Pillow",
                    "#f5c842"
                )

                self._cam_active = False

            except Exception:
                pass

        self.frame.after(0, _update)

    # ── Surbrillance cases contournement ─────────────────────────────────────

    def activer_surbrillance_obstacle(self, obstacle, cases_itin, cases_blanches, callback):
        """
        Met en surbrillance les cases cliquables pour contournement.
        cases_itin   : cases ○ praticables (vert)
        cases_blanches: cases ░ convertibles (orange)
        callback     : appelé avec (x, y) quand l'utilisateur clique
        """
        self._desactiver_surbrillance()
        self._obstacle_pos = tuple(obstacle)
        self._callback_case_cliquee = callback
        self._cases_surbrillance = (
            [(c[0], c[1], "itin")  for c in cases_itin] +
            [(c[0], c[1], "blanc") for c in cases_blanches]
        )
        if cases_itin or cases_blanches:
            self.label_instruction.config(
                text="⬆ Cliquez une case verte/orange pour contourner l'obstacle")
        self._redessiner()

    def _desactiver_surbrillance(self):
        self._cases_surbrillance = []
        self._obstacle_pos = None
        self._callback_case_cliquee = None
        self.label_instruction.config(text="")

    # ── Polling scène ─────────────────────────────────────────────────────────

    def _poll_scene(self):
        try:
            while True:
                event_type, data = self.bridge.scene_queue.get_nowait()
                if event_type == "scene_update":
                    self.scene = data
                    self._redessiner()
        except Exception:
            pass
        self.frame.after(300, self._poll_scene)

    def _on_position_update(self, pos):
        self.nao_pos = pos
        self.label_pos.config(text="Position NAO : ({}, {})".format(pos[0], pos[1]))
        self._redessiner()

    def _on_chemin_update(self, positions):
        self.chemin_positions = positions
        self._redessiner()

    # ── Dessin scène ──────────────────────────────────────────────────────────

    def _redessiner(self):
        if not self.scene:
            self.canvas.delete("all")
            self.canvas.create_text(200, 100,
                text="Aucune scène chargée.\nOuvrez un fichier dans l'éditeur.",
                fill="white", font=("Arial", 13), justify="center")
            return

        self.canvas.delete("all")
        t = self.taille_case
        hauteur = len(self.scene)
        largeur = len(self.scene[0]) if hauteur else 0
        chemin_set = {(p[0], p[1]) for p in self.chemin_positions}
        surb_itin  = {(c[0], c[1]) for c in self._cases_surbrillance if c[2] == "itin"}
        surb_blanc = {(c[0], c[1]) for c in self._cases_surbrillance if c[2] == "blanc"}

        for y in range(hauteur):
            for x in range(largeur):
                sym = self.scene[y][x]
                couleur = COULEURS.get(sym, "#f0f0f0")

                if sym == "○":
                    couleur = "#ffe066" if (x, y) in chemin_set else "#aeaeae"
                elif sym == "1" and (x, y) in chemin_set:
                    couleur = "#ff3333"

                # Surbrillance obstacle
                if self._obstacle_pos and (x, y) == self._obstacle_pos:
                    couleur = "#ff2222"  # Obstacle = rouge vif
                elif (x, y) in surb_itin:
                    couleur = "#22dd66"  # Case itinéraire contournement = vert
                elif (x, y) in surb_blanc:
                    couleur = "#ffaa00"  # Case blanche convertible = orange

                x1, y1 = x * t, y * t
                self.canvas.create_rectangle(x1, y1, x1+t, y1+t,
                    fill=couleur, outline="#555", width=1)

                # Bordure pulsée sur les cases cliquables
                if (x, y) in surb_itin or (x, y) in surb_blanc:
                    self.canvas.create_rectangle(x1+2, y1+2, x1+t-2, y1+t-2,
                        fill="", outline="white", width=2)

                if sym not in ("X", "○", "░", "", "N", "E", "1"):
                    self.canvas.create_text(x1+t//2, y1+t//2, text=sym,
                        fill="white" if sym == "0" else "#333",
                        font=("Arial", max(8, t//3), "bold"))

        if self.nao_pos:
            nx, ny = self.nao_pos
            x1, y1 = nx*t+4, ny*t+4
            self.canvas.create_oval(x1, y1, x1+t-8, y1+t-8,
                fill="#ff3333", outline="white", width=2)
            self.canvas.create_text(nx*t+t//2, ny*t+t//2,
                text="♦", fill="white", font=("Arial", max(8, t//3), "bold"))

        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
