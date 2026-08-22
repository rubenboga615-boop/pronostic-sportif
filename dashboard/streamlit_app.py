#!/usr/bin/env python3
"""Dashboard Streamlit pour le pronostic football."""

import streamlit as st

st.set_page_config(
    page_title="Pronostic Sportif",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ Pronostic Sportif")
st.markdown("Moteur probabiliste de pronostic football")

# Sidebar
st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Aller à",
    ["Accueil", "Matchs à venir", "Prédictions", "Évaluation", "Sources"],
)

if page == "Accueil":
    st.header("📊 Tableau de bord")
    st.info("Le dashboard sera connecté à l'API une fois les données importées.")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Matchs prédits", "0")
    col2.metric("Accuracy", "—")
    col3.metric("ROI", "—")
    col4.metric("Sources actives", "0/4")

elif page == "Matchs à venir":
    st.header("📅 Matchs à venir")
    st.warning("Aucun match chargé. Lancez le pipeline de collecte quotidienne.")

elif page == "Prédictions":
    st.header("🎯 Prédictions")
    st.warning("Aucune prédiction disponible.")

elif page == "Évaluation":
    st.header("📈 Évaluation")
    st.warning("Exécutez le backtest pour voir les métriques.")

elif page == "Sources":
    st.header("🔌 Sources de données")
    st.info("Football-Data.co.uk | Understat | API-Football | The Odds API")
