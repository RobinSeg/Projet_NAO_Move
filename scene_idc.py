# =============================================================================
# scene_idc.py — Navigation autonome du robot (Python 3, subprocess)
#
# Lancé par NaoBridge quand l'utilisateur clique "▶ Lancer NAO".
# Tourne indépendamment de l'interface tkinter.
#
# Étapes :
#   1. Lit la scène JSON (grille 2D de symboles)
#   2. Calcule le/les chemin(s) optimal(aux) par BFS
#   3. Se connecte au serveur NAO sur port 9561
#   4. Envoie les commandes de déplacement une par une
#   5. Gère obstacles, contournement, navigation live (JSON relu si modifié)
#
# Communication stdout → NaoBridge :
#   [NAO_POS] x y          → position courante du robot
#   [NAO_CHEMIN] [[x,y]…]  → chemin BFS calculé
#   [NAO_CHOIX_CHEMIN] […] → plusieurs chemins → demande choix utilisateur
#   [NAO_CHOIX_OBSTACLE]   → obstacle robot réel → demande contourner/demi-tour
#   [NAO_OBSTACLE_CASES]   → obstacle simulation → propose cases de contournement
#
# Communication stdin ← NaoBridge :
#   "0"/"1"/…              → index du chemin choisi
#   "case:x:y"             → case de contournement choisie
#   "retour"               → demi-tour
#
# Variables d'environnement :
#   NAO_SCENE_PATH : chemin vers le fichier JSON de la scène
#   NAO_IP         : IP du robot (127.0.0.1 = simulation Chorégraphe)
# =============================================================================
import socket
import threading
import os
import sys
import time
import json
from collections import deque

scene_path = os.environ.get("NAO_SCENE_PATH", "scene.json")

with open(scene_path, "r", encoding="utf-8") as f:
    scene = json.load(f)

def _pos(x, y):
    print("[NAO_POS] {} {}".format(x, y))
    sys.stdout.flush()

def _emit_chemin(positions):
    print("[NAO_CHEMIN] {}".format(json.dumps(positions)))
    sys.stdout.flush()

def _emit_choix_chemin(chemins):
    """Envoie plusieurs chemins possibles pour que l'interface propose un choix."""
    print("[NAO_CHOIX_CHEMIN] {}".format(json.dumps(chemins)))
    sys.stdout.flush()

def _emit_choix_obstacle():
    """Demande à l'interface ce qu'il faut faire face à un obstacle (robot réel)."""
    print("[NAO_CHOIX_OBSTACLE]")
    sys.stdout.flush()

def _emit_obstacle_cases(cx, cy, cases_itin, cases_blanches):
    """
    Simulation : obstacle détecté.
    cases_itin   = cases ○ du chemin original permettant de contourner (déjà praticables)
    cases_blanches = cases ░ adjacentes convertibles en ○
    """
    print("[NAO_OBSTACLE_CASES] {}".format(
        json.dumps({
            "obstacle":       [cx, cy],
            "cases_itin":     cases_itin,
            "cases_blanches": cases_blanches
        })))
    sys.stdout.flush()

def trouver_position(sc, symbole):
    for y in range(len(sc)):
        for x in range(len(sc[0])):
            if sc[y][x] == symbole:
                return [x, y]
    return None

def calculer_orientation_initiale(nao, e):
    dx, dy = e[0] - nao[0], e[1] - nao[1]
    return {(0,-1): 0, (1,0): 1, (0,1): 2, (-1,0): 3}.get((dx, dy), 0)

