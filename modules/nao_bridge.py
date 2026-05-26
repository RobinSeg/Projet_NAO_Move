# =============================================================================
# modules/nao_bridge.py
# Bus de communication central de l'application NAO Move
#
# Rôle : faire le lien entre les modules d'interface (éditeur, vue NAO, logs)
# et le subprocess scene_idc.py qui pilote le robot.
#
# Problème fondamental : tkinter N'EST PAS thread-safe.
# On ne peut pas modifier un widget depuis un thread secondaire.
# Solution : pattern Producer-Consumer avec queues thread-safe.
#   - Les threads déposent dans les queues (log_queue, position_queue...)
#   - Le thread principal (tkinter) consomme via root.after() toutes les 100ms
#
# Flux de données :
#   scene_idc.py (subprocess)
#     stdout → [NAO_POS]       → position_queue → vue NAO
#     stdout → [NAO_CHEMIN]    → chemin_callbacks → vue NAO
#     stdout → [NAO_CHOIX_*]  → callbacks → popups tkinter
#     stdout → autres lignes  → log_queue → module logs
#   Interface → stdin subprocess → réponses aux choix utilisateur
# =============================================================================

import threading
import queue
import subprocess
import sys
import os
import json as _json


def get_resource_path(filename):
    """
    Retourne le chemin absolu d'un fichier ressource.
    - En mode .exe (PyInstaller) : cherche dans le dossier temporaire _MEIPASS
    - En mode script : chemin relatif au dossier du projet
    """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), filename)


def get_python_executable():
    """
    Retourne le chemin de l'exécutable Python à utiliser pour lancer scene_idc.py.
    - En mode .exe : cherche python3 dans le PATH ou des emplacements connus
    - En mode script : utilise le même interpréteur que l'application
    """
    if hasattr(sys, '_MEIPASS'):
        import shutil
        python = shutil.which("python") or shutil.which("python3")
        if python:
            return python
        # Emplacements Windows classiques
        for candidate in [
            r"C:\Python311\python.exe",
            r"C:\Python310\python.exe",
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                r"Programs\Python\Python311\python.exe"
            ),
        ]:
            if os.path.exists(candidate):
                return candidate
        return "python"
    return sys.executable


