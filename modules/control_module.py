# =============================================================================
# modules/control_module.py — Onglet "Contrôle Manuel"
#
# Permet de piloter le robot manuellement en temps réel.
#
# Ports :
#   9561 : commandes (handshake "CONTROL", debut:/fin:, tete:, actions)
#   8080 : flux vidéo JPEG (affiché en plein écran dans le Canvas)
#
# Clavier :
#   Z/Q/S/D  = déplacements (continus — maintenir enfoncé)
#   A/E      = rotations (continus)
#   Flèches  = tête (discret, une commande par appui)
#
# Actions : Bonjour (animation), S'asseoir, Se lever, TTS (parler)
# =============================================================================
import tkinter as tk
import threading
import socket
import struct
import io
from modules.base_module import BaseModule

# ── Ports ─────────────────────────────────────────────────────────────────────
PORT_SERVER = 9561   # Commandes robot
PORT_CAM    = 8080   # Flux vidéo

# ── Mapping touches clavier → actions robot ───────────────────────────────────
# Ces touches déclenchent un mouvement CONTINU (debut:/fin:)
TOUCHES_CORPS = {
    "z": "avant",           # Avancer
    "s": "arriere",         # Reculer
    "q": "gauche",          # Déplacement latéral gauche (marche crabe)
    "d": "droite",          # Déplacement latéral droite
    "a": "rotation_gauche", # Rotation sur place vers la gauche
    "e": "rotation_droite", # Rotation sur place vers la droite
}

# Ces touches déplacent la tête (discret, une fois par appui)
TOUCHES_TETE = {
    "up":    "haut",    # Tête vers le haut
    "down":  "bas",     # Tête vers le bas
    "left":  "gauche",  # Tête vers la gauche
    "right": "droite",  # Tête vers la droite
}

# ── Couleurs des boutons ───────────────────────────────────────────────────────
BG_CORPS = "#4a9"    # Vert : déplacements principaux (ZQSD)
BG_ROT   = "#669"    # Violet : rotations (A/E)
BG_TETE  = "#555"    # Gris : contrôle tête
BG_ACT   = "#ffffff" # Blanc : bouton enfoncé