def bfs_tous_chemins(sc, start, but):
    """BFS qui retourne TOUS les chemins de longueur minimale."""
    queue = deque([(start, [start])])
    visite = {start}
    chemins_optimaux = []
    longueur_min = None

    while queue:
        (x, y), chemin_actuel = queue.popleft()

        # Si on dépasse la longueur minimale connue, on arrête
        if longueur_min is not None and len(chemin_actuel) > longueur_min:
            break

        if (x, y) == but:
            longueur_min = len(chemin_actuel)
            chemins_optimaux.append(chemin_actuel)
            continue

        for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
            nx, ny = x + dx, y + dy
            if (nx, ny) not in visite and 0 <= ny < len(sc) and 0 <= nx < len(sc[0]):
                if sc[ny][nx] in ("○", "◘", "1"):
                    visite.add((nx, ny))
                    queue.append(((nx, ny), chemin_actuel + [(nx, ny)]))

    return [[[p[0], p[1]] for p in c] for c in chemins_optimaux]

def bfs_depuis(sc, start, but):
    """BFS simple depuis une position courante."""
    queue = deque([(start, [start])])
    visite = {start}
    while queue:
        (x, y), chemin_actuel = queue.popleft()
        if (x, y) == but:
            return [[p[0], p[1]] for p in chemin_actuel]
        for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
            nx, ny = x + dx, y + dy
            if (nx, ny) not in visite and 0 <= ny < len(sc) and 0 <= nx < len(sc[0]):
                if sc[ny][nx] in ("○", "◘", "1"):
                    visite.add((nx, ny))
                    queue.append(((nx, ny), chemin_actuel + [(nx, ny)]))
    return []

def deduire_commandes(positions, orientation_initiale):
    DIR = {(0,-1): 0, (1,0): 1, (0,1): 2, (-1,0): 3}
    commandes = []
    orientation = orientation_initiale

    for i in range(1, len(positions)):
        px, py = positions[i-1]
        nx, ny = positions[i]
        direction_cible = DIR[(nx-px, ny-py)]
        diff = (direction_cible - orientation) % 4

        if diff == 0:
            commandes.append("avant")
        elif diff == 1:
            commandes.append("droite")
            orientation = (orientation + 1) % 4
        elif diff == 3:
            commandes.append("gauche")
            orientation = (orientation - 1) % 4
        elif diff == 2:
            commandes.append("rotation")
            orientation = (orientation + 2) % 4
            commandes.append("avant")

    return commandes

# ── Initialisation ────────────────────────────────────────────────────────────

NAO = trouver_position(scene, "N")
E   = trouver_position(scene, "E")
BUT = tuple(trouver_position(scene, "◘"))
orientation_initiale = calculer_orientation_initiale(NAO, E)

# Recherche de tous les chemins optimaux
tous_chemins = bfs_tous_chemins(scene, (NAO[0], NAO[1]), BUT)

if not tous_chemins:
    print("Aucun chemin disponible dans la scene. Arret.")
    sys.stdout.flush()
    os._exit(0)

# Variables partagées navigation (définies tôt car utilisées dès le choix de chemin)
arret            = threading.Event()
feedback_recu    = threading.Event()
obstacle_detecte = threading.Event()
choix_obstacle   = {"valeur": None}
choix_event      = threading.Event()
historique_commandes = []

def lire_stdin():
    """Thread qui lit les réponses de l'interface via stdin."""
    while not arret.is_set():
        try:
            line = sys.stdin.readline().strip()
            if not line:
                continue
            if line.isdigit():
                choix_obstacle["valeur"] = line
                choix_event.set()
            elif (line in ("contourner", "retour")
                  or line.startswith("cases:")
                  or line.startswith("case:")):
                choix_obstacle["valeur"] = line
                choix_event.set()
        except Exception:
            break

# Si plusieurs chemins de même longueur → demander à l'utilisateur de choisir
if len(tous_chemins) > 1:
    _emit_choix_chemin(tous_chemins)
    # lire_stdin gère la réponse (index chiffre) via choix_event
    choix_obstacle["valeur"] = None
    choix_event.clear()
    # Démarrer lire_stdin tôt pour capter la réponse
    _stdin_thread = threading.Thread(target=lire_stdin, daemon=True)
    _stdin_thread.start()
    choix_event.wait(timeout=120)
    idx_str = choix_obstacle.get("valeur", "0") or "0"
    try:
        idx = int(idx_str) if idx_str.isdigit() else 0
    except Exception:
        idx = 0
    idx = max(0, min(idx, len(tous_chemins) - 1))
    choix_obstacle["valeur"] = None
    positions_chemin = tous_chemins[idx]
