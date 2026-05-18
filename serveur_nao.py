#serveur_nao.py
#a ouvrir dans choregraphe avant le reste
import socket
import sys
import math
import time
import select
import json
import struct
import threading
from naoqi import ALProxy
import os

IP          = os.environ.get("NAO_IP", "127.0.0.1")
PORT_NAO    = 9559
PORT_SERVER = 9561
PORT_CAM    = 8080

def log(msg):
    print(msg)
    sys.stdout.flush()

scene = None

def verifier_case(x, y):
    if scene is None:
        return "OBSTACLE"
    if not (0 <= y < len(scene) and 0 <= x < len(scene[0])):
        return "OBSTACLE"
    val = scene[y][x]
    if val in ("X", "0", "1"):
        return "OBSTACLE"
    return "OK"

time.sleep(2)

motion  = ALProxy("ALMotion",         IP, PORT_NAO)
posture = ALProxy("ALRobotPosture",   IP, PORT_NAO)
life    = ALProxy("ALAutonomousLife", IP, PORT_NAO)

try:
    video  = ALProxy("ALVideoDevice", IP, PORT_NAO)
    CAM_OK = True
    log("Camera initialisee.")
except Exception as e:
    video  = None
    CAM_OK = False
    log("Camera non disponible : {}".format(e))

# ── Initialisation robot ──────────────────────────────────────────────────────

def init_robot(conn):
    """Initialise le robot et envoie PRET au client."""
    try:
        conn.send("INIT:Activation des moteurs...\n".encode())
        life.setState("disabled")
    except Exception as e:
        log("ALAutonomousLife non disponible : {}".format(e))
        conn.send("INIT:Activation des moteurs (sans ALAutonomousLife)...\n".encode())
    conn.send("INIT:WakeUp...\n".encode())
    motion.wakeUp()
    conn.send("INIT:Mise en position...\n".encode())
    posture.goToPosture("StandInit", 0.5)
    conn.send("PRET\n".encode())
    log("NAO pret, signal PRET envoye.")

# ── Mouvements ────────────────────────────────────────────────────────────────

MOUVEMENTS = {
    "rotation":        (lambda: motion.moveTo(0, 0, math.pi),                                                         "NAO a effectue la rotation 180\n"),
    "rotation_gauche": (lambda: motion.moveTo(0.001, 0, math.pi / 2),                                                 "NAO a effectue la rotation gauche\n"),
    "rotation_droite": (lambda: motion.moveTo(0.001, 0, -math.pi / 2),                                                "NAO a effectue la rotation droite\n"),
    "avant":           (lambda: motion.moveTo(0.3, 0, 0),                                                              "NAO a avance\n"),
    "arriere":         (lambda: motion.moveTo(-0.3, 0, 0),                                                             "NAO a recule\n"),
    "gauche":          (lambda: (motion.moveTo(0.001, 0, math.pi / 2),  time.sleep(1), motion.moveTo(0.3, 0, 0)),     "NAO a tourne a gauche et avance\n"),
    "droite":          (lambda: (motion.moveTo(0.001, 0, -math.pi / 2), time.sleep(1), motion.moveTo(0.3, 0, 0)),     "NAO a tourne a droite et avance\n"),
}

def jouer_mystical():
    try:
        anim = ALProxy("ALAnimationPlayer", IP, PORT_NAO)
        log("Animation Mystical en cours...")
        anim.run("animations/Stand/Entertainment/Mystical_1")
        log("Animation Mystical terminee.")
    except Exception as e:
        log("Mystical_1 non disponible : {}".format(e))
        try:
            anim = ALProxy("ALAnimationPlayer", IP, PORT_NAO)
            anim.run("animations/Stand/Entertainment/Mystical_2")
        except Exception as e2:
            log("Mystical_2 aussi indisponible : {}".format(e2))

def traiter_commande(conn, commande):
    """Traite une commande et renvoie True si on doit stopper."""
    commande = commande.strip()
    if not commande:
        return False
    log("Commande recue : {}".format(commande))

    if commande.startswith("verifier:"):
        coords   = commande.split(":")[1].strip("[]").split(",")
        cx, cy   = int(coords[0]), int(coords[1])
        resultat = verifier_case(cx, cy)
        log("Verification [{},{}] -> {}".format(cx, cy, resultat))
        conn.send("{}\n".format(resultat).encode())

    elif commande == "mystical":
        jouer_mystical()
        conn.send("Animation Mystical terminee\n".encode())

    elif commande == "stop":
        conn.send("Arret demande\n".encode())
        return True

    elif commande in MOUVEMENTS:
        action, feedback = MOUVEMENTS[commande]
        action()
        conn.send(feedback.encode())

    else:
        conn.send("Commande inconnue : {}\n".format(commande).encode())

    return False

# ── Serveur caméra (port 8080) ────────────────────────────────────────────────

