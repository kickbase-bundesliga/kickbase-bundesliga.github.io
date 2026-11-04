# -*- coding: utf-8 -*-
"""
Statistik-Reiter: Kennzahlen aus allen Spieltagspunkten eines Ligasystems (docs/data/<system>/stats.json).

Datenbasis: MdPoints je Manager und Saison aus der Datenbank. Aeltere Saisons haben nicht fuer alle
Ligen Spieltagspunkte (nur Abschlusstabellen) - die zaehlen dann nur bei den Saisonpunkten mit.
Ein Spieltag mit 0 oder Minuspunkten gilt als "nicht oder unvollstaendig aufgestellt" (Kickbase zieht
je fehlendem Spieler 100 Punkte ab, leer = -1.100; mit 11 Spielern ins Minus ist praktisch ausgeschlossen)
bzw. noch nicht dabei und zaehlt bei
Schnitt, Median, Tiefstwerten und Spieltagsplaetzen nicht mit, nur in der Verteilung als eigene Gruppe.

Wird von build_site.py aufgerufen (build_system).
"""
import json
import math
import os
import statistics

TOP = 25                 # Laenge der Bestenlisten
MIN_MD_KONSTANZ = 30     # mindestens so viele Spieltage fuer Konstanz-Listen
MIN_ANTEIL_SAISON = 0.7  # Saison-Bestwerte: mindestens 70 % der gespielten Spieltage dabei
MIN_MD_SAISON = 10       # ... und mindestens 10 Spieltage (laufende Saison erst ab dem 10.)
BUCKETS = [(1, 299, "1–299"), (300, 599, "300–599"), (600, 899, "600–899"),
           (900, 1199, "900–1.199"), (1200, 1499, "1.200–1.499"), (1500, 10 ** 9, "ab 1.500")]


def _kennzahlen(werte):
    if not werte:
        return None
    w = sorted(werte)
    return {"n": len(w), "mean": round(sum(w) / len(w), 1), "median": round(statistics.median(w), 1),
            "max": w[-1], "min": w[0], "p1000": round(100.0 * sum(1 for x in w if x >= 1000) / len(w), 1)}


def _bucket(p):
    for i, (lo, hi, _) in enumerate(BUCKETS):
        if lo <= p <= hi:
            return i
    return None


def _push(lst, item, key, n=TOP, reverse=True):
    lst.append(item)
    lst.sort(key=key, reverse=reverse)
    del lst[n:]