else:
    positions_chemin = tous_chemins[0]
    _stdin_thread = None

chemin = deduire_commandes(positions_chemin, orientation_initiale)

print("Chemin deduit : {}".format(chemin))
sys.stdout.flush()
_emit_chemin(positions_chemin)

# ── Connexion socket ──────────────────────────────────────────────────────────

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
nao_ip = os.environ.get("NAO_IP", "127.0.0.1")
client.connect((nao_ip, 9561))
print("Connecte. En attente de l'initialisation du NAO...")
sys.stdout.flush()

client.send((json.dumps(scene) + "\n").encode())

client.settimeout(60)
buffer_init = ""
pret = False
try:
    while not pret:
        data = client.recv(1024).decode()
        buffer_init += data
        for ligne in buffer_init.split("\n")[:-1]:
            ligne = ligne.strip()
            if ligne.startswith("INIT:"):
                print("[INIT] " + ligne[5:]); sys.stdout.flush()
            elif ligne == "PRET":
                pret = True; break
        buffer_init = buffer_init.split("\n")[-1]
except socket.timeout:
    print("[ERREUR] Timeout serveur."); sys.stdout.flush()
    client.close(); os._exit(0)

client.settimeout(None)
print("\nNAO pret ! Demarrage dans 5 secondes..."); sys.stdout.flush()
for i in range(5, 0, -1):
    print("  {}...".format(i)); sys.stdout.flush(); time.sleep(1)
print("C'est parti !\n"); sys.stdout.flush()

# ── Variables globales navigation ─────────────────────────────────────────────

def envoyer(cmd):
    try: client.send((cmd + "\n").encode())
    except: pass

def recevoir():
    buffer = ""
    while not arret.is_set():
        try:
            data = client.recv(1024).decode()
            if not data: break
            buffer += data
            lignes = buffer.split("\n"); buffer = lignes[-1]
            for ligne in lignes[:-1]:
                ligne = ligne.strip()
                if not ligne: continue
                if ligne == "OBSTACLE": obstacle_detecte.set()
                elif ligne == "OK": obstacle_detecte.clear()
                else: print("[NAO] >>", ligne); sys.stdout.flush()
                feedback_recu.set()
        except: break

threading.Thread(target=recevoir, daemon=True).start()
# Démarrer lire_stdin seulement s'il n'a pas déjà été lancé pour le choix de chemin
if not (_stdin_thread is not None and _stdin_thread.is_alive()):
    threading.Thread(target=lire_stdin, daemon=True).start()

# ── Déplacement ───────────────────────────────────────────────────────────────

DEPLACEMENT = {0:(0,-1), 1:(1,0), 2:(0,1), 3:(-1,0)}
DEPLACEMENT_ARRIERE = {0:(0,1), 1:(-1,0), 2:(0,-1), 3:(1,0)}
orientation = orientation_initiale

def calculer_deplacement(cmd):
    global orientation
    if cmd == "rotation": orientation = (orientation+2)%4; return (0,0)
    elif cmd == "rotation_gauche": orientation = (orientation-1)%4; return (0,0)
    elif cmd == "rotation_droite": orientation = (orientation+1)%4; return (0,0)
    elif cmd == "avant": return DEPLACEMENT[orientation]
    elif cmd == "arriere": return DEPLACEMENT_ARRIERE[orientation]
    elif cmd == "gauche": orientation = (orientation-1)%4; return DEPLACEMENT[orientation]
    elif cmd == "droite": orientation = (orientation+1)%4; return DEPLACEMENT[orientation]
    return (0,0)

def orientation_apres(cmd, o):
    if cmd == "rotation": return (o+2)%4
    elif cmd in ("rotation_gauche","gauche"): return (o-1)%4
    elif cmd in ("rotation_droite","droite"): return (o+1)%4
    return o

