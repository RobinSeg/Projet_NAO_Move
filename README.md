# NAO Move

Application Python 3 (tkinter) de contrôle du robot NAO V6 via simulation Chorégraphe.

## Structure

```
NAO Move/
├── main.py                  # Point d'entrée
├── scene_idc.py             # Client navigation (Python 3, lancé en subprocess)
├── serveur_nao.py           # Serveur NAO (Python 2 / Chorégraphe)
├── scene-icon.ico           # Icône de l'application
├── build.bat                # Script de compilation .exe
├── NAO_Move.spec            # Configuration PyInstaller
└── modules/
    ├── __init__.py
    ├── base_module.py       # Classe de base des modules
    ├── tab_manager.py       # Gestion des onglets
    ├── nao_bridge.py        # Communication inter-modules + subprocess
    ├── editor_module.py     # Onglet éditeur de scène
    ├── view_module.py       # Onglet vue robot temps réel
    └── logs_module.py       # Onglet logs
```

## Lancer l'application (mode développement)

```
py -3.11 main.py
```

## Compiler en .exe / INSTALLER

Double-cliquer sur `build.bat` — PyInstaller doit être installé ou sera installé automatiquement.

Le .exe final se trouve dans `dist/NAO Move.exe`.

## Workflow

1. Ouvrir **Chorégraphe** et démarrer la simulation du robot NAO
2. Lancer **NAO Move**
3. **Onglet Éditeur** : dessiner la scène avec les symboles :
   - `X` = mur / obstacle
   - `○` = case praticable (chemin possible pour le BFS)
   - `N` = position de départ de NAO
   - `E` = case adjacente à N indiquant son orientation initiale
   - `◘` = objectif à atteindre
   - `1`, `0` = obstacles optionnels
4. **Éditeur** : Enregistrer la scène (💾 Enregistrer sous)
5. **Éditeur** : Cliquer **▶ Lancer NAO**
   - `serveur_nao.py` se connecte au robot via Chorégraphe (Python 2)
   - `scene_idc.py` calcule le chemin BFS et envoie les commandes (Python 3)
   - Tout se passe en arrière-plan, aucune fenêtre ne s'ouvre
6. **Onglet Vue NAO** : suivre le déplacement du robot en temps réel
7. **Onglet Logs** : consulter l'historique des commandes et événements

## Notes techniques

- `serveur_nao.py` est lancé via le Python embarqué dans Chorégraphe (`Python 2.7 + naoqi`)
- `scene_idc.py` est lancé via Python 3 (détecté automatiquement dans le PATH)
- La communication entre les deux se fait via socket local (port 9561)
- Les positions NAO sont remontées à l'interface via stdout (`[NAO_POS] x y`)
- Le chemin BFS est transmis via stdout (`[NAO_CHEMIN] [[x,y],...]`)