class ControlModule(BaseModule):
    """
    Module de contrôle manuel du robot NAO.
    Hérite de BaseModule qui fournit self.frame et self.bridge.
    """

    def _build(self):
        """Initialise le module et construit l'interface."""
        # ── État connexion ──
        self._connecte          = False
        self._sock              = None      # Socket commandes (port 9561)
        self._touches_enfoncees = set()     # Touches actuellement enfoncées

        # ── État caméra ──
        self._cam_active = False
        self._cam_photo  = None             # Référence image (anti-GC tkinter)
        self._sock_cam   = None             # Socket caméra (port 8080)


        # ── Layout : grille 3 lignes × 2 colonnes ──
        # Ligne 0 : barre d'outils (colspan 2)
        # Ligne 1 : caméra | panneau contrôles
        # Ligne 2 : barre de statut (colspan 2)
        self.frame.grid_rowconfigure(0, weight=0)
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_rowconfigure(2, weight=0)
        self.frame.grid_columnconfigure(0, weight=1)   # Caméra : extensible
        self.frame.grid_columnconfigure(1, weight=0)   # Panneau : taille fixe

        self._creer_barre_outils()
        self._creer_canvas_camera()
        self._creer_panneau_controles()
        self._creer_statut()

        # Bind clavier sur le frame — actif après clic sur la caméra
        self.frame.bind("<KeyPress>",   self._on_key_press)
        self.frame.bind("<KeyRelease>", self._on_key_release)

    # =========================================================================
    # INTERFACE
    # =========================================================================

    def _creer_barre_outils(self):
        """Barre du haut : connexion, état, instructions."""
        fb = tk.Frame(self.frame, pady=4, padx=8, relief="groove", borderwidth=1)
        fb.grid(row=0, column=0, columnspan=2, sticky="ew")

        tk.Label(fb, text="🎮 Contrôle Manuel",
                 font=("Arial", 11, "bold")).pack(side="left", padx=8)

        # Bouton Connecter — démarre la connexion en arrière-plan
        self.btn_connect = tk.Button(
            fb, text="🔌 Connecter",
            bg="#4a9", fg="white", font=("Arial", 9, "bold"),
            padx=8, relief="flat", command=self._connecter
        )
        self.btn_connect.pack(side="left", padx=4)

        # Bouton Déconnecter — ferme toutes les connexions proprement
        self.btn_disconnect = tk.Button(
            fb, text="⏹ Déconnecter",
            bg="#c44", fg="white", font=("Arial", 9, "bold"),
            padx=8, relief="flat", command=self._deconnecter, state="disabled"
        )
        self.btn_disconnect.pack(side="left", padx=4)

        # Indicateur d'état connexion
        self.label_conn = tk.Label(
            fb, text="● Déconnecté", fg="#c44", font=("Arial", 9, "bold")
        )
        self.label_conn.pack(side="left", padx=12)

        tk.Label(
            fb, text="Cliquez sur la caméra pour activer le clavier",
            fg="#888", font=("Arial", 8, "italic")
        ).pack(side="right", padx=8)

    def _creer_canvas_camera(self):
        """Zone d'affichage du flux vidéo de la caméra."""
        self.canvas_cam = tk.Canvas(self.frame, bg="#000", width=640, height=480)
        self.canvas_cam.grid(row=1, column=0, sticky="nsew", padx=(6, 3), pady=4)
        self._afficher_texte_cam("Connectez-vous pour afficher\nla caméra du robot")

        # Clic sur la caméra → donne le focus au frame pour le clavier
        self.canvas_cam.bind("<Button-1>", lambda e: self.frame.focus_set())

    def _afficher_texte_cam(self, msg, couleur="white"):
        """Affiche un message texte centré dans le canvas caméra."""
        self.canvas_cam.delete("all")
        self.canvas_cam.create_text(
            320, 240, text=msg,
            fill=couleur, font=("Arial", 14), justify="center"
        )

    def _creer_panneau_controles(self):
        """
        Panneau de droite : boutons de contrôle organisés en sections.
        Sections : Corps (ZQSD), Tête (flèches), Actions, Audio, TTS.
        """
        p = tk.Frame(
            self.frame, relief="groove", borderwidth=1,
            padx=10, pady=8, bg="#1e1e1e", width=240
        )
        p.grid(row=1, column=1, sticky="ns", padx=(3, 6), pady=4)
        p.grid_propagate(False)  # Taille fixe même si le contenu est plus petit
        self._btns = {}  # Référence boutons pour flash visuel

        # ── Section Corps ─────────────────────────────────────────────────────
        # Layout AZERTY : A Z E sur ligne 0, Q S D sur ligne 1
        tk.Label(
            p, text="Corps", font=("Arial", 10, "bold"),
            bg="#1e1e1e", fg="white"
        ).pack(pady=(0, 4))

        grid_corps = tk.Frame(p, bg="#1e1e1e")
        grid_corps.pack()

        positions = {
            "a": (0, 0), "z": (0, 1), "e": (0, 2),
            "q": (1, 0), "s": (1, 1), "d": (1, 2)
        }
        labels = {
            "z": "⬆ Z", "q": "← Q", "s": "⬇ S",
            "d": "→ D", "a": "↺ A", "e": "↻ E"
        }
        bg_map = {
            "z": BG_CORPS, "q": BG_CORPS, "s": BG_CORPS,
            "d": BG_CORPS, "a": BG_ROT,   "e": BG_ROT
        }

        for key, (r, c) in positions.items():
            btn = tk.Button(
                grid_corps, text=labels[key], width=6, height=2,
                bg=bg_map[key], fg="white", relief="raised",
                font=("Arial", 9, "bold"), activebackground=BG_ACT
            )
            btn.grid(row=r, column=c, padx=2, pady=2)
            # ButtonPress/Release pour le mouvement continu (comme le clavier)
            btn.bind("<ButtonPress-1>",   lambda e, k=key: self._debut_action(k))
            btn.bind("<ButtonRelease-1>", lambda e, k=key: self._fin_action(k))
            self._btns[key] = btn
            btn._bg_normal = bg_map[key]  # Couleur de repos pour le reset visuel

        # ── Section Tête ─────────────────────────────────────────────────────
        tk.Frame(p, height=1, bg="#444").pack(fill="x", pady=6)
        tk.Label(
            p, text="Tête (flèches)", font=("Arial", 10, "bold"),
            bg="#1e1e1e", fg="white"
        ).pack(pady=(0, 4))

        grid_tete = tk.Frame(p, bg="#1e1e1e")
        grid_tete.pack()

        tete_pos    = {"up": (0,1), "left": (1,0), "centre": (1,1), "right": (1,2), "down": (2,1)}
        tete_labels = {"up": "▲", "down": "▼", "left": "◄", "right": "►", "centre": "●"}

        for key, (r, c) in tete_pos.items():
            btn = tk.Button(
                grid_tete, text=tete_labels[key], width=3, height=1,
                bg=BG_TETE, fg="white", relief="raised", font=("Arial", 11)
            )
            btn.grid(row=r, column=c, padx=2, pady=2)
            btn.bind("<ButtonPress-1>", lambda e, k=key: self._action_tete(k))
            self._btns["tete_" + key] = btn
            btn._bg_normal = BG_TETE

        # ── Section Actions ───────────────────────────────────────────────────
        tk.Frame(p, height=1, bg="#444").pack(fill="x", pady=6)
        tk.Label(
            p, text="Actions", font=("Arial", 10, "bold"),
            bg="#1e1e1e", fg="white"
        ).pack(pady=(0, 4))

        # Bonjour : animation salut avec le bras droit
        tk.Button(
            p, text="👋 Bonjour", width=16,
            bg="#c87", fg="white", relief="raised", font=("Arial", 9),
            command=self._action_bonjour
        ).pack(pady=2)

        # S'asseoir / Se lever : postures NAO
        tk.Button(
            p, text="🪑 S'asseoir", width=16,
            bg="#558", fg="white", relief="raised", font=("Arial", 9),
            command=self._action_sit
        ).pack(pady=2)

        tk.Button(
            p, text="🧍 Se lever", width=16,
            bg="#558", fg="white", relief="raised", font=("Arial", 9),
            command=self._action_standup
        ).pack(pady=2)

        # ── Section TTS ───────────────────────────────────────────────────────
        # Envoie du texte au robot qui le dit avec sa voix
        tk.Frame(p, height=1, bg="#444").pack(fill="x", pady=6)
        tk.Label(
            p, text="Parler (TTS)", font=("Arial", 10, "bold"),
            bg="#1e1e1e", fg="white"
        ).pack(pady=(0, 4))

        self.entry_tts = tk.Entry(p, width=18, font=("Arial", 9))
        self.entry_tts.pack(pady=2)
        # Entrée valide le texte comme un clic sur le bouton
        self.entry_tts.bind("<Return>", lambda e: self._action_tts())

        tk.Button(
            p, text="▶ Dire", width=16,
            bg="#558", fg="white", relief="raised", font=("Arial", 9),
            command=self._action_tts
        ).pack(pady=2)

        # ── Dernière commande envoyée ─────────────────────────────────────────
        tk.Frame(p, height=1, bg="#444").pack(fill="x", pady=6)
        self.label_cmd = tk.Label(
            p, text="—", font=("Consolas", 9, "bold"),
            bg="#1e1e1e", fg="#f5c842"
        )
        self.label_cmd.pack(anchor="w")

    def _creer_statut(self):
        """Barre de statut en bas."""
        sf = tk.Frame(self.frame, relief="sunken", borderwidth=1, pady=2)
        sf.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.label_statut_ctrl = tk.Label(
            sf, text="Déconnecté — cliquez sur Connecter",
            anchor="w", padx=8, font=("Arial", 9)
        )
        self.label_statut_ctrl.pack(side="left")

    def _set_statut(self, msg, couleur="#333"):
        """Met à jour le texte de la barre de statut."""
        self.label_statut_ctrl.config(text=msg, fg=couleur)

    # =========================================================================
    # CONNEXION AU SERVEUR NAO
    # =========================================================================

    def _connecter(self):
        """Lance la connexion en arrière-plan (thread daemon)."""
        ip = getattr(self.bridge, "robot_ip", "127.0.0.1")
        self._set_statut("Connexion à {}...".format(ip))
        threading.Thread(
            target=self._thread_connexion, args=(ip,), daemon=True
        ).start()

    def _thread_connexion(self, ip):
        """
        Thread de connexion :
        1. Connexion TCP sur port 9561
        2. Envoi du handshake "CONTROL\n"
        3. Attente des messages INIT: et PRET du serveur
        4. Démarrage des threads de réception et caméra
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, PORT_SERVER))

            # Identification : ce client est un contrôleur manuel (pas navigation)
            sock.send("CONTROL\n".encode())

            # Lecture des messages d'init jusqu'au signal PRET
            buf  = ""
            pret = False
            while not pret:
                data = sock.recv(1024).decode(errors="replace")
                if not data:
                    raise Exception("Connexion fermée pendant l'initialisation")
                buf += data
                for ligne in buf.split("\n")[:-1]:
                    ligne = ligne.strip()
                    if ligne.startswith("INIT:"):
                        # Afficher les étapes d'init dans les logs
                        self.bridge.log("[CTRL] " + ligne[5:], "INFO")
                    elif ligne == "PRET":
                        pret = True
                        break
                buf = buf.split("\n")[-1]

            sock.settimeout(None)  # Mode bloquant pour la suite
            self._sock     = sock
            self._connecte = True
            self.frame.after(0, self._on_connecte)

            # Thread qui reçoit les réponses du serveur et détecte la déconnexion
            threading.Thread(
                target=self._recevoir_boucle, daemon=True
            ).start()

            # Démarrer le flux caméra en parallèle
            self._demarrer_camera(ip)

        except Exception as e:
            self.frame.after(
                0, lambda err=str(e): self._set_statut("Erreur : {}".format(err), "#c44")
            )

    def _on_connecte(self):
        """Appelé dans le thread principal quand la connexion est établie."""
        ip = getattr(self.bridge, "robot_ip", "127.0.0.1")
        self.label_conn.config(text="● Connecté — {}".format(ip), fg="#4a9")
        self.btn_connect.config(state="disabled")
        self.btn_disconnect.config(state="normal")
        self._set_statut(
            "Connecté — cliquez sur la caméra puis utilisez ZQSD", "#4a9"
        )
        self.frame.focus_set()  # Activer le clavier immédiatement

    def _deconnecter(self):
        """
        Déconnexion propre :
        - Relâche toutes les touches (arrêt des mouvements)
        - Arrête la caméra et l'audio
        - Ferme le socket
        - Remet l'UI en état déconnecté
        """
        self._connecte = False

        # Relâcher toutes les touches encore enfoncées → stopper mouvements
        for key in list(self._touches_enfoncees):
            self._relacher_bouton(key)
            action = TOUCHES_CORPS.get(key)
            if action:
                self._envoyer("fin:{}".format(action))
        self._touches_enfoncees.clear()

        # Arrêter caméra et audio
        self._arreter_camera()

        # Fermer le socket de commandes
        try:
            if self._sock:
                self._sock.send("stop\n".encode())
                self._sock.close()
        except Exception:
            pass
        self._sock = None

        # Remettre l'UI en état initial
        self.label_conn.config(text="● Déconnecté", fg="#c44")
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")
        self._set_statut("Déconnecté.")
        self._afficher_texte_cam("Déconnecté")

    def _recevoir_boucle(self):
        """
        Thread de réception des réponses du serveur.
        - Affiche les retours dans les logs
        - Détecte automatiquement si le serveur (Chorégraphe) se ferme
          et déclenche une déconnexion propre
        """
        buf = ""
        while self._connecte:
            try:
                # recv() bloquant : se débloque si le serveur ferme la connexion
                data = self._sock.recv(1024).decode(errors="replace")
                if not data:
                    break  # Serveur fermé proprement (EOF)
                buf += data
                for ligne in buf.split("\n")[:-1]:
                    if ligne.strip():
                        self.bridge.log("[CTRL] " + ligne.strip(), "INFO")
                buf = buf.split("\n")[-1]
            except Exception:
                break  # Erreur socket (Chorégraphe fermé brutalement)

        # Si on sort de la boucle alors qu'on était connecté → déconnexion serveur
        if self._connecte:
            self.bridge.log("[CTRL] Serveur déconnecté.", "WARN")
            self.frame.after(0, self._deconnecter)

    # =========================================================================
    # ENVOI DE COMMANDES
    # =========================================================================

    def _envoyer(self, msg):
        """
        Envoie une commande texte au serveur (port 9561).
        Détecte les erreurs d'envoi et déclenche une déconnexion si nécessaire.
        """
        if not self._connecte or not self._sock:
            return
        try:
            self._sock.send((msg + "\n").encode())
        except Exception:
            # Le serveur n'est plus joignable
            self._set_statut("Serveur déconnecté.", "#c44")
            self.frame.after(0, self._deconnecter)

    # =========================================================================
    # MOUVEMENTS CORPS (continus — debut:/fin:)
    # =========================================================================

    def _debut_action(self, key):
        """
        Début d'un mouvement (touche enfoncée).
        Envoie "debut:action" au serveur qui démarre moveToward en boucle.
        Ignore la répétition automatique du clavier (key repeat).
        """
        if key in self._touches_enfoncees:
            return  # Déjà enfoncée → ignorer le key repeat
        action = TOUCHES_CORPS.get(key)
        if not action:
            return
        self._touches_enfoncees.add(key)
        self._envoyer("debut:{}".format(action))
        self.label_cmd.config(text="▶ {}".format(action))

        # Effet visuel : bouton enfoncé (sunken + blanc)
        btn = self._btns.get(key)
        if btn:
            btn.config(relief="sunken", bg=BG_ACT, fg="#333")

    def _fin_action(self, key):
        """
        Fin d'un mouvement (touche relâchée).
        Envoie "fin:action" au serveur qui arrête moveToward.
        """
        self._touches_enfoncees.discard(key)
        action = TOUCHES_CORPS.get(key)
        if not action:
            return
        self._envoyer("fin:{}".format(action))
        self.label_cmd.config(text="⏹ {}".format(action))
        self._relacher_bouton(key)

    def _relacher_bouton(self, key):
        """Remet le bouton dans son état visuel normal (raised + couleur d'origine)."""
        btn = self._btns.get(key)
        if btn:
            try:
                btn.config(relief="raised", bg=btn._bg_normal, fg="white")
            except Exception:
                pass

    # =========================================================================
    # CONTRÔLE TÊTE (discret — une commande par appui)
    # =========================================================================

    def _action_tete(self, direction):
        """
        Déplace la tête dans la direction donnée.
        Chaque appui incrémente l'angle de INC_TETE radians (défini côté serveur).
        """
        if direction == "centre":
            self._envoyer("tete:centre")
            self.label_cmd.config(text="tete:centre")
        else:
            tete_dir = TOUCHES_TETE.get(direction, direction)
            self._envoyer("tete:{}".format(tete_dir))
            self.label_cmd.config(text="tete:{}".format(tete_dir))

        # Flash rapide sur le bouton tête (120ms)
        btn = self._btns.get("tete_" + direction)
        if btn:
            btn.config(bg="#aaa")
            self.frame.after(120, lambda b=btn: b.config(bg=BG_TETE))

    # =========================================================================
    # ACTIONS SPÉCIALES
    # =========================================================================

    def _action_bonjour(self):
        """Animation salut avec le bras droit (bloquante côté serveur)."""
        self._envoyer("bonjour")
        self.label_cmd.config(text="bonjour")

    def _action_sit(self):
        """Posture S'asseoir (goToPosture Sit)."""
        self._envoyer("sit")
        self.label_cmd.config(text="sit")

    def _action_standup(self):
        """Posture Se lever (goToPosture StandInit)."""
        self._envoyer("standup")
        self.label_cmd.config(text="standup")

    def _action_tts(self):
        """Envoie le texte de la zone de saisie au robot (ALTextToSpeech)."""
        texte = self.entry_tts.get().strip()
        if not texte:
            return
        self._envoyer("dire:{}".format(texte))
        self.label_cmd.config(text="dire: {}".format(texte[:20]))
        self.bridge.log("[CTRL] TTS : {}".format(texte), "INFO")

    # =========================================================================
    # CLAVIER
    # =========================================================================

    def _on_key_press(self, event):
        """
        Touche enfoncée :
        - ZQSD/AE → début mouvement continu
        - Flèches  → commande tête discrète
        """
        key = event.keysym.lower()
        if key in TOUCHES_CORPS:
            self._debut_action(key)
        elif key in TOUCHES_TETE:
            self._action_tete(key)

    def _on_key_release(self, event):
        """
        Touche relâchée :
        - ZQSD/AE → fin mouvement continu
        - Flèches  → rien (discret, déjà traité au KeyPress)
        """
        key = event.keysym.lower()
        if key in TOUCHES_CORPS:
            self._fin_action(key)

    # =========================================================================
    # FLUX VIDÉO (port 8080)
    # =========================================================================

    def _demarrer_camera(self, ip):
        """Démarre le thread de lecture du flux vidéo."""
        self._cam_active = True
        threading.Thread(
            target=self._lire_flux_camera, args=(ip,), daemon=True
        ).start()

    def _arreter_camera(self):
        """Arrête le flux vidéo et ferme le socket caméra."""
        self._cam_active = False
        try:
            if self._sock_cam:
                self._sock_cam.close()
        except Exception:
            pass
        self._sock_cam = None

    def _lire_flux_camera(self, ip):
        """
        Thread de lecture du flux vidéo.
        Protocole : 4 octets big-endian (taille JPEG) + données JPEG.
        Utilise recv_exact pour garantir la réception complète de chaque frame.
        """
        self.frame.after(
            0, lambda: self._afficher_texte_cam(
                "Connexion caméra {}:{}...".format(ip, PORT_CAM)
            )
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((ip, PORT_CAM))
        except Exception as e:
            # En simulation, le serveur caméra n'existe pas → message informatif
            msg = (
                "Caméra non disponible\n(mode simulation)"
                if ip == "127.0.0.1"
                else "Caméra inaccessible :\n{}".format(str(e))
            )
            self.frame.after(0, lambda m=msg: self._afficher_texte_cam(m, "#888"))
            return

        self._sock_cam = sock
        sock.settimeout(10)

        def recv_exact(s, n):
            """Reçoit exactement n octets (gère la fragmentation TCP)."""
            data = b""
            while len(data) < n:
                chunk = s.recv(n - len(data))
                if not chunk:
                    raise Exception("Connexion fermée")
                data += chunk
            return data

        self.frame.after(0, lambda: self._afficher_texte_cam(""))

        while self._cam_active:
            try:
                # Lire la taille de la frame (4 octets big-endian)
                taille = struct.unpack(">I", recv_exact(sock, 4))[0]
                # Lire les données JPEG
                jpeg   = recv_exact(sock, taille)
                self._afficher_frame(jpeg)
            except socket.timeout:
                continue
            except Exception:
                break

        sock.close()
        self.frame.after(0, lambda: self._afficher_texte_cam("Caméra déconnectée."))

    def _afficher_frame(self, jpeg_data):
        """
        Décode et affiche une frame JPEG dans le canvas caméra.
        Nécessite Pillow (pip install Pillow).
        S'adapte à la taille actuelle du canvas.
        """
        def _update():
            try:
                from PIL import Image, ImageTk
                cw = self.canvas_cam.winfo_width()  or 640
                ch = self.canvas_cam.winfo_height() or 480
                img = Image.open(io.BytesIO(jpeg_data)).resize((cw, ch))
                # Stocker la référence pour éviter le garbage collector tkinter
                self._cam_photo = ImageTk.PhotoImage(img)
                self.canvas_cam.delete("all")
                self.canvas_cam.create_image(0, 0, anchor="nw", image=self._cam_photo)
            except ImportError:
                self._afficher_texte_cam(
                    "pip install Pillow\npour la caméra", "#f5c842"
                )
                self._cam_active = False
            except Exception:
                pass
        self.frame.after(0, _update)

    # =========================================================================
    # FLUX AUDIO (port 8081)
    # =========================================================================




