# Journal des décisions

> Une décision par entrée : ce qui a été tranché, pourquoi, et ce que ça
> interdit. Une décision inscrite ici fait autorité tant qu'elle n'est pas
> explicitement révoquée par une entrée ultérieure.
>
> Ce fichier existe parce que les mêmes questions se rouvrent tous les trois
> mois, faute d'avoir gardé le motif à côté du choix.

---

## D-01 — Douze saisons, dont une de chauffe

**Décidé le 07/09/2026.**

Le corpus va de 2014/15 à 2025/26 pour les cinq championnats.

2014/15 est **importée mais exclue de l'entraînement**. Sans saison antérieure,
2015/16 s'entraînerait sur un Elo resté à sa valeur initiale, un historique de
forme vide et un classement partiel : la première saison d'entraînement serait
la plus mal décrite de toutes. C'est aussi la première saison couverte par
Understat, ce qui aligne les deux sources.

**Interdit** : retirer une saison de la configuration d'un seul championnat.
Deux tests le vérifient.

---

## D-02 — Protocole de validation décalé de deux saisons

**Décidé le 07/09/2026. Remplace le découpage initial.**

```
Chauffe       2014/15
Entraînement  2015/16 → 2022/23
Validation    2023/24
Test          2024/25 + 2025/26
```

Le découpage d'origine (entraînement jusqu'à 2021/22, test sur 2023/24) datait
de l'époque où 2023/24 était la dernière saison terminée.

Deux saisons de test et non une : sur 380 matchs, un rendement simulé de −3 %
n'est distinguable ni de 0 %, ni de −8 %. Doubler l'échantillon de test resserre
la mesure davantage qu'ajouter une saison à un entraînement qui en compte huit —
la pondération temporelle du Dixon-Coles, de demi-vie proche d'un an, ne voit de
toute façon que les dernières.

**Interdit** : déplacer les dates de découpage sans le signaler dans le rapport.
Le modèle **de production**, lui, se réentraîne sur tout, jusqu'au dernier match
joué : le découpage sert à mesurer, pas à brider.

---

## D-03 — football-data.org écarté

**Décidé le 07/09/2026.**

Service distinct de Football-Data.**co.uk** malgré la quasi-homonymie. C'est une
vraie API REST, mais **elle ne fournit pas les cotes des bookmakers**. L'edge,
`offered_odds`, le rendement simulé et toute la comparaison au marché en
dépendent.

Football-Data.co.uk n'a pas d'API et n'en a pas besoin : ses fichiers sont à une
adresse stable, `mmz4281/{saison}/{code}.csv`.

---

## D-04 — La probabilité du marché n'est jamais une variable d'entrée

**Décidé le 07/09/2026. Contredit le document d'origine, qui la classait en
priorité haute.**

`implied_prob_home/draw/away` et le consensus de marché **ne doivent pas
alimenter le modèle**.

La probabilité du marché est le meilleur prédicteur unique disponible. Donnée en
entrée, le modèle apprend à la recopier ; les probabilités convergent vers celles
du bookmaker et **l'edge tend vers zéro par construction**, puisque
`edge = p_modèle − p_marché`. Le résultat serait un excellent log-loss pour un
rendement nul — l'échec le plus difficile à diagnostiquer.

La cote reste la **référence** et la base du calcul d'edge. Jamais une entrée.

**Autorisé** : une expérience explicite à deux modèles séparés — aveugle au
marché, informé — comparés sur le même jeu de test. Jamais un modèle unique qui
mélange les deux rôles.

---

## D-05 — Dixon-Coles n'est pas remplacé par un gradient boosting

**Décidé le 07/09/2026. Tranche l'ambiguïté du schéma « Moteur statistique
(XGBoost/LightGBM) » du cahier des charges IA.**

Un gradient boosting **ne produit pas de matrice de scores**. Il sort une
probabilité par marché, sans loi jointe. Or c'est la matrice qui permet de
calculer correctement la probabilité de deux sélections d'un même match — le
fondement de la couche coupons, et la seule façon de traiter les marchés
corrélés en Phase 2.

**Architecture retenue** : Dixon-Coles pour la distribution des scores, **plus**
une éventuelle couche de gradient boosting par-dessus, qui consommerait enfin les
variables dérivées pour corriger le 1N2. Les deux, jamais l'un à la place de
l'autre.

---

## D-06 — Les coupons ne sont pas publiés avant validation du moteur

**Décidé le 07/09/2026.**