def calculer_case_cible(cmd, o):
    if cmd == "avant": dx, dy = DEPLACEMENT[o]
    elif cmd == "gauche": dx, dy = DEPLACEMENT[(o-1)%4]
    elif cmd == "droite": dx, dy = DEPLACEMENT[(o+1)%4]
    else: return (NAO[0], NAO[1])
    return (NAO[0]+dx, NAO[1]+dy)

def executer_commande(cmd):
    feedback_recu.clear(); envoyer(cmd); feedback_recu.wait()
    dx, dy = calculer_deplacement(cmd)
    NAO[0] += dx; NAO[1] += dy
    _pos(NAO[0], NAO[1])

INVERSES = {
    "rotation": "rotation", "avant": "arriere", "arriere": "avant",
    "gauche": ("arriere","rotation_droite"), "droite": ("arriere","rotation_gauche"),
}

def retour_position_initiale():
    print("[!] Retour position initiale..."); sys.stdout.flush()
    for cmd in reversed(historique_commandes):
        if arret.is_set(): break
        inverse = INVERSES.get(cmd, cmd)
        cmds = inverse if isinstance(inverse, tuple) else [inverse]
        for c in cmds: executer_commande(c)

def verifier_prochaine_case(cmd, o):
    if cmd in ("rotation","rotation_gauche","rotation_droite"): return True
    cx, cy = calculer_case_cible(cmd, o)
    feedback_recu.clear()
    envoyer("verifier:[{},{}]".format(cx, cy))
    feedback_recu.wait()
    return not obstacle_detecte.is_set()

