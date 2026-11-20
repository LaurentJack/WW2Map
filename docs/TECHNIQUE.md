# Carte WW2 — documentation technique

Présentation et captures : [README](../README.md). Les commandes ci-dessous se lancent depuis la racine du dépôt.

Carte interactive des lieux de la Seconde Guerre mondiale : batailles et opérations, camps (concentration, transit, internement, prisonniers de guerre), massacres, sites militaires (forts, bunkers, bases), événements (libérations, bombardements, procès), cimetières, mémoriaux et musées.

## Lancer l'application

**Version autonome à partager : `dist/WW2Map.exe` (≈ 720 Mo).** Ce fichier unique contient toute l'application et se lance de n'importe où, sans le reste du dossier.
- Les fichiers forment une archive ZIP collée à la fin de l'exe. Le lanceur les sert directement depuis cette archive, sans rien décompresser sur le disque.
- La fenêtre s'ouvre en quelques secondes. Au premier lancement, l'antivirus peut analyser le fichier plus longuement.
- Windows SmartScreen peut avertir « éditeur inconnu », car l'exe n'est pas signé : cliquer « Informations complémentaires » puis « Exécuter quand même ».

**Version légère, dans ce dossier : double-cliquez sur `WW2Map.exe`** (17 Mo). La carte s'ouvre dans sa propre fenêtre et utilise les fichiers du dossier : pratique pendant le développement, car une modification est visible sans reconstruire l'exe.
- Le lanceur démarre un petit serveur local (127.0.0.1, invisible depuis le réseau) et affiche la carte avec Edge WebView2, déjà présent sur Windows 10 et 11. Si WebView2 manque, la carte s'ouvre dans le navigateur par défaut, avec une petite fenêtre « Fermer » pour arrêter.
- L'exe léger doit rester **dans ce dossier**, à côté de `index.html`, `css/`, `js/`, `vendor/` et `data/`.
- Fonds de carte, LIDAR, satellite et couches IGN restent chargés en direct : il faut internet. Sans connexion, le fond reste vide, mais les lieux, les cartes GSGS, les cartes de situation et la ligne de front fonctionnent. Leaflet est fourni dans `vendor/` et non chargé depuis un CDN.