Un coupon multiplie les probabilités, donc **les erreurs de probabilité**. La
calibration mesurée du moteur — annoncé 0,84, observé 0,67, un rapport de 0,80 —
se compose en puissance :

| Coupon | Annoncé | Réel | Écart |
|---|---|---|---|
| 3 sélections à 0,84 | 0,59 | 0,30 | ÷ 2,0 |
| 4 sélections | 0,50 | 0,20 | ÷ 2,5 |
| 5 sélections | 0,42 | 0,14 | ÷ 3,1 |

Le rendement suit la même loi : à −3,16 % par sélection, un coupon de cinq
jambes rend `0,9684⁵ − 1` = **−14,8 %**.

Le combiné est un **amplificateur**, pas un handicap : avec un edge réellement
positif par jambe, il amplifie dans le bon sens. Mais il exige un moteur calibré,
et le nôtre ne peut pas l'être tant que la saison de validation n'existe pas.

**Condition de publication** : rendement positif du générateur de coupons,
mesuré comme une stratégie à part entière sur les deux saisons de test.

---

## D-07 — La montante est écartée du moteur

**Décidé le 07/09/2026. Contredit le document d'origine.**

Une progression **ne change jamais l'espérance** ; elle ne transforme que la
variance. Sur un modèle à espérance négative, elle accélère la ruine. Même à
espérance positive, la probabilité d'aller au bout de *n* paliers est `p^n` : à
p = 0,70, cinq paliers aboutissent 17 % du temps.

**Retenu** : mise fixe d'abord, **Kelly fractionnaire** (un quart) quand le
modèle est validé.

**Toléré côté produit** : une montante proposée comme choix explicite de
l'utilisateur, jamais comme recommandation du moteur, et accompagnée de sa
probabilité d'aboutissement réelle.

---

## D-08 — L'IA rédige, elle ne juge pas

**Décidé le 07/09/2026. Tranche le point 23 du cahier des charges IA.**

Le cahier des charges demandait à la fois que l'IA « ne modifie jamais les
calculs » et qu'elle rende un verdict `validé / à réviser` sur les sélections.
Les deux ne tiennent pas ensemble : un verdict qui agit place l'IA dans le chemin
de décision, sans qu'elle ait accès aux preuves — ni aux matchs d'entraînement,
ni à la vraisemblance, ni à la matrice.

Elle casserait aussi la traçabilité : `data_cutoff_at` et `source_versions`
existent pour qu'un pronostic soit rejouable des années plus tard. Une sortie de
modèle de langage n'est pas reproductible.

**Retenu** : l'IA **rédige seulement**. Les contrôles de cohérence sont des
règles déterministes en code — nombre de jambes, une sélection par match,
probabilité minimale, edge minimal, absence de sélections contradictoires.

**Réservé** : un verdict consultatif, journalisé, **jamais bloquant**, dont on
mesure sur une saison s'il sépare réellement les coupons perdants. À défaut de
preuve, il est supprimé.

---

## D-09 — La présentation est exacte, pas « convaincante »

**Décidé le 07/09/2026. Corrige le point 18 du cahier des charges IA.**

Un modèle de langage à qui l'on demande d'être convaincant au sujet d'une
probabilité de 0,55 produit un texte qui sonne comme 0,85. Placé en série avec un
moteur déjà surconfiant, c'est un second amplificateur d'erreur.

**Consigne de rédaction** : claire, exacte, énonçant la probabilité **et** son
incertitude. « 62 % — le modèle se trompe presque quatre fois sur dix » est un
texte acceptable ; « une valeur sûre » ne l'est pas.

---

## D-10 — L'administrateur ne modifie jamais un chiffre

**Décidé le 07/09/2026.**

L'interface d'administration permet de **suspendre, dépublier et relancer**.
Elle ne permet **jamais** de modifier à la main une probabilité, une cote, un
edge ou un résultat réglé.

Si un administrateur peut retoucher un pronostic, l'historique de performance
cesse d'être une mesure et devient une déclaration. Tout l'intérêt du projet
repose sur le fait que ce chiffre est vérifiable.

**Correction d'une donnée fausse** : par migration versionnée et journalisée,
jamais par l'interface.

---

## D-11 — Publication en deux temps, avec interrupteur d'arrêt

**Décidé le 07/09/2026.**

Un coupon généré naît au statut `brouillon`. Il devient `publié` par une règle
automatique **ou** par une action d'administration, et l'interface porte un
**interrupteur d'arrêt global** qui suspend immédiatement toute publication.

Sans ce point d'arrêt, un modèle qui déraille un dimanche matin publie sa journée
entière avant que quiconque s'en aperçoive.