def recharger_scene():
    """Relit le JSON seulement si le fichier a changé (comparaison mtime)."""
    try:
        mtime = os.path.getmtime(scene_path)
        if mtime <= recharger_scene._last_mtime:
            return scene  # Pas de changement
        recharger_scene._last_mtime = mtime
        with open(scene_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return scene

recharger_scene._last_mtime = os.path.getmtime(scene_path)

def _bfs_contournement(sc, depart, arrivee, exclure=None, priorite_itin=True):
    """
    BFS de contournement.
    - Cases autorisées : ○ et ░ uniquement (pas X, 0, 1, N, E)
      Exception : ◘ est autorisé SEULEMENT si c'est la destination arrivee
    - exclure : case obstacle à éviter
    - priorite_itin : explore les cases ○ en premier (chemin existant prioritaire)
    Retourne la liste de positions [[x,y], ...] ou [] si impossible.
    """
    if arrivee is None:
        return []
    start = tuple(depart)
    but   = tuple(arrivee)
    excl  = tuple(exclure) if exclure else None

    def case_valide(x2, y2):
        if (x2, y2) == excl:
            return False
        if not (0 <= y2 < len(sc) and 0 <= x2 < len(sc[0])):
            return False
        sym = sc[y2][x2]
        # Autoriser ◘ uniquement comme destination finale
        if (x2, y2) == but and sym == "◘":
            return True
        return sym in ("○", "░", "")

    from collections import deque as _deque

    # Si priorite_itin : explorer les cases ○ avant les ░
    # On fait 2 passes BFS : d'abord en ne passant que par ○,
    # si pas de chemin → on autorise aussi ░
    for cases_ok in [{"○"}, {"○", "░", ""}]:
        q   = _deque([(start, [start])])
        vis = {start}
        while q:
            (x2, y2), ch = q.popleft()
            if (x2, y2) == but:
                return [[p[0], p[1]] for p in ch]
            voisins = []
            for dx2, dy2 in [(0,1),(0,-1),(1,0),(-1,0)]:
                nx2, ny2 = x2+dx2, y2+dy2
                if (nx2, ny2) not in vis and case_valide(nx2, ny2):
                    sym = sc[ny2][nx2] if (nx2, ny2) != but else "◘"
                    if (nx2, ny2) == but or sym in cases_ok:
                        vis.add((nx2, ny2))
                        voisins.append(((nx2, ny2), ch + [(nx2, ny2)]))
            # Trier : cases ○ en premier (priorité itinéraire)
            if priorite_itin:
                voisins.sort(key=lambda v: 0 if sc[v[0][1]][v[0][0]] == "○" else 1)
            q.extend(voisins)
        # Réinitialiser pour la 2e passe
        pass

    return []

def recalculer_depuis_position_courante(sc):
    """
    Recalcule un chemin BFS depuis la position courante du robot (NAO)
    jusqu'à BUT, en tenant compte de la scène mise à jour.
    Retourne (positions, commandes) ou ([], []) si aucun chemin trouvé.
    """
    nouveau_chemin_pos = bfs_depuis(sc, (NAO[0], NAO[1]), BUT)
    if not nouveau_chemin_pos:
        return [], []
    nouvelles_cmds = deduire_commandes(nouveau_chemin_pos, orientation)
    return nouveau_chemin_pos, nouvelles_cmds

# ── Boucle principale ─────────────────────────────────────────────────────────

print("Chemin deduit ({} commandes) : {}".format(len(chemin), chemin))
sys.stdout.flush()
_pos(NAO[0], NAO[1])

# scene_courante pour détecter les changements live
scene_courante = [ligne[:] for ligne in scene]
echec = False
i = 0

while i < len(chemin) and not arret.is_set():
    commande = chemin[i]

    # ── Vérification scène live ──────────────────────────────────────────
    nouvelle_scene = recharger_scene()
    if nouvelle_scene != scene_courante:
        print("[LIVE] Scene modifiee, recalcul du chemin..."); sys.stdout.flush()
        scene_courante = nouvelle_scene
        # Mettre à jour la scène locale
        for y2 in range(len(nouvelle_scene)):
            for x2 in range(len(nouvelle_scene[0])):
                scene[y2][x2] = nouvelle_scene[y2][x2]
        # Recalculer depuis la position courante
        nouvelles_pos, nouvelles_cmds = recalculer_depuis_position_courante(scene)
        if not nouvelles_cmds:
            print("[LIVE] Aucun chemin disponible depuis la position courante."); sys.stdout.flush()
            # Trouver la dernière case en commun et y retourner
            chemin_pos_commun = [p for p in positions_chemin[:historique_commandes.__len__()+1]
                                  if 0 <= p[1] < len(scene) and 0 <= p[0] < len(scene[0])
                                  and scene[p[1]][p[0]] in ("○","◘","N","1")]
            if chemin_pos_commun:
                last = chemin_pos_commun[-1]
                print("[LIVE] Retour vers ({},{})".format(last[0], last[1])); sys.stdout.flush()
            retour_position_initiale()
            echec = True
            break
        else:
            positions_chemin = nouvelles_pos
            chemin = nouvelles_cmds
            _emit_chemin(positions_chemin)
            print("[LIVE] Nouveau chemin : {}".format(chemin)); sys.stdout.flush()
            i = 0
            historique_commandes.clear()
            continue

    # ── Vérification case cible AVANT exécution ──────────────────────────
    # On vérifie la case que la commande courante va atteindre
    if not verifier_prochaine_case(commande, orientation):
        cx, cy = calculer_case_cible(commande, orientation)

        # Trouver la case du chemin APRÈS l'obstacle (= i+1 dans positions_chemin)
        case_apres_obstacle = None
        for k in range(i + 1, len(positions_chemin)):
            px, py = positions_chemin[k][0], positions_chemin[k][1]
            if (px, py) != (cx, cy):
                case_apres_obstacle = (px, py)
                break

        # Cas spécial : l'obstacle est la dernière case (ou = objectif)
        if case_apres_obstacle is None:
            case_apres_obstacle = BUT
            print("[OBSTACLE] Derniere case avant objectif, contournement direct vers but.")
            sys.stdout.flush()

        nao_ip = os.environ.get("NAO_IP", "127.0.0.1")

        if nao_ip == "127.0.0.1":
            # ── Simulation ────────────────────────────────────────────────

            # Cas 1 : l'obstacle est la dernière case avant ◘
            # → chercher chemin direct vers BUT en contournant
            if case_apres_obstacle == BUT:
                print("[OBSTACLE] Derniere case avant objectif."); sys.stdout.flush()
                troncon_but = _bfs_contournement(
                    scene, [NAO[0], NAO[1]], BUT, [cx, cy])
                if troncon_but:
                    nouvelles_cmds = deduire_commandes(troncon_but, orientation)
                    if nouvelles_cmds:
                        # Proposer à l'utilisateur : contourner ou demi-tour
                        _emit_obstacle_cases(cx, cy, [], [])
                        choix_event.clear()
                        choix_event.wait(timeout=60)
                        choix = choix_obstacle.get("valeur", "retour")
                        choix_obstacle["valeur"] = None
                        if choix != "retour":
                            positions_chemin = troncon_but
                            chemin = nouvelles_cmds
                            _emit_chemin(positions_chemin)
                            print("[OBSTACLE] Contournement vers but : {}".format(chemin))
                            sys.stdout.flush()
                            i = 0
                            historique_commandes.clear()
                            continue
                # Pas de chemin → demi-tour
                _emit_obstacle_cases(cx, cy, [], [])
                choix_event.clear()
                choix_event.wait(timeout=60)
                choix_obstacle["valeur"] = None
                print("[OBSTACLE] Impossible de contourner, retour."); sys.stdout.flush()
                retour_position_initiale()
                echec = True
                break

            # Cas 2 : il existe des cases itinéraires après l'obstacle
            # → reprendre le chemin original après l'obstacle (priorité)
            # Chercher un contournement vers case_apres_obstacle en passant
            # uniquement par cases ○ et ░ (pas la case obstacle)
            troncon = _bfs_contournement(
                scene, [NAO[0], NAO[1]], case_apres_obstacle, [cx, cy])

            # Cases ░ adjacentes à l'obstacle (pour proposer dans le viewer)
            cases_blanches = []
            for adx, ady in [(0,-1),(0,1),(-1,0),(1,0)]:
                ax, ay = cx+adx, cy+ady
                if (0 <= ax < len(scene[0]) and 0 <= ay < len(scene)
                        and scene[ay][ax] in ("░", "")
                        and (ax, ay) != (NAO[0], NAO[1])):
                    cases_blanches.append([ax, ay])

            # Cases ○ du troncon qui ne font pas partie du chemin original
            chemin_set_orig = {(p[0], p[1]) for p in positions_chemin}
            cases_itin_contournement = []
            if troncon:
                cases_itin_contournement = [[p[0], p[1]] for p in troncon
                    if (p[0], p[1]) not in chemin_set_orig
                    or (p[0], p[1]) == case_apres_obstacle]

            _emit_obstacle_cases(cx, cy, cases_itin_contournement, cases_blanches)
            choix_event.clear()
            choix_event.wait(timeout=60)
            choix = choix_obstacle.get("valeur", "retour")
            choix_obstacle["valeur"] = None

            if choix == "retour":
                print("[OBSTACLE] Retour position initiale."); sys.stdout.flush()
                retour_position_initiale()
                echec = True
                break

            # L'utilisateur a cliqué une case blanche → la convertir en ○
            if choix and choix.startswith("case:"):
                parts = choix.split(":")
                try:
                    nc_x, nc_y = int(parts[1]), int(parts[2])
                    if scene[nc_y][nc_x] in ("░", ""):
                        scene[nc_y][nc_x] = "○"
                        try:
                            with open(scene_path, "r", encoding="utf-8") as f:
                                sc_disk = json.load(f)
                            sc_disk[nc_y][nc_x] = "○"
                            with open(scene_path, "w", encoding="utf-8") as f:
                                json.dump(sc_disk, f, ensure_ascii=False, indent=2)
                            recharger_scene._last_mtime = os.path.getmtime(scene_path)
                        except Exception as e:
                            print("[OBSTACLE] Erreur sauvegarde : {}".format(e))
                    # Recalculer le contournement avec la nouvelle case
                    troncon = _bfs_contournement(
                        scene, [NAO[0], NAO[1]], case_apres_obstacle, [cx, cy])
                except Exception as e:
                    print("[OBSTACLE] Erreur case : {}".format(e))

            # Tenter le contournement avec le troncon disponible
            if troncon:
                idx_reprise = None
                for k in range(len(positions_chemin)):
                    if (positions_chemin[k][0], positions_chemin[k][1]) == case_apres_obstacle:
                        idx_reprise = k
                        break
                # Assembler : troncon (sans doublon) + reste du chemin original
                # troncon[-1] == case_apres_obstacle == positions_chemin[idx_reprise]
                # → on garde troncon[:-1] + positions_chemin[idx_reprise:] pour éviter le doublon
                nouveau_chemin_pos = (troncon[:-1] + positions_chemin[idx_reprise:]
                    if idx_reprise is not None else troncon)
                nouvelles_cmds = deduire_commandes(nouveau_chemin_pos, orientation)
                if nouvelles_cmds:
                    positions_chemin = nouveau_chemin_pos
                    chemin = nouvelles_cmds
                    _emit_chemin(positions_chemin)
                    print("[OBSTACLE] Contournement : {}".format(chemin))
                    sys.stdout.flush()
                    i = 0
                    historique_commandes.clear()
                    continue

            print("[OBSTACLE] Impossible de contourner, retour."); sys.stdout.flush()
            retour_position_initiale()
            echec = True
            break

        else:
            # ── Robot réel ──
            _emit_choix_obstacle()
            choix_event.clear()
            choix_event.wait(timeout=60)
            choix = choix_obstacle.get("valeur", "retour")
            choix_obstacle["valeur"] = None

            if choix == "contourner":
                print("[OBSTACLE] Tentative de contournement..."); sys.stdout.flush()
                nouveau_troncon = _bfs_contournement(
                    scene, [NAO[0], NAO[1]], case_apres_obstacle)
                if nouveau_troncon and case_apres_obstacle:
                    idx_reprise = None
                    for k in range(len(positions_chemin)):
                        if (positions_chemin[k][0], positions_chemin[k][1]) == case_apres_obstacle:
                            idx_reprise = k
                            break
                    nouveau_chemin_pos = (nouveau_troncon[:-1] +
                        positions_chemin[idx_reprise:] if idx_reprise is not None
                        else nouveau_troncon)
                    nouvelles_cmds = deduire_commandes(nouveau_chemin_pos, orientation)
                    if nouvelles_cmds:
                        positions_chemin = nouveau_chemin_pos
                        chemin = nouvelles_cmds
                        _emit_chemin(positions_chemin)
                        print("[OBSTACLE] Contournement : {}".format(chemin))
                        sys.stdout.flush()
                        i = 0
                        historique_commandes.clear()
                        continue
                print("[OBSTACLE] Impossible de contourner, retour."); sys.stdout.flush()
                retour_position_initiale()
                echec = True
                break
            else:
                print("[OBSTACLE] Retour position initiale."); sys.stdout.flush()
                retour_position_initiale()
                echec = True
                break

    # ── Exécution commande ───────────────────────────────────────────────
    feedback_recu.clear()
    envoyer(commande)
    feedback_recu.wait()

    o_apres = orientation_apres(commande, orientation)
    dx, dy = calculer_deplacement(commande)
    orientation = o_apres  # mise à jour explicite de l'orientation globale
    NAO[0] += dx; NAO[1] += dy
    historique_commandes.append(commande)
    _pos(NAO[0], NAO[1])
    print("[{}/{}] {}".format(i+1, len(chemin), commande)); sys.stdout.flush()


    i += 1

if arret.is_set():
    print("[ARRET] Programme stoppe proprement.")
elif echec:
    print("\nEchec : obstacle detecte.")
else:
    print("\nObjectif atteint !")
    envoyer("mystical")  # Animation d'arrivée

sys.stdout.flush()
envoyer("stop")
time.sleep(2)
client.close()