Reconstruire les deux exe après une modification (Python 3.11, car PyInstaller n'existe pas encore pour 3.15). Fermez d'abord l'exe léger s'il est ouvert :

```bash
py -3.11 -m venv scripts/.venv-exe
scripts/.venv-exe/Scripts/python -m pip install pyinstaller pywebview pillow
scripts/.venv-exe/Scripts/python scripts/exe/build_exe.py
```

Sans l'exe, on peut servir le dossier en local avec `python -m http.server 8765`, puis ouvrir http://localhost:8765.

## Fonctionnalités

- Carte OpenStreetMap ou relief (OpenTopoMap), regroupement des marqueurs
- Filtres par catégorie, pays, période (1933–1946) et source
- Recherche plein texte (insensible aux accents)
- Liste des résultats triés chronologiquement ; un clic centre la carte sur le lieu
- Fiche de chaque lieu : dates, description, lien vers Wikipédia / Wikidata

## Cartes et photos aériennes anciennes

À activer dans le menu des couches, en haut à droite. Le curseur « Carte ancienne » règle la transparence pour comparer avec la carte actuelle.

**Fond satellite.** OpenStreetMap ne publie pas d'images satellite. Le fond « Satellite (Esri) » (imagerie mondiale Esri World Imagery, mention © Esri obligatoire, usage non commercial) s'ajoute aux fonds « Plan » et « Relief ».

**Rideau de comparaison.** Le bouton « ⇆ Comparer », en haut à droite, coupe la carte en deux. Pendant la comparaison, les couches anciennes passent en opacité pleine ; l'opacité précédente est rétablie à la sortie. Exemple, **LIDAR | satellite** : choisir le fond « Satellite (Esri) », cocher un relief LIDAR belge, puis cliquer sur « Comparer ». À gauche du trait, toutes les couches anciennes affichées : cartes et photos aériennes ci-dessous, feuilles GSGS, cartes de situation et ligne de front. À droite, la carte actuelle seule. On fait glisser la poignée pour déplacer la limite. Les couches sont découpées (propriété CSS `clip`) dans leurs panneaux Leaflet `hist`, `gsgs` et `overlayPane`.

| Couche | Zone | Source |
|---|---|---|
| Carte de France 1950 (SCAN 50) | France | IGN – Géoplateforme |
| Photos aériennes 1950-1965 | France | IGN – Géoplateforme |
| Photos aériennes 1947 | Calvados (plages et bataille de Normandie) | IGN – BD ORTHO Historique |
| Carte d'état-major 1820-1866 | France | IGN – Géoplateforme |
| Photos aériennes 1971 | Wallonie | SPW – Géoportail de la Wallonie |
| Relief LiDAR HD (ombrage du MNT) | France (couverture nationale en cours d'achèvement : zones non encore acquises vides) | IGN – Géoplateforme (WMTS `IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.SHADOW`) |
| Relief LIDAR 2021-2022 (ombrage du MNT, 0,5 m) | Wallonie | SPW – Géoportail de la Wallonie (service `RELIEF/WALLONIE_MNT_2021_2022_HILLSHADE`) |
| Relief LIDAR DHMV II (ombrage multidirectionnel, 0,25 m) | Flandre et Bruxelles | Digitaal Vlaanderen (WMS `DHMV`, couche `DHMV_II_HILL_25cm`) |
| Photos aériennes 1953 | Berlin | Geoportal Berlin (dl-zero-de/2.0) |

Toutes ces couches sont chargées en direct depuis les services publics : il faut une connexion internet.

Le relief LIDAR montre le terrain sans la végétation. Dans les forêts des Ardennes, on y voit encore les trous d'obus, les tranchées, les trous de combat et les abris de 1944-1945, par exemple autour de Bastogne (bois Jacques, Foy). En France, les cratères de bombes de la pointe du Hoc (6 juin 1944) apparaissent nettement. En Flandre, on y voit les traces de la Grande Guerre autour d'Ypres. Les couches s'affichent à partir du zoom 9. Elles fonctionnent aussi avec le rideau de comparaison.

## Cartes de situation 1944-1945 (positions, mouvements, lignes de front)

Cartes quotidiennes du **12th Army Group** américain : divisions alliées et allemandes, lignes de front, limites d'armées. Elles viennent de la collection « World War II Military Situation Maps » de la Library of Congress (416 cartes, du 6 juin 1944 au 26 juillet 1945, domaine public), via les copies de Wikimedia Commons. Dans l'application : section « Cartes de situation », avec un curseur de date et un réglage d'opacité.

Fonctionnement (`scripts/sitmaps/`) :

1. **Calage d'une carte de référence par fond de carte**. Les points de calage (villes, coins du cadre) sont dans `gcps_1M.json`. `georef.py` ajuste une projection conique conforme de Lambert, celle des cartes d'origine, puis une transformation affine. Le résultat va dans `gcps_1M.fit.json`. Erreur moyenne : environ 1,5 km. Le contrôle sur des villes indépendantes (Luxembourg, Liège, Trèves, Metz, Arlon, Sedan…) donne environ 1 km.
2. **Alignement automatique de chaque carte du jour sur la référence**. OpenCV utilise des points ORB, puis SIFT en secours pour les tirages pâles, avec une homographie RANSAC, sur le canal rouge égalisé pour être insensible aux tirages gris ou bleus. Les cartes dessinées sur un autre fond sont ignorées, de même que les feuilles voisines qui ne couvrent pas au moins 90 % du cadre.
3. **Reprojection en Web Mercator**, découpe du cadre, export WebP transparent dans `data/sitmaps/<fond>/`, puis mise à jour de `data/sitmaps_<fond>.js`.

```bash
python -m venv scripts/.venv
scripts/.venv/Scripts/python -m pip install numpy pillow opencv-python-headless
scripts/.venv/Scripts/python scripts/sitmaps/build_sitmaps.py --series 1M --from 1944-09-01 --to 1945-04-15
```

**État : les 416 cartes de la série (6 juin 1944 – 26 juillet 1945) sont calées et superposables**, une par jour. Elles se répartissent sur 13 fonds de carte différents. Les calques font environ 540 Mo au total (`data/sitmaps/`). Un seul scan est atypique : le 10 septembre 1944 contient deux feuilles côte à côte. Les deux sont calées séparément (voir `SCAN_CROPS` dans `build_sitmaps.py`) et affichées ensemble :
- le front principal, sur le fond 1:1 000 000 ;
- la Bretagne, avec le siège de Brest : feuille « FUSAG Outline Maps 1:1 000 000, Sheet 1 », 5°W–1°E, 46°N–50°N, `gcps_bzh_0910.json`, calée sur 4 coins et 16 repères de degré, ≈ 0,9 km.

Quand plusieurs feuilles couvrent des régions différentes le même jour, l'application les superpose toutes. Si elles se chevauchent à plus de 50 %, elle garde la mieux alignée.

Fonds de carte utilisés par la série :

| Fond | Période (approx.) | État |
|---|---|---|
| 1:500 000, feuille 3 Normandie (2°W–1°E, 48°N–50°N) | juin – juillet 1944 | **calé** (`gcps_500k_s3.json`, 20 repères du carroyage, erreur ≈ 0,2 km) |
| 1:500 000, feuille Bretagne – Maine – Anjou (≈ 3°40'W–0°, 47°13'N–49°23'N) | début août 1944 | **calé** (`gcps_500k_bzh.json`, 16 villes + 11 repères de bord, erreur ≈ 0,8 km) |
| 1:500 000, feuille Maine – Orléanais (≈ 1°40'W–1°30'E, 47°15'N–49°25'N : poche de Falaise, Le Mans, Chartres, Tours) | mi-août 1944 | **calé** (`gcps_500k_mo.json`, 25 villes, erreur ≈ 1,1 km) |
| 1:750 000, Normandie – Loire – Paris | 22–23 août 1944 | **calé par transfert** (`gcps_750k_a.json`, 131 points automatiques ; contrôle hors zone commune : Paris, Orléans, Poitiers, Bourges ≈ 1 km) |
| 1:500 000, Avranches – Le Mans | 11–12 août 1944 | **calé par transfert** (`gcps_500k_am.json`, 247 points ; contrôle ≈ 0,5 km) |
| Seine – Paris (libération de Paris) | 24–25 août 1944 | **calé par transfert** (`gcps_500k_sp.json`, 334 points ; Paris, Rouen, Mantes, Pontoise ≈ 0,5–1 km) |
| 1:750 000, Seine – Paris – Champagne | 26 août – 1er sept. 1944 | **calé par transfert** (`gcps_750k_b.json` ; ≈ 1 km à l'ouest, 1,5–2 km à l'est) |
| début septembre, nord de la France – Belgique | 2–5 sept. 1944 | **calé par transfert + 12 villes** (`gcps_750k_c.json`, ≈ 0,8 km ; 2–3 km à l'extrême nord-est) |
| 1:1 000 000, France – Belgique – Rhénanie (2°E–9°E, 48°N–52°N) | automne 1944 – hiver 1945 | **calé** (`gcps_1M.json`, erreur ≈ 1,5 km) |
| autre fond (à identifier) | septembre 1944, mars 1945 | à caler |
| 1:1 000 000, Rhénanie – Allemagne de l'Ouest | fin mars – avril 1945 | **calé par transfert + 12 villes** (`gcps_1M_rh.json`, ≈ 0,9 km ; 2–3 km aux bords) |
| Allemagne centrale | mi-avril 1945 | **calé par transfert** (`gcps_1000k_avr.json`, 208 points ; contrôle ≈ 1 km) |
| 1:1 500 000, Allemagne et zones d'occupation, **projection d'Albers** (parallèles 54°20' et 47°40' d'après la légende) | 20 mai – 26 juillet 1945 | **calé à la main** (`gcps_1400k_occ.json`, repères de longitude + 15 villes, ≈ 2 km) |
| 1:1 400 000, Allemagne entière | fin avril – mi-mai 1945 | **calé par transfert + 9 villes** (`gcps_1400k_de.json`, ≈ 1,5 km ; 3–4 km sur la côte nord) |

**Calage par transfert** (`transfer_gcps.py`) : quand un nouveau fond recouvre en partie des fonds déjà calés, ses points de calage sont créés automatiquement. Le script apparie les détails communs (SIFT et RANSAC, échelles libres) et leur attribue les coordonnées issues des fonds calés. Une source qui donne moins de 60 correspondances cohérentes est ignorée. Il faut toujours contrôler le résultat sur des villes hors de la zone commune, et compléter à la main si besoin.

```bash
scripts/.venv/Scripts/python scripts/sitmaps/transfer_gcps.py 1944-08-28 750k_b 750k_a 500k_mo 500k_s3 --lat0 48.5 --lon0 2 --neatline 216,147,3606,3316
```

Pour ajouter un fond : créer un fichier `gcps_<série>.json` sur le modèle de `gcps_1M.json`, lancer `georef.py`, puis déclarer la série dans `SERIES` de `build_sitmaps.py` et ajouter `data/sitmaps_<série>.js` dans `index.html`. Un point de calage peut n'avoir qu'une coordonnée (`"lat"` seule ou `"lon"` seule). C'est le cas des repères de carroyage tracés sur un bord de carte qui n'est ni un méridien ni un parallèle.

### Ligne de front vectorisée

Case « Ligne de front (tracé vectorisé) » de la section des cartes de situation. Elle utilise le même curseur de date et le bouton « ⏵ Animer », qui fait défiler les jours. Elle peut s'afficher seule, sur le fond actuel, ou par-dessus les cartes scannées. Un jour sans tracé reprend le dernier front connu, jusqu'à 3 jours avant, et le signale.

Le tracé est extrait automatiquement des cartes calées (`scripts/fronts/`) :

```bash
scripts/.venv/Scripts/python scripts/fronts/build_fronts.py --jobs 8   # ≈ 30 min ; --only 1944-12-24 pour une date
```

1. `extract.py` garde l'encre presque noire (V < 75), ce qui exclut les routes grises et les cours d'eau bleus. Il garde ensuite les traits épais : les écritures, symboles, dents du front et limites d'armées, plus fins, disparaissent.
2. Les traits sont ramenés à une ligne d'un pixel (amincissement de Zhang-Suen), suivis d'un nœud à l'autre et débarrassés de leurs petites branches.
3. On écarte encore les traits plus fins que le front de la même carte, les tracés à la règle, les petites boucles (lettres) et les courts traits droits (légende, soulignements), ainsi que les mots de l'en-tête (« SECRET », « COPY NO. »).
4. Les cartes étant déjà reprojetées, pixel → latitude/longitude est direct. Résultat : `data/fronts.js`.

Contrôle (planches de toutes les dates) : l'extraction est fiable de mi-juin à mi-août 1944, puis de mi-octobre 1944 à mai 1945. Elle couvre les Ardennes, la Rhénanie, la poche de la Ruhr et l'Allemagne. Le tracé est souvent interrompu là où des symboles d'unités recouvrent le front.

Entre fin août et début octobre 1944, les cartes ne tracent pas le front en trait noir, et seules des limites d'armées ressortent. Ces dates, et quelques cartes isolées ratées, sont écartées dans `scripts/fronts/overrides.json` (`"drop"`). On peut y régler une carte (`"params"`) ou exclure une zone (`"exclude"`, rectangles lon/lat). Au total, 273 cartes sur 351 ont un front.

## Cartes topographiques militaires GSGS (1937-1944)

Ce sont les cartes britanniques du *Geographical Section, General Staff*, dans leur édition US Army Map Service (domaine public), numérisées par la bibliothèque Perry-Castañeda (université du Texas) et copiées sur Wikimedia Commons. Dans l'application : section « Cartes topographiques GSGS », une case par série. Les feuilles se chargent à la demande, à partir du zoom 8, uniquement celles qui sont visibles.

| Série | Feuilles calées | Précision vérifiée |
|---|---|---|
| Belgique et NE de la France 1:100 000 (GSGS 2364, révisée 1943) | 19 / 19 | résidu 5–100 m ; Bruxelles, Louvain, Alost, Bastogne… au centre |
| Allemagne 1:250 000 (GSGS 4346, AMS M501/M508), colonnes K à N | 22 / 22 | résidu 0,1–0,9 km ; grande ville de chaque feuille contrôlée (4 villes par feuille de bord) |
| Normandie 1:100 000 (GSGS 4249, AMS M661, 1943), réduction des feuilles 1:50 000 GSGS 4250 du débarquement | 12 / 12 (8E : moitié est seulement) | calage sur le quadrillage kilométrique, résidu 13–32 m ; 40 villes contrôlées |
| France 1:250 000 (GSGS 4042, AMS M561) | 30 / 30 | calage sur les graduations du cadre, résidu 20–120 m ; 45 villes contrôlées, toutes à moins de ≈ 0,5 km |

Méthode (`scripts/gsgs/`) :
1. `download.py` télécharge les feuilles depuis Commons.
2. L'emprise de chaque feuille est lue sur l'identifiant AMS imprimé en bas à droite, par exemple « N5000-E820/100x200 » : 50°N, 8°20′E, 1° × 2°. Pour la série allemande, une règle suffit : feuille « X-NN » = (NN−1)° à NN°N, à partir de 6°20′, 8°20′, 10°20′ ou 12°20′E pour K, L, M ou N. Planches de lecture : `stamps.py`.
3. `neatline.py` détecte automatiquement le cadre intérieur de la carte :
   - densité d'encre et seuil adaptatif ;
   - recalage sur le trait noir le plus proche ;
   - gestion du double cadre ;
   - contrôle des proportions attendues.
4. `build.py` ajuste une projection conique locale sur les 4 coins, reprojette, découpe et écrit `data/gsgs/` et `data/gsgs.js`. Les feuilles atypiques peuvent recevoir une boîte approximative (`zone_hint`) ou des coins relevés à la main (`corners_px`, cas de Düsseldorf).

À noter :
- **Contrôle visuel indispensable.** Une détection fausse mais cohérente (rectangle aux bonnes proportions) n'est trahie ni par les proportions ni par le résidu. C'est un contrôle sur une ville connue qui a révélé l'erreur de Düsseldorf (10–15 km).
- **France 1:250 000 : méthode propre.** L'identifiant AMS est faux de 3 à 7 minutes d'arc, et le cadre n'est ni un méridien ni un parallèle : c'est un rectangle du quadrillage Lambert (zone 2, méridien de Paris). On cale donc chaque feuille sur les graduations d'une minute (barres noir/blanc) de ses quatre bords :
  1. `minute_bars.py` suit la bande graduée de chaque bord et relève toutes les transitions de minute (≈ 1 px). `refine_frame()` recale aussi les coins des cadres mal détectés (`corners_fix`).
  2. Les minutes sont numérotées d'après l'emprise approximative (`extent_approx`). Sur chaque bord, une étiquette imprimée (« 1°30′ », « 47°0′ »…) donne le décalage entier à appliquer (`tick_corr` : `top`, `left`, `bottom`, `right`). Ces 120 étiquettes ont été lues sur des planches de contrôle.
  3. `frame_ticks.py` ajuste une conique conforme (méridien de Paris) + affine sur ces points qui ne portent qu'une coordonnée, ou un modèle quadratique si le scan est déformé (Brest, Épinal). Le résultat est écrit dans `sheets.json` (`model`), puis `build.py` reprojette.
  - Piège rencontré : déduire la numérotation des bords bas et droit du modèle haut + gauche suppose que le quadrillage est exactement aligné. C'est faux d'une minute sur les feuilles de l'ouest (Bretagne, Normandie), avec un écart qui croît vers l'est. D'où la lecture d'une étiquette sur chacun des quatre bords.
  - Les zones blanches « covered by sheet… » en haut d'Auxerre, Orléans et Épinal sont à l'intérieur du cadre : elles restent opaques.
- **Normandie 1:100 000 (`grid100k.py`, `sheets100k.json`).** Le 1:50 000 de Normandie (GSGS 4250) n'est pas disponible en accès libre : ni Commons ni la bibliothèque de l'université du Texas ne l'ont (seulement 8 feuilles du Nord). On utilise donc sa réduction au 1:100 000, téléchargée sur maps.lib.utexas.edu (cache `scripts/.cache/gsgs/raw100k/`). La feuille 7E (Bayeux, plages Gold, Juno et Sword) manque dans la collection.
  - Chaque feuille porte un quadrillage d'un kilomètre : Lambert zone I (NTF, EPSG:27561) à l'ouest, « Nord de Guerre » (EPSG:27500, numéros modulo 100 km) à l'est, incliné d'environ 4° par rapport au cadre.
  - `sheets100k.json` donne, par feuille, le coin haut-gauche du cadre en pixels, la projection et les numéros de la première ligne verticale et horizontale lus en marge.
  - Le programme redresse le quadrillage (recherche de l'angle), détecte toutes les lignes par profils et mesure l'écartement réel : il varie de 81,5 à 83 px/km selon le scan. Il numérote ensuite de proche en proche. Les 1 200 à 4 300 intersections donnent un ajustement de degré 2, plus une correction locale par maille d'un kilomètre (pliures du papier).
  - Piège : le trait épais du cadre, juste au-dessus de la première ligne, peut prendre l'indice 0. On compare donc la numérotation du modèle aux numéros imprimés en marge, avec une planche de contrôle. Le décalage constaté est noté dans `"fix"` (7 feuilles).
  - Le Havre (8E) porte un second quadrillage sur sa moitié ouest, qui perturbe la détection : seule la moitié est (Yvetot, Caudebec, Duclair) est calée (`left_frac`). Chaque feuille n'est affichée que dans l'enveloppe des intersections détectées, plus 0,6 km.
- **Feuilles allemandes de bord.** Pour Bâle, Osnabrück, Rostock et Stralsund, la détection automatique échoue : bande blanche « covered by… », mer, scan déformé. Leurs coins ont donc été relevés à la main sur les intersections étiquetées du cadre (`corners_px`). Pour Bâle, la bande blanche à l'ouest est exclue par un polygone en pixels (`mask_px`). Rostock et Stralsund gardent un résidu de 0,4–0,5 km aux coins, à cause de la déformation du scan.

## Données

| Fichier | Source | Contenu |
|---|---|---|
| `data/sites.js` | Sélection manuelle | Lieux majeurs, décrits en français. Coordonnées approximatives pour les batailles étendues. |
| `data/wikidata.js` | [Wikidata](https://www.wikidata.org) (CC0), généré | Tous les éléments géolocalisés liés à la 2e GM en BE/FR/DE |
| `data/ehri_camps.js` | [EHRI](https://geodata.ehri-project.eu), jeu « Concentration camps » (EHRI-camps-2022), généré | Camps et sous-camps (Außenlager) avec leur camp principal ; pays attribué via les frontières Natural Earth. Pas de dates dans la source. |
| `data/osm.js` | © contributeurs [OpenStreetMap](https://www.openstreetmap.org/copyright) (ODbL), via QLever, généré | Bunkers, fortifications, abris antiaériens et champs de bataille rattachés à 1939-1945 |

### Mettre à jour les bunkers et champs de bataille OpenStreetMap

```bash
python scripts/fetch_osm.py
```

Les données sont extraites en deux requêtes du service SPARQL **QLever** (université de Fribourg, `https://qlever.dev/api/osm-planet`, copie complète d'OSM). Le pays vient directement des relations frontières que l'objet intersecte. Les serveurs Overpass publics, essayés d'abord, étaient trop souvent saturés pour une extraction sur trois pays. Résultat actuel : 3 394 sites retenus sur environ 28 000 objets candidats.

OSM indique rarement l'époque d'un bunker.
- **France et Allemagne :** un élément n'est retenu que si sa date de construction (1928-1945), son nom, sa description ou sa ligne défensive le rattachent à la Seconde Guerre mondiale (Atlantikwall, Westwall, Maginot, Regelbau, abris antiaériens, WN/Stützpunkt…).
- **Belgique :** toutes les fortifications sont retenues (bunkers, forts, casemates, tranchées, citadelles, environ 3 000 éléments), avec leur époque dans le champ `ep`, que l'application filtre (section « Époque »).
  - Les forts et citadelles non datés sont tous antérieurs à 1914.
  - Les 12 forts Brialmont de Liège et les 9 de Namur (1888-1892) sont rattachés à leur position fortifiée.
  - Les forts neufs des années 1930 (Ében-Émael, Aubin-Neufchâteau, Battice, Tancrémont) sont classés 1939-1945.
  - Les autres éléments sont datés par leur date, leur nom ou leur description (1914-1918, 1939-1945, après 1945). Sans indice, ils restent « époque non précisée » : c'est le cas d'environ 2 500 bunkers, dont beaucoup de 1914-1918 en Flandre et de la ligne KW, rarement renseignés dans OSM.

**Licence ODbL** : en cas de diffusion publique de la carte, la mention « © contributeurs OpenStreetMap » est obligatoire (elle figure dans le pied de page), et toute base de données dérivée doit rester sous ODbL.

### Mettre à jour les camps EHRI

```bash
python scripts/fetch_ehri_camps.py
```

Les camps déjà présents dans la sélection manuelle ou Wikidata (moins de 3 km et nom commun) sont ignorés. La fiche de métadonnées EHRI ne précise pas de licence : citez l'EHRI comme source en cas de diffusion publique.

À propos des **Arolsen Archives** : elles ne publient pas de liste téléchargeable des sous-camps. Seuls existent des documents numérisés, par exemple la liste UNRRA de 1946 des camps et Kommandos, et des exports sur demande. Le jeu EHRI, construit en partie à partir de ces sources, sert ici de substitut.

### Mettre à jour l'import Wikidata

```bash
python scripts/fetch_wikidata.py
```

Le script interroge le service SPARQL public, puis l'API Wikidata par lots. Il affiche les types d'éléments qu'il n'a pas su classer : ajoutez-les dans `RULES` pour les inclure.

### Ajouter un lieu à la main

Ajoutez une ligne dans `data/sites.js` :

```js
{ n: "Nom", c: "battle", sub: "Sous-type", cc: "BE", lat: 50.0, lon: 5.0, s: "1944-12-16", e: "1945-01-25", d: "Description." },
```

Catégories : `battle`, `camp`, `massacre`, `military`, `event`, `memorial`, `museum`. Pays : `BE`, `FR`, `DE`.

## Autres archives publiques à intégrer

- **CWGC** (Commonwealth War Graves Commission) : cimetières et sépultures
- **ABMC** (American Battle Monuments Commission) : cimetières et mémoriaux américains
- **Volksbund** : cimetières militaires allemands
- **Mémoire des hommes** (ministère des Armées) : lieux de mémoire, sépultures de guerre
- **Arolsen Archives** : déportations (sur demande, voir plus haut)
- **USHMM Encyclopedia of Camps and Ghettos** : dates d'ouverture et de fermeture des sous-camps
- **CegeSoma / Archives de l'État** (Belgique) : occupation et résistance en Belgique
- **OpenStreetMap** : mémoriaux (`historic=memorial` + `memorial=war_memorial`), épaves (`historic=wreck`)