class NaoBridge:
    """
    Bus de communication central.
    Instancié une seule fois dans NaoApp et partagé avec tous les modules.
    """

    def __init__(self):
        # ── Queues thread-safe (remplies par threads, vidées par polling tkinter) ──
        self.log_queue      = queue.Queue()  # Messages de log (level, msg)
        self.position_queue = queue.Queue()  # Positions NAO (x, y)
        self.scene_queue    = queue.Queue()  # Mises à jour de scène

        # ── Callbacks enregistrés par les modules ──
        self._status_callback        = None  # Barre de statut (main.py)
        self._log_callbacks          = []    # Module logs
        self._position_callbacks     = []    # Vue NAO (position robot)
        self._chemin_callbacks       = []    # Vue NAO (surbrillance chemin BFS)
        self._choix_chemin_callback  = None  # Popup choix chemin (main.py)
        self._choix_obstacle_callback = None # Popup obstacle (main.py)
        self._obstacle_cases_callback = None # Popup cases simulation (main.py)

        # ── État du subprocess scene_idc.py ──
        self._process = None  # Processus Python 3 de navigation
        self._running = False # True tant que l'application tourne
        self._root    = None  # Référence root tkinter pour after()

        # ── Configuration ──
        self.scene_courante = None
        self.chemin_courant = None
        self.robot_ip = "127.0.0.1"  # IP simulation par défaut

    # ── Enregistrement des callbacks ──────────────────────────────────────────

    def set_status_callback(self, cb):   self._status_callback = cb
    def add_log_callback(self, cb):      self._log_callbacks.append(cb)
    def add_position_callback(self, cb): self._position_callbacks.append(cb)
    def add_chemin_callback(self, cb):   self._chemin_callbacks.append(cb)
    def set_choix_chemin_callback(self, cb):   self._choix_chemin_callback = cb
    def set_choix_obstacle_callback(self, cb): self._choix_obstacle_callback = cb
    def set_obstacle_cases_callback(self, cb): self._obstacle_cases_callback = cb

    # ── API publique ──────────────────────────────────────────────────────────

    def set_scene(self, scene, chemin=None):
        """Notifie un changement de scène (appelé par l'éditeur)."""
        self.scene_courante = scene
        if chemin:
            self.chemin_courant = chemin
        self.scene_queue.put(("scene_update", scene))

    def log(self, msg, level="INFO"):
        """Envoie un message de log (thread-safe, via queue)."""
        self.log_queue.put((level, msg))

    def update_status(self, msg):
        """Met à jour la barre de statut (thread principal uniquement)."""
        if self._status_callback:
            self._status_callback(msg)

    def envoyer_stdin(self, texte):
        """
        Envoie une réponse à scene_idc.py via stdin.
        Utilisé pour les choix utilisateur (chemin, obstacle).
        """
        try:
            if self._process and self._process.poll() is None:
                self._process.stdin.write(texte + "\n")
                self._process.stdin.flush()
        except Exception as e:
            self.log("Erreur stdin : {}".format(e), "ERROR")

    def start(self, root):
        """Démarre le polling des queues (appelé une fois au démarrage)."""
        self._root    = root
        self._running = True
        self._poll()

    def stop(self):
        """Arrête le bridge et stoppe la navigation en cours."""
        self._running = False
        self.stop_nao()

    # ── Polling thread-safe ───────────────────────────────────────────────────

    def _poll(self):
        """
        Méthode appelée toutes les 100ms dans le thread principal (via root.after).
        Vide les queues et dispatche les événements aux modules abonnés.
        C'est le seul endroit où les widgets tkinter sont modifiés depuis
        des données produites par des threads secondaires.
        """
        if not self._running:
            return

        # Vider la queue de logs → module logs
        try:
            while True:
                level, msg = self.log_queue.get_nowait()
                for cb in self._log_callbacks:
                    cb(level, msg)
        except queue.Empty:
            pass

        # Vider la queue de positions → vue NAO
        try:
            while True:
                pos = self.position_queue.get_nowait()
                for cb in self._position_callbacks:
                    cb(pos)
        except queue.Empty:
            pass

        # La scene_queue est consommée directement par view_module._poll_scene()
        # Elle n'est pas vidée ici pour éviter de priver view_module des événements

        self._root.after(100, self._poll)

    # ── Gestion du subprocess scene_idc.py ───────────────────────────────────

    def launch_nao(self, scene_path):
        """
        Lance scene_idc.py en subprocess avec :
        - stdout capturé pour parser les marqueurs [NAO_*]
        - stdin ouvert pour envoyer les réponses aux choix
        - Variables d'environnement : NAO_SCENE_PATH, NAO_IP
        """
        if self._process and self._process.poll() is None:
            self.log("scene_idc deja en cours.", "WARN")
            return
        if not os.path.exists(scene_path):
            self.log("Fichier scene introuvable : {}".format(scene_path), "ERROR")
            return

        script = get_resource_path("scene_idc.py")
        if not os.path.exists(script):
            self.log("scene_idc.py introuvable : {}".format(script), "ERROR")
            return

        python_exe = get_python_executable()
        self.log("Python : {}".format(python_exe), "INFO")
        self.log("Lancement navigation : {}".format(scene_path), "INFO")
        self.update_status("Connexion au NAO...")

        env = os.environ.copy()
        env["NAO_SCENE_PATH"] = scene_path
        env["NAO_IP"]         = self.robot_ip

        def _run():
            """Thread interne qui lit stdout du subprocess ligne par ligne."""
            try:
                creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                self._process = subprocess.Popen(
                    [python_exe, script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,   # Ouvert pour envoyer les réponses
                    text=True,
                    env=env,
                    cwd=os.path.dirname(script),
                    creationflags=creation_flags
                )

                # Lire chaque ligne de stdout et parser les marqueurs
                for line in self._process.stdout:
                    line = line.rstrip()
                    if not line:
                        continue

                    if line.startswith("[NAO_POS]"):
                        # Position du robot : [NAO_POS] x y
                        parts = line.split()
                        if len(parts) == 3:
                            try:
                                x, y = int(parts[1]), int(parts[2])
                                self.position_queue.put((x, y))
                            except ValueError:
                                pass

                    elif line.startswith("[NAO_CHEMIN]"):
                        # Chemin BFS calculé : [NAO_CHEMIN] [[x,y], ...]
                        try:
                            positions = _json.loads(line[len("[NAO_CHEMIN]"):].strip())
                            for cb in self._chemin_callbacks:
                                cb(positions)
                        except Exception:
                            pass

                    elif line.startswith("[NAO_CHOIX_CHEMIN]"):
                        # Plusieurs chemins optimaux → popup de choix
                        try:
                            chemins = _json.loads(line[len("[NAO_CHOIX_CHEMIN]"):].strip())
                            if self._choix_chemin_callback and self._root:
                                self._root.after(0, lambda c=chemins: self._choix_chemin_callback(c))
                        except Exception as e:
                            self.log("Erreur parsing choix chemin : {}".format(e), "ERROR")
                            self.envoyer_stdin("0")  # Fallback : chemin 0

                    elif line.startswith("[NAO_CHOIX_OBSTACLE]"):
                        # Obstacle détecté en mode robot → popup contourner/demi-tour
                        if self._choix_obstacle_callback and self._root:
                            self._root.after(0, self._choix_obstacle_callback)

                    elif line.startswith("[NAO_OBSTACLE_CASES]"):
                        # Obstacle en simulation → popup avec cases disponibles
                        try:
                            data = _json.loads(line[len("[NAO_OBSTACLE_CASES]"):].strip())
                            if self._obstacle_cases_callback and self._root:
                                self._root.after(0, lambda d=data: self._obstacle_cases_callback(d))
                        except Exception as e:
                            self.log("Erreur parsing obstacle cases : {}".format(e), "ERROR")
                            self.envoyer_stdin("retour")

                    else:
                        # Ligne ordinaire → module logs
                        level = "ERROR" if "erreur" in line.lower() or "error" in line.lower() else "INFO"
                        self.log_queue.put((level, line))

                self._process.wait()
                self.log_queue.put(("INFO", "Navigation terminée (code {}).".format(
                    self._process.returncode)))
                # Remettre le statut à Prêt. une fois la navigation terminée
                if self._root:
                    self._root.after(0, lambda: self.update_status("Prêt."))

            except Exception as e:
                self.log_queue.put(("ERROR", "Erreur subprocess : {}".format(e)))
                if self._root:
                    self._root.after(0, lambda: self.update_status("Prêt."))

        threading.Thread(target=_run, daemon=True).start()

    def stop_nao(self):
        """Stoppe le subprocess de navigation en cours."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self.log("Navigation arrêtée.", "INFO")
            self.update_status("NAO déconnecté.")