def build(system, seasons_cfg, quali, managers, league_level, short_league, out_dir):
    names = [s["name"] for s in seasons_cfg]
    cfg_of = {s["name"]: s for s in seasons_cfg}

    # --------------------------------------------------------------- Rohdaten je Saison
    # rows[s] = [(mid, liga, ebene, [md1..mdN], Saisonpunkte, Platz)]
    rows, last_md = {}, {}
    for s in names:
        rs = []
        for mid, m in managers.items():
            d = m.get(s)
            if not isinstance(d, dict) or not d.get("League") or d["League"] not in league_level:
                continue
            md = [p if (p or 0) > 0 else 0 for p in (d.get("MdPoints") or [])[1:]]
            rs.append((mid, d["League"], league_level[d["League"]], md, d.get("Points"), d.get("Place")))
        rows[s] = rs
        last_md[s] = max([i + 1 for r in rs for i, p in enumerate(r[3]) if p] or [0])

    def werte(s, filt=None):
        out = []
        for r in rows[s]:
            if filt and not filt(r):
                continue
            out.extend(p for p in r[3][:last_md[s]] if p)
        return out

    levels = sorted(set(r[2] for s in names for r in rows[s]))

    # --------------------------------------------------------------- Saisons / Ebenen / Ligen
    saisons, verlauf, verteilung = [], {}, {"labels": [b[2] for b in BUCKETS], "data": {}}
    alle_werte, je_ebene = [], {lv: [] for lv in levels}

    def zaehlen(ws, nullen):
        c = [0] * len(BUCKETS)
        for p in ws:
            c[_bucket(p)] += 1
        return {"c": c, "z": nullen}

    for s in names:
        if not last_md[s]:
            continue
        info = {"s": s, "quali": s in quali, "md": last_md[s], "md_soll": int(cfg_of[s]["matchday_number"]),
                "first": int(cfg_of[s]["first_matchday"]), "mgr": len(rows[s]),
                "mgr_md": sum(1 for r in rows[s] if any(r[3][:last_md[s]])),
                "all": _kennzahlen(werte(s)), "levels": {}, "leagues": [], "matchdays": []}
        nullen_s = 0
        for lv in levels:
            ws = werte(s, lambda r: r[2] == lv)
            if not ws:
                continue
            k = _kennzahlen(ws)
            pts = [r[4] for r in rows[s] if r[2] == lv and r[4] and any(r[3][:last_md[s]])]
            k["season_mean"] = round(sum(pts) / len(pts)) if pts else None
            k["season_median"] = round(statistics.median(pts)) if pts else None
            info["levels"][str(lv)] = k
            if s not in quali:
                je_ebene[lv].extend(ws)
                verlauf.setdefault(str(lv), {})[s] = k["mean"]
            nz = sum(1 for r in rows[s] if r[2] == lv and any(r[3][:last_md[s]]) for p in r[3][:last_md[s]] if not p)
            nullen_s += nz
            verteilung["data"].setdefault(s, {})[str(lv)] = zaehlen(ws, nz)
        for liga in sorted(set(r[1] for r in rows[s]), key=lambda n: (league_level[n], n)):
            ws = werte(s, lambda r: r[1] == liga)
            if ws:
                k = _kennzahlen(ws)
                k.update({"name": short_league(liga), "level": league_level[liga]})
                info["leagues"].append(k)
        for k in range(last_md[s]):
            ws = [r[3][k] for r in rows[s] if k < len(r[3]) and r[3][k]]
            if not ws:
                continue
            e = _kennzahlen(ws)
            e["k"] = k + 1
            e["lv"] = {}
            for lv in levels:
                wl = [r[3][k] for r in rows[s] if r[2] == lv and k < len(r[3]) and r[3][k]]
                if wl:
                    e["lv"][str(lv)] = [round(sum(wl) / len(wl)), round(statistics.median(wl))]
            info["matchdays"].append(e)
        if s not in quali:
            alle_werte.extend(werte(s))
        saisons.append(info)

    gesamt = {"all": _kennzahlen(alle_werte), "levels": {str(lv): _kennzahlen(w) for lv, w in je_ebene.items() if w}}
    # Verteilung gesamt
    for lv in levels:
        c, z = [0] * len(BUCKETS), 0
        for s, d in verteilung["data"].items():
            if s in quali or str(lv) not in d:
                continue
            c = [a + b for a, b in zip(c, d[str(lv)]["c"])]
            z += d[str(lv)]["z"]
        verteilung["data"].setdefault("all", {})[str(lv)] = {"c": c, "z": z}

    # --------------------------------------------------------------- Spieltagsplaetze je Liga
    # Fuer jede Liga und jeden Spieltag: Sieger, Letzter, Ligaschnitt
    siege, letzte, md_n = {}, {}, {}
    glueck = []
    ueber_schnitt = {}        # (mid, s) -> [bool je Spieltag oder None]
    sieg_reihe = {}           # (mid, s) -> [bool je Spieltag oder None]
    for s in names:
        if s in quali or not last_md[s]:
            continue
        ligen = {}
        for r in rows[s]:
            ligen.setdefault(r[1], []).append(r)
        for liga, rs in ligen.items():
            mit = [r for r in rs if any(r[3][:last_md[s]])]
            if len(mit) < 4:
                continue
            for k in range(last_md[s]):
                tag = [(r[0], r[3][k]) for r in mit if k < len(r[3]) and r[3][k]]
                if len(tag) < max(4, len(mit) // 2):
                    continue
                schnitt = sum(p for _, p in tag) / len(tag)
                hoch = max(p for _, p in tag)
                tief = min(p for _, p in tag)
                for mid, p in tag:
                    md_n[mid] = md_n.get(mid, 0) + 1
                    ueber_schnitt.setdefault((mid, s), [None] * last_md[s])[k] = p > schnitt
                    sieg_reihe.setdefault((mid, s), [None] * last_md[s])[k] = p == hoch
                    if p == hoch:
                        siege[mid] = siege.get(mid, 0) + 1
                        _push(glueck, [p, mid, s, k + 1, short_league(liga), round(schnitt)], key=lambda x: -x[0], n=15)
                    if p == tief:
                        letzte[mid] = letzte.get(mid, 0) + 1

    # Pech: hoechste Punktzahl ohne Spieltagssieg - je Liga-Spieltag nur der Zweite zaehlt
    pech = []
    for s in names:
        if s in quali or not last_md[s]:
            continue
        ligen = {}
        for r in rows[s]:
            if any(r[3][:last_md[s]]):
                ligen.setdefault(r[1], []).append(r)
        for liga, rs in ligen.items():
            if len(rs) < 4:
                continue
            for k in range(last_md[s]):
                tag = sorted(((r[3][k], r[0]) for r in rs if k < len(r[3]) and r[3][k]), reverse=True)
                if len(tag) < max(4, len(rs) // 2) or tag[0][0] == tag[1][0]:
                    continue
                _push(pech, [tag[1][0], tag[1][1], s, k + 1, short_league(liga), tag[0][0], tag[0][1]],
                      key=lambda x: x[0], n=15)

    def serie(flags):
        best = cur = 0
        for f in flags:
            cur = cur + 1 if f else 0
            best = max(best, cur)
        return best

    serie_ueber, serie_sieg, serie_1000 = [], [], []
    for (mid, s), flags in ueber_schnitt.items():
        n = serie(flags)
        if n >= 3:
            _push(serie_ueber, [n, mid, s], key=lambda x: x[0], n=15)
    for (mid, s), flags in sieg_reihe.items():
        n = serie(flags)
        if n >= 2:
            _push(serie_sieg, [n, mid, s], key=lambda x: x[0], n=15)
    for s in names:
        if s in quali:
            continue
        for r in rows[s]:
            n = serie(p >= 1000 for p in r[3][:last_md[s]])
            if n >= 2:
                _push(serie_1000, [n, r[0], s, short_league(r[1])], key=lambda x: x[0], n=15)

    plaetze = []
    for mid, n in md_n.items():
        if n >= 10:
            plaetze.append([mid, n, siege.get(mid, 0), letzte.get(mid, 0)])
    meist_siege = sorted(plaetze, key=lambda x: (-x[2], x[1]))[:20]
    meist_letzte = sorted(plaetze, key=lambda x: (-x[3], x[1]))[:20]
    siegquote = sorted([p for p in plaetze if p[1] >= MIN_MD_KONSTANZ], key=lambda x: -x[2] / x[1])[:20]

    # --------------------------------------------------------------- Rekorde
    hoch, tief, saison_best, saison_schwach, saison_punkte, ohne_sieg = [], [], [], [], [], []
    sieg_in = {}
    for (mid, s), flags in sieg_reihe.items():
        sieg_in[(mid, s)] = sum(1 for f in flags if f)
    for s in names:
        if s in quali or not last_md[s]:
            continue
        fertig = s != names[-1]
        for r in rows[s]:
            for k, p in enumerate(r[3][:last_md[s]]):
                if not p:
                    continue
                _push(hoch, [p, r[0], s, k + 1, short_league(r[1])], key=lambda x: x[0])
                _push(tief, [p, r[0], s, k + 1, short_league(r[1])], key=lambda x: -x[0])
            ws = [p for p in r[3][:last_md[s]] if p]
            if len(ws) >= max(MIN_MD_SAISON, MIN_ANTEIL_SAISON * last_md[s]):
                avg = round(sum(ws) / len(ws), 1)
                e = [avg, r[0], s, short_league(r[1]), len(ws), r[5]]
                _push(saison_best, e, key=lambda x: x[0])
                _push(saison_schwach, e, key=lambda x: -x[0])
                if (r[0], s) in sieg_in and sieg_in[(r[0], s)] == 0:
                    _push(ohne_sieg, e, key=lambda x: x[0], n=15)
            if fertig and r[4]:
                _push(saison_punkte, [r[4], r[0], s, short_league(r[1]), int(cfg_of[s]["matchday_number"])],
                      key=lambda x: x[0])

    # --------------------------------------------------------------- Konstanz
    karriere = {}
    for s in names:
        if s in quali:
            continue
        for r in rows[s]:
            karriere.setdefault(r[0], []).extend(p for p in r[3][:last_md[s]] if p)
    konstanz = []
    for mid, ws in karriere.items():
        if len(ws) >= MIN_MD_KONSTANZ:
            mu = sum(ws) / len(ws)
            sd = math.sqrt(sum((x - mu) ** 2 for x in ws) / (len(ws) - 1))
            konstanz.append([mid, len(ws), round(mu), round(sd), max(ws), min(ws)])
    konstant = sorted(konstanz, key=lambda x: x[3])[:20]
    # Wundertueten: nur aktive Manager (sonst fuehren Dauer-Nichtaufsteller mit Teil-Aufstellungen)
    grenze = 0.75 * (gesamt["all"] or {"mean": 0})["mean"]
    wundertuete = sorted([k for k in konstanz if k[2] >= grenze], key=lambda x: -x[3])[:20]

    # --------------------------------------------------------------- Auf- und Abstieg
    ebene = {}
    avg_of = {}
    liga_mu = {}
    for s in names:
        for r in rows[s]:
            ebene[(r[0], s)] = r[2]
            ws = [p for p in r[3][:last_md[s]] if p]
            if len(ws) >= max(3, 0.5 * last_md[s]):
                avg_of[(r[0], s)] = (sum(ws) / len(ws), r[5], r[1])
        for liga in set(r[1] for r in rows[s]):
            ws = werte(s, lambda r: r[1] == liga)
            if ws:
                liga_mu[(s, liga)] = sum(ws) / len(ws)
    gruppen = {"auf": {}, "ab": {}, "bleib": {}}
    ab_mit_schnitt, auf_mit_schnitt = [], []
    for i in range(1, len(names)):
        alt, neu = names[i - 1], names[i]
        if alt in quali or not last_md[neu]:
            continue
        naechste = names[i + 1] if i + 1 < len(names) else None
        neu_info = next((x for x in saisons if x["s"] == neu), {"levels": {}})
        lv_schnitt = {lv: (neu_info["levels"].get(str(lv)) or {}).get("mean") for lv in levels}
        for mid in managers:
            a, b = ebene.get((mid, alt)), ebene.get((mid, neu))
            if a is None or b is None:
                continue
            if abs(a - b) > 1:
                continue            # mehrere Ebenen = Neustart nach Pause, kein normaler Auf-/Abstieg
            art = "auf" if b < a else "ab" if b > a else "bleib"
            # Wie lief es in der Vorsaison - gemessen am Schnitt der eigenen Liga?
            if (mid, alt) in avg_of and art != "bleib" and (alt, avg_of[(mid, alt)][2]) in liga_mu:
                mu_a, platz_a, liga_a = avg_of[(mid, alt)]
                e = [round(mu_a, 1), mid, alt, a, b, platz_a, round(mu_a - liga_mu[(alt, liga_a)])]
                if art == "ab" and e[6] > 0:
                    _push(ab_mit_schnitt, e, key=lambda x: x[6], n=15)
                elif art == "auf" and e[6] < 0:
                    _push(auf_mit_schnitt, e, key=lambda x: -x[6], n=15)
            # Erste Saison nach dem Wechsel im Vergleich zum Ebenenschnitt
            if (mid, neu) not in avg_of or not lv_schnitt.get(b):
                continue
            g = gruppen[art].setdefault(str(b), {"n": 0, "sum": 0.0, "ueber": 0, "platz": 0, "pn": 0,
                                                 "wieder": 0, "wn": 0})
            mu, platz, _ = avg_of[(mid, neu)]
            g["n"] += 1
            g["sum"] += mu
            g["ueber"] += mu > lv_schnitt[b]
            if platz:
                g["platz"] += platz
                g["pn"] += 1
            if naechste:
                c = ebene.get((mid, naechste))
                if c is not None:
                    g["wn"] += 1
                    g["wieder"] += (c > b) if art == "auf" else (c < b) if art == "ab" else 0
    wechsel = {}
    for art, d in gruppen.items():
        for lv, g in d.items():
            wechsel.setdefault(lv, {})[art] = {
                "n": g["n"], "mean": round(g["sum"] / g["n"]) if g["n"] else None,
                "ueber": round(100.0 * g["ueber"] / g["n"]) if g["n"] else None,
                "platz": round(g["platz"] / g["pn"], 1) if g["pn"] else None,
                "wieder": round(100.0 * g["wieder"] / g["wn"]) if g["wn"] else None}
    ebene_schnitt = {str(lv): (gesamt["levels"].get(str(lv)) or {}).get("mean") for lv in levels}

    out = {
        "levels": levels,
        "seasons": list(reversed(saisons)),
        "total": gesamt,
        "trend": verlauf,
        "dist": verteilung,
        "records": {"high": hoch, "low": tief, "season_best": saison_best, "season_worst": saison_schwach,
                    "season_points": saison_punkte, "no_win": ohne_sieg, "bad_luck": pech,
                    "lucky": sorted(glueck, key=lambda x: x[0])[:15]},
        "managers": {"steady": konstant, "wild": wundertuete, "wins": meist_siege, "lasts": meist_letzte,
                     "win_rate": siegquote, "streak_above": serie_ueber, "streak_win": serie_sieg,
                     "streak_1000": serie_1000},
        "moves": {"by_level": wechsel, "level_mean": ebene_schnitt, "down_high": ab_mit_schnitt,
                  "up_low": auf_mit_schnitt},
        "min_md": MIN_MD_KONSTANZ,
    }
    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf8") as fp:
        json.dump(out, fp, ensure_ascii=False, separators=(",", ":"))
    return out