def serveur_camera():
    if not CAM_OK:
        log("Serveur camera desactive.")
        return

    srv_cam = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_cam.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_cam.bind(("0.0.0.0", PORT_CAM))
    srv_cam.listen(5)  # Plusieurs clients simultanés possibles
    log("Serveur camera en attente (port {})...".format(PORT_CAM))

    sub_id = video.subscribeCamera("NAOMove_cam", 0, 1, 11, 10)
    log("Camera souscrite : {}".format(sub_id))

    while True:
        if not select.select([srv_cam], [], [], 2.0)[0]:
            continue
        try:
            cam_conn, addr = srv_cam.accept()
            log("Client camera connecte : {}".format(addr))
            # Thread par client caméra
            t = threading.Thread(target=_servir_camera, args=(cam_conn, sub_id))
            t.setDaemon(True)
            t.start()
        except Exception:
            break

    try:
        video.unsubscribe(sub_id)
        srv_cam.close()
    except: pass

def _servir_camera(cam_conn, sub_id):
    try:
        while True:
            try:
                frame = video.getImageRemote(sub_id)
                if frame is None:
                    time.sleep(0.05)
                    continue
                w, h = frame[0], frame[1]
                raw  = bytes(bytearray(frame[6]))
                try:
                    from PIL import Image as PILImage
                    import io as _io
                    img  = PILImage.frombytes("RGB", (w, h), raw)
                    buf  = _io.BytesIO()
                    img.save(buf, format="JPEG", quality=70)
                    jpeg = buf.getvalue()
                except ImportError:
                    import Image as PILImage
                    import StringIO as _sio
                    img  = PILImage.fromstring("RGB", (w, h), raw)
                    buf  = _sio.StringIO()
                    img.save(buf, format="JPEG", quality=70)
                    jpeg = buf.getvalue()
                taille = struct.pack(">I", len(jpeg))
                cam_conn.sendall(taille + jpeg)
                time.sleep(0.1)
            except Exception as e:
                log("Erreur frame : {}".format(e))
                break
    finally:
        try: cam_conn.close()
        except: pass

# ── Serveur principal (port 9561) — multi-sessions ───────────────────────────

t_cam = threading.Thread(target=serveur_camera)
t_cam.setDaemon(True)
t_cam.start()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", PORT_SERVER))
server.listen(5)  # Accepter plusieurs connexions
log("En attente de connexion (port {})...".format(PORT_SERVER))

while True:
    if not select.select([server], [], [], 1.0)[0]:
        continue
    conn, addr = server.accept()
    log("Nouvelle connexion : {}".format(addr))

    # Lire la première ligne pour identifier le type de client
    first_line = ""
    try:
        conn.settimeout(10)
        while "\n" not in first_line:
            first_line += conn.recv(4096).decode()
        conn.settimeout(None)
    except Exception as e:
        log("Erreur handshake : {}".format(e))
        conn.close()
        continue

    premiere, reste = first_line.split("\n", 1)
    premiere = premiere.strip()

    # ── Client contrôle manuel ──
    if premiere == "CONTROL":
        log("Client controle manuel connecte.")
        init_robot(conn)
        # Servir en boucle dans un thread pour ne pas bloquer
        def _session_controle(c, r):
            buf     = r
            stopper = False
            while not stopper:
                try:
                    if not select.select([c], [], [], 1.0)[0]:
                        continue
                    data = c.recv(1024).decode()
                    if not data:
                        break
                    buf += data
                    lignes = buf.split("\n")
                    buf    = lignes[-1]
                    for cmd in lignes[:-1]:
                        if traiter_commande(c, cmd):
                            stopper = True
                            break
                except Exception as e:
                    log("Erreur controle : {}".format(e))
                    break
            c.close()
            log("Client controle deconnecte.")
        t = threading.Thread(target=_session_controle, args=(conn, reste))
        t.setDaemon(True)
        t.start()

    # ── Client navigation (scene_idc.py) ──
    else:
        log("Client navigation connecte.")
        try:
            scene = json.loads(premiere)
            log("Scene recue ({} lignes).".format(len(scene)))
        except Exception as e:
            log("Erreur JSON scene : {}".format(e))
            conn.close()
            continue

        init_robot(conn)

        buf     = reste
        stopper = False
        while not stopper:
            try:
                if not select.select([conn], [], [], 1.0)[0]:
                    continue
                data = conn.recv(1024).decode()
                if not data:
                    log("Client navigation deconnecte.")
                    break
                buf += data
                lignes  = buf.split("\n")
                buf     = lignes[-1]
                for cmd in lignes[:-1]:
                    if traiter_commande(conn, cmd):
                        stopper = True
                        break
            except Exception as e:
                if "10054" in str(e) or "10053" in str(e):
                    log("Client deconnecte.")
                else:
                    log("Erreur : {}".format(e))
                break

        conn.close()
        log("Session navigation terminee.")
