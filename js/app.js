// Carte WW2 — logique de l'application
(function () {
  "use strict";

  const CATEGORIES = {
    battle:   { label: "Bataille / opération",            color: "#c0392b" },
    camp:     { label: "Camp (concentration, transit, prisonniers…)", color: "#6c3483" },
    massacre: { label: "Massacre / crime de guerre",      color: "#1c1c1c" },
    military: { label: "Site militaire (fort, bunker, base)", color: "#8a6d1d" },
    event:    { label: "Événement (libération, bombardement…)", color: "#e67e22" },
    memorial: { label: "Cimetière / mémorial",            color: "#7f8c8d" },
    museum:   { label: "Musée",                           color: "#2471a3" },
  };
  const COUNTRIES = { BE: "Belgique", FR: "France", DE: "Allemagne" };
  const SOURCES = {
    curated: "Sélection manuelle",
    wikidata: "Wikidata (import automatique)",
    ehri: "EHRI — camps et sous-camps",
    osm: "OpenStreetMap — bunkers, champs de bataille",
  };
  const LINK_LABELS = { ehri: "Fiche EHRI", osm: "Voir sur OpenStreetMap" };

  // ---- Données ----
  const curated = (window.WW2_SITES || []).map((s, i) => ({ ...s, id: "c" + i, src: "curated" }));
  const wiki = (window.WW2_WIKIDATA || []).map((s) => ({ ...s, id: s.qid, src: "wikidata" }));
  const ehri = (window.WW2_EHRI || []).map((s, i) => ({ ...s, id: "e" + i, src: "ehri" }));
  const osmSites = (window.WW2_OSM || []).map((s, i) => ({ ...s, id: "o" + i, src: "osm" }));
  const all = curated.concat(wiki, ehri, osmSites).filter((s) => CATEGORIES[s.c] && COUNTRIES[s.cc]);

  const yearOf = (d) => (d ? parseInt(String(d).slice(0, 4), 10) : null);
  all.forEach((s) => {
    s.y0 = yearOf(s.s);
    s.y1 = yearOf(s.e) ?? s.y0;
    s.search = [s.n, s.d, s.sub, s.place, s.parent].filter(Boolean).join(" ").toLowerCase()
      .normalize("NFD").replace(/[̀-ͯ]/g, "");
  });

  // ---- Carte ----
  const map = L.map("map", { zoomControl: true }).setView([49.8, 5.5], 6);
  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: "© OpenStreetMap",
  }).addTo(map);
  const topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    maxZoom: 17, attribution: "© OpenStreetMap, SRTM | © OpenTopoMap (CC-BY-SA)",
  });
  // Vue satellite actuelle (OpenStreetMap n'en publie pas) : imagerie mondiale Esri
  const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 20, maxNativeZoom: 19, attribution: "Imagerie © Esri, Maxar, Earthstar Geographics",
  });
  // ---- Cartes et photos aériennes historiques (superposables) ----
  const IGN = "© IGN – Géoplateforme";
  const ign = (layer, matrixSet, format, opts) => L.tileLayer(
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
    `&LAYER=${layer}&STYLE=${opts.style || "normal"}&TILEMATRIXSET=${matrixSet}` +
    `&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=${format}`,
    { attribution: IGN, maxZoom: 18, pane: "hist", ...opts },
  );
  const FRANCE = L.latLngBounds([41.2, -5.3], [51.2, 9.7]);
  // couches historiques dans leur propre panneau (au-dessus du fond actuel) : le rideau peut les découper
  map.createPane("hist").style.zIndex = 250;
  const HISTORICAL = {
    "🇫🇷 Carte de France 1950 (IGN, 1:50 000)": ign("GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN50.1950", "PM_3_15", "image/jpeg",
      { maxNativeZoom: 15, minZoom: 3, bounds: FRANCE }),
    "🇫🇷 Photos aériennes 1950-1965 (IGN)": ign("ORTHOIMAGERY.ORTHOPHOTOS.1950-1965", "PM_0_18", "image/png",
      { maxNativeZoom: 18, bounds: FRANCE }),
    "🇫🇷 Normandie : photos aériennes 1947 (Calvados, IGN)": ign("orthophoto_1947_calvados", "PM_0_18", "image/png",
      { style: "transparent", maxNativeZoom: 18, bounds: L.latLngBounds([48.75, -1.17], [49.44, 0.45]) }),
    "🇫🇷 Carte d'état-major 1820-1866 (IGN)": ign("GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40", "PM_6_15", "image/jpeg",
      { maxNativeZoom: 15, minZoom: 6, bounds: FRANCE }),
    "🇧🇪 Wallonie : photos aériennes 1971 (SPW)": L.tileLayer.wms(
      "https://geoservices.wallonie.be/arcgis/services/IMAGERIE/ORTHO_1971/MapServer/WMSServer",
      { layers: "0", format: "image/png", version: "1.3.0", maxZoom: 18, minZoom: 9, pane: "hist",
        bounds: L.latLngBounds([49.45, 2.8], [50.86, 6.45]), attribution: "© SPW – Géoportail de la Wallonie" }),
    // Relief LIDAR (ombrage du modèle numérique de terrain) : trous d'obus, tranchées, abris, emplacements
    // de pièces restent visibles sous la végétation, notamment dans les Ardennes (bataille des Ardennes)
    "🇧🇪 Wallonie : relief LIDAR 2021-2022 (0,5 m)": L.tileLayer.wms(
      "https://geoservices.wallonie.be/arcgis/services/RELIEF/WALLONIE_MNT_2021_2022_HILLSHADE/MapServer/WMSServer",
      { layers: "0", format: "image/png", version: "1.3.0", maxZoom: 19, minZoom: 9, pane: "hist",
        bounds: L.latLngBounds([49.45, 2.8], [50.86, 6.45]), attribution: "Relief LIDAR © SPW – Géoportail de la Wallonie" }),
    "🇧🇪 Flandre et Bruxelles : relief LIDAR DHMV II (0,25 m)": L.tileLayer.wms(
      "https://geo.api.vlaanderen.be/DHMV/wms",
      { layers: "DHMV_II_HILL_25cm", format: "image/png", version: "1.3.0", maxZoom: 19, minZoom: 9, pane: "hist",
        bounds: L.latLngBounds([50.65, 2.5], [51.53, 5.95]), attribution: "Relief LIDAR © Digitaal Vlaanderen (DHMV II)" }),
    "🇩🇪 Berlin : photos aériennes 1953": L.tileLayer.wms(
      "https://gdi.berlin.de/services/wms/luftbild_1953_22",
      { layers: "c_luftbilder_1953_22_raster", format: "image/png", version: "1.3.0", maxZoom: 18, minZoom: 10, pane: "hist",
        bounds: L.latLngBounds([52.33, 13.08], [52.68, 13.77]), attribution: "Geoportal Berlin / Luftbilder 1953 (dl-zero-de/2.0)" }),
  };
  let histOpacity = 0.85;
  Object.values(HISTORICAL).forEach((l) => l.setOpacity(histOpacity));
  L.control.layers({ "Plan (OSM)": osm, "Relief (OpenTopoMap)": topo, "Satellite (Esri)": sat }, HISTORICAL, { collapsed: true }).addTo(map);

  // Curseur d'opacité, visible seulement quand une couche historique est active
  const OpacityControl = L.Control.extend({
    options: { position: "topright" },
    onAdd() {
      const div = L.DomUtil.create("div", "leaflet-bar opacity-control");
      div.innerHTML = `<label>Carte ancienne <input type="range" min="0" max="100" value="${histOpacity * 100}"></label>`;
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);
      div.querySelector("input").addEventListener("input", (e) => setHistOpacity(e.target.value / 100));
      this._div = div;
      return div;
    },
  });
  const opacityCtl = new OpacityControl().addTo(map);
  function setHistOpacity(v) {
    histOpacity = v;
    Object.values(HISTORICAL).forEach((l) => l.setOpacity(v));
    opacityCtl._div.querySelector("input").value = Math.round(v * 100);
  }
  const syncOpacityCtl = () => {
    const anyOn = Object.values(HISTORICAL).some((l) => map.hasLayer(l));
    opacityCtl._div.style.display = anyOn ? "" : "none";
  };
  map.on("overlayadd overlayremove", syncOpacityCtl);
  syncOpacityCtl();
  L.control.scale({ imperial: false }).addTo(map);

  // ---- Rideau de comparaison : à gauche les cartes anciennes, à droite la carte actuelle ----
  (function swipe() {
    const PANES = ["hist", "gsgs", "overlayPane"];  // cartes anciennes, GSGS, cartes de situation et front
    let on = false, frac = 0.5;
    const bar = L.DomUtil.create("div", "swipe-bar", map.getContainer());
    bar.innerHTML = '<div class="swipe-handle" title="Glisser pour comparer">⇆</div>';
    bar.hidden = true;
    L.DomEvent.disableClickPropagation(bar);
    const panes = () => PANES.map((n) => map.getPane(n)).filter(Boolean);
    function update() {
      if (!on) return;
      const size = map.getSize();
      const x = Math.round(size.x * frac);
      bar.style.left = x + "px";
      const nw = map.containerPointToLayerPoint([0, 0]);
      const se = map.containerPointToLayerPoint(size);
      const cx = map.containerPointToLayerPoint([x, 0]).x;
      const clip = `rect(${nw.y}px, ${cx}px, ${se.y}px, ${nw.x}px)`;
      panes().forEach((p) => { p.style.clip = clip; });
    }
    let savedOpacity = null;
    function setOn(v) {
      on = v;
      bar.hidden = !v;
      btn.classList.toggle("active", v);
      // en comparaison, la couche ancienne (ou le LIDAR) est opaque à gauche : le fond choisi (plan, satellite)
      // n'apparaît qu'à droite ; l'opacité précédente est rétablie à la sortie
      if (v) { savedOpacity = histOpacity; setHistOpacity(1); update(); }
      else { if (savedOpacity !== null) setHistOpacity(savedOpacity); panes().forEach((p) => { p.style.clip = ""; }); }
    }
    let dragging = false;
    bar.addEventListener("pointerdown", (e) => { dragging = true; bar.setPointerCapture(e.pointerId); map.dragging.disable(); e.preventDefault(); });
    bar.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const r = map.getContainer().getBoundingClientRect();
      frac = Math.min(0.98, Math.max(0.02, (e.clientX - r.left) / r.width));
      update();
    });
    const end = () => { if (dragging) { dragging = false; map.dragging.enable(); } };
    bar.addEventListener("pointerup", end);
    bar.addEventListener("pointercancel", end);
    map.on("move zoom zoomend resize viewreset", update);
    let btn;
    const Ctl = L.Control.extend({
      options: { position: "topright" },
      onAdd() {
        btn = L.DomUtil.create("a", "leaflet-bar swipe-toggle");
        btn.href = "#"; btn.role = "button";
        btn.title = "Rideau de comparaison : cartes anciennes à gauche, carte actuelle à droite";
        btn.textContent = "⇆ Comparer";
        L.DomEvent.on(btn, "click", (e) => { L.DomEvent.stop(e); setOn(!on); });
        return btn;
      },
    });
    new Ctl().addTo(map);
  })();

  const cluster = L.markerClusterGroup({ maxClusterRadius: 45, disableClusteringAtZoom: 14, chunkedLoading: true });
  map.addLayer(cluster);

  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function fmtDate(d) {
    if (!d) return "";
    const p = String(d).split("-");
    if (p.length === 1) return p[0];
    const months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
    if (p.length === 2) return `${months[+p[1] - 1]} ${p[0]}`;
    return `${+p[2]} ${months[+p[1] - 1]} ${p[0]}`;
  }
  function fmtRange(s) {
    if (!s.s) return "";
    if (!s.e || s.e === s.s) return fmtDate(s.s);
    return `${fmtDate(s.s)} – ${fmtDate(s.e)}`;
  }

  function popupHtml(s) {
    const cat = CATEGORIES[s.c];
    const link = s.url
      ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${LINK_LABELS[s.src] || "Article"}</a>`
      : `<a href="https://fr.wikipedia.org/w/index.php?search=${encodeURIComponent(s.n)}" target="_blank" rel="noopener">Rechercher sur Wikipédia</a>`;
    const wd = s.qid ? ` · <a href="https://www.wikidata.org/wiki/${esc(s.qid)}" target="_blank" rel="noopener">Wikidata ${esc(s.qid)}</a>` : "";
    return `<div class="popup">
      <h3>${esc(s.n)}</h3>
      <span class="tag" style="background:${cat.color}">${esc(s.sub || cat.label)}</span>
      ${s.s ? `<div class="dates">${esc(fmtRange(s))}</div>` : ""}
      ${s.d ? `<p>${esc(s.d)}</p>` : ""}
      <p class="src">${esc(COUNTRIES[s.cc])} · ${esc(SOURCES[s.src])}<br>${link}${wd}</p>
    </div>`;
  }

  const markers = new Map();
  all.forEach((s) => {
    const icon = L.divIcon({
      className: "",
      html: `<div class="ww2-marker" style="background:${CATEGORIES[s.c].color}"></div>`,
      iconSize: [16, 16], iconAnchor: [8, 8], popupAnchor: [0, -8],
    });
    const m = L.marker([s.lat, s.lon], { icon, title: s.n }).bindPopup(() => popupHtml(s), { maxWidth: 320 });
    markers.set(s.id, m);
  });

  // ---- Cartes de situation quotidiennes (12th Army Group) ----
  (function sitmaps() {
    // Pour chaque jour, on affiche toutes les feuilles qui couvrent des régions différentes
    // (ex. 10 septembre 1944 : front principal + Bretagne). Si deux feuilles couvrent la même
    // région (chevauchement > 50 %), on garde celle dont l'alignement est le plus sûr.
    const area = (b) => Math.max(0, b[1][0] - b[0][0]) * Math.max(0, b[1][1] - b[0][1]);
    const overlap = (a, b) => area([[Math.max(a[0][0], b[0][0]), Math.max(a[0][1], b[0][1])],
                                   [Math.min(a[1][0], b[1][0]), Math.min(a[1][1], b[1][1])]]);
    const groups = new Map();
    (window.WW2_SITMAPS || []).forEach((m) => {
      if (!groups.has(m.date)) groups.set(m.date, []);
      groups.get(m.date).push(m);
    });
    const list = [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([date, maps]) => {
      const kept = [];
      maps.sort((a, b) => (b.inliers || 0) - (a.inliers || 0)).forEach((m) => {
        if (kept.every((k) => overlap(k.bounds, m.bounds) < 0.5 * Math.min(area(k.bounds), area(m.bounds)))) kept.push(m);
      });
      return { date, maps: kept };
    });
    if (!list.length) return;
    const $ = (id) => document.getElementById(id);
    $("sitmap-section").hidden = false;
    const slider = $("sitmap-slider");
    slider.max = list.length - 1;
    let idx = list.length - 1, overlays = [];
    // lignes de front vectorisées (scripts/fronts) : par date, toutes séries confondues
    const fronts = new Map();
    (window.WW2_FRONTS || []).forEach((f) => {
      if (!fronts.has(f.date)) fronts.set(f.date, []);
      fronts.get(f.date).push(...f.lines);
    });
    const frontDates = [...fronts.keys()].sort();
    const frontLayer = L.layerGroup();
    if (!frontDates.length) $("front-on").parentElement.hidden = true;
    function showFront(date) {
      frontLayer.clearLayers();
      $("front-note").textContent = "";
      if (!$("front-on").checked) return;
      // date sans tracé : on garde le dernier front connu (au plus 3 jours avant)
      let d = date;
      if (!fronts.has(d)) {
        const prev = frontDates.filter((x) => x <= date).pop();
        if (prev && (new Date(date) - new Date(prev)) / 864e5 <= 3) d = prev; else d = null;
      }
      if (!d) { $("front-note").textContent = "pas de front tracé ce jour"; return; }
      if (d !== date) $("front-note").textContent = "front du " + new Date(d + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
      L.polyline(fronts.get(d), { color: "#c0392b", weight: 3, opacity: 0.9, interactive: false }).addTo(frontLayer);
    }
    const fmt = (d) => new Date(d + "T12:00:00").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "long", year: "numeric" });
    const clear = () => { overlays.forEach((o) => map.removeLayer(o)); overlays = []; };
    function show() {
      const day = list[idx];
      slider.value = idx;
      $("sitmap-label").textContent = fmt(day.date) + (day.maps.length > 1 ? ` (${day.maps.length} cartes)` : "");
      $("sitmap-label").title = day.maps.map((m) => m.label || "").join(" + ");
      $("sitmap-link").href = day.maps[0].source;
      showFront(day.date);
      if (!$("sitmap-on").checked) return;
      const opacity = $("sitmap-opacity").value / 100;
      // réutiliser les calques existants quand le nombre de feuilles ne change pas (évite le clignotement)
      if (overlays.length !== day.maps.length) {
        clear();
        overlays = day.maps.map((m) => L.imageOverlay(m.file, m.bounds,
          { opacity, attribution: "Cartes de situation : 12th Army Group / Library of Congress" }).addTo(map));
      } else {
        day.maps.forEach((m, i) => { overlays[i].setUrl(m.file); overlays[i].setBounds(L.latLngBounds(m.bounds)); });
      }
    }
    const syncControls = () => { $("sitmap-controls").hidden = !($("sitmap-on").checked || $("front-on").checked); };
    $("sitmap-on").addEventListener("change", (e) => {
      syncControls();
      if (e.target.checked) {
        show();
        const b = L.latLngBounds(list[idx].maps[0].bounds);
        if (!map.getBounds().intersects(b)) map.fitBounds(b);
      } else clear();
    });
    $("front-on").addEventListener("change", (e) => {
      syncControls();
      if (e.target.checked) {
        frontLayer.addTo(map);
        show();
        const b = L.latLngBounds(list[idx].maps[0].bounds);
        if (!map.getBounds().intersects(b)) map.fitBounds(b);
      } else { stop(); map.removeLayer(frontLayer); }
    });
    // animation jour par jour
    let timer = null;
    function stop() { clearInterval(timer); timer = null; $("sitmap-play").textContent = "⏵ Animer"; }
    $("sitmap-play").addEventListener("click", () => {
      if (timer) return stop();
      if (idx >= list.length - 1) idx = 0;
      $("sitmap-play").textContent = "⏸ Pause";
      timer = setInterval(() => { if (idx >= list.length - 1) return stop(); idx++; show(); },
        $("sitmap-on").checked ? 900 : 350);
    });
    slider.addEventListener("input", () => { stop(); idx = +slider.value; show(); });
    $("sitmap-prev").addEventListener("click", () => { stop(); if (idx > 0) { idx--; show(); } });
    $("sitmap-next").addEventListener("click", () => { stop(); if (idx < list.length - 1) { idx++; show(); } });
    $("sitmap-opacity").addEventListener("input", (e) => overlays.forEach((o) => o.setOpacity(e.target.value / 100)));
    show();
  })();

  // ---- Cartes topographiques GSGS (feuilles calées, chargées à la demande) ----
  (function gsgs() {
    const sheets = window.WW2_GSGS || [];
    if (!sheets.length) return;
    const $ = (id) => document.getElementById(id);
    $("gsgs-section").hidden = false;
    const MIN_ZOOM = 8;            // en dessous, trop de feuilles à charger pour une lecture utile
    const series = [...new Set(sheets.map((s) => s.series))];
    const labels = Object.fromEntries(sheets.map((s) => [s.series, s.label]));
    const on = new Set();
    const shown = new Map();       // clé feuille → calque Leaflet
    $("gsgs-series").innerHTML = series.map((k) =>
      `<label class="check"><input type="checkbox" value="${k}"> ${esc(labels[k])}<span class="count">${sheets.filter((s) => s.series === k).length}</span></label>`
    ).join("");
    const pane = map.createPane("gsgs");   // sous les cartes de situation et les marqueurs
    pane.style.zIndex = 390;
    function refreshSheets() {
      const view = map.getBounds().pad(0.2);
      const zoomOk = map.getZoom() >= MIN_ZOOM;
      $("gsgs-hint").style.fontWeight = on.size && !zoomOk ? "600" : "";
      const wanted = new Set(zoomOk ? sheets.filter((s) => on.has(s.series) && view.intersects(L.latLngBounds(s.bounds)))
        .map((s) => s.series + "/" + s.sheet) : []);
      for (const [k, layer] of shown) if (!wanted.has(k)) { map.removeLayer(layer); shown.delete(k); }
      const opacity = $("gsgs-opacity").value / 100;
      sheets.forEach((s) => {
        const k = s.series + "/" + s.sheet;
        if (wanted.has(k) && !shown.has(k)) {
          shown.set(k, L.imageOverlay(s.file, s.bounds, { opacity, pane: "gsgs",
            attribution: "Cartes GSGS : War Office / US Army Map Service (domaine public), via Wikimedia Commons" }).addTo(map));
        }
      });
    }
    $("gsgs-series").addEventListener("change", (e) => {
      if (e.target.checked) on.add(e.target.value); else on.delete(e.target.value);
      if (e.target.checked && map.getZoom() < MIN_ZOOM) {
        const b = sheets.filter((s) => s.series === e.target.value).reduce((acc, s) => acc.extend(L.latLngBounds(s.bounds)), L.latLngBounds([]));
        if (!map.getBounds().intersects(b)) map.fitBounds(b); else map.setZoom(MIN_ZOOM);
      }
      refreshSheets();
    });
    $("gsgs-opacity").addEventListener("input", (e) => shown.forEach((l) => l.setOpacity(e.target.value / 100)));
    map.on("moveend zoomend", refreshSheets);
  })();

  // ---- Filtres ----
  const state = {
    cats: new Set(Object.keys(CATEGORIES)),
    countries: new Set(Object.keys(COUNTRIES)),
    sources: new Set(Object.keys(SOURCES)),
    q: "", yMin: 1939, yMax: 1945, undated: true,
  };

  function buildChecks(containerId, dict, set, colorFn, countKey) {
    const el = document.getElementById(containerId);
    el.innerHTML = Object.entries(dict).map(([k, v]) => {
      const label = typeof v === "string" ? v : v.label;
      const n = all.filter((s) => s[countKey] === k).length;
      const dot = colorFn ? `<span class="dot" style="background:${colorFn(k)}"></span>` : "";
      return `<label class="check"><input type="checkbox" value="${k}" checked>${dot}${esc(label)}<span class="count">${n}</span></label>`;
    }).join("");
    el.addEventListener("change", (e) => {
      if (e.target.checked) set.add(e.target.value); else set.delete(e.target.value);
      refresh();
    });
  }
  buildChecks("cat-filters", CATEGORIES, state.cats, (k) => CATEGORIES[k].color, "c");
  buildChecks("country-filters", COUNTRIES, state.countries, null, "cc");
  buildChecks("source-filters", SOURCES, state.sources, null, "src");

  const yMinEl = document.getElementById("year-min");
  const yMaxEl = document.getElementById("year-max");
  function onYears(e) {
    let a = +yMinEl.value, b = +yMaxEl.value;
    if (a > b) { if (e.target === yMinEl) b = a; else a = b; yMinEl.value = a; yMaxEl.value = b; }
    state.yMin = a; state.yMax = b; refresh();
  }
  yMinEl.addEventListener("input", onYears);
  yMaxEl.addEventListener("input", onYears);
  document.getElementById("include-undated").addEventListener("change", (e) => { state.undated = e.target.checked; refresh(); });

  let t;
  document.getElementById("search").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.q = e.target.value.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
      refresh();
    }, 150);
  });

  function visible(s) {
    if (!state.cats.has(s.c) || !state.countries.has(s.cc) || !state.sources.has(s.src)) return false;
    if (s.y0 == null) { if (!state.undated) return false; }
    else if (s.y1 < state.yMin || s.y0 > state.yMax) return false;
    if (state.q && !s.search.includes(state.q)) return false;
    return true;
  }

  const listEl = document.getElementById("result-list");
  const MAX_LIST = 300;
  function refresh() {
    document.getElementById("year-label").textContent = `${state.yMin} – ${state.yMax}`;
    const shown = all.filter(visible).sort((a, b) => (a.y0 ?? 9999) - (b.y0 ?? 9999) || (a.s || "").localeCompare(b.s || "") || a.n.localeCompare(b.n));
    cluster.clearLayers();
    cluster.addLayers(shown.map((s) => markers.get(s.id)));
    document.getElementById("result-count").textContent = shown.length;
    listEl.innerHTML = shown.slice(0, MAX_LIST).map((s) =>
      `<li data-id="${esc(s.id)}"><span class="dot" style="background:${CATEGORIES[s.c].color}"></span>${esc(s.n)}<span class="meta">${s.y0 ?? ""} ${s.cc}</span></li>`
    ).join("") + (shown.length > MAX_LIST ? `<li class="more">… et ${shown.length - MAX_LIST} autres (affinez la recherche)</li>` : "");
  }

  listEl.addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]");
    if (!li) return;
    const m = markers.get(li.dataset.id);
    map.setView(m.getLatLng(), Math.max(map.getZoom(), 14));
    cluster.zoomToShowLayer(m, () => m.openPopup());
    document.getElementById("sidebar").classList.remove("open");
  });
  document.getElementById("toggle-sidebar").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("open");
  });

  refresh();
})();
