# -*- coding: utf-8 -*-
"""Gemeinsame Kennung (User-Agent) fuer alle Abrufe bei Kickbase.

Bewusst offen: Kickbase soll sehen, dass die Abrufe von der KBL-Ligaseite kommen
und dass Poeti (KBL-Admin) dahintersteht. Wer das hier aendert, aendert es fuer
alle Skripte (automatik, Spieltag-Extras, Marktwerte, API-Erkundung).
"""
USER_AGENT = "KBL-Ligaseite/1.0 (betrieben von Poeti, KBL-Admin; +https://kickbase-bundesliga.github.io)"
